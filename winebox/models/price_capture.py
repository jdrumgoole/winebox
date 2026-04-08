"""Shared types for the wine price tracker.

These embedded subdocuments are used by both WinePrice and WinePriceHistory,
as well as the price tracker API schemas.
"""

import enum
from typing import Optional

from pydantic import BaseModel


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
