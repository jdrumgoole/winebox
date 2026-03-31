"""Case model — a physical case of wine.

A case is a container that holds a fixed number of bottles (case_size).
Cases are never deleted — they become empty when all bottles are transferred.
This preserves the full purchase and provenance history.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import Field

from winebox.db import MongoDocument, PyObjectId


class Case(MongoDocument):
    """A physical case of wine bottles."""

    owner_id: PyObjectId
    wine_id: PyObjectId  # → Wine record (the wine identity)

    # Case properties
    case_size: int = Field(..., ge=1, le=100, description="Original bottle capacity")
    barcode: Optional[str] = Field(None, max_length=100, description="Case barcode")

    # Purchase info
    purchase_date: Optional[datetime] = None
    purchase_price: Optional[float] = Field(None, ge=0, description="Price paid for the case")
    provenance: Optional[str] = Field(None, max_length=500, description="Where the case was bought")
    notes: Optional[str] = Field(None, max_length=2000)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "cases"

    def __repr__(self) -> str:
        return f"<Case(id={self.id}, wine_id={self.wine_id}, case_size={self.case_size})>"
