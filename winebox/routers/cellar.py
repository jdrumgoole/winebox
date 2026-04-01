"""Cellar inventory endpoints."""

from typing import Any

from fastapi import APIRouter

from winebox.models import Wine
from winebox.models.bottle import Bottle
from winebox.models.bottle_event import BottleEvent, BottleEventType
from winebox.models.case import Case
# Bottle/BottleEvent used by /grouped endpoint; Case used by /summary
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

    # Case count from cases collection
    case_col = Case.get_pymongo_collection()
    total_cases = await case_col.count_documents({"owner_id": current_user.id})

    return {
        "total_bottles": total_bottles,
        "unique_wines": unique_wines,
        "total_wines_tracked": total_wines_tracked,
        "total_cases": total_cases,
        "by_vintage": by_vintage,
        "by_country": by_country,
        "by_grape_variety": by_grape,
        "by_wine_type": by_wine_type,
        "by_price_tier": by_price_tier,
    }


@router.get("/grouped")
async def get_cellar_grouped(
    current_user: RequireAuth,
) -> dict:
    """Get cellar contents grouped by wine identity with case/bottle breakdown.

    Returns wines with their cases and loose bottles, all derived from
    the bottles collection (event-sourced state).
    """
    bottle_col = Bottle.get_pymongo_collection()
    event_col = BottleEvent.get_pymongo_collection()
    case_col = Case.get_pymongo_collection()

    # Get all bottles for this user with their latest event
    pipeline = [
        {"$match": {"owner_id": current_user.id}},
        {"$lookup": {
            "from": "bottle_events",
            "let": {"bid": "$_id"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$bottle_id", "$$bid"]}}},
                {"$sort": {"created_at": -1}},
                {"$limit": 1},
            ],
            "as": "latest_event",
        }},
        {"$addFields": {
            "status": {"$ifNull": [{"$arrayElemAt": ["$latest_event.event_type", 0]}, "unknown"]},
        }},
        {"$match": {"status": BottleEventType.ADDED.value}},  # Only bottles in cellar
    ]

    cursor = await bottle_col.aggregate(pipeline)
    bottles_in_cellar = await cursor.to_list(length=None)

    # Group by wine_id
    wine_groups: dict[str, dict[str, Any]] = {}
    for b in bottles_in_cellar:
        wine_id = str(b["wine_id"])
        if wine_id not in wine_groups:
            wine_groups[wine_id] = {
                "wine_id": wine_id,
                "name": b.get("name", "Unknown"),
                "winery": b.get("winery"),
                "vintage": b.get("vintage"),
                "grape_variety": b.get("grape_variety"),
                "country": b.get("country"),
                "region": b.get("region"),
                "wine_type": b.get("wine_type"),
                "total_bottles": 0,
                "cases": {},
                "loose_bottles": 0,
            }

        group = wine_groups[wine_id]
        group["total_bottles"] += 1

        case_id = b.get("case_id")
        if case_id:
            case_key = str(case_id)
            if case_key not in group["cases"]:
                group["cases"][case_key] = {"id": case_key, "bottles_remaining": 0}
            group["cases"][case_key]["bottles_remaining"] += 1
        else:
            group["loose_bottles"] += 1

    # Enrich cases with metadata
    all_case_ids = set()
    for g in wine_groups.values():
        all_case_ids.update(g["cases"].keys())

    if all_case_ids:
        from bson import ObjectId
        case_docs = await case_col.find(
            {"_id": {"$in": [ObjectId(cid) for cid in all_case_ids]}}
        ).to_list(length=None)
        case_lookup = {str(c["_id"]): c for c in case_docs}

        for g in wine_groups.values():
            enriched_cases = []
            for case_key, case_info in g["cases"].items():
                doc = case_lookup.get(case_key, {})
                enriched_cases.append({
                    "id": case_key,
                    "case_size": doc.get("case_size", 0),
                    "bottles_remaining": case_info["bottles_remaining"],
                    "purchase_date": doc.get("purchase_date", None),
                    "purchase_price": doc.get("purchase_price"),
                    "provenance": doc.get("provenance"),
                })
            g["cases"] = enriched_cases
    else:
        for g in wine_groups.values():
            g["cases"] = []

    wines = sorted(wine_groups.values(), key=lambda w: w["name"].lower())

    return {
        "wines": wines,
        "total_wines": len(wines),
        "total_bottles": sum(w["total_bottles"] for w in wines),
        "total_cases": sum(len(w["cases"]) for w in wines),
    }
