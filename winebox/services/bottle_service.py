"""Cellar item creation service — shared logic for all wine addition paths.

Whenever wine bottles enter the cellar (checkin, import, demo, met-to-cellar),
this service creates CellarItem documents (one per case or loose bottle)
and corresponding CellarEvent records.

The import pipeline batches thousands of rows per round-trip, so the shape
below is split into two layers:

- :func:`build_cellar_items_and_events` — pure function, no DB access.
  Returns the records to insert so callers can accumulate many wines'
  worth and issue a single ``insert_many``.
- :func:`create_cellar_items_for_wine` — convenience wrapper that calls
  the builder and inserts. Used by the one-wine-at-a-time paths
  (checkin, add-to-cellar, case add-via-API).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId

from winebox.db import PyObjectId
from winebox.models.cellar import CellarItem, EmbeddedWine
from winebox.models.cellar_event import CellarEvent, CellarEventType
from winebox.models.wine import Wine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CellarRecords:
    """The CellarItem + CellarEvent pair produced for one wine addition."""

    items: list[CellarItem]
    events: list[CellarEvent]


def _wine_to_embedded(wine: Wine) -> EmbeddedWine:
    """Snapshot wine identity into an immutable embedded descriptor."""
    return EmbeddedWine(
        wine_id=wine.id,
        name=wine.name,
        winery=wine.winery,
        vintage=wine.vintage,
        grape_variety=wine.grape_variety,
        country=wine.country,
        region=wine.region,
        wine_type=wine.wine_type,
        estimated_price_low=wine.estimated_price_low,
        estimated_price_high=wine.estimated_price_high,
        price_tier=wine.price_tier,
    )


def build_cellar_items_and_events(
    owner_id: PyObjectId,
    wine: Wine,
    quantity: int,
    case_size: Optional[int] = None,
    num_cases: int = 1,
    purchase_date: Optional[datetime] = None,
    purchase_price: Optional[float] = None,
    provenance: Optional[str] = None,
    created_at: Optional[datetime] = None,
    import_batch_id: Optional[PyObjectId] = None,
) -> CellarRecords:
    """Build CellarItem + CellarEvent records without inserting them.

    Rules:
      - ``case_size`` set and positive → ``num_cases`` cases plus a loose
        remainder for any bottles beyond ``num_cases * case_size``.
      - ``case_size`` unset → one loose-bottle item holding all ``quantity``.

    The ``import_batch_id`` tag on every record is what lets
    ``batch_ops.rollback_batch`` undo the cellar side of an import.
    """
    now = created_at or datetime.now(timezone.utc)
    embedded_wine = _wine_to_embedded(wine)
    items: list[CellarItem] = []
    events: list[CellarEvent] = []

    def _add(item_type: str, qty: int, **extra: Any) -> None:
        item_id = ObjectId()
        items.append(CellarItem(
            id=item_id,
            cellar_id=owner_id,
            item_type=item_type,
            wine=embedded_wine,
            quantity=qty,
            import_batch_id=import_batch_id,
            created_at=now,
            updated_at=now,
            **extra,
        ))
        events.append(CellarEvent(
            cellar_id=owner_id,
            cellar_item_id=item_id,
            item_type=item_type,
            event_type=CellarEventType.ADDED,
            quantity=qty,
            import_batch_id=import_batch_id,
            event_date=now,
            created_at=now,
        ))

    if case_size and case_size > 0:
        for _ in range(num_cases):
            _add(
                "case", case_size,
                case_size=case_size,
                purchase_price=purchase_price,
                purchase_date=purchase_date,
                provenance=provenance,
            )

        # 14 bottles with case_size=12 → 1 case + 2 loose
        loose_remainder = quantity - (num_cases * case_size)
        if loose_remainder > 0:
            _add("bottle", loose_remainder)
    else:
        _add("bottle", quantity)

    return CellarRecords(items=items, events=events)


async def create_cellar_items_for_wine(
    owner_id: PyObjectId,
    wine: Wine,
    quantity: int,
    case_size: Optional[int] = None,
    num_cases: int = 1,
    purchase_date: Optional[datetime] = None,
    purchase_price: Optional[float] = None,
    provenance: Optional[str] = None,
    created_at: Optional[datetime] = None,
    import_batch_id: Optional[PyObjectId] = None,
) -> dict[str, Any]:
    """Build and insert CellarItem + CellarEvent records for one wine.

    Used by the one-wine-at-a-time paths (checkin, add-to-cellar,
    case add-via-API). High-volume paths (import processor) should call
    :func:`build_cellar_items_and_events` directly and batch their own
    ``insert_many`` across many wines.

    Returns a dict with ``items_created``, ``cases_created``,
    ``bottles_created``, and the list of generated ``cellar_item_ids``.
    """
    records = build_cellar_items_and_events(
        owner_id=owner_id,
        wine=wine,
        quantity=quantity,
        case_size=case_size,
        num_cases=num_cases,
        purchase_date=purchase_date,
        purchase_price=purchase_price,
        provenance=provenance,
        created_at=created_at,
        import_batch_id=import_batch_id,
    )

    # Batch insert — 2 round-trips total
    await CellarItem.insert_many(records.items)
    await CellarEvent.insert_many(records.events)

    cases_created = sum(1 for i in records.items if i.item_type == "case")
    total_bottles = sum(i.quantity for i in records.items)

    logger.info(
        "Created %d cellar items (%d cases, %d bottles) for wine %s (owner %s)",
        len(records.items), cases_created, total_bottles, wine.name, owner_id,
    )

    return {
        "items_created": len(records.items),
        "cases_created": cases_created,
        "bottles_created": total_bottles,
        "cellar_item_ids": [item.id for item in records.items],
    }


# Legacy alias for backward compatibility during transition
create_bottles_for_wine = create_cellar_items_for_wine
