"""X-Wines dataset API router for wine autocomplete and reference data.

Provides endpoints for:
- Wine search/autocomplete for check-in form (Atlas Search with regex fallback)
- Wine details lookup
- Dataset statistics for footer attribution
- Search result exports
"""

import logging
import re
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from winebox.database import get_database
from winebox.models import XWinesMetadata, XWinesWine
from winebox.services.xwines_enrichment import tokenize
from winebox.schemas.export import ExportFormat
from winebox.schemas.xwines import (
    FacetBucket,
    SearchFacets,
    XWinesSearchResponse,
    XWinesStats,
    XWinesWineDetail,
    XWinesWineSearchResult,
)
from winebox.services import export_service
from winebox.services.rate_limit import MAX_REFERENCE_RESULTSET, make_limiter

logger = logging.getLogger(__name__)

limiter = make_limiter()


# ---------------------------------------------------------------------------
# In-memory cache for filter dropdowns (types & countries).
# These change only when xwines data is re-imported, so a long TTL is fine.
# ---------------------------------------------------------------------------
_FILTER_CACHE_TTL = 3600  # 1 hour

_filter_cache: dict[str, Any] = {
    "types": None,
    "countries": None,
    "updated_at": 0.0,
}


def _cache_is_valid() -> bool:
    return (
        _filter_cache["types"] is not None
        and _filter_cache["countries"] is not None
        and (time.monotonic() - _filter_cache["updated_at"]) < _FILTER_CACHE_TTL
    )


def invalidate_filter_cache() -> None:
    """Invalidate the filter cache, forcing a refresh on next request."""
    _filter_cache["types"] = None
    _filter_cache["countries"] = None
    _filter_cache["updated_at"] = 0.0


async def refresh_filter_cache() -> None:
    """Populate the types/countries cache from the database."""
    try:
        collection = XWinesWine.get_pymongo_collection()

        types_pipeline: list[dict] = [
            {"$match": {"wine_type": {"$ne": None}}},
            {"$group": {"_id": "$wine_type"}},
            {"$sort": {"_id": 1}},
        ]
        types_cursor = await collection.aggregate(types_pipeline)
        types_results = await types_cursor.to_list(length=100)
        types = [doc["_id"] for doc in types_results if doc["_id"]]

        countries_pipeline: list[dict] = [
            {"$match": {"country_code": {"$ne": None}, "country": {"$ne": None}}},
            {
                "$group": {
                    "_id": {"code": "$country_code", "name": "$country"},
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"count": -1, "_id.name": 1}},
        ]
        countries_cursor = await collection.aggregate(countries_pipeline)
        countries_results = await countries_cursor.to_list(length=500)
        countries = [
            {"code": doc["_id"]["code"], "name": doc["_id"]["name"], "count": doc["count"]}
            for doc in countries_results
        ]

        _filter_cache["types"] = types
        _filter_cache["countries"] = countries
        _filter_cache["updated_at"] = time.monotonic()
        logger.info("X-Wines filter cache refreshed: %d types, %d countries", len(types), len(countries))
    except Exception:
        logger.exception("Failed to refresh X-Wines filter cache")

router = APIRouter()


async def _get_price_filtered_ids(
    price_min: float | None,
    price_max: float | None,
) -> set[int] | None:
    """Get xwines_ids that match the price range filter.

    Returns None if no price filter is active (meaning no filtering needed).
    Returns a set of matching IDs if a filter is active.

    Uses price_low_usd for lower bound and price_high_usd for upper bound,
    so a wine matches if its price range overlaps with the requested range.
    """
    if price_min is None and price_max is None:
        return None

    db = get_database()
    query: dict = {}
    if price_min is not None:
        # Wine's high price must be >= our min (wine's range overlaps from above)
        query["price_high_usd"] = {"$gte": price_min}
    if price_max is not None:
        # Wine's low price must be <= our max (wine's range overlaps from below)
        query.setdefault("price_low_usd", {})
        query["price_low_usd"]["$lte"] = price_max

    cursor = db["xwines_prices"].find(query, {"xwines_id": 1, "_id": 0})
    docs = await cursor.to_list(length=50000)
    return {doc["xwines_id"] for doc in docs}


