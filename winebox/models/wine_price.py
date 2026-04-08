"""Wine price models for the price tracker.

Stores wine prices grouped by wine identity (name + vintage + type).
Each WinePrice document holds up to 20 recent price observations.
Older prices overflow to the WinePriceHistory collection.
"""

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from winebox.db import MongoDocument, PyObjectId
from winebox.models.price_capture import CaptureType, GeoCoordinates, ShopLocation


class PriceSource(str, enum.Enum):
    """Where a price observation came from."""

    PRICE_CAPTURE_APP = "price_capture_app"
    KAGGLE_IMPORT = "kaggle_import"
    XWINES_IMPORT = "xwines_import"
    CSV_IMPORT = "csv_import"
    WEB_SCRAPER = "web_scraper"


class PriceEntry(BaseModel):
    """A single price observation embedded in a WinePrice document."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: PriceSource = PriceSource.PRICE_CAPTURE_APP
    price: float
    currency: str = "EUR"
    owner_id: Optional[PyObjectId] = None
    location: ShopLocation = Field(default_factory=ShopLocation)
    coordinates: Optional[GeoCoordinates] = None
    notes: Optional[str] = None
    photo_path: Optional[str] = None
    capture_type: Optional[CaptureType] = None


# Maximum number of price entries kept in a WinePrice document.
# Older entries are archived to WinePriceHistory.
MAX_PRICES_PER_WINE = 20


class WinePrice(MongoDocument):
    """A wine with its recent price history.

    Each document represents a unique wine identified by
    (wine_name, vintage, wine_type). The prices array holds
    up to MAX_PRICES_PER_WINE entries, newest last.
    """

    wine_name: str
    vintage: Optional[int] = None
    wine_type: Optional[str] = None

    prices: list[PriceEntry] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "wine_prices"


class WinePriceHistory(MongoDocument):
    """Archived price observation that overflowed from a WinePrice document.

    This is a global archive — not scoped per owner. Each document is
    a single historical price entry with the wine identity denormalised.
    """

    # Wine identity (denormalised from WinePrice)
    wine_name: str
    vintage: Optional[int] = None
    wine_type: Optional[str] = None

    # Price observation fields (flattened from PriceEntry)
    timestamp: datetime
    source: PriceSource = PriceSource.PRICE_CAPTURE_APP
    price: float
    currency: str = "EUR"
    owner_id: Optional[PyObjectId] = None
    location: ShopLocation = Field(default_factory=ShopLocation)
    coordinates: Optional[GeoCoordinates] = None
    notes: Optional[str] = None
    photo_path: Optional[str] = None
    capture_type: Optional[CaptureType] = None

    archived_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "wine_prices_history"
