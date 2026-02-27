"""Tests for X-Wines enrichment service."""

import io
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from winebox.models import XWinesWine, Wine
from winebox.services.xwines_enrichment import (
    enrich_parsed_with_xwines,
    parse_xwines_grapes,
)


# ---------------------------------------------------------------------------
# parse_xwines_grapes
# ---------------------------------------------------------------------------


def test_parse_xwines_grapes_python_list() -> None:
    """Python-style single-quoted list is parsed correctly."""
    result = parse_xwines_grapes("['Merlot', 'Cabernet Sauvignon']")
    assert result == "Merlot, Cabernet Sauvignon"


def test_parse_xwines_grapes_json_list() -> None:
    """JSON-style double-quoted list is parsed correctly."""
    result = parse_xwines_grapes('["Chardonnay", "Pinot Grigio"]')
    assert result == "Chardonnay, Pinot Grigio"


def test_parse_xwines_grapes_single_item() -> None:
    """Single-element list is parsed correctly."""
    result = parse_xwines_grapes("['Syrah']")
    assert result == "Syrah"


def test_parse_xwines_grapes_empty_string() -> None:
    """Empty string returns None."""
    assert parse_xwines_grapes("") is None


def test_parse_xwines_grapes_none() -> None:
    """None returns None."""
    assert parse_xwines_grapes(None) is None


def test_parse_xwines_grapes_plain_string() -> None:
    """Plain string (not a list) is returned as-is."""
    result = parse_xwines_grapes("Tempranillo")
    assert result == "Tempranillo"


def test_parse_xwines_grapes_empty_list() -> None:
    """Empty list returns None."""
    assert parse_xwines_grapes("[]") is None


# ---------------------------------------------------------------------------
# enrich_parsed_with_xwines — integration tests (require MongoDB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_fills_gaps(init_test_db) -> None:
    """Empty parsed fields are filled from X-Wines match."""
    # Insert an X-Wines wine
    xwine = XWinesWine(
        xwines_id=100,
        name="Chateau Margaux",
        wine_type="Red",
        winery_name="Chateau Margaux",
        country="France",
        country_code="FR",
        region_name="Bordeaux",
        grapes="['Cabernet Sauvignon', 'Merlot']",
        abv=13.5,
        avg_rating=4.5,
        rating_count=1000,
    )
    await xwine.insert()

    # Parsed data with only name detected
    parsed = {"name": "Chateau Margaux"}

    result = await enrich_parsed_with_xwines(parsed)

    assert result["name"] == "Chateau Margaux"
    assert result["winery"] == "Chateau Margaux"
    assert result["grape_variety"] == "Cabernet Sauvignon, Merlot"
    assert result["region"] == "Bordeaux"
    assert result["country"] == "France"
    assert result["alcohol_percentage"] == 13.5
    assert result["wine_type"] == "red"  # Lowercased
    assert result["xwines_id"] == 100


@pytest.mark.asyncio
async def test_enrich_preserves_existing(init_test_db) -> None:
    """Non-empty parsed fields are NOT overwritten by X-Wines data."""
    xwine = XWinesWine(
        xwines_id=200,
        name="Opus One",
        wine_type="Red",
        winery_name="Opus One Winery",
        country="United States",
        country_code="US",
        region_name="Napa Valley",
        grapes="['Cabernet Sauvignon']",
        abv=14.5,
        avg_rating=4.7,
        rating_count=500,
    )
    await xwine.insert()

    # Parsed data with some fields already filled by OCR
    parsed = {
        "name": "Opus One",
        "winery": "My Custom Winery",  # Should NOT be overwritten
        "country": "USA",  # Should NOT be overwritten
        "grape_variety": "Pinot Noir",  # Should NOT be overwritten
    }

    result = await enrich_parsed_with_xwines(parsed)

    assert result["winery"] == "My Custom Winery"
    assert result["country"] == "USA"
    assert result["grape_variety"] == "Pinot Noir"
    # But empty fields should be filled
    assert result["region"] == "Napa Valley"
    assert result["alcohol_percentage"] == 14.5
    assert result["wine_type"] == "red"
    assert result["xwines_id"] == 200


