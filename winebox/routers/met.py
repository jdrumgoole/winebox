"""Endpoints for listing and summarising wines the user has met."""

from fastapi import APIRouter

from winebox.models import Wine
from winebox.models.wine import WineCollection
from winebox.schemas.wine import WineWithInventory
from winebox.services.auth import RequireAuth

router = APIRouter()


@router.get("", response_model=list[WineWithInventory])
async def get_met_wines(
    current_user: RequireAuth,
    skip: int = 0,
    limit: int = 100,
) -> list[WineWithInventory]:
    """List wines the current user has encountered."""
    wines = await Wine.find(
        Wine.owner_id == current_user.id,
        Wine.collection == WineCollection.MET,
    ).skip(skip).limit(limit).sort(-Wine.created_at).to_list()

    return [WineWithInventory.model_validate(wine) for wine in wines]


@router.get("/summary")
async def get_met_summary(
    current_user: RequireAuth,
) -> dict:
    """Get summary statistics for met wines."""
    collection = Wine.get_pymongo_collection()

    base_match = {"owner_id": current_user.id, "collection": WineCollection.MET.value}

    # Total met wines
    total_met = await Wine.find(
        Wine.owner_id == current_user.id,
        Wine.collection == WineCollection.MET,
    ).count()

    # Added to cellar count
    added_to_cellar = await Wine.find(
        Wine.owner_id == current_user.id,
        Wine.collection == WineCollection.MET,
        Wine.added_to_cellar == True,  # noqa: E712
    ).count()

    # By country
    by_country_pipeline = [
        {"$match": {**base_match, "country": {"$ne": None}}},
        {"$group": {"_id": "$country", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    cursor = collection.aggregate(by_country_pipeline)
    by_country_result = await cursor.to_list(length=None)
    by_country = {row["_id"]: row["count"] for row in by_country_result}

    # By grape variety
    by_grape_pipeline = [
        {"$match": {**base_match, "grape_variety": {"$ne": None}}},
        {"$group": {"_id": "$grape_variety", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    cursor = collection.aggregate(by_grape_pipeline)
    by_grape_result = await cursor.to_list(length=None)
    by_grape = {row["_id"]: row["count"] for row in by_grape_result}

    return {
        "total_met": total_met,
        "added_to_cellar": added_to_cellar,
        "by_country": by_country,
        "by_grape_variety": by_grape,
    }
