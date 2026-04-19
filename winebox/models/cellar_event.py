"""Cellar event model — tracks actions on physical items (cases and bottles).

Events happen to physical items, not to abstract wines. You drink a bottle,
sell a case — the wine descriptor is on the cellar item, not on the event.

Phase 4 of the cases-first-class plan converges the legacy `Transaction`
collection onto this model. To act as a superset of `Transaction`, the
schema gained:

- `wine_id` / `owner_id` — denormalised so the wine-scoped and user-scoped
  queries Transaction supports today don't need to follow `cellar_item_id`
  back to the `cellars` collection.
- `case_size_at_event` / `provenance_at_event` — frozen snapshots so the
  activity feed still reads correctly after a case is fully consumed and
  its `cellars` row is deleted.
- `removal_reason` / `removal_notes` — match the categorical fields the
  Transaction-driven UI already understands.
- `sale_price_usd` — clearer unit name; `sale_price` is kept populated for
  backward compatibility with existing readers.

All new fields are Optional — pre-Phase-4 events stay valid and the
backfill (4c) can fill what it can.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import Field

from winebox.db import MongoDocument, PyObjectId
from winebox.models.transaction import RemovalReason


class CellarEventType(str, Enum):
    """Types of events that can happen to cellar items."""

    ADDED = "added"
    DRUNK = "drunk"
    SOLD = "sold"
    GIFTED = "gifted"
    BREAKAGE = "breakage"
    OTHER = "other"


class CellarEvent(MongoDocument):
    """One event per action on a cellar item (case or bottle)."""

    cellar_id: PyObjectId  # = user._id
    cellar_item_id: Optional[PyObjectId] = None  # nullable for legacy backfill rows
    item_type: str  # "case" | "bottle" | "legacy" (for unmigrated Transaction rows)
    event_type: CellarEventType
    quantity: int = 1  # Bottles affected

    # Phase 4 — denormalised for fast wine-scoped / user-scoped queries that
    # Transaction supports today. Optional so existing rows stay valid until
    # the backfill catches them up; new writes always populate both.
    wine_id: Optional[PyObjectId] = None
    owner_id: Optional[PyObjectId] = None  # mirror of cellar_id

    # Phase 4 — case context snapshots, frozen at event time so the UI
    # still reads after the case row is deleted.
    case_size_at_event: Optional[int] = None
    provenance_at_event: Optional[str] = None

    # Phase 4 — Transaction-level reason granularity. `event_type` is the
    # canonical enum; `removal_reason` is the parallel UI-facing one
    # ({DRUNK↔DRINK, SOLD↔SELL, GIFTED↔GIFT, OTHER↔OTHER}).
    removal_reason: Optional[RemovalReason] = None
    removal_notes: Optional[str] = None  # distinct from generic `notes`

    # Context
    notes: Optional[str] = None
    tasting_notes: Optional[str] = None
    sale_price: Optional[float] = None  # legacy; populated alongside sale_price_usd
    sale_price_usd: Optional[float] = None
    buyer: Optional[str] = None
    gift_recipient: Optional[str] = None

    # Tracking
    import_batch_id: Optional[PyObjectId] = None
    event_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    class Settings:
        name = "cellar_events"