async def _atlas_search(
    q: str,
    limit: int,
    wine_type: str | None,
    country: str | None,
    skip: int = 0,
    allowed_ids: set[int] | None = None,
) -> tuple[list[dict], int, SearchFacets | None]:
    """Attempt Atlas Search with facets.

    Uses compound query requiring ALL search terms to match (AND logic),
    with phrase matching for score boosting. This eliminates false positives
    where only some terms match (e.g., "Chateau Magdelaine" won't match
    wines with just "Chateau").

    Returns (results, total, facets) or raises on failure.
    """
    db = get_database()
    collection = db["xwines_wines"]

    # Split query into clean tokens - each term MUST appear (AND logic)
    # tokenize strips commas/punctuation so composite names like
    # "Chateau Lynch-Bages, Pauillac, Bordeaux" produce clean terms.
    terms = tokenize(q)

    # Build term clauses for each token.
    # For short queries (<=3 terms) use must (AND all).
    # For longer composite queries (4+ terms) use should with
    # minimumShouldMatch to tolerate terms like "Bordeaux" that
    # exist only in region_name (not indexed for text search).
    term_clauses: list[dict] = []
    for term in terms:
        term_clauses.append(
            {
                "text": {
                    "query": term,
                    "path": ["name", "winery_name"],
                    "fuzzy": {"maxEdits": 1, "prefixLength": 2},
                }
            }
        )

    # Phrase-match clauses for score boosting
    boost_clauses: list[dict] = [
        # Highest priority: exact phrase match in name
        {
            "phrase": {
                "query": q,
                "path": "name",
                "score": {"boost": {"value": 10}},
            }
        },
        # Medium priority: phrase match in winery_name
        {
            "phrase": {
                "query": q,
                "path": "winery_name",
                "score": {"boost": {"value": 5}},
            }
        },
    ]

    filter_clauses: list[dict] = []
    if wine_type:
        filter_clauses.append({"text": {"query": wine_type, "path": "wine_type"}})
    if country:
        filter_clauses.append({"text": {"query": country, "path": "country_code"}})

    if len(terms) >= 4:
        # Allow one unmatched term for composite names (e.g. region/country
        # tokens that only exist in region_name, not in name/winery_name)
        compound: dict = {
            "should": term_clauses + boost_clauses,
            "minimumShouldMatch": len(terms) - 1,
        }
    else:
        compound = {"must": term_clauses, "should": boost_clauses}
    if filter_clauses:
        compound["filter"] = filter_clauses

    search_stage = {
        "$search": {
            "index": "xwines_search",
            "compound": compound,
        }
    }

    # Sort by search score with rating_count as tiebreaker for stable
    # pagination.  $sort + $limit coalesces into a top-k heap internally,
    # so MongoDB only maintains (skip + limit) entries — not a full sort.
    # No $addFields needed: $meta works directly in $sort after $search.
    # Optional price filter: restrict to allowed xwines_ids
    price_match: list[dict] = []
    if allowed_ids is not None:
        price_match = [{"$match": {"xwines_id": {"$in": list(allowed_ids)}}}]

    pipeline: list[dict] = [
        search_stage,
        *price_match,
        {"$sort": {"score": {"$meta": "searchScore"}, "rating_count": -1}},
        {"$skip": skip},
        {"$limit": limit},
    ]
    cursor = await collection.aggregate(pipeline)
    results = await cursor.to_list(length=limit)

    # Run count pipeline
    count_pipeline: list[dict] = [
        search_stage,
        *price_match,
        {"$count": "total"},
    ]
    count_cursor = await collection.aggregate(count_pipeline)
    count_result = await count_cursor.to_list(length=1)
    total = count_result[0]["total"] if count_result else 0

    # Run facet pipeline via $searchMeta
    # Mirror the same term-matching logic used in the search stage
    facet_term_clauses: list[dict] = [
        {
            "text": {
                "query": term,
                "path": ["name", "winery_name"],
                "fuzzy": {"maxEdits": 1, "prefixLength": 2},
            }
        }
        for term in terms
    ]
    if len(terms) >= 4:
        facet_operator: dict = {
            "compound": {
                "should": facet_term_clauses,
                "minimumShouldMatch": len(terms) - 1,
            }
        }
    else:
        facet_operator = {
            "compound": {
                "must": facet_term_clauses,
            }
        }
    facet_pipeline: list[dict] = [
        {
            "$searchMeta": {
                "index": "xwines_search",
                "facet": {
                    "operator": facet_operator,
                    "facets": {
                        "wine_type": {
                            "type": "string",
                            "path": "wine_type",
                            "numBuckets": 20,
                        },
                        "country": {
                            "type": "string",
                            "path": "country",
                            "numBuckets": 50,
                        },
                    },
                },
            }
        }
    ]
    facet_cursor = await collection.aggregate(facet_pipeline)
    facet_result = await facet_cursor.to_list(length=1)

    facets = None
    if facet_result:
        meta = facet_result[0].get("facet", {})
        facets = SearchFacets(
            wine_type=[
                FacetBucket(value=b["_id"], count=b["count"])
                for b in meta.get("wine_type", {}).get("buckets", [])
            ],
            country=[
                FacetBucket(value=b["_id"], count=b["count"])
                for b in meta.get("country", {}).get("buckets", [])
            ],
        )

    return results, total, facets