@pytest.mark.asyncio
async def test_enrich_no_match(init_test_db) -> None:
    """Returns parsed unchanged when no X-Wines match found."""
    parsed = {
        "name": "Completely Unknown Wine XYZZY",
        "winery": "Some Winery",
    }

    result = await enrich_parsed_with_xwines(parsed)

    assert result == parsed
    assert "xwines_id" not in result


@pytest.mark.asyncio
async def test_enrich_adds_xwines_id(init_test_db) -> None:
    """xwines_id is added when a match is found."""
    xwine = XWinesWine(
        xwines_id=42,
        name="Merlot Reserve",
        wine_type="Red",
        winery_name="Test Winery",
        avg_rating=3.5,
        rating_count=100,
    )
    await xwine.insert()

    parsed = {"name": "Merlot Reserve"}
    result = await enrich_parsed_with_xwines(parsed)

    assert result["xwines_id"] == 42


@pytest.mark.asyncio
async def test_enrich_short_name_skipped(init_test_db) -> None:
    """Names shorter than 2 chars are skipped."""
    parsed = {"name": "A"}
    result = await enrich_parsed_with_xwines(parsed)
    assert result == parsed
    assert "xwines_id" not in result


@pytest.mark.asyncio
async def test_enrich_no_name_skipped(init_test_db) -> None:
    """Missing name is skipped."""
    parsed = {"winery": "Some Winery"}
    result = await enrich_parsed_with_xwines(parsed)
    assert result == parsed


# ---------------------------------------------------------------------------
# Scan endpoint enrichment — integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_returns_xwines_fields(client: AsyncClient, init_test_db, sample_image_bytes: bytes) -> None:
    """Scan endpoint includes wine_type and xwines_id from enrichment."""
    # Insert an X-Wines wine that will match the OCR result
    xwine = XWinesWine(
        xwines_id=300,
        name="Test Scan Wine",
        wine_type="White",
        winery_name="Scan Winery",
        country="Italy",
        country_code="IT",
        region_name="Tuscany",
        grapes="['Trebbiano']",
        abv=12.0,
        avg_rating=4.0,
        rating_count=50,
    )
    await xwine.insert()

    # Mock OCR to return a name that matches our X-Wines entry
    with patch("winebox.routers.wines.vision_service") as mock_vision, \
         patch("winebox.routers.wines.ocr_service") as mock_ocr, \
         patch("winebox.routers.wines.wine_parser") as mock_parser:
        mock_vision.is_available.return_value = False
        mock_ocr.extract_text_from_bytes = AsyncMock(return_value="Test Scan Wine")
        mock_parser.parse.return_value = {"name": "Test Scan Wine"}

        response = await client.post(
            "/api/wines/scan",
            files={"front_label": ("label.png", io.BytesIO(sample_image_bytes), "image/png")},
        )

    assert response.status_code == 200
    data = response.json()
    parsed = data["parsed"]

    assert parsed["wine_type"] == "white"
    assert parsed["xwines_id"] == 300
    assert parsed["region"] == "Tuscany"
    assert parsed["grape_variety"] == "Trebbiano"


# ---------------------------------------------------------------------------
# Check-in endpoint wine_type_id — integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkin_accepts_wine_type_id(client: AsyncClient, init_test_db, sample_image_bytes: bytes) -> None:
    """wine_type_id form field is saved on the Wine document."""
    # Mock vision to not be available, and OCR to return minimal data
    with patch("winebox.routers.wines.vision_service") as mock_vision, \
         patch("winebox.routers.wines.ocr_service") as mock_ocr, \
         patch("winebox.routers.wines.wine_parser") as mock_parser:
        mock_vision.is_available.return_value = False
        mock_ocr.extract_text.return_value = "Test Wine"
        mock_parser.parse.return_value = {"name": "Test Wine"}

        response = await client.post(
            "/api/wines/checkin",
            data={
                "name": "Checkin Wine Type Test",
                "wine_type_id": "red",
                "quantity": "1",
            },
            files={"front_label": ("label.png", io.BytesIO(sample_image_bytes), "image/png")},
        )

    assert response.status_code == 201
    wine_data = response.json()
    assert wine_data["name"] == "Checkin Wine Type Test"
    assert wine_data["wine_type_id"] == "red"

    # Verify in database
    wine = await Wine.find_one(Wine.name == "Checkin Wine Type Test")
    assert wine is not None
    assert wine.wine_type_id == "red"
