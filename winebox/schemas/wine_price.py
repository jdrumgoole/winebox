"""Pydantic schemas for the wine price API."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ShopLocationIn(BaseModel):
    """Location input from the client."""

    shop_name: Optional[str] = Field(None, max_length=200)
    town_city: Optional[str] = Field(None, max_length=200)
    state_county: Optional[str] = Field(None, max_length=200)
    country: Optional[str] = Field(None, max_length=100)


class GeoCoordinatesIn(BaseModel):
    """GPS coordinates from the device."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_metres: Optional[float] = Field(None, ge=0)


class PriceEntryOut(BaseModel):
    """Output schema for a single price observation."""

    timestamp: datetime
    source: str
    price: float
    currency: str = "EUR"
    owner_id: Optional[str] = None
    location: ShopLocationIn = Field(default_factory=ShopLocationIn)
    coordinates: Optional[GeoCoordinatesIn] = None
    notes: Optional[str] = None
    photo_url: Optional[str] = None
    capture_type: Optional[str] = None


class WinePriceOut(BaseModel):
    """Output schema for a wine with its price history."""

    id: str
    wine_name: str
    vintage: Optional[int] = None
    wine_type: Optional[str] = None
    prices: list[PriceEntryOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class WinePriceSummaryOut(BaseModel):
    """Lighter output for list endpoints."""

    id: str
    wine_name: str
    vintage: Optional[int] = None
    wine_type: Optional[str] = None
    price_count: int = 0
    latest_price: Optional[float] = None
    latest_currency: Optional[str] = None
    latest_timestamp: Optional[datetime] = None


class WinePriceHistoryEntryOut(BaseModel):
    """Output schema for an archived price observation."""

    id: str
    wine_name: str
    vintage: Optional[int] = None
    wine_type: Optional[str] = None
    timestamp: datetime
    source: str
    price: float
    currency: str = "EUR"
    location: ShopLocationIn = Field(default_factory=ShopLocationIn)
    notes: Optional[str] = None
    archived_at: datetime