async def _regex_search(
    q: str,
    limit: int,
    wine_type: str | None,
    country: str | None,
    skip: int = 0,
    allowed_ids: set[int] | None = None,
) -> tuple[list[XWinesWine], int]:
    """Fallback regex-based search for local MongoDB (no Atlas Search).

    Requires ALL search terms to appear (AND logic) to eliminate false positives.
    Uses three-tier matching to prioritize exact phrase matches:
    1. First: Full phrase at START of name (highest priority)
    2. Second: Full phrase with word boundaries anywhere
    3. Third: All terms present as substrings (fallback)

    Results are combined and deduplicated, preserving priority order.
    """
    escaped_q = re.escape(q)
    terms = tokenize(q)

    # Build filter conditions for wine_type and country
    filter_conditions: dict = {}
    if wine_type:
        filter_conditions["wine_type"] = {
            "$regex": re.compile(f"^{re.escape(wine_type)}$", re.IGNORECASE)
        }
    if country:
        filter_conditions["country_code"] = country.upper()
    if allowed_ids is not None:
        filter_conditions["xwines_id"] = {"$in": list(allowed_ids)}

    # Helper to build AND condition requiring all terms to appear
    def build_all_terms_condition() -> dict:
        """Build $and condition requiring ALL terms in name OR winery_name."""
        term_conditions = []
        for term in terms:
            term_pattern = re.compile(re.escape(term), re.IGNORECASE)
            term_conditions.append(
                {
                    "$or": [
                        {"name": {"$regex": term_pattern}},
                        {"winery_name": {"$regex": term_pattern}},
                    ]
                }
            )
        return {"$and": term_conditions} if len(term_conditions) > 1 else term_conditions[0]

    # Three-tier search patterns with decreasing priority
    # All tiers require ALL terms to match (AND logic)

    # Tier 1: Full phrase at START of name
    start_pattern = re.compile(f"^{escaped_q}", re.IGNORECASE)
    tier1_conditions: dict = {"name": {"$regex": start_pattern}}
    tier1_conditions.update(filter_conditions)

    # Tier 2: Full phrase with word boundaries anywhere in name/winery
    word_boundary_pattern = re.compile(rf"\b{escaped_q}\b", re.IGNORECASE)
    tier2_conditions: dict = {
        "$or": [
            {"name": {"$regex": word_boundary_pattern}},
            {"winery_name": {"$regex": word_boundary_pattern}},
        ]
    }
    tier2_conditions.update(filter_conditions)

    # Tier 3: All terms present as substrings (AND logic)
    tier3_base = build_all_terms_condition()
    tier3_conditions: dict = {**tier3_base}
    tier3_conditions.update(filter_conditions)

    # Fetch results from each tier, sorted by popularity
    sort_order = [("rating_count", -1), ("avg_rating", -1), ("name", 1)]

    # Cap each tier load — without this a wildcard search could pull all
    # ~150K X-Wines reference rows into memory before the dedupe + slice.
    # MAX_REFERENCE_RESULTSET is well above any realistic skip+limit window.
    tier1_wines = await XWinesWine.find(tier1_conditions).sort(sort_order).limit(MAX_REFERENCE_RESULTSET).to_list()
    tier2_wines = await XWinesWine.find(tier2_conditions).sort(sort_order).limit(MAX_REFERENCE_RESULTSET).to_list()
    tier3_wines = await XWinesWine.find(tier3_conditions).sort(sort_order).limit(MAX_REFERENCE_RESULTSET).to_list()

    # Combine and deduplicate results while preserving tier priority
    seen_ids: set[int] = set()
    combined: list[XWinesWine] = []

    for wine_list in [tier1_wines, tier2_wines, tier3_wines]:
        for wine in wine_list:
            if wine.xwines_id not in seen_ids:
                seen_ids.add(wine.xwines_id)
                combined.append(wine)

    # Apply pagination
    total = len(combined)
    wines = combined[skip : skip + limit]

    return wines, total


