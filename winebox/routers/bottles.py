"""Bottle management endpoints — loose bottles and removal events.

All data lives in the cellars and cellar_events collections.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException

from winebox.models.cellar import CellarItem
from winebox.models.cellar_event import CellarEvent, CellarEventType
from winebox.models.wine import Wine
from winebox.routers.cases import AddBottlesRequest, AddEventRequest, _find_or_create_wine
from winebox.services.auth import RequireAuth

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("")
async def add_loose_bottles(request: AddBottlesRequest, current_user: RequireAuth) -> dict:
    """Add loose bottles (no case) to the cellar."""
    wine = await _find_or_create_wine(
        current_user.id,
        request.name, request.winery, request.vintage,
        request.grape_variety, request.country, request.region,
        request.wine_type,
    )

    from winebox.services.bottle_service import create_cellar_items_for_wine
    result = await create_cellar_items_for_wine(
        owner_id=current_user.id,
        wine=wine,
        quantity=request.quantity,
    )

    # Sync Wine.inventory.quantity so search finds this wine
    wines_col = Wine.get_pymongo_collection()
    await wines_col.update_one(
        {"_id": wine.id},
        {"$inc": {"inventory.quantity": request.quantity}},
    )

    return {
        "wine_id": str(wine.id),
        "bottles_created": result["bottles_created"],
    }


@router.get("")
async def list_bottles(
    current_user: RequireAuth,
    wine_id: str | None = None,
) -> dict:
    """List cellar items, optionally filtered by wine_id.

    Returns items in a format compatible with the frontend removal flow.
    Each item has an id, quantity, and in_cellar status.
    """
    cellar_col = CellarItem.get_pymongo_collection()
    query: dict[str, Any] = {"cellar_id": current_user.id}
    if wine_id:
        try:
            query["wine.wine_id"] = ObjectId(wine_id)
        except InvalidId:
            raise HTTPException(status_code=400, detail="Invalid wine_id")

    items = await cellar_col.find(query).sort("created_at", -1).to_list(length=None)

    result = []
    for item in items:
        wine = item.get("wine", {})
        qty = item.get("quantity", 0)
        result.append({
            "id": str(item["_id"]),
            "wine_id": str(wine.get("wine_id", "")),
            "case_id": str(item["_id"]) if item.get("item_type") == "case" else None,
            "name": wine.get("name", ""),
            "winery": wine.get("winery"),
            "vintage": wine.get("vintage"),
            "grape_variety": wine.get("grape_variety"),
            "country": wine.get("country"),
            "region": wine.get("region"),
            "wine_type": wine.get("wine_type"),
            "status": "added" if qty > 0 else "removed",
            "in_cellar": qty > 0,
            "quantity": qty,
            "item_type": item.get("item_type", "bottle"),
            "created_at": item["created_at"].isoformat() if item.get("created_at") else None,
        })

    return {"bottles": result, "total": len(result)}


@router.post("/{item_id}/events")
async def add_item_event(
    item_id: str,
    request: AddEventRequest,
    current_user: RequireAuth,
) -> dict:
    """Record a removal event for a cellar item (drunk, sold, gifted, etc.).

    Decrements the item's quantity and creates a CellarEvent.
    """
    try:
        oid = ObjectId(item_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Item not found")

    cellar_col = CellarItem.get_pymongo_collection()
    item = await cellar_col.find_one({"_id": oid, "cellar_id": current_user.id})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if request.event_type == CellarEventType.ADDED:
        raise HTTPException(
            status_code=400,
            detail="Cannot manually add 'added' events. Use the add cases/bottles endpoints.",
        )

    current_qty = item.get("quantity", 0)
    if current_qty <= 0:
        return {
            "event_id": None,
            "bottle_id": item_id,
            "event_type": request.event_type.value,
        }

    now = request.event_date or datetime.now(timezone.utc)

    # Decrement by 1 (the frontend removes one bottle at a time)
    new_qty = max(0, current_qty - 1)
    await cellar_col.update_one(
        {"_id": oid},
        {"$set": {"quantity": new_qty, "updated_at": now}},
    )

    event = CellarEvent(
        cellar_id=current_user.id,
        cellar_item_id=oid,
        item_type=item.get("item_type", "bottle"),
        event_type=request.event_type,
        quantity=1,
        event_date=now,
        notes=request.notes,
        tasting_notes=request.tasting_notes,
        sale_price=request.sale_price,
        buyer=request.buyer,
        gift_recipient=request.gift_recipient,
    )
    await event.insert()

    wine = item.get("wine", {})
    logger.info(
        "Cellar item %s event: %s (wine=%s, user=%s)",
        item_id, request.event_type.value, wine.get("name"), current_user.id,
    )

    return {
        "event_id": str(event.id),
        "bottle_id": item_id,
        "event_type": request.event_type.value,
    }


@router.get("/{item_id}/events")
async def get_item_events(
    item_id: str,
    current_user: RequireAuth,
) -> dict:
    """Get the event history for a cellar item (most recent first)."""
    try:
        oid = ObjectId(item_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Item not found")

    cellar_col = CellarItem.get_pymongo_collection()
    item = await cellar_col.find_one({"_id": oid, "cellar_id": current_user.id})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    events = await CellarEvent.find(
        {"cellar_item_id": oid}
    ).sort([("created_at", -1)]).to_list()

    return {
        "bottle_id": item_id,
        "events": [
            {
                "id": str(e.id),
                "event_type": e.event_type.value,
                "event_date": e.event_date.isoformat(),
                "quantity": e.quantity,
                "notes": e.notes,
                "tasting_notes": e.tasting_notes,
                "sale_price": e.sale_price,
                "buyer": e.buyer,
                "gift_recipient": e.gift_recipient,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
    }
