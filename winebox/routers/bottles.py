"""Bottle management endpoints — loose bottles and event recording."""

import logging
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException

from winebox.models.bottle import Bottle
from winebox.models.bottle_event import BottleEvent, BottleEventType
from winebox.models.wine import Wine
from winebox.routers.cases import AddBottlesRequest, AddEventRequest, _find_or_create_wine, _bottle_dict
from winebox.services.auth import RequireAuth

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("")
async def add_loose_bottles(request: AddBottlesRequest, current_user: RequireAuth) -> dict:
    """Add loose bottles (no case) to the cellar.

    Creates a Wine record (or reuses existing), N Bottle records,
    and N 'added' events.
    """
    wine = await _find_or_create_wine(
        current_user.id,
        request.name, request.winery, request.vintage,
        request.grape_variety, request.country, request.region,
        request.wine_type,
    )

    now = datetime.now(timezone.utc)
    bottle_ids = [ObjectId() for _ in range(request.quantity)]
    bottles = [
        Bottle(id=bid, **_bottle_dict(current_user.id, wine, case_id=None), created_at=now)
        for bid in bottle_ids
    ]
    await Bottle.insert_many(bottles)

    events = [
        BottleEvent(
            bottle_id=bid,
            owner_id=current_user.id,
            event_type=BottleEventType.ADDED,
            event_date=now,
            created_at=now,
        )
        for bid in bottle_ids
    ]
    await BottleEvent.insert_many(events)

    logger.info(
        "Created %d loose bottles of %s for user %s",
        request.quantity, wine.name, current_user.id,
    )

    return {
        "wine_id": str(wine.id),
        "bottles_created": request.quantity,
    }


@router.get("")
async def list_bottles(
    current_user: RequireAuth,
    wine_id: str | None = None,
) -> dict:
    """List bottles, optionally filtered by wine_id, with current status."""
    query: dict[str, Any] = {"owner_id": current_user.id}
    if wine_id:
        try:
            query["wine_id"] = ObjectId(wine_id)
        except InvalidId:
            raise HTTPException(status_code=400, detail="Invalid wine_id")

    bottles = await Bottle.find(query).sort([("created_at", -1)]).to_list()
    event_col = BottleEvent.get_pymongo_collection()

    result = []
    for bottle in bottles:
        latest = await event_col.find_one(
            {"bottle_id": bottle.id},
            sort=[("created_at", -1)],
        )
        latest_type = latest["event_type"] if latest else "unknown"

        result.append({
            "id": str(bottle.id),
            "wine_id": str(bottle.wine_id),
            "case_id": str(bottle.case_id) if bottle.case_id else None,
            "name": bottle.name,
            "winery": bottle.winery,
            "vintage": bottle.vintage,
            "grape_variety": bottle.grape_variety,
            "country": bottle.country,
            "region": bottle.region,
            "wine_type": bottle.wine_type,
            "status": latest_type,
            "in_cellar": latest_type == BottleEventType.ADDED.value,
            "created_at": bottle.created_at.isoformat(),
        })

    return {"bottles": result, "total": len(result)}


@router.post("/{bottle_id}/events")
async def add_bottle_event(
    bottle_id: str,
    request: AddEventRequest,
    current_user: RequireAuth,
) -> dict:
    """Record an event for a bottle (drunk, sold, gifted, breakage, other).

    This changes the bottle's state. The bottle record itself is never
    modified — only events are appended.
    """
    try:
        oid = ObjectId(bottle_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Bottle not found")

    bottle = await Bottle.find_one({"_id": oid, "owner_id": current_user.id})
    if not bottle:
        raise HTTPException(status_code=404, detail="Bottle not found")

    # Don't allow 'added' events via this endpoint (use add_cases/add_loose_bottles)
    if request.event_type == BottleEventType.ADDED:
        raise HTTPException(
            status_code=400,
            detail="Cannot manually add 'added' events. Use the add cases/bottles endpoints.",
        )

    event = BottleEvent(
        bottle_id=bottle.id,
        owner_id=current_user.id,
        event_type=request.event_type,
        event_date=request.event_date or datetime.now(timezone.utc),
        notes=request.notes,
        tasting_notes=request.tasting_notes,
        sale_price=request.sale_price,
        buyer=request.buyer,
        gift_recipient=request.gift_recipient,
        created_at=datetime.now(timezone.utc),
    )
    await event.insert()

    logger.info(
        "Bottle %s event: %s (wine=%s, user=%s)",
        bottle_id, request.event_type.value, bottle.name, current_user.id,
    )

    return {
        "event_id": str(event.id),
        "bottle_id": bottle_id,
        "event_type": request.event_type.value,
    }


@router.get("/{bottle_id}/events")
async def get_bottle_events(
    bottle_id: str,
    current_user: RequireAuth,
) -> dict:
    """Get the event history for a bottle (most recent first)."""
    try:
        oid = ObjectId(bottle_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Bottle not found")

    bottle = await Bottle.find_one({"_id": oid, "owner_id": current_user.id})
    if not bottle:
        raise HTTPException(status_code=404, detail="Bottle not found")

    events = await BottleEvent.find(
        {"bottle_id": bottle.id}
    ).sort([("created_at", -1)]).to_list()

    return {
        "bottle_id": bottle_id,
        "events": [
            {
                "id": str(e.id),
                "event_type": e.event_type.value,
                "event_date": e.event_date.isoformat(),
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