async def _batch_lookup_prices(xwines_ids: list[int]) -> dict[int, dict]:
    """Batch lookup base price data for X-Wines IDs from the xwines_prices collection.

    Returns base prices (vintage=null) for search results where no vintage context
    is available. For vintage-specific prices, use the enrichment service.
    """
    if not xwines_ids:
        return {}
    try:
        db = get_database()
        cursor = db["xwines_prices"].find(
            {"xwines_id": {"$in": xwines_ids}, "vintage": None},
            {"_id": 0, "xwines_id": 1, "price_low_usd": 1, "price_high_usd": 1, "price_tier": 1},
        )
        return {doc["xwines_id"]: doc async for doc in cursor}
    except Exception as e:
        logger.debug("Price lookup failed: %s", e)
        return {}


def _wine_doc_to_result(doc: dict, price_data: dict | None = None) -> XWinesWineSearchResult:
    """Convert a raw MongoDB document to a search result."""
    prices = price_data or {}
    return XWinesWineSearchResult(
        id=doc.get("xwines_id", 0),
        name=doc.get("name", ""),
        winery=doc.get("winery_name"),
        wine_type=doc.get("wine_type", ""),
        country=doc.get("country"),
        region=doc.get("region_name"),
        abv=doc.get("abv"),
        avg_rating=doc.get("avg_rating"),
        rating_count=doc.get("rating_count", 0),
        price_low_usd=prices.get("price_low_usd"),
        price_high_usd=prices.get("price_high_usd"),
        price_tier=prices.get("price_tier"),
    )


def _wine_model_to_result(wine: XWinesWine, price_data: dict | None = None) -> XWinesWineSearchResult:
    """Convert a MongoDocument model to a search result."""
    prices = price_data or {}
    return XWinesWineSearchResult(
        id=wine.xwines_id,
        name=wine.name,
        winery=wine.winery_name,
        wine_type=wine.wine_type,
        country=wine.country,
        region=wine.region_name,
        abv=wine.abv,
        avg_rating=wine.avg_rating,
        rating_count=wine.rating_count,
        price_low_usd=prices.get("price_low_usd"),
        price_high_usd=prices.get("price_high_usd"),
        price_tier=prices.get("price_tier"),
    )


