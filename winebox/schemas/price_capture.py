"""Pydantic schemas for the price capture API."""

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


class PriceCaptureCreate(BaseModel):
    """Input schema for creating a new price capture."""

    capture_type: str = Field("bottle", pattern="^(bottle|shelf)$")
    wine_name: Optional[str] = Field(None, max_length=500)
    vintage: Optional[int] = Field(None, ge=1900, le=2100)
    wine_type: Optional[str] = Field(None, max_length=50)
    price: Optional[float] = Field(None, ge=0)
    currency: str = Field("EUR", max_length=3)
    notes: Optional[str] = Field(None, max_length=2000)
    location: ShopLocationIn = Field(default_factory=ShopLocationIn)
    coordinates: Optional[GeoCoordinatesIn] = None
    captured_at: Optional[datetime] = None


class PriceCaptureOut(BaseModel):
    """Output schema for a price capture."""

    id: str
    capture_type: str
    wine_name: Optional[str] = None
    vintage: Optional[int] = None
    wine_type: Optional[str] = None
    price: Optional[float] = None
    currency: str = "EUR"
    notes: Optional[str] = None
    photo_url: Optional[str] = None
    location: ShopLocationIn = Field(default_factory=ShopLocationIn)
    coordinates: Optional[GeoCoordinatesIn] = None
    captured_at: datetime
    created_at: datetime
