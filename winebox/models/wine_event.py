"""WineEvent model — unified append-only event log for bottles and cases.

Every state change is recorded as an event in a single collection.
Events can be scoped to an individual bottle or an entire case.

For bottles: scope='bottle', bottle_id set
For cases: scope='case', case_id set (also creates per-bottle events)

The current state of any bottle is derived from its most recent
bottle-scoped event. Events are never updated or deleted.
"""

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import Field

from winebox.db import MongoDocument, PyObjectId


class WineEventType(str, enum.Enum):
    """Types of wine events (applies to both bottles and cases)."""

    ADDED = "added"            # Entered the cellar
    PURCHASED = "purchased"    # Acquired (case-level)
    DRUNK = "drunk"            # Consumed by owner
    SOLD = "sold"              # Sold to someone
    GIFTED = "gifted"          # Given away
    BREAKAGE = "breakage"      # Broken or damaged
    OTHER = "other"            # Any other reason


class WineEventScope(str, enum.Enum):
    """Whether the event applies to a bottle or a case."""

    BOTTLE = "bottle"
    CASE = "case"


class WineEvent(MongoDocument):
    """An event in a bottle or case lifecycle — append-only, single collection."""

    owner_id: PyObjectId

    # Scope — determines which ID field is relevant
    scope: WineEventScope = WineEventScope.BOTTLE

    # Foreign keys (one or both set depending on scope)
    bottle_id: Optional[PyObjectId] = None  # Set for bottle-scoped events
    case_id: Optional[PyObjectId] = None    # Set for case-scoped events

    # Event details
    event_type: WineEventType
    event_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the event occurred (may differ from created_at)",
    )

    # Context fields (populated based on event_type)
    notes: Optional[str] = Field(None, max_length=2000)
    tasting_notes: Optional[str] = Field(None, max_length=2000)
    sale_price: Optional[float] = Field(None, ge=0)
    buyer: Optional[str] = Field(None, max_length=500)
    gift_recipient: Optional[str] = Field(None, max_length=500)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "wine_events"

    def __repr__(self) -> str:
        target = f"bottle={self.bottle_id}" if self.scope == WineEventScope.BOTTLE else f"case={self.case_id}"
        return f"<WineEvent({target}, type={self.event_type})>"


