"""Case and bottle management endpoints."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from winebox.models.cellar_event import CellarEventType

from winebox.models.wine import Wine
from winebox.services.auth import RequireAuth

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------

class _WineIdentity(BaseModel):
    """Fields that identify the wine a case or loose bottle refers to.

    Split out so AddCaseRequest and AddBottlesRequest can't drift on
    field constraints (they already had identical validation).
    """

    name: str = Field(..., max_length=500)
    winery: Optional[str] = Field(None, max_length=500)
    vintage: Optional[int] = Field(None, ge=1900, le=2100)
    grape_variety: Optional[str] = Field(None, max_length=500)
    country: Optional[str] = Field(None, max_length=255)
    region: Optional[str] = Field(None, max_length=255)
    wine_type: Optional[str] = Field(None, max_length=50)


class AddCaseRequest(_WineIdentity):
    """Request to add one or more cases of wine."""

    case_size: int = Field(..., ge=1, le=100)
    num_cases: int = Field(1, ge=1, le=100)
    purchase_date: Optional[datetime] = None
    purchase_price: Optional[float] = Field(None, ge=0)
    provenance: Optional[str] = Field(None, max_length=500)


class AddBottlesRequest(_WineIdentity):
    """Request to add loose bottles (no case)."""

    quantity: int = Field(..., ge=1, le=1000)


class AddCaseEventRequest(BaseModel):
    """Request to record a case-level event (sold, gifted, etc.)."""

    event_type: CellarEventType
    event_date: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=2000)
    sale_price: Optional[float] = Field(None, ge=0)
    buyer: Optional[str] = Field(None, max_length=500)
    gift_recipient: Optional[str] = Field(None, max_length=500)


class AddEventRequest(AddCaseEventRequest):
    """Request to record a bottle (wine) event — adds tasting_notes."""

    tasting_notes: Optional[str] = Field(None, max_length=2000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _find_or_create_wine(
    owner_id: Any,
    name: str,
    winery: str | None = None,
    vintage: int | None = None,
    grape_variety: str | None = None,
    country: str | None = None,
    region: str | None = None,
    wine_type: str | None = None,
) -> Wine:
    """Find an existing Wine by identity or create a new one."""
    conditions: dict[str, Any] = {"owner_id": owner_id, "name": name}
    if winery:
        conditions["winery"] = winery
    if vintage:
        conditions["vintage"] = vintage

    wine = await Wine.find_one(conditions)
    if wine:
        return wine

    wine = Wine(
        owner_id=owner_id,
        name=name,
        winery=winery,
        vintage=vintage,
        grape_variety=grape_variety,
        country=country,
        region=region,
        wine_type_id=wine_type,
        front_label_text="",
    )
    await wine.insert()
    return wine



# ---------------------------------------------------------------------------
# Case endpoints
# ---------------------------------------------------------------------------

@router.post("")
async def add_cases(request: AddCaseRequest, current_user: RequireAuth) -> dict:
    """Add one or more cases of wine to the cellar.

    Creates a Wine record (or reuses existing), N Case records,
    and N × case_size Bottle records with 'added' events.
    """
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
        quantity=request.num_cases * request.case_size,
        case_size=request.case_size,
        num_cases=request.num_cases,
        purchase_date=request.purchase_date,
        purchase_price=request.purchase_price,
        provenance=request.provenance,
    )

    # Sync Wine.inventory.quantity
    total_bottles = request.num_cases * request.case_size
    wines_col = Wine.get_pymongo_collection()
    await wines_col.update_one(
        {"_id": wine.id},
        {"$inc": {"inventory.quantity": total_bottles}},
    )

    # Build response matching old format
    from winebox.models.cellar import CellarItem
    cellar_col = CellarItem.get_pymongo_collection()
    case_items = await cellar_col.find({
        "cellar_id": current_user.id,
        "item_type": "case",
        "wine.wine_id": wine.id,
    }).sort("created_at", -1).limit(request.num_cases).to_list(length=request.num_cases)

    cases_created_list = [
        {"id": str(item["_id"]), "case_size": item.get("case_size", 0)}
        for item in case_items
    ]

    logger.info(
        "Created %d cases (%d bottles) of %s for user %s",
        result["cases_created"], result["bottles_created"], wine.name, current_user.id,
    )

    return {
        "wine_id": str(wine.id),
        "cases_created": result["cases_created"],
        "bottles_created": result["bottles_created"],
        "cases": cases_created_list,
    }


@router.get("")
async def list_cases(current_user: RequireAuth) -> dict:
    """List all cases for the current user from the cellars collection."""
    from winebox.models.cellar import CellarItem
    cellar_col = CellarItem.get_pymongo_collection()

    from winebox.services.rate_limit import MAX_USER_RESULTSET
    items = await cellar_col.find(
        {"cellar_id": current_user.id, "item_type": "case"}
    ).sort("created_at", -1).to_list(length=MAX_USER_RESULTSET)

    result = []
    for item in items:
        wine = item.get("wine", {})
        result.append({
            "id": str(item["_id"]),
            "wine_id": str(wine.get("wine_id", "")),
            "case_size": item.get("case_size", 0),
            "bottles_remaining": item.get("quantity", 0),
            "purchase_date": item["purchase_date"].isoformat() if item.get("purchase_date") else None,
            "purchase_price": item.get("purchase_price"),
            "provenance": item.get("provenance"),
            "created_at": item["created_at"].isoformat(),
        })

    return {"cases": result, "total": len(result)}


@router.get("/{case_id}")
async def get_case(case_id: str, current_user: RequireAuth) -> dict:
    """Get case details from the cellars collection."""
    from winebox.models.cellar import CellarItem
    try:
        oid = ObjectId(case_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Case not found")

    cellar_col = CellarItem.get_pymongo_collection()
    item = await cellar_col.find_one({
        "_id": oid, "cellar_id": current_user.id, "item_type": "case"
    })
    if not item:
        raise HTTPException(status_code=404, detail="Case not found")

    wine = item.get("wine", {})

    return {
        "id": str(item["_id"]),
        "wine_id": str(wine.get("wine_id", "")),
        "case_size": item.get("case_size", 0),
        "bottles_remaining": item.get("quantity", 0),
        "purchase_date": item["purchase_date"].isoformat() if item.get("purchase_date") else None,
        "purchase_price": item.get("purchase_price"),
        "provenance": item.get("provenance"),
        "created_at": item["created_at"].isoformat() if item.get("created_at") else None,
    }


@router.post("/{case_id}/events")
async def add_case_event(
    case_id: str,
    request: AddCaseEventRequest,
    current_user: RequireAuth,
) -> dict:
    """Record a case-level event (sold, gifted, etc.).

    Creates a CellarEvent and decrements the case's quantity.
    """
    from winebox.models.cellar import CellarItem
    from winebox.models.cellar_event import CellarEvent, CellarEventType

    try:
        oid = ObjectId(case_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Case not found")

    cellar_col = CellarItem.get_pymongo_collection()
    item = await cellar_col.find_one({
        "_id": oid, "cellar_id": current_user.id, "item_type": "case"
    })
    if not item:
        raise HTTPException(status_code=404, detail="Case not found")

    now = request.event_date or datetime.now(timezone.utc)
    bottles_remaining = item.get("quantity", 0)

    if bottles_remaining <= 0:
        return {
            "event_id": None,
            "case_id": case_id,
            "event_type": request.event_type.value,
            "bottles_affected": 0,
        }

    # Create cellar event
    event = CellarEvent(
        cellar_id=current_user.id,
        cellar_item_id=oid,
        item_type="case",
        event_type=request.event_type,
        quantity=bottles_remaining,
        event_date=now,
        notes=request.notes,
        sale_price=request.sale_price,
        buyer=request.buyer,
        gift_recipient=request.gift_recipient,
    )
    await event.insert()

    # Decrement case quantity to 0 (entire case affected)
    await cellar_col.update_one(
        {"_id": oid},
        {"$set": {"quantity": 0, "updated_at": now}},
    )

    logger.info(
        "Case %s event: %s (%d bottles affected, user %s)",
        case_id, request.event_type.value, bottles_remaining, current_user.id,
    )

    return {
        "event_id": str(event.id),
        "case_id": case_id,
        "event_type": request.event_type.value,
        "bottles_affected": bottles_remaining,
    }
