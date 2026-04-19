"""Case-aware cellar debit service.

Resolves a removal request (wine_id + quantity + optional cellar_item_id)
into a concrete list of (`CellarItem`, qty_to_debit) pairs, applies the
debits to the `cellars` collection, and records matching `CellarEvent`
rows so the event log stays in sync with the inventory mutation.

The checkout endpoint is the only caller today, but any future removal
path (admin, bulk, imports) should route through here so we have a
single source of truth for "which bottle(s) did we take off the shelf?"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId

from winebox.models.cellar import CellarItem
from winebox.models.cellar_event import CellarEvent, CellarEventType
from winebox.models.transaction import RemovalReason


# Map the Transaction-style `removal_reason` onto the CellarEvent-style
# `event_type`. Keeps Phase 3 small — Phase 4 drops RemovalReason entirely.
_REMOVAL_REASON_TO_EVENT_TYPE: dict[RemovalReason, CellarEventType] = {
    RemovalReason.DRINK: CellarEventType.DRUNK,
    RemovalReason.SELL: CellarEventType.SOLD,
    RemovalReason.GIFT: CellarEventType.GIFTED,
    RemovalReason.OTHER: CellarEventType.OTHER,
}


def event_type_from_removal_reason(reason: Optional[RemovalReason]) -> CellarEventType:
    """Default to DRUNK when no reason is supplied — matches what most
    freshly-recorded events mean historically."""
    if reason is None:
        return CellarEventType.DRUNK
    return _REMOVAL_REASON_TO_EVENT_TYPE.get(reason, CellarEventType.OTHER)


class CellarDebitError(ValueError):
    """Raised when a debit request cannot be satisfied.

    Carries an HTTP-friendly `status_code` so the router can surface the
    right response without recomputing the category:
    - 404 → source/wine not found, or malformed id (uniform to avoid
      cross-user existence leaks)
    - 422 → source exists but has insufficient bottles, or the requested
      quantity exceeds total available
    """

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class DebitedSource:
    """One (CellarItem, qty_debited) pair — the unit of a debit."""

    cellar_item_id: ObjectId
    item_type: str  # "case" | "bottle"
    quantity_debited: int
    case_size: Optional[int] = None
    provenance: Optional[str] = None


async def debit_cellar_for_wine(
    *,
    wine_id: ObjectId,
    owner_id: ObjectId,
    quantity: int,
    cellar_item_id: Optional[str] = None,
    event_type: CellarEventType = CellarEventType.DRUNK,
    removal_reason: Optional[RemovalReason] = None,
    event_notes: Optional[str] = None,
    removal_notes: Optional[str] = None,
    sale_price: Optional[float] = None,
    gift_recipient: Optional[str] = None,
    tasting_notes: Optional[str] = None,
) -> list[DebitedSource]:
    """Debit `quantity` bottles from this wine's cellar rows.

    When `cellar_item_id` is given, only that specific row is debited
    (so cases keep their provenance even when the user picks a source).
    When omitted, the helper picks in a deterministic order — loose
    bottles first, then the oldest case (by `purchase_date`, then
    `created_at`), consuming as many rows as needed to reach `quantity`.

    Applies the debit in place (updates `cellars.quantity`) and writes
    a `CellarEvent` per debited source.

    Returns the list of sources that were debited, in the order they
    were consumed. Callers can use this to populate legacy Transaction
    rows, log per-source audit info, or choose a primary source when
    only one ends up mattering (e.g. a 1-bottle debit).

    Raises `CellarDebitError` on any validation failure.
    """
    if quantity < 1:
        raise CellarDebitError("Quantity must be at least 1.", status_code=422)

    cellar_col = CellarItem.get_pymongo_collection()

    # Resolve candidate rows.
    if cellar_item_id is not None:
        try:
            item_oid = ObjectId(cellar_item_id)
        except (InvalidId, TypeError):
            # Malformed id — treat as not-found to avoid leaking whether
            # a valid-looking id belongs to another user.
            raise CellarDebitError("Cellar item not found.", status_code=404)

        item = await cellar_col.find_one({
            "_id": item_oid,
            "cellar_id": owner_id,
            "wine.wine_id": wine_id,
        })
        if item is None:
            raise CellarDebitError("Cellar item not found.", status_code=404)
        if (item.get("quantity") or 0) < quantity:
            bottles_remaining = item.get("quantity") or 0
            raise CellarDebitError(
                f"Source has {bottles_remaining} bottle(s) remaining; "
                f"cannot remove {quantity}.",
                status_code=422,
            )
        plan = [(item, quantity)]
    else:
        # Fallback: pick in deterministic order.
        # Loose bottles first — their provenance is undefined, so draining
        # them before touching a named case is what a careful cellarer
        # would do.
        items = await cellar_col.find({
            "cellar_id": owner_id,
            "wine.wine_id": wine_id,
            "quantity": {"$gt": 0},
        }).to_list(length=None)

        bottles = [i for i in items if i.get("item_type") == "bottle"]
        cases = sorted(
            (i for i in items if i.get("item_type") == "case"),
            key=lambda i: (
                i.get("purchase_date") or datetime.min.replace(tzinfo=timezone.utc),
                i.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
                i["_id"],
            ),
        )

        plan: list[tuple[dict, int]] = []
        remaining = quantity
        for item in (*bottles, *cases):
            if remaining <= 0:
                break
            available = item.get("quantity") or 0
            if available <= 0:
                continue
            take = min(available, remaining)
            plan.append((item, take))
            remaining -= take

        if remaining > 0:
            # Not enough physical rows to cover the request. Surface the
            # total available so the caller's error is actionable.
            total_available = sum((i.get("quantity") or 0) for i in items)
            raise CellarDebitError(
                f"Not enough bottles in stock. Available: {total_available}, "
                f"Requested: {quantity}.",
                status_code=422,
            )

    # Apply debits + record events.
    now = datetime.now(timezone.utc)
    debited: list[DebitedSource] = []
    for item, take in plan:
        await cellar_col.update_one(
            {"_id": item["_id"]},
            {"$inc": {"quantity": -take}, "$set": {"updated_at": now}},
        )
        # Pro-rate sale_price across multiple sources when the fallback
        # spreads the debit: total price / total bottles × bottles in this row.
        event_sale_price: Optional[float] = None
        if sale_price is not None and quantity > 0:
            event_sale_price = round(sale_price * take / quantity, 2)
        item_type = item.get("item_type", "bottle")
        event = CellarEvent(
            cellar_id=owner_id,
            owner_id=owner_id,
            wine_id=wine_id,
            cellar_item_id=item["_id"],
            item_type=item_type,
            event_type=event_type,
            quantity=take,
            event_date=now,
            removal_reason=removal_reason,
            notes=event_notes,
            removal_notes=removal_notes if event_type == CellarEventType.OTHER else None,
            tasting_notes=tasting_notes if event_type == CellarEventType.DRUNK else None,
            # Snapshot case context so the event survives the case being deleted.
            case_size_at_event=item.get("case_size") if item_type == "case" else None,
            provenance_at_event=item.get("provenance") if item_type == "case" else None,
            # Populate both `sale_price` (legacy) and `sale_price_usd` (clearer
            # unit name) so readers on either field work.
            sale_price=event_sale_price,
            sale_price_usd=event_sale_price,
            gift_recipient=gift_recipient if event_type == CellarEventType.GIFTED else None,
        )
        await event.insert()
        debited.append(DebitedSource(
            cellar_item_id=item["_id"],
            item_type=item.get("item_type", "bottle"),
            quantity_debited=take,
            case_size=item.get("case_size"),
            provenance=item.get("provenance"),
        ))

    return debited
