"""Cellar inventory endpoints."""

from fastapi import APIRouter

from winebox.models import Wine
from winebox.models.wine import WineCollection
from winebox.schemas.wine import WineWithInventory
from winebox.services.auth import RequireAuth

router = APIRouter()


@router.get("", response_model=list[WineWithInventory])
async def get_cellar_inventory(
    current_user: RequireAuth,
    skip: int = 0,
    limit: int = 100,
) -> list[WineWithInventory]:
    """Get current cellar inventory (wines in stock)."""
    wines = await Wine.find(
        {"owner_id": current_user.id, "collection": WineCollection.CELLAR, "inventory.quantity": {"$gt": 0}}
    ).skip(skip).limit(limit).sort([("name", 1)]).to_list()

    return [WineWithInventory.model_validate(wine) for wine in wines]


@router.get("/summary")
async def get_cellar_summary(
    current_user: RequireAuth,
) -> dict:
    """Get cellar summary statistics.

    Uses a single $facet aggregation to compute all breakdowns in one
    round-trip instead of 8 separate queries.
    """
    base_match = {
        "owner_id": current_user.id,
        "collection": "cellar",
        "inventory.quantity": {"$gt": 0},
    }

    pipeline = [
        {"$match": base_match},
        {"$facet": {
            "total_bottles": [
                {"$group": {"_id": None, "total": {"$sum": "$inventory.quantity"}}},
            ],
            "unique_wines": [
                {"$count": "count"},
            ],
            "by_vintage": [
                {"$match": {"vintage": {"$ne": None}}},
                {"$group": {"_id": "$vintage", "count": {"$sum": "$inventory.quantity"}}},
                {"$sort": {"_id": -1}},
            ],
            "by_country": [
                {"$match": {"country": {"$ne": None}}},
                {"$group": {"_id": "$country", "count": {"$sum": "$inventory.quantity"}}},
                {"$sort": {"count": -1}},
            ],
            "by_grape": [
                {"$match": {"grape_variety": {"$ne": None}}},
                {"$group": {"_id": "$grape_variety", "count": {"$sum": "$inventory.quantity"}}},
                {"$sort": {"count": -1}},
            ],
            "by_wine_type": [
                {"$match": {"wine_type_id": {"$ne": None}}},
                {"$group": {"_id": "$wine_type_id", "count": {"$sum": "$inventory.quantity"}}},
                {"$sort": {"count": -1}},
            ],
            "by_price_tier": [
                {"$match": {"price_tier": {"$ne": None}}},
                {"$group": {"_id": "$price_tier", "count": {"$sum": "$inventory.quantity"}}},
                {"$sort": {"count": -1}},
            ],
        }},
    ]

    cursor = await Wine.get_pymongo_collection().aggregate(pipeline)
    result = await cursor.to_list(length=None)
    facets = result[0] if result else {}

    total_bottles = facets.get("total_bottles", [{}])[0].get("total", 0) if facets.get("total_bottles") else 0
    unique_wines = facets.get("unique_wines", [{}])[0].get("count", 0) if facets.get("unique_wines") else 0

    # Total wines tracked uses a different filter (includes out-of-stock)
    total_wines_tracked = await Wine.find(
        {"owner_id": current_user.id, "collection": WineCollection.CELLAR}
    ).count()

    by_vintage = {str(row["_id"]): row["count"] for row in facets.get("by_vintage", [])}
    by_country = {row["_id"]: row["count"] for row in facets.get("by_country", [])}
    by_grape = {row["_id"]: row["count"] for row in facets.get("by_grape", [])}
    by_wine_type = {row["_id"]: row["count"] for row in facets.get("by_wine_type", [])}
    by_price_tier = {row["_id"]: row["count"] for row in facets.get("by_price_tier", [])}

    return {
        "total_bottles": total_bottles,
        "unique_wines": unique_wines,
        "total_wines_tracked": total_wines_tracked,
        "by_vintage": by_vintage,
        "by_country": by_country,
        "by_grape_variety": by_grape,
        "by_wine_type": by_wine_type,
        "by_price_tier": by_price_tier,
    }
