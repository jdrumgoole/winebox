"""CaseEvent model — append-only event log for case lifecycle.

When an entire case is bought, sold, gifted, etc., a single CaseEvent
records the action rather than creating individual BottleEvents for
every bottle. The state of each bottle in the case is derived from:
  1. The latest CaseEvent on its parent case (if any)
  2. OR the latest BottleEvent on the bottle itself

A bottle-level event overrides a case-level event (e.g. if a case was
sold but one bottle was kept, that bottle gets an individual 'added'
event to bring it back).
"""

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import Field

from winebox.db import MongoDocument, PyObjectId


class CaseEventType(str, enum.Enum):
    """Types of events in a case's lifecycle."""

    PURCHASED = "purchased"    # Case acquired (first event)
    SOLD = "sold"              # Entire case sold
    GIFTED = "gifted"          # Entire case given away
    BREAKAGE = "breakage"      # Entire case damaged
    OTHER = "other"            # Any other case-level event


class CaseEvent(MongoDocument):
    """An event in a case's lifecycle — append-only."""

    case_id: PyObjectId  # → Case record
    owner_id: PyObjectId

    # Event details
    event_type: CaseEventType
    event_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    # Context fields
    notes: Optional[str] = Field(None, max_length=2000)
    sale_price: Optional[float] = Field(None, ge=0)  # For sold
    buyer: Optional[str] = Field(None, max_length=500)  # For sold
    gift_recipient: Optional[str] = Field(None, max_length=500)  # For gifted

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "case_events"

    def __repr__(self) -> str:
        return f"<CaseEvent(id={self.id}, case_id={self.case_id}, type={self.event_type})>"
