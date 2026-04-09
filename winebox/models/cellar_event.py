"""Cellar event model — tracks actions on physical items (cases and bottles).

Events happen to physical items, not to abstract wines. You drink a bottle,
sell a case — the wine descriptor is on the cellar item, not on the event.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import Field

from winebox.db import MongoDocument, PyObjectId


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
    cellar_item_id: PyObjectId  # References cellars._id
    item_type: str  # "case" | "bottle"
    event_type: CellarEventType
    quantity: int = 1  # Bottles affected

    # Context
    notes: Optional[str] = None
    tasting_notes: Optional[str] = None
    sale_price: Optional[float] = None
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
