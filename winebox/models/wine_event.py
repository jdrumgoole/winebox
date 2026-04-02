"""WineEvent model — append-only event log for individual bottle lifecycle.

Every state change for a bottle of wine is recorded as an event. The
current state of any bottle is derived from its most recent event.
Events are never updated or deleted — full audit trail.

A bottle is "in cellar" if its latest event is 'added'.
A bottle has left the cellar if its latest event is any other type.
"""

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import Field

from winebox.db import MongoDocument, PyObjectId


class WineEventType(str, enum.Enum):
    """Types of events in a bottle's lifecycle."""

    ADDED = "added"        # Bottle entered the cellar
    DRUNK = "drunk"        # Consumed by owner
    SOLD = "sold"          # Sold to someone
    GIFTED = "gifted"      # Given away
    BREAKAGE = "breakage"  # Broken or damaged
    OTHER = "other"        # Any other reason for leaving


# Backward-compatible aliases
BottleEventType = WineEventType


class WineEvent(MongoDocument):
    """An event in a bottle's lifecycle — append-only."""

    bottle_id: PyObjectId  # → Bottle record
    owner_id: PyObjectId

    # Event details
    event_type: WineEventType
    event_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the event occurred (may differ from created_at)",
    )

    # Context fields (populated based on event_type)
    notes: Optional[str] = Field(None, max_length=2000)
    tasting_notes: Optional[str] = Field(None, max_length=2000)  # For drunk
    sale_price: Optional[float] = Field(None, ge=0)              # For sold
    buyer: Optional[str] = Field(None, max_length=500)           # For sold
    gift_recipient: Optional[str] = Field(None, max_length=500)  # For gifted

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "bottle_events"  # Keep same collection name for backward compat

    def __repr__(self) -> str:
        return f"<WineEvent(id={self.id}, bottle_id={self.bottle_id}, type={self.event_type})>"


# Backward-compatible alias
BottleEvent = WineEvent
