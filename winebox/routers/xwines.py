"""X-Wines dataset API router for wine autocomplete and reference data.

Provides endpoints for:
- Wine search/autocomplete for check-in form
- Wine details lookup
- Dataset statistics for footer attribution
"""

import re

from fastapi import APIRouter, HTTPException, Query

from winebox.models import XWinesMetadata, XWinesWine
from winebox.schemas.xwines import (
    XWinesSearchResponse,
    XWinesStats,
    XWinesWineDetail,
    XWinesWineSearchResult,
)

router = APIRouter()


@router.get("/search", response_model=XWinesSearchResponse)
async def search_wines(
    q: str = Query(..., min_length=2, description="Search query (min 2 characters)"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results to return"),
    wine_type: str | None = Query(None, description="Filter by wine type"),
    country: str | None = Query(None, description="Filter by country code"),
) -> XWinesSearchResponse:
    """Search X-Wines dataset for autocomplete.

    Returns wines matching the query by name or winery name.
    Results are sorted by rating count (popularity) then average rating.
    """
    # Build search query - search in name and winery_name
    search_pattern = re.compile(re.escape(q), re.IGNORECASE)
    conditions = {
        "$or": [
            {"name": {"$regex": search_pattern}},
            {"winery_name": {"$regex": search_pattern}},
        ]
    }

    # Apply optional filters
    if wine_type:
        conditions["wine_type"] = {"$regex": re.compile(f"^{re.escape(wine_type)}$", re.IGNORECASE)}
    if country:
        conditions["country_code"] = country.upper()

    # Get wines sorted by popularity
    wines = await XWinesWine.find(conditions).sort(
        [("rating_count", -1), ("avg_rating", -1), ("name", 1)]
    ).limit(limit).to_list()

    # Count total matches
    total = await XWinesWine.find(conditions).count()

    # Convert to response format
    results = [
        XWinesWineSearchResult(
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
        for wine in wines
    ]

    return XWinesSearchResponse(results=results, total=total)


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
        pipeline = [
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
        pipeline = [
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