@router.get("/search", response_model=XWinesSearchResponse)
@limiter.limit("120/minute;2000/hour")
async def search_wines(
    request: Request,
    q: str | None = Query(None, min_length=2, max_length=200, description="Search query (min 2 characters)"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results to return"),
    skip: int = Query(0, ge=0, le=10000, description="Number of results to skip"),
    wine_type: str | None = Query(None, max_length=50, description="Filter by wine type"),
    country: str | None = Query(None, max_length=100, description="Filter by country code"),
    price_min: float | None = Query(None, ge=0, description="Minimum price (USD)"),
    price_max: float | None = Query(None, ge=0, description="Maximum price (USD)"),
) -> XWinesSearchResponse:
    """Search X-Wines dataset for autocomplete.

    Uses Atlas Search when available (fuzzy matching, relevance scoring, facets).
    Falls back to regex search on local MongoDB instances.

    Price filtering: specify price_min and/or price_max to filter by estimated
    retail price range. Only wines with price data will be returned when a
    price filter is active.
    """
    # Validate price range
    if price_min is not None and price_max is not None and price_min > price_max:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"Minimum price (${price_min:.0f}) cannot exceed maximum price (${price_max:.0f})",
        )

    # Pre-filter by price if requested
    allowed_ids = await _get_price_filtered_ids(price_min, price_max)

    # If price filter is active but no wines match, return empty immediately
    if allowed_ids is not None and len(allowed_ids) == 0:
        return XWinesSearchResponse(
            results=[], total=0, skip=skip, limit=limit, facets=None
        )

    # No text query — filter-only search (by type, country, price)
    if not q:
        conditions: dict = {}
        if wine_type:
            conditions["wine_type"] = {
                "$regex": re.compile(f"^{re.escape(wine_type)}$", re.IGNORECASE)
            }
        if country:
            conditions["country_code"] = country.upper()
        if allowed_ids is not None:
            conditions["xwines_id"] = {"$in": list(allowed_ids)}

        sort_order = [("rating_count", -1), ("avg_rating", -1), ("name", 1)]
        wines = await XWinesWine.find(conditions).sort(sort_order).skip(skip).limit(limit).to_list()
        total = await XWinesWine.find(conditions).count()
        xwines_ids = [wine.xwines_id for wine in wines if wine.xwines_id]
        price_map = await _batch_lookup_prices(xwines_ids)
        results = [
            _wine_model_to_result(wine, price_map.get(wine.xwines_id))
            for wine in wines
        ]
        return XWinesSearchResponse(
            results=results, total=total, skip=skip, limit=limit, facets=None
        )

    # Try Atlas Search first — fall back to regex if it fails or returns
    # empty (Atlas Search silently returns 0 results when no search index
    # exists for the database, rather than raising an exception).
    try:
        docs, total, facets = await _atlas_search(
            q, limit, wine_type, country, skip, allowed_ids
        )
        if total > 0:
            xwines_ids = [doc.get("xwines_id") for doc in docs if doc.get("xwines_id")]
            price_map = await _batch_lookup_prices(xwines_ids)
            results = [
                _wine_doc_to_result(doc, price_map.get(doc.get("xwines_id")))
                for doc in docs
            ]
            return XWinesSearchResponse(
                results=results, total=total, skip=skip, limit=limit, facets=facets
            )
        logger.debug("Atlas Search returned 0 results, falling back to regex")
    except Exception as e:
        logger.debug("Atlas Search unavailable, falling back to regex: %s", e)

    # Fallback to regex search
    wines, total = await _regex_search(
        q, limit, wine_type, country, skip, allowed_ids
    )
    xwines_ids = [wine.xwines_id for wine in wines if wine.xwines_id]
    price_map = await _batch_lookup_prices(xwines_ids)
    results = [
        _wine_model_to_result(wine, price_map.get(wine.xwines_id))
        for wine in wines
    ]
    return XWinesSearchResponse(
        results=results, total=total, skip=skip, limit=limit, facets=None
    )


@router.get("/wines/{wine_id}", response_model=XWinesWineDetail)
async def get_wine(wine_id: int) -> XWinesWineDetail:
    """Get full details for a specific X-Wines wine."""
    wine = await XWinesWine.find_one({"xwines_id": wine_id})

    if not wine:
        raise HTTPException(status_code=404, detail="Wine not found")

    price_map = await _batch_lookup_prices([wine_id])
    prices = price_map.get(wine_id, {})

    return XWinesWineDetail(
        id=wine.xwines_id,
        name=wine.name,
        wine_type=wine.wine_type,
        elaborate=wine.elaborate,
        grapes=wine.grapes,
        harmonize=wine.harmonize,
        abv=wine.abv,
        body=wine.body,
        acidity=wine.acidity,
        country_code=wine.country_code,
        country=wine.country,
        region_id=wine.region_id,
        region_name=wine.region_name,
        winery_id=wine.winery_id,
        winery_name=wine.winery_name,
        website=wine.website,
        vintages=wine.vintages,
        avg_rating=wine.avg_rating,
        rating_count=wine.rating_count,
        price_low_usd=prices.get("price_low_usd"),
        price_high_usd=prices.get("price_high_usd"),
        price_tier=prices.get("price_tier"),
    )


@router.get("/stats", response_model=XWinesStats)
async def get_stats() -> XWinesStats:
    """Get X-Wines dataset statistics for footer attribution."""
    # Get metadata
    metadata_docs = await XWinesMetadata.find().to_list()
    metadata = {doc.key: doc.value for doc in metadata_docs}

    # Get actual wine count
    wine_count = await XWinesWine.count()

    return XWinesStats(
        wine_count=wine_count,
        rating_count=int(metadata.get("rating_count", "0")),
        version=metadata.get("version"),
        import_date=metadata.get("import_date"),
        source=metadata.get("source", "https://github.com/rogerioxavier/X-Wines"),
    )


