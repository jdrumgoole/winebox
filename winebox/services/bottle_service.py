"""Bottle creation service — shared logic for all wine addition paths.

Whenever wine bottles enter the cellar (checkin, import, demo, met-to-cellar),
this service creates the corresponding Bottle + WineEvent records.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId

from winebox.db import PyObjectId
from winebox.models.bottle import Bottle
from winebox.models.wine_event import WineEvent, WineEventType, WineEventScope
from winebox.models.case import Case
from winebox.models.wine import Wine

logger = logging.getLogger(__name__)


async def create_bottles_for_wine(
    owner_id: PyObjectId,
    wine: Wine,
    quantity: int,
    case_size: Optional[int] = None,
    num_cases: int = 1,
    purchase_date: Optional[datetime] = None,
    purchase_price: Optional[float] = None,
    provenance: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Create Bottle and WineEvent records for wine entering the cellar.

    Args:
        owner_id: Owner's ID.
        wine: The Wine record (identity).
        quantity: Number of bottles (if loose) or bottles per case.
        case_size: If set, creates cases of this size.
        num_cases: Number of cases to create (ignored if case_size is None).
        purchase_date: When the wine was purchased.
        purchase_price: Price paid (per case if cased, per bottle if loose).
        provenance: Where the wine was bought.
        created_at: Override creation timestamp (for migrations/demo).

    Returns:
        Dict with bottles_created, cases_created, case_ids, bottle_ids.
    """
    now = created_at or datetime.now(timezone.utc)
    all_bottle_ids: list[ObjectId] = []
    case_ids: list[ObjectId] = []

    if case_size and case_size > 0:
        # Create all cases, then batch-insert bottles and events
        all_cases = []
        all_bottles = []
        all_events = []

        for _ in range(num_cases):
            case = Case(
                owner_id=owner_id,
                wine_id=wine.id,
                case_size=case_size,
                purchase_date=purchase_date,
                purchase_price=purchase_price,
                provenance=provenance,
                created_at=now,
            )
            all_cases.append(case)
            case_ids.append(case.id)

            bottle_ids = [ObjectId() for _ in range(case_size)]
            for bid in bottle_ids:
                all_bottles.append(Bottle(
                    id=bid,
                    owner_id=owner_id,
                    wine_id=wine.id,
                    case_id=case.id,
                    name=wine.name,
                    winery=wine.winery,
                    vintage=wine.vintage,
                    grape_variety=wine.grape_variety,
                    country=wine.country,
                    region=wine.region,
                    wine_type=wine.wine_type_id,
                    created_at=now,
                ))
                all_events.append(WineEvent(
                    scope=WineEventScope.BOTTLE,
                    bottle_id=bid,
                    owner_id=owner_id,
                    event_type=WineEventType.ADDED,
                    event_date=now,
                    created_at=now,
                ))
            all_bottle_ids.extend(bottle_ids)

        # 3 round-trips total regardless of num_cases
        await Case.insert_many(all_cases)
        await Bottle.insert_many(all_bottles)
        await WineEvent.insert_many(all_events)
    else:
        # Create loose bottles
        bottle_ids = [ObjectId() for _ in range(quantity)]
        bottles = [
            Bottle(
                id=bid,
                owner_id=owner_id,
                wine_id=wine.id,
                case_id=None,
                name=wine.name,
                winery=wine.winery,
                vintage=wine.vintage,
                grape_variety=wine.grape_variety,
                country=wine.country,
                region=wine.region,
                wine_type=wine.wine_type_id,
                created_at=now,
            )
            for bid in bottle_ids
        ]
        await Bottle.insert_many(bottles)

        events = [
            WineEvent(scope=WineEventScope.BOTTLE, 
                bottle_id=bid,
                owner_id=owner_id,
                event_type=WineEventType.ADDED,
                event_date=now,
                created_at=now,
            )
            for bid in bottle_ids
        ]
        await WineEvent.insert_many(events)
        all_bottle_ids.extend(bottle_ids)

    total_bottles = len(all_bottle_ids)
    logger.info(
        "Created %d bottles (%d cases) for wine %s (owner %s)",
        total_bottles, len(case_ids), wine.name, owner_id,
    )

    return {
        "bottles_created": total_bottles,
        "cases_created": len(case_ids),
        "bottle_ids": all_bottle_ids,
        "case_ids": case_ids,
    }
