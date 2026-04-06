"""Price capture model for the wine price tracker.

Stores individual bottle or shelf captures with pricing, location,
and optional photos. Each capture records where and when a wine price
was observed.
"""

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from winebox.db import MongoDocument, PyObjectId


class CaptureType(str, enum.Enum):
    """Whether the capture is a single bottle or a shelf of bottles."""

    BOTTLE = "bottle"
    SHELF = "shelf"


class ShopLocation(BaseModel):
    """Embedded subdocument for the physical location of a price observation."""

    shop_name: Optional[str] = None
    town_city: Optional[str] = None
    state_county: Optional[str] = None
    country: Optional[str] = None


class GeoCoordinates(BaseModel):
    """Embedded subdocument for GPS coordinates captured from the device."""

    latitude: float
    longitude: float
    accuracy_metres: Optional[float] = None


class PriceCapture(MongoDocument):
    """A wine price observation captured in a shop.

    Records a bottle or shelf photo along with the price, location,
    and timestamp. Used to build a wine price index over time.
    """

    # Owner reference for data isolation
    owner_id: PyObjectId

    # What was captured
    capture_type: CaptureType = CaptureType.BOTTLE
    wine_name: Optional[str] = None
    vintage: Optional[int] = None
    wine_type: Optional[str] = None  # e.g. "Red", "White", "Rosé"

    # Price information
    price: Optional[float] = None
    currency: str = "EUR"
    notes: Optional[str] = None

    # Photo (stored as a path relative to image storage)
    photo_path: Optional[str] = None

    # Location
    location: ShopLocation = Field(default_factory=ShopLocation)
    coordinates: Optional[GeoCoordinates] = None

    # Timestamps
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "price_captures"
