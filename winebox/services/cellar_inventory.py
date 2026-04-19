"""Cellar-inventory breakdown service.

Computes the case-vs-loose breakdown of a wine's inventory from the
`CellarItem` collection so every UI surface (search, wine list, detail,
cellar) can render the same chips without a second round-trip or an N+1
query.

Single source of truth for the per-wine case/loose math — mirrors the
logic already in `winebox/routers/cellar.py:get_cellar_grouped` but
generalised over an arbitrary set of wine ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId

from winebox.models.cellar import CellarItem


@dataclass
class CaseEntry:
    """One case of a wine in the cellar. Plain-dict-friendly."""

    cellar_item_id: str
    case_size: int
    bottles_remaining: int
    provenance: Optional[str] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "cellar_item_id": self.cellar_item_id,
            "case_size": self.case_size,
            "bottles_remaining": self.bottles_remaining,
            "provenance": self.provenance,
            "purchase_price": self.purchase_price,
            "purchase_date": self.purchase_date,
        }


@dataclass
class Breakdown:
    """Case/loose decomposition for a single wine."""

    cases: list[CaseEntry] = field(default_factory=list)
    loose_bottles: int = 0
    total_quantity: int = 0
    first_case_size: Optional[int] = None

    def to_inventory_dict(self, updated_at: Optional[datetime] = None) -> dict:
        """Shape compatible with `winebox.schemas.wine.InventoryInfo`."""
        return {
            "quantity": self.total_quantity,
            "case_size": self.first_case_size,
            "cases": [c.to_dict() for c in self.cases],
            "loose_bottles": self.loose_bottles,
            "updated_at": updated_at,
        }


async def fetch_breakdowns_for_wines(
    wine_ids: list[ObjectId], owner_id: ObjectId
) -> dict[str, Breakdown]:
    """Return `{wine_id_str: Breakdown}` for every requested id.

    One Mongo round-trip via `$in` — so callers pay constant cost
    regardless of page size. Wines with no cellar rows get an empty
    `Breakdown` so the caller can apply the same shape uniformly.

    Case ordering within a wine is stable: oldest purchase first, then
    provenance alphabetical, then cellar_item_id as last-resort tiebreak.
    """
    breakdowns: dict[str, Breakdown] = {str(wid): Breakdown() for wid in wine_ids}
    if not wine_ids:
        return breakdowns

    cellar_col = CellarItem.get_pymongo_collection()
    cursor = cellar_col.find({
        "cellar_id": owner_id,
        "wine.wine_id": {"$in": wine_ids},
        "quantity": {"$gt": 0},
    })
    items = await cursor.to_list(length=None)

    for item in items:
        wine = item.get("wine") or {}
        wid = str(wine.get("wine_id", ""))
        if wid not in breakdowns:
            continue
        bucket = breakdowns[wid]
        qty = int(item.get("quantity") or 0)
        bucket.total_quantity += qty

        if item.get("item_type") == "case":
            case_size = int(item.get("case_size") or 0)
            bucket.cases.append(CaseEntry(
                cellar_item_id=str(item["_id"]),
                case_size=case_size,
                bottles_remaining=qty,
                provenance=item.get("provenance"),
                purchase_price=item.get("purchase_price"),
                purchase_date=item.get("purchase_date"),
            ))
            if bucket.first_case_size is None and case_size > 0:
                bucket.first_case_size = case_size
        else:
            bucket.loose_bottles += qty

    for bucket in breakdowns.values():
        bucket.cases.sort(
            key=lambda c: (
                c.purchase_date or datetime.min,
                c.provenance or "",
                c.cellar_item_id,
            )
        )
        # first_case_size after sort == size of the earliest-purchased case
        bucket.first_case_size = bucket.cases[0].case_size if bucket.cases else None

    return breakdowns


async def attach_breakdowns(
    responses: list,  # list[WineWithInventory] — untyped to avoid schema import cycle
    wines: list,      # list[Wine] — source docs (parallel to responses)
    owner_id: ObjectId,
) -> None:
    """Mutate each `WineWithInventory` response in place to carry its
    case/loose breakdown.

    Contract (and why this looks more careful than "just overwrite"):
    - The aggregate `quantity` is **preserved** from the Wine doc's
      embedded `InventoryInfo`. Today there are two write paths that
      maintain inventory state — `/api/cases` / `/api/bottles` update
      CellarItem *and* the Wine doc, while `/api/wines/record` +
      `/api/wines/{id}/checkout` update only the Wine doc. Overwriting
      `quantity` from CellarItem would desync the record-then-checkout
      path. Phase 4 of the cases-first-class plan converges these onto
      CellarEvent; until then, the Wine doc's aggregate is authoritative.
    - `cases[]` is taken from CellarItem rows with `item_type="case"` —
      these are the only case records, so CellarItem is authoritative
      for case shape and provenance.
    - `loose_bottles` is derived as `max(0, quantity - sum(cases))` so
      cases always reconcile against the aggregate, even when the two
      write paths briefly disagree.
    - `case_size` echoes the first case's size for backward compatibility.

    Pairs 1:1 with `wines`. Wines owned by someone else get an empty
    breakdown — defence in depth against a wire-up mistake leaking
    another user's cases.
    """
    from winebox.schemas.wine import CaseBreakdown, InventoryInfo

    if not responses:
        return
    wine_ids = [w.id for w in wines if w.owner_id == owner_id]
    breakdowns = await fetch_breakdowns_for_wines(wine_ids, owner_id)

    for response, wine in zip(responses, wines):
        wid = str(wine.id)
        breakdown = breakdowns.get(wid, Breakdown())
        existing = response.inventory
        aggregate_quantity = existing.quantity if existing else 0
        existing_updated = existing.updated_at if existing else None

        cases_total = sum(c.bottles_remaining for c in breakdown.cases)
        loose_derived = max(0, aggregate_quantity - cases_total)

        response.inventory = InventoryInfo(
            quantity=aggregate_quantity,
            case_size=breakdown.first_case_size,
            cases=[CaseBreakdown(**c.to_dict()) for c in breakdown.cases],
            loose_bottles=loose_derived,
            updated_at=existing_updated or datetime.now(timezone.utc),
        )
