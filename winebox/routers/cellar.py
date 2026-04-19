"""Cellar inventory endpoints.

Reads from the `cellars` collection — one document per physical item
(case or loose bottle) in the user's cellar.
"""

from typing import Any

from fastapi import APIRouter, Query

from winebox.models.cellar import CellarItem
from winebox.models import Wine
from winebox.models.wine import WineCollection
from winebox.schemas.wine import WineWithInventory
from winebox.services.auth import RequireAuth
from winebox.services.cellar_inventory import attach_breakdowns
from winebox.services.rate_limit import MAX_PAGE_SIZE, MAX_USER_RESULTSET

router = APIRouter()


@router.get("", response_model=list[WineWithInventory])
async def get_cellar_inventory(
    current_user: RequireAuth,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
) -> list[WineWithInventory]:
    """Get current cellar inventory (wines in stock)."""
    wines = await Wine.find(
        {"owner_id": current_user.id, "collection": WineCollection.CELLAR, "inventory.quantity": {"$gt": 0}}
    ).skip(skip).limit(limit).sort([("name", 1)]).to_list()

    results = [WineWithInventory.model_validate(wine) for wine in wines]
    await attach_breakdowns(results, wines, current_user.id)
    return results


@router.get("/summary")
async def get_cellar_summary(
    current_user: RequireAuth,
) -> dict:
    """Get cellar summary statistics.

    Uses $facet aggregation on the cellars collection for all breakdowns
    in one round-trip.
    """
    cellar_col = CellarItem.get_pymongo_collection()

    base_match = {
        "cellar_id": current_user.id,
        "quantity": {"$gt": 0},
    }

    pipeline = [
        {"$match": base_match},
        {"$facet": {
            "total_bottles": [
                {"$group": {"_id": None, "total": {"$sum": "$quantity"}}},
            ],
            "unique_wines": [
                {"$group": {"_id": "$wine.wine_id"}},
                {"$count": "count"},
            ],
            "total_cases": [
                {"$match": {"item_type": "case"}},
                {"$count": "count"},
            ],
            "by_vintage": [
                {"$match": {"wine.vintage": {"$ne": None}}},
                {"$group": {"_id": "$wine.vintage", "count": {"$sum": "$quantity"}}},
                {"$sort": {"_id": -1}},
            ],
            "by_country": [
                {"$match": {"wine.country": {"$ne": None}}},
                {"$group": {"_id": "$wine.country", "count": {"$sum": "$quantity"}}},
                {"$sort": {"count": -1}},
            ],
            "by_grape": [
                {"$match": {"wine.grape_variety": {"$ne": None}}},
                {"$group": {"_id": "$wine.grape_variety", "count": {"$sum": "$quantity"}}},
                {"$sort": {"count": -1}},
            ],
            "by_wine_type": [
                {"$match": {"wine.wine_type": {"$ne": None}}},
                {"$group": {"_id": "$wine.wine_type", "count": {"$sum": "$quantity"}}},
                {"$sort": {"count": -1}},
            ],
            "by_price_tier": [
                {"$match": {"wine.price_tier": {"$ne": None}}},
                {"$group": {"_id": "$wine.price_tier", "count": {"$sum": "$quantity"}}},
                {"$sort": {"count": -1}},
            ],
            "value_by_wine_type": [
                {"$addFields": {
                    "estimated_price_mid": {
                        "$cond": {
                            "if": {"$and": [
                                {"$ne": ["$wine.estimated_price_low", None]},
                                {"$ne": ["$wine.estimated_price_high", None]},
                            ]},
                            "then": {"$divide": [
                                {"$add": ["$wine.estimated_price_low", "$wine.estimated_price_high"]},
                                2,
                            ]},
                            "else": {"$cond": {
                                "if": {"$ne": ["$wine.estimated_price_low", None]},
                                "then": "$wine.estimated_price_low",
                                "else": "$wine.estimated_price_high",
                            }},
                        }
                    },
                }},
                {"$group": {
                    "_id": {"$ifNull": ["$wine.wine_type", "other"]},
                    "bottles": {"$sum": "$quantity"},
                    "total_value": {"$sum": {
                        "$multiply": [
                            {"$ifNull": ["$estimated_price_mid", 0]},
                            "$quantity",
                        ]
                    }},
                }},
                {"$sort": {"total_value": -1}},
            ],
        }},
    ]

    cursor = await cellar_col.aggregate(pipeline)
    result = await cursor.to_list(length=None)
    facets = result[0] if result else {}

    total_bottles = facets.get("total_bottles", [{}])[0].get("total", 0) if facets.get("total_bottles") else 0
    unique_wines = facets.get("unique_wines", [{}])[0].get("count", 0) if facets.get("unique_wines") else 0
    total_cases = facets.get("total_cases", [{}])[0].get("count", 0) if facets.get("total_cases") else 0

    by_vintage = {str(row["_id"]): row["count"] for row in facets.get("by_vintage", [])}
    by_country = {row["_id"]: row["count"] for row in facets.get("by_country", [])}
    by_grape = {row["_id"]: row["count"] for row in facets.get("by_grape", [])}
    by_wine_type = {row["_id"]: row["count"] for row in facets.get("by_wine_type", [])}
    by_price_tier = {row["_id"]: row["count"] for row in facets.get("by_price_tier", [])}
    value_by_wine_type = [
        {
            "wine_type": row["_id"],
            "bottles": row["bottles"],
            "total_value": round(row["total_value"], 2),
        }
        for row in facets.get("value_by_wine_type", [])
    ]

    return {
        "total_bottles": total_bottles,
        "unique_wines": unique_wines,
        "total_wines_tracked": unique_wines,
        "total_cases": total_cases,
        "by_vintage": by_vintage,
        "by_country": by_country,
        "by_grape_variety": by_grape,
        "by_wine_type": by_wine_type,
        "by_price_tier": by_price_tier,
        "value_by_wine_type": value_by_wine_type,
    }


