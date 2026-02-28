"""X-Wines dataset API router for wine autocomplete and reference data.

Provides endpoints for:
- Wine search/autocomplete for check-in form (Atlas Search with regex fallback)
- Wine details lookup
- Dataset statistics for footer attribution
- Search result exports
"""

import logging
import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from winebox.database import get_database
from winebox.models import XWinesMetadata, XWinesWine
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

logger = logging.getLogger(__name__)

router = APIRouter()


async def _atlas_search(
    q: str,
    limit: int,
    wine_type: str | None,
    country: str | None,
    skip: int = 0,
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

    # Split query into terms - each term MUST appear (AND logic)
    terms = q.split()

    # Build must clauses - require ALL terms to appear in name or winery_name
    # This prevents false positives where only some terms match
    must_clauses: list[dict] = []
    for term in terms:
        must_clauses.append(
            {
                "text": {
                    "query": term,
                    "path": ["name", "winery_name"],
                    "fuzzy": {"maxEdits": 1, "prefixLength": 2},
                }
            }
        )

    # Build should clauses for score boosting - phrase matches rank higher
    should_clauses: list[dict] = [
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

    compound: dict = {"must": must_clauses, "should": should_clauses}
    if filter_clauses:
        compound["filter"] = filter_clauses

    search_stage = {
        "$search": {
            "index": "xwines_search",
            "compound": compound,
        }
    }

    # Run search pipeline for results (with skip for pagination)
    # Sort by search score first (phrase matches rank higher), then by popularity
    pipeline: list[dict] = [
        search_stage,
        {"$addFields": {"searchScore": {"$meta": "searchScore"}}},
        {"$sort": {"searchScore": -1, "rating_count": -1, "avg_rating": -1}},
        {"$skip": skip},
        {"$limit": limit},
    ]
    results = await collection.aggregate(pipeline).to_list(length=limit)

    # Run count pipeline
    count_pipeline: list[dict] = [
        search_stage,
        {"$count": "total"},
    ]
    count_result = await collection.aggregate(count_pipeline).to_list(length=1)
    total = count_result[0]["total"] if count_result else 0

    # Run facet pipeline via $searchMeta
    # Use compound with must clauses to match the search query behavior (AND logic)
    facet_must_clauses: list[dict] = [
        {
            "text": {
                "query": term,
                "path": ["name", "winery_name"],
                "fuzzy": {"maxEdits": 1, "prefixLength": 2},
            }
        }
        for term in terms
    ]
    facet_pipeline: list[dict] = [
        {
            "$searchMeta": {
                "index": "xwines_search",
                "facet": {
                    "operator": {
                        "compound": {
                            "must": facet_must_clauses,
                        }
                    },
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
    facet_result = await collection.aggregate(facet_pipeline).to_list(length=1)

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
    terms = q.split()

    # Build filter conditions for wine_type and country
    filter_conditions: dict = {}
    if wine_type:
        filter_conditions["wine_type"] = {
            "$regex": re.compile(f"^{re.escape(wine_type)}$", re.IGNORECASE)
        }
    if country:
        filter_conditions["country_code"] = country.upper()

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

    tier1_wines = await XWinesWine.find(tier1_conditions).sort(sort_order).to_list()
    tier2_wines = await XWinesWine.find(tier2_conditions).sort(sort_order).to_list()
    tier3_wines = await XWinesWine.find(tier3_conditions).sort(sort_order).to_list()

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


def _wine_doc_to_result(doc: dict) -> XWinesWineSearchResult:
    """Convert a raw MongoDB document to a search result."""
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
    )


def _wine_model_to_result(wine: XWinesWine) -> XWinesWineSearchResult:
    """Convert a Beanie model to a search result."""
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
    )


@router.get("/search", response_model=XWinesSearchResponse)
async def search_wines(
    q: str = Query(..., min_length=2, description="Search query (min 2 characters)"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results to return"),
    skip: int = Query(0, ge=0, description="Number of results to skip"),
    wine_type: str | None = Query(None, description="Filter by wine type"),
    country: str | None = Query(None, description="Filter by country code"),
) -> XWinesSearchResponse:
    """Search X-Wines dataset for autocomplete.

    Uses Atlas Search when available (fuzzy matching, relevance scoring, facets).
    Falls back to regex search on local MongoDB instances.
    """
    # Try Atlas Search first
    try:
        docs, total, facets = await _atlas_search(q, limit, wine_type, country, skip)
        results = [_wine_doc_to_result(doc) for doc in docs]
        return XWinesSearchResponse(
            results=results, total=total, skip=skip, limit=limit, facets=facets
        )
    except Exception as e:
        logger.debug("Atlas Search unavailable, falling back to regex: %s", e)

    # Fallback to regex search
    wines, total = await _regex_search(q, limit, wine_type, country, skip)
    results = [_wine_model_to_result(wine) for wine in wines]
    return XWinesSearchResponse(
        results=results, total=total, skip=skip, limit=limit, facets=None
    )


@router.get("/wines/{wine_id}", response_model=XWinesWineDetail)
async def get_wine(wine_id: int) -> XWinesWineDetail:
    """Get full details for a specific X-Wines wine."""
    wine = await XWinesWine.find_one(XWinesWine.xwines_id == wine_id)

    if not wine:
        raise HTTPException(status_code=404, detail="Wine not found")

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
    """List distinct wine types in the X-Wines dataset."""
    # Use MongoDB aggregation for efficient distinct values
    # Falls back to Python aggregation if aggregation is not supported (e.g., mongomock)
    try:
        pipeline: list[dict] = [
            {"$match": {"wine_type": {"$ne": None}}},
            {"$group": {"_id": "$wine_type"}},
            {"$sort": {"_id": 1}},
        ]
        results = await XWinesWine.aggregate(pipeline).to_list()
        return [doc["_id"] for doc in results if doc["_id"]]
    except Exception:
        # Fallback to Python aggregation for compatibility
        wines = await XWinesWine.find(
            XWinesWine.wine_type != None  # noqa: E711
        ).to_list()
        types = set(wine.wine_type for wine in wines if wine.wine_type)
        return sorted(list(types))


@router.get("/countries", response_model=list[dict])
async def list_countries() -> list[dict]:
    """List countries with wine counts in the X-Wines dataset."""
    # Use MongoDB aggregation for efficient grouping
    # Falls back to Python aggregation if aggregation is not supported (e.g., mongomock)
    try:
        pipeline: list[dict] = [
            {"$match": {"country_code": {"$ne": None}, "country": {"$ne": None}}},
            {
                "$group": {
                    "_id": {"code": "$country_code", "name": "$country"},
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"count": -1, "_id.name": 1}},
        ]
        results = await XWinesWine.aggregate(pipeline).to_list()
        return [
            {"code": doc["_id"]["code"], "name": doc["_id"]["name"], "count": doc["count"]}
            for doc in results
        ]
    except Exception:
        # Fallback to Python aggregation for compatibility
        from collections import Counter

        wines = await XWinesWine.find(
            XWinesWine.country_code != None  # noqa: E711
        ).to_list()

        country_counts: Counter[tuple[str, str]] = Counter()
        for wine in wines:
            if wine.country_code and wine.country:
                country_counts[(wine.country_code, wine.country)] += 1

        sorted_countries = sorted(country_counts.items(), key=lambda x: (-x[1], x[0][1]))
        return [
            {"code": code, "name": name, "count": count}
            for (code, name), count in sorted_countries
        ]


@router.get("/export")
async def export_xwines_search(
    q: str = Query(..., min_length=2, description="Search query (min 2 characters)"),
    format: ExportFormat = Query(default=ExportFormat.JSON, description="Export format"),
    wine_type: str | None = Query(None, description="Filter by wine type"),
    country: str | None = Query(None, description="Filter by country code"),
    limit: int = Query(1000, ge=1, le=10000, description="Maximum results to export"),
) -> Response:
    """Export X-Wines search results in various formats.

    Supports CSV, XLSX, YAML, and JSON formats.
    """
    # Execute search without pagination (get all results up to limit)
    try:
        docs, total, _ = await _atlas_search(q, limit, wine_type, country, skip=0)
        results = [_wine_doc_to_result(doc) for doc in docs]
    except Exception as e:
        logger.debug("Atlas Search unavailable, falling back to regex: %s", e)
        wines, total = await _regex_search(q, limit, wine_type, country, skip=0)
        results = [_wine_model_to_result(wine) for wine in wines]

    # Build filters applied metadata
    filters_applied = {"q": q}
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
