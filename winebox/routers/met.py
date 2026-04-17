"""Endpoints for listing and summarising wines the user has met."""

from fastapi import APIRouter, Query

from winebox.models import Wine
from winebox.models.wine import WineCollection
from winebox.schemas.wine import WineWithInventory
from winebox.services.auth import RequireAuth
from winebox.services.rate_limit import MAX_PAGE_SIZE

router = APIRouter()


@router.get("", response_model=list[WineWithInventory])
async def get_met_wines(
    current_user: RequireAuth,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
) -> list[WineWithInventory]:
    """List wines the current user has encountered."""
    wines = await Wine.find(
        {"owner_id": current_user.id, "collection": WineCollection.MET}
    ).skip(skip).limit(limit).sort([("created_at", -1)]).to_list()

    return [WineWithInventory.model_validate(wine) for wine in wines]


@router.get("/summary")
async def get_met_summary(
    current_user: RequireAuth,
) -> dict:
    """Get summary statistics for met wines.

    Uses a single $facet aggregation to compute all breakdowns in one
    round-trip instead of 4 separate queries.
    """
    base_match = {"owner_id": current_user.id, "collection": WineCollection.MET.value}

    pipeline = [
        {"$match": base_match},
        {"$facet": {
            "total_met": [
                {"$count": "count"},
            ],
            "added_to_cellar": [
                {"$match": {"added_to_cellar": True}},
                {"$count": "count"},
            ],
            "by_country": [
                {"$match": {"country": {"$ne": None}}},
                {"$group": {"_id": "$country", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ],
            "by_grape": [
                {"$match": {"grape_variety": {"$ne": None}}},
                {"$group": {"_id": "$grape_variety", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ],
        }},
    ]

    cursor = await Wine.get_pymongo_collection().aggregate(pipeline)
    result = await cursor.to_list(length=None)
    facets = result[0] if result else {}

    total_met = facets.get("total_met", [{}])[0].get("count", 0) if facets.get("total_met") else 0
    added_to_cellar = facets.get("added_to_cellar", [{}])[0].get("count", 0) if facets.get("added_to_cellar") else 0
    by_country = {row["_id"]: row["count"] for row in facets.get("by_country", [])}
    by_grape = {row["_id"]: row["count"] for row in facets.get("by_grape", [])}

    return {
        "total_met": total_met,
        "added_to_cellar": added_to_cellar,
        "by_country": by_country,
        "by_grape_variety": by_grape,
    }
