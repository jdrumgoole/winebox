"""Cellar inventory endpoints."""

from fastapi import APIRouter

from winebox.models import Wine
from winebox.schemas.wine import WineWithInventory
from winebox.services.auth import RequireAuth

router = APIRouter()


@router.get("", response_model=list[WineWithInventory])
async def get_cellar_inventory(
    _: RequireAuth,
    skip: int = 0,
    limit: int = 100,
) -> list[WineWithInventory]:
    """Get current cellar inventory (wines in stock)."""
    wines = await Wine.find(
        Wine.inventory.quantity > 0
    ).skip(skip).limit(limit).sort(Wine.name).to_list()

    return [WineWithInventory.model_validate(wine) for wine in wines]


@router.get("/summary")
async def get_cellar_summary(
    _: RequireAuth,
) -> dict:
    """Get cellar summary statistics."""
    # Total bottles in cellar using aggregation
    total_bottles_pipeline = [
        {"$match": {"inventory.quantity": {"$gt": 0}}},
        {"$group": {"_id": None, "total": {"$sum": "$inventory.quantity"}}},
    ]
    total_bottles_result = await Wine.aggregate(total_bottles_pipeline).to_list()
    total_bottles = total_bottles_result[0]["total"] if total_bottles_result else 0

    # Unique wines in stock
    unique_wines = await Wine.find(Wine.inventory.quantity > 0).count()

    # Total wines ever tracked (including out of stock)
    total_wines_tracked = await Wine.count()

    # Wines by vintage (in stock)
    by_vintage_pipeline = [
        {"$match": {"inventory.quantity": {"$gt": 0}, "vintage": {"$ne": None}}},
        {"$group": {"_id": "$vintage", "count": {"$sum": "$inventory.quantity"}}},
        {"$sort": {"_id": -1}},
    ]
    by_vintage_result = await Wine.aggregate(by_vintage_pipeline).to_list()
    by_vintage = {str(row["_id"]): row["count"] for row in by_vintage_result}

    # Wines by country (in stock)
    by_country_pipeline = [
        {"$match": {"inventory.quantity": {"$gt": 0}, "country": {"$ne": None}}},
        {"$group": {"_id": "$country", "count": {"$sum": "$inventory.quantity"}}},
        {"$sort": {"count": -1}},
    ]
    by_country_result = await Wine.aggregate(by_country_pipeline).to_list()
    by_country = {row["_id"]: row["count"] for row in by_country_result}

    # Wines by grape variety (in stock)
    by_grape_pipeline = [
        {"$match": {"inventory.quantity": {"$gt": 0}, "grape_variety": {"$ne": None}}},
        {"$group": {"_id": "$grape_variety", "count": {"$sum": "$inventory.quantity"}}},
        {"$sort": {"count": -1}},
    ]
    by_grape_result = await Wine.aggregate(by_grape_pipeline).to_list()
    by_grape = {row["_id"]: row["count"] for row in by_grape_result}

    return {
        "total_bottles": total_bottles,
        "unique_wines": unique_wines,
        "total_wines_tracked": total_wines_tracked,
        "by_vintage": by_vintage,
        "by_country": by_country,
        "by_grape_variety": by_grape,
    }
