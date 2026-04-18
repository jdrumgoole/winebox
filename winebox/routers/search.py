"""Search endpoints — HTTP wrapper around services/search_service."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request

from winebox.models.wine import WineCollection
from winebox.schemas.wine import WineWithInventory
from winebox.services.auth import RequireAuth
from winebox.services.rate_limit import MAX_PAGE_SIZE, make_limiter
from winebox.services.search_service import WineSearchFilters, search_wines

router = APIRouter()


# Maximum length for search query parameters to prevent DoS
MAX_QUERY_LENGTH = 200

limiter = make_limiter()


@router.get("", response_model=list[WineWithInventory])
@limiter.limit("120/minute;2000/hour")
async def search_wines_endpoint(
    request: Request,
    current_user: RequireAuth,
    q: Annotated[str | None, Query(description="Full-text search query", max_length=MAX_QUERY_LENGTH)] = None,
    vintage: Annotated[int | None, Query(description="Wine vintage year")] = None,
    grape: Annotated[str | None, Query(description="Grape variety", max_length=MAX_QUERY_LENGTH)] = None,
    winery: Annotated[str | None, Query(description="Winery name", max_length=MAX_QUERY_LENGTH)] = None,
    region: Annotated[str | None, Query(description="Wine region", max_length=MAX_QUERY_LENGTH)] = None,
    country: Annotated[str | None, Query(description="Country", max_length=MAX_QUERY_LENGTH)] = None,
    checked_in_after: Annotated[datetime | None, Query(description="Checked in after date")] = None,
    checked_in_before: Annotated[datetime | None, Query(description="Checked in before date")] = None,
    checked_out_after: Annotated[datetime | None, Query(description="Checked out after date")] = None,
    checked_out_before: Annotated[datetime | None, Query(description="Checked out before date")] = None,
    in_stock: Annotated[bool | None, Query(description="Only wines currently in stock")] = None,
    collection: Annotated[WineCollection | None, Query(description="Filter by collection: cellar or met")] = None,
    storage: Annotated[str | None, Query(description="Storage type: 'case' or 'loose'")] = None,
    provenance: Annotated[str | None, Query(description="Case provenance (where purchased)", max_length=MAX_QUERY_LENGTH)] = None,
    wine_type: Annotated[str | None, Query(description="Wine type: red, white, rosé, sparkling, etc.", max_length=MAX_QUERY_LENGTH)] = None,
    price_tier: Annotated[str | None, Query(description="Price tier: budget, value, mid_range, premium, luxury, ultra_premium", max_length=MAX_QUERY_LENGTH)] = None,
    enriched: Annotated[str | None, Query(description="Enrichment filter: 'yes' for enriched, 'no' for unenriched")] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
) -> list[WineWithInventory]:
    """Search wines by various criteria.

    Use ``q`` for full-text search across name, winery, region, and label
    text. Other parameters filter on specific fields.
    """
    filters = WineSearchFilters(
        q=q,
        vintage=vintage,
        grape=grape,
        winery=winery,
        region=region,
        country=country,
        checked_in_after=checked_in_after,
        checked_in_before=checked_in_before,
        checked_out_after=checked_out_after,
        checked_out_before=checked_out_before,
        in_stock=in_stock,
        collection=collection,
        storage=storage,
        provenance=provenance,
        wine_type=wine_type,
        price_tier=price_tier,
        enriched=enriched,
    )
    wines = await search_wines(current_user.id, filters, skip, limit)
    return [WineWithInventory.model_validate(w) for w in wines]
