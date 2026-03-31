"""Case and bottle management endpoints."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from winebox.models.bottle import Bottle
from winebox.models.bottle_event import BottleEvent, BottleEventType
from winebox.models.case import Case
from winebox.models.wine import Wine
from winebox.services.auth import RequireAuth

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------

class AddCaseRequest(BaseModel):
    """Request to add one or more cases of wine."""

    name: str = Field(..., max_length=500)
    winery: Optional[str] = Field(None, max_length=500)
    vintage: Optional[int] = Field(None, ge=1000, le=2100)
    grape_variety: Optional[str] = Field(None, max_length=500)
    country: Optional[str] = Field(None, max_length=255)
    region: Optional[str] = Field(None, max_length=255)
    wine_type: Optional[str] = Field(None, max_length=50)

    case_size: int = Field(..., ge=1, le=100)
    num_cases: int = Field(1, ge=1, le=100)
    purchase_date: Optional[datetime] = None
    purchase_price: Optional[float] = Field(None, ge=0)
    provenance: Optional[str] = Field(None, max_length=500)


class AddBottlesRequest(BaseModel):
    """Request to add loose bottles (no case)."""

    name: str = Field(..., max_length=500)
    winery: Optional[str] = Field(None, max_length=500)
    vintage: Optional[int] = Field(None, ge=1000, le=2100)
    grape_variety: Optional[str] = Field(None, max_length=500)
    country: Optional[str] = Field(None, max_length=255)
    region: Optional[str] = Field(None, max_length=255)
    wine_type: Optional[str] = Field(None, max_length=50)

    quantity: int = Field(..., ge=1, le=1000)


class AddEventRequest(BaseModel):
    """Request to record a bottle event."""

    event_type: BottleEventType
    event_date: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=2000)
    tasting_notes: Optional[str] = Field(None, max_length=2000)
    sale_price: Optional[float] = Field(None, ge=0)
    buyer: Optional[str] = Field(None, max_length=500)
    gift_recipient: Optional[str] = Field(None, max_length=500)


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


def _bottle_dict(
    owner_id: Any, wine: Wine, case_id: Any | None = None,
) -> dict[str, Any]:
    """Build a Bottle document dict with denormalised wine identity."""
    return {
        "owner_id": owner_id,
        "wine_id": wine.id,
        "case_id": case_id,
        "name": wine.name,
        "winery": wine.winery,
        "vintage": wine.vintage,
        "grape_variety": wine.grape_variety,
        "country": wine.country,
        "region": wine.region,
        "wine_type": wine.wine_type_id,
    }


async def _get_latest_event(bottle_id: Any) -> BottleEvent | None:
    """Get the most recent event for a bottle."""
    events = await BottleEvent.find(
        {"bottle_id": bottle_id}
    ).sort([("created_at", -1)]).limit(1).to_list()
    return events[0] if events else None


async def _count_bottles_in_cellar(query: dict[str, Any]) -> int:
    """Count bottles whose latest event is 'added' (still in cellar)."""
    # Get all bottle IDs matching the query
    bottle_col = Bottle.get_pymongo_collection()
    event_col = BottleEvent.get_pymongo_collection()

    bottle_ids = [
        doc["_id"]
        async for doc in bottle_col.find(query, {"_id": 1})
    ]
    if not bottle_ids:
        return 0

    # Aggregate: for each bottle, get latest event, keep only 'added'
    pipeline = [
        {"$match": {"bottle_id": {"$in": bottle_ids}}},
        {"$sort": {"created_at": -1}},
        {"$group": {"_id": "$bottle_id", "latest_type": {"$first": "$event_type"}}},
        {"$match": {"latest_type": BottleEventType.ADDED.value}},
        {"$count": "count"},
    ]
    result = await event_col.aggregate(pipeline).to_list(length=1)
    return result[0]["count"] if result else 0


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

    now = datetime.now(timezone.utc)
    cases_created = []
    total_bottles = 0

    for _ in range(request.num_cases):
        # Create case
        case = Case(
            owner_id=current_user.id,
            wine_id=wine.id,
            case_size=request.case_size,
            purchase_date=request.purchase_date,
            purchase_price=request.purchase_price,
            provenance=request.provenance,
            created_at=now,
        )
        await case.insert()

        # Create bottles with pre-generated IDs
        bottle_ids = [ObjectId() for _ in range(request.case_size)]
        bottles = [
            Bottle(id=bid, **_bottle_dict(current_user.id, wine, case_id=case.id), created_at=now)
            for bid in bottle_ids
        ]
        await Bottle.insert_many(bottles)

        # Create 'added' events
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

        total_bottles += request.case_size
        cases_created.append({
            "id": str(case.id),
            "case_size": request.case_size,
        })

    logger.info(
        "Created %d cases (%d bottles) of %s for user %s",
        request.num_cases, total_bottles, wine.name, current_user.id,
    )

    return {
        "wine_id": str(wine.id),
        "cases_created": len(cases_created),
        "bottles_created": total_bottles,
        "cases": cases_created,
    }


@router.get("")
async def list_cases(current_user: RequireAuth) -> dict:
    """List all cases for the current user."""
    cases = await Case.find({"owner_id": current_user.id}).sort(
        [("created_at", -1)]
    ).to_list()

    result = []
    for case in cases:
        remaining = await _count_bottles_in_cellar({"case_id": case.id})
        result.append({
            "id": str(case.id),
            "wine_id": str(case.wine_id),
            "case_size": case.case_size,
            "bottles_remaining": remaining,
            "purchase_date": case.purchase_date.isoformat() if case.purchase_date else None,
            "purchase_price": case.purchase_price,
            "provenance": case.provenance,
            "created_at": case.created_at.isoformat(),
        })

    return {"cases": result, "total": len(result)}


@router.get("/{case_id}")
async def get_case(case_id: str, current_user: RequireAuth) -> dict:
    """Get case details with bottle list."""
    try:
        oid = ObjectId(case_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Case not found")

    case = await Case.find_one({"_id": oid, "owner_id": current_user.id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Get all bottles in this case
    bottles = await Bottle.find({"case_id": case.id}).to_list()
    event_col = BottleEvent.get_pymongo_collection()

    bottle_list = []
    bottles_remaining = 0
    for bottle in bottles:
        # Get latest event
        latest = await event_col.find_one(
            {"bottle_id": bottle.id},
            sort=[("created_at", -1)],
        )
        status = latest["event_type"] if latest else "unknown"
        in_cellar = status == BottleEventType.ADDED.value

        if in_cellar:
            bottles_remaining += 1

        bottle_list.append({
            "id": str(bottle.id),
            "status": status,
            "in_cellar": in_cellar,
            "name": bottle.name,
            "created_at": bottle.created_at.isoformat(),
        })

    return {
        "id": str(case.id),
        "wine_id": str(case.wine_id),
        "case_size": case.case_size,
        "bottles_remaining": bottles_remaining,
        "bottles": bottle_list,
        "purchase_date": case.purchase_date.isoformat() if case.purchase_date else None,
        "purchase_price": case.purchase_price,
        "provenance": case.provenance,
        "created_at": case.created_at.isoformat(),
    }