@router.get("/types", response_model=list[str])
async def list_wine_types() -> list[str]:
    """List distinct wine types in the X-Wines dataset (cached)."""
    if not _cache_is_valid():
        await refresh_filter_cache()
    return _filter_cache["types"] or []


@router.get("/countries", response_model=list[dict])
async def list_countries() -> list[dict]:
    """List countries with wine counts in the X-Wines dataset (cached)."""
    if not _cache_is_valid():
        await refresh_filter_cache()
    return _filter_cache["countries"] or []


@router.get("/export")
@limiter.limit("10/minute;30/hour")
async def export_xwines_search(
    request: Request,
    q: str | None = Query(None, min_length=2, max_length=200, description="Search query (min 2 characters)"),
    format: ExportFormat = Query(default=ExportFormat.JSON, description="Export format"),
    wine_type: str | None = Query(None, max_length=50, description="Filter by wine type"),
    country: str | None = Query(None, max_length=100, description="Filter by country code"),
    price_min: float | None = Query(None, ge=0, description="Minimum price (USD)"),
    price_max: float | None = Query(None, ge=0, description="Maximum price (USD)"),
    limit: int = Query(1000, ge=1, le=10000, description="Maximum results to export"),
) -> Response:
    """Export X-Wines search results in various formats.

    Supports CSV, XLSX, YAML, and JSON formats.
    """
    # Pre-filter by price if requested
    allowed_ids = await _get_price_filtered_ids(price_min, price_max)

    # Execute search without pagination (get all results up to limit)
    if not q:
        # Filter-only (no text search)
        conditions: dict = {}
        if wine_type:
            conditions["wine_type"] = {"$regex": re.compile(f"^{re.escape(wine_type)}$", re.IGNORECASE)}
        if country:
            conditions["country_code"] = country.upper()
        if allowed_ids is not None:
            conditions["xwines_id"] = {"$in": list(allowed_ids)}
        wines = await XWinesWine.find(conditions).sort([("rating_count", -1)]).limit(limit).to_list()
        xwines_ids = [wine.xwines_id for wine in wines if wine.xwines_id]
        price_map = await _batch_lookup_prices(xwines_ids)
        results = [_wine_model_to_result(wine, price_map.get(wine.xwines_id)) for wine in wines]
    else:
        try:
            docs, total, _ = await _atlas_search(q, limit, wine_type, country, skip=0, allowed_ids=allowed_ids)
            xwines_ids = [doc.get("xwines_id") for doc in docs if doc.get("xwines_id")]
            price_map = await _batch_lookup_prices(xwines_ids)
            results = [_wine_doc_to_result(doc, price_map.get(doc.get("xwines_id"))) for doc in docs]
        except Exception as e:
            logger.debug("Atlas Search unavailable, falling back to regex: %s", e)
            wines, total = await _regex_search(q, limit, wine_type, country, skip=0, allowed_ids=allowed_ids)
            xwines_ids = [wine.xwines_id for wine in wines if wine.xwines_id]
            price_map = await _batch_lookup_prices(xwines_ids)
            results = [_wine_model_to_result(wine, price_map.get(wine.xwines_id)) for wine in wines]

    # Build filters applied metadata
    filters_applied: dict = {}
    if q:
        filters_applied["q"] = q
    if wine_type:
        filters_applied["wine_type"] = wine_type
    if country:
        filters_applied["country"] = country

    # Convert results to dictionaries for export
    results_dicts = [result.model_dump() for result in results]

    # Generate export based on format
    if format == ExportFormat.CSV:
        content = export_service.export_xwines_to_csv(results_dicts)
        media_type = "text/csv"
    elif format == ExportFormat.XLSX:
        content = export_service.export_xwines_to_xlsx(results_dicts)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif format == ExportFormat.YAML:
        content = export_service.export_xwines_to_yaml(results_dicts, filters_applied)
        media_type = "application/x-yaml"
    else:  # JSON
        json_data = export_service.export_xwines_to_json(results_dicts, filters_applied)
        import json
        content = json.dumps(json_data, indent=2).encode("utf-8")
        media_type = "application/json"

    # Generate filename
    filename = export_service.generate_xwines_filename(format)

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
