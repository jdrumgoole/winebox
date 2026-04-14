"""Tests for price capture Pydantic schemas."""

import pytest
from pydantic import ValidationError

from winebox.schemas.price_capture import (
    GeoCoordinatesIn,
    PriceCaptureCreate,
    PriceCaptureOut,
    ShopLocationIn,
)


def test_shop_location_defaults() -> None:
    """ShopLocationIn fields default to None."""
    loc = ShopLocationIn()
    assert loc.shop_name is None
    assert loc.town_city is None
    assert loc.state_county is None
    assert loc.country is None


def test_shop_location_with_values() -> None:
    """ShopLocationIn accepts valid field values."""
    loc = ShopLocationIn(
        shop_name="Berry Bros",
        town_city="London",
        state_county="Greater London",
        country="UK",
    )
    assert loc.shop_name == "Berry Bros"
    assert loc.country == "UK"


def test_geo_coordinates_valid() -> None:
    """GeoCoordinatesIn accepts valid lat/lon."""
    coords = GeoCoordinatesIn(latitude=51.5074, longitude=-0.1278, accuracy_metres=10.0)
    assert coords.latitude == 51.5074
    assert coords.longitude == -0.1278
    assert coords.accuracy_metres == 10.0


def test_geo_coordinates_bounds() -> None:
    """GeoCoordinatesIn rejects out-of-range lat/lon."""
    with pytest.raises(ValidationError):
        GeoCoordinatesIn(latitude=91, longitude=0)
    with pytest.raises(ValidationError):
        GeoCoordinatesIn(latitude=0, longitude=181)
    with pytest.raises(ValidationError):
        GeoCoordinatesIn(latitude=0, longitude=0, accuracy_metres=-1)


def test_price_capture_create_defaults() -> None:
    """PriceCaptureCreate defaults to bottle type and EUR currency."""
    capture = PriceCaptureCreate()
    assert capture.capture_type == "bottle"
    assert capture.currency == "EUR"
    assert capture.wine_name is None
    assert capture.price is None


def test_price_capture_create_shelf() -> None:
    """PriceCaptureCreate accepts shelf type."""
    capture = PriceCaptureCreate(capture_type="shelf", wine_name="Margaux 2015", price=89.99)
    assert capture.capture_type == "shelf"
    assert capture.price == 89.99


def test_price_capture_create_invalid_type() -> None:
    """PriceCaptureCreate rejects invalid capture types."""
    with pytest.raises(ValidationError):
        PriceCaptureCreate(capture_type="invalid")


def test_price_capture_create_negative_price() -> None:
    """PriceCaptureCreate rejects negative prices."""
    with pytest.raises(ValidationError):
        PriceCaptureCreate(price=-10.0)


def test_price_capture_create_with_coordinates() -> None:
    """PriceCaptureCreate accepts embedded coordinates."""
    capture = PriceCaptureCreate(
        wine_name="Test Wine",
        price=15.0,
        coordinates=GeoCoordinatesIn(latitude=48.8566, longitude=2.3522),
    )
    assert capture.coordinates is not None
    assert capture.coordinates.latitude == 48.8566


def test_price_capture_out_schema() -> None:
    """PriceCaptureOut contains all expected fields."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    out = PriceCaptureOut(
        id="abc123",
        capture_type="bottle",
        wine_name="Test",
        price=20.0,
        captured_at=now,
        created_at=now,
    )
    assert out.id == "abc123"
    assert out.currency == "EUR"
    assert out.photo_url is None
