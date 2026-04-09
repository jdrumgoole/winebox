"""Cellar item model — one document per physical item (case or bottle) in the cellar.

The wine descriptor is embedded because it will never change for a given
physical item. A bottle of Chateau Margaux 2015 will always be Chateau
Margaux 2015.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from winebox.db import MongoDocument, PyObjectId


class EmbeddedWine(BaseModel):
    """Wine descriptor embedded in a cellar item. Immutable snapshot."""

    wine_id: PyObjectId
    name: str
    winery: Optional[str] = None
    vintage: Optional[int] = None
    grape_variety: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    wine_type: Optional[str] = None
    estimated_price_low: Optional[float] = None
    estimated_price_high: Optional[float] = None
    price_tier: Optional[str] = None


class CellarItem(MongoDocument):
    """One document per physical item in the cellar (case or loose bottle).

    Data grows by adding documents, not by appending to arrays.
    Each item is self-contained — no external lookups needed for display.
    """

    cellar_id: PyObjectId  # = user._id
    item_type: str  # "case" | "bottle"

    # The wine in this item (embedded, immutable)
    wine: EmbeddedWine

    # Quantity — bottle: always 1, case: bottles remaining
    quantity: int = 1

    # Case-specific fields (only when item_type == "case")
    case_size: Optional[int] = Field(None, ge=1, le=100)
    purchase_price: Optional[float] = Field(None, ge=0)
    purchase_date: Optional[datetime] = None
    provenance: Optional[str] = None

    # Tracking
    import_batch_id: Optional[PyObjectId] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    class Settings:
        name = "cellars"
