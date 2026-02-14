"""X-Wines dataset API router for wine autocomplete and reference data.

Provides endpoints for:
- Wine search/autocomplete for check-in form
- Wine details lookup
- Dataset statistics for footer attribution
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from winebox.database import get_db
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
    db: AsyncSession = Depends(get_db),
) -> XWinesSearchResponse:
    """Search X-Wines dataset for autocomplete.

    Returns wines matching the query by name or winery name.
    Results are sorted by rating count (popularity) then average rating.
    """
    # Build search query - search in name and winery_name
    search_pattern = f"%{q}%"
    query = select(XWinesWine).where(
        or_(
            XWinesWine.name.ilike(search_pattern),
            XWinesWine.winery_name.ilike(search_pattern),
        )
    )

    # Apply optional filters
    if wine_type:
        query = query.where(XWinesWine.wine_type.ilike(wine_type))
    if country:
        query = query.where(XWinesWine.country_code == country.upper())

    # Order by popularity (rating_count) then quality (avg_rating)
    query = query.order_by(
        XWinesWine.rating_count.desc().nulls_last(),
        XWinesWine.avg_rating.desc().nulls_last(),
        XWinesWine.name,
    ).limit(limit)

    result = await db.execute(query)
    wines = result.scalars().all()

    # Count total matches for info
    count_query = select(func.count()).select_from(XWinesWine).where(
        or_(
            XWinesWine.name.ilike(search_pattern),
            XWinesWine.winery_name.ilike(search_pattern),
        )
    )
    if wine_type:
        count_query = count_query.where(XWinesWine.wine_type.ilike(wine_type))
    if country:
        count_query = count_query.where(XWinesWine.country_code == country.upper())

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Convert to response format
    results = [
        XWinesWineSearchResult(
            id=wine.id,
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
async def get_wine(
    wine_id: int,
    db: AsyncSession = Depends(get_db),
) -> XWinesWineDetail:
    """Get full details for a specific X-Wines wine."""
    result = await db.execute(select(XWinesWine).where(XWinesWine.id == wine_id))
    wine = result.scalar_one_or_none()

    if not wine:
        raise HTTPException(status_code=404, detail="Wine not found")

    return XWinesWineDetail.model_validate(wine)


@router.get("/stats", response_model=XWinesStats)
async def get_stats(
    db: AsyncSession = Depends(get_db),
) -> XWinesStats:
    """Get X-Wines dataset statistics for footer attribution."""
    # Get metadata
    metadata_result = await db.execute(select(XWinesMetadata))
    metadata_rows = metadata_result.scalars().all()
    metadata = {row.key: row.value for row in metadata_rows}

    # Get actual wine count
    count_result = await db.execute(select(func.count()).select_from(XWinesWine))
    wine_count = count_result.scalar() or 0

    return XWinesStats(
        wine_count=wine_count,
        rating_count=int(metadata.get("rating_count", "0")),
        version=metadata.get("version"),
        import_date=metadata.get("import_date"),
        source=metadata.get("source", "https://github.com/rogerioxavier/X-Wines"),
    )


@router.get("/types", response_model=list[str])
async def list_wine_types(
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """List distinct wine types in the X-Wines dataset."""
    result = await db.execute(
        select(XWinesWine.wine_type)
        .distinct()
        .where(XWinesWine.wine_type.isnot(None))
        .order_by(XWinesWine.wine_type)
    )
    types = result.scalars().all()
    return [t for t in types if t]


@router.get("/countries", response_model=list[dict])
async def list_countries(
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List countries with wine counts in the X-Wines dataset."""
    result = await db.execute(
        select(
            XWinesWine.country_code,
            XWinesWine.country,
            func.count(XWinesWine.id).label("count"),
        )
        .where(XWinesWine.country_code.isnot(None))
        .group_by(XWinesWine.country_code, XWinesWine.country)
        .order_by(func.count(XWinesWine.id).desc())
    )
    rows = result.all()
    return [
        {"code": row.country_code, "name": row.country, "count": row.count}
        for row in rows
    ]
