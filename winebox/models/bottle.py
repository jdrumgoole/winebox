"""Bottle model — an individual, immutable wine bottle.

Each bottle is a write-once record representing a physical bottle of wine.
The bottle never changes — its lifecycle state is tracked via WineEvent
records (event sourcing). Wine metadata is denormalised at creation time
so the cellar can be rendered without joining to the Wine collection.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import Field

from winebox.db import MongoDocument, PyObjectId


class Bottle(MongoDocument):
    """An individual wine bottle — immutable after creation."""

    owner_id: PyObjectId
    wine_id: PyObjectId  # → Wine record (for grouping)
    case_id: Optional[PyObjectId] = None  # → Case (None = loose bottle)

    # Future barcode scanning
    barcode: Optional[str] = Field(None, max_length=100)

    # Denormalised wine identity (immutable — the wine in the bottle never changes)
    name: str = Field(..., max_length=500)
    winery: Optional[str] = Field(None, max_length=500)
    vintage: Optional[int] = Field(None, ge=1000, le=2100)
    grape_variety: Optional[str] = Field(None, max_length=500)
    country: Optional[str] = Field(None, max_length=255)
    region: Optional[str] = Field(None, max_length=255)
    wine_type: Optional[str] = Field(None, max_length=50)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "bottles"

    def __repr__(self) -> str:
        return f"<Bottle(id={self.id}, name={self.name}, case_id={self.case_id})>"