@router.get("/grouped")
async def get_cellar_grouped(
    current_user: RequireAuth,
) -> dict:
    """Get cellar contents grouped by wine identity with case/bottle breakdown.

    Single query on the cellars collection — no cross-collection joins.
    """
    cellar_col = CellarItem.get_pymongo_collection()

    items = await cellar_col.find(
        {"cellar_id": current_user.id, "quantity": {"$gt": 0}}
    ).sort("wine.name", 1).to_list(length=MAX_USER_RESULTSET)

    # Group by wine_id
    wine_groups: dict[str, dict[str, Any]] = {}
    for item in items:
        wine = item.get("wine", {})
        wine_id = str(wine.get("wine_id", ""))
        if wine_id not in wine_groups:
            wine_groups[wine_id] = {
                "wine_id": wine_id,
                "name": wine.get("name", "Unknown"),
                "winery": wine.get("winery"),
                "vintage": wine.get("vintage"),
                "grape_variety": wine.get("grape_variety"),
                "country": wine.get("country"),
                "region": wine.get("region"),
                "wine_type": wine.get("wine_type"),
                "total_bottles": 0,
                "cases": [],
                "loose_bottles": 0,
            }

        group = wine_groups[wine_id]
        qty = item.get("quantity", 0)
        group["total_bottles"] += qty

        if item.get("item_type") == "case":
            group["cases"].append({
                "id": str(item["_id"]),
                "case_size": item.get("case_size", 0),
                "bottles_remaining": qty,
                "purchase_date": item.get("purchase_date"),
                "purchase_price": item.get("purchase_price"),
                "provenance": item.get("provenance"),
            })
        else:
            group["loose_bottles"] += qty

    wines = sorted(wine_groups.values(), key=lambda w: w["name"].lower())

    return {
        "wines": wines,
        "total_wines": len(wines),
        "total_bottles": sum(w["total_bottles"] for w in wines),
        "total_cases": sum(len(w["cases"]) for w in wines),
    }
