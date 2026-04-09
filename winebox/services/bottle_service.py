"""Cellar item creation service — shared logic for all wine addition paths.

Whenever wine bottles enter the cellar (checkin, import, demo, met-to-cellar),
this service creates CellarItem documents (one per case or loose bottle)
and corresponding CellarEvent records.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId

from winebox.db import PyObjectId
from winebox.models.cellar import CellarItem, EmbeddedWine
from winebox.models.cellar_event import CellarEvent, CellarEventType
from winebox.models.wine import Wine

logger = logging.getLogger(__name__)


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
        wine_type=wine.wine_type_id,
        estimated_price_low=wine.estimated_price_low,
        estimated_price_high=wine.estimated_price_high,
        price_tier=wine.price_tier,
    )


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
    """Create CellarItem and CellarEvent records for wine entering the cellar.

    Args:
        owner_id: Owner's ID.
        wine: The Wine record (identity).
        quantity: Number of bottles (if loose) or bottles per case.
        case_size: If set, creates cases of this size.
        num_cases: Number of cases to create (ignored if case_size is None).
        purchase_date: When the wine was purchased.
        purchase_price: Price paid per case (or per bottle if loose).
        provenance: Where the wine was bought.
        created_at: Override creation timestamp (for demo data).
        import_batch_id: Link to import batch (for undo).

    Returns:
        Dict with items_created, cases_created, cellar_item_ids.
    """
    now = created_at or datetime.now(timezone.utc)
    embedded_wine = _wine_to_embedded(wine)
    cellar_items: list[CellarItem] = []
    cellar_events: list[CellarEvent] = []

    if case_size and case_size > 0:
        for _ in range(num_cases):
            item = CellarItem(
                id=ObjectId(),
                cellar_id=owner_id,
                item_type="case",
                wine=embedded_wine,
                quantity=case_size,
                case_size=case_size,
                purchase_price=purchase_price,
                purchase_date=purchase_date,
                provenance=provenance,
                import_batch_id=import_batch_id,
                created_at=now,
                updated_at=now,
            )
            cellar_items.append(item)
            cellar_events.append(CellarEvent(
                cellar_id=owner_id,
                cellar_item_id=item.id,
                item_type="case",
                event_type=CellarEventType.ADDED,
                quantity=case_size,
                import_batch_id=import_batch_id,
                event_date=now,
                created_at=now,
            ))

        # Handle loose remainder (e.g. 14 bottles with case_size=12 → 1 case + 2 loose)
        loose_remainder = quantity - (num_cases * case_size)
        if loose_remainder > 0:
            item = CellarItem(
                id=ObjectId(),
                cellar_id=owner_id,
                item_type="bottle",
                wine=embedded_wine,
                quantity=loose_remainder,
                import_batch_id=import_batch_id,
                created_at=now,
                updated_at=now,
            )
            cellar_items.append(item)
            cellar_events.append(CellarEvent(
                cellar_id=owner_id,
                cellar_item_id=item.id,
                item_type="bottle",
                event_type=CellarEventType.ADDED,
                quantity=loose_remainder,
                import_batch_id=import_batch_id,
                event_date=now,
                created_at=now,
            ))
    else:
        # Loose bottles — one cellar item
        item = CellarItem(
            id=ObjectId(),
            cellar_id=owner_id,
            item_type="bottle",
            wine=embedded_wine,
            quantity=quantity,
            import_batch_id=import_batch_id,
            created_at=now,
            updated_at=now,
        )
        cellar_items.append(item)
        cellar_events.append(CellarEvent(
            cellar_id=owner_id,
            cellar_item_id=item.id,
            item_type="bottle",
            event_type=CellarEventType.ADDED,
            quantity=quantity,
            import_batch_id=import_batch_id,
            event_date=now,
            created_at=now,
        ))

    # Batch insert — 2 round-trips total
    await CellarItem.insert_many(cellar_items)
    await CellarEvent.insert_many(cellar_events)

    cases_created = sum(1 for i in cellar_items if i.item_type == "case")
    total_bottles = sum(i.quantity for i in cellar_items)

    logger.info(
        "Created %d cellar items (%d cases, %d bottles) for wine %s (owner %s)",
        len(cellar_items), cases_created, total_bottles, wine.name, owner_id,
    )

    return {
        "items_created": len(cellar_items),
        "cases_created": cases_created,
        "bottles_created": total_bottles,
        "cellar_item_ids": [item.id for item in cellar_items],
    }


# Legacy alias for backward compatibility during transition
create_bottles_for_wine = create_cellar_items_for_wine
