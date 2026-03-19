"""Tests for X-Wines enrichment in the check-in flow."""

import io
import random
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from winebox.models import Wine, XWinesWine


# ---------------------------------------------------------------------------
# Helper: insert an X-Wines reference wine
# ---------------------------------------------------------------------------

async def _insert_xwines_wine(**kwargs) -> XWinesWine:
    """Insert an XWinesWine with sensible defaults."""
    uid = random.randint(100000, 999999)
    defaults = {
        "xwines_id": uid,
        "name": f"Enrichment Test Wine {uid}",
        "wine_type": "Red",
        "winery_name": "Enrichment Winery",
        "country": "France",
        "country_code": "FR",
        "region_name": "Bordeaux",
        "grapes": "['Merlot', 'Cabernet Franc']",
        "abv": 13.0,
        "avg_rating": 4.2,
        "rating_count": 200,
    }
    defaults.update(kwargs)
    xwine = XWinesWine(**defaults)
    await xwine.insert()
    return xwine


# ---------------------------------------------------------------------------
# Check-in with enrichment: enriched_fields and xwines_id are set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkin_enriches_empty_fields(
    client: AsyncClient, init_test_db, sample_image_bytes: bytes
) -> None:
    """Check-in with a matching wine name fills empty fields from X-Wines."""
    xwine = await _insert_xwines_wine()
    wine_name = xwine.name

    with patch("winebox.routers.wines.checkin.vision_service") as mock_vision, \
         patch("winebox.routers.wines.checkin.ocr_service") as mock_ocr, \
         patch("winebox.routers.wines.checkin.wine_parser") as mock_parser:
        mock_vision.is_available.return_value = False
        mock_ocr.extract_text = AsyncMock(return_value=wine_name)
        mock_parser.parse.return_value = {"name": wine_name}

        response = await client.post(
            "/api/wines/checkin",
            data={"quantity": "1"},
            files={"front_label": ("label.png", io.BytesIO(sample_image_bytes), "image/png")},
        )

    assert response.status_code == 201
    data = response.json()

    # Enriched fields should be populated
    assert data["winery"] == "Enrichment Winery"
    assert data["grape_variety"] == "Merlot, Cabernet Franc"
    assert data["region"] == "Bordeaux"
    assert data["country"] == "France"
    assert data["alcohol_percentage"] == 13.0

    # Enrichment metadata should be present
    assert data["xwines_id"] == xwine.xwines_id
    assert "winery" in data["enriched_fields"]
    assert "grape_variety" in data["enriched_fields"]
    assert "region" in data["enriched_fields"]
    assert "country" in data["enriched_fields"]
    assert "alcohol_percentage" in data["enriched_fields"]


# ---------------------------------------------------------------------------
# Enrichment does not overwrite OCR/user-provided values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkin_enrichment_preserves_existing_values(
    client: AsyncClient, init_test_db, sample_image_bytes: bytes
) -> None:
    """User/OCR-provided fields are NOT overwritten by X-Wines enrichment."""
    xwine = await _insert_xwines_wine()
    wine_name = xwine.name

    with patch("winebox.routers.wines.checkin.vision_service") as mock_vision, \
         patch("winebox.routers.wines.checkin.ocr_service") as mock_ocr, \
         patch("winebox.routers.wines.checkin.wine_parser") as mock_parser:
        mock_vision.is_available.return_value = False
        mock_ocr.extract_text = AsyncMock(return_value=wine_name)
        mock_parser.parse.return_value = {"name": wine_name}

        response = await client.post(
            "/api/wines/checkin",
            data={
                "name": wine_name,
                "winery": "My Own Winery",
                "country": "Spain",
                "quantity": "1",
            },
            files={"front_label": ("label.png", io.BytesIO(sample_image_bytes), "image/png")},
        )

    assert response.status_code == 201
    data = response.json()

    # User-provided values should be preserved
    assert data["winery"] == "My Own Winery"
    assert data["country"] == "Spain"

    # Empty fields should still be enriched
    assert data["grape_variety"] == "Merlot, Cabernet Franc"
    assert data["region"] == "Bordeaux"

    # Only truly enriched fields should be listed
    assert "winery" not in data["enriched_fields"]
    assert "country" not in data["enriched_fields"]
    assert "grape_variety" in data["enriched_fields"]
    assert "region" in data["enriched_fields"]


# ---------------------------------------------------------------------------
# No enrichment when no X-Wines match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkin_no_enrichment_when_no_match(
    client: AsyncClient, init_test_db, sample_image_bytes: bytes
) -> None:
    """No enrichment metadata when the wine name doesn't match X-Wines."""
    # No X-Wines data inserted

    with patch("winebox.routers.wines.checkin.vision_service") as mock_vision, \
         patch("winebox.routers.wines.checkin.ocr_service") as mock_ocr, \
         patch("winebox.routers.wines.checkin.wine_parser") as mock_parser:
        mock_vision.is_available.return_value = False
        mock_ocr.extract_text = AsyncMock(return_value="Totally Unknown Wine XYZZY")
        mock_parser.parse.return_value = {"name": "Totally Unknown Wine XYZZY"}

        response = await client.post(
            "/api/wines/checkin",
            data={"quantity": "1"},
            files={"front_label": ("label.png", io.BytesIO(sample_image_bytes), "image/png")},
        )

    assert response.status_code == 201
    data = response.json()

    assert data["enriched_fields"] is None
    assert data["xwines_id"] is None


# ---------------------------------------------------------------------------
# Enrichment fields in GET /api/wines/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enriched_fields_in_wine_detail_api(
    client: AsyncClient, init_test_db, sample_image_bytes: bytes
) -> None:
    """GET /api/wines/{id} includes enriched_fields and xwines_id."""
    xwine = await _insert_xwines_wine()
    wine_name = xwine.name

    with patch("winebox.routers.wines.checkin.vision_service") as mock_vision, \
         patch("winebox.routers.wines.checkin.ocr_service") as mock_ocr, \
         patch("winebox.routers.wines.checkin.wine_parser") as mock_parser:
        mock_vision.is_available.return_value = False
        mock_ocr.extract_text = AsyncMock(return_value=wine_name)
        mock_parser.parse.return_value = {"name": wine_name}

        checkin_resp = await client.post(
            "/api/wines/checkin",
            data={"quantity": "1"},
            files={"front_label": ("label.png", io.BytesIO(sample_image_bytes), "image/png")},
        )

    assert checkin_resp.status_code == 201
    wine_id = checkin_resp.json()["id"]

    # Fetch via GET
    detail_resp = await client.get(f"/api/wines/{wine_id}")
    assert detail_resp.status_code == 200
    data = detail_resp.json()

    assert data["xwines_id"] == xwine.xwines_id
    assert isinstance(data["enriched_fields"], list)
    assert len(data["enriched_fields"]) > 0


# ---------------------------------------------------------------------------
# Enrichment metadata is persisted in database
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkin_enrichment_persisted_in_db(
    client: AsyncClient, init_test_db, sample_image_bytes: bytes
) -> None:
    """Enrichment fields are persisted on the Wine document in MongoDB."""
    xwine = await _insert_xwines_wine()
    wine_name = xwine.name

    with patch("winebox.routers.wines.checkin.vision_service") as mock_vision, \
         patch("winebox.routers.wines.checkin.ocr_service") as mock_ocr, \
         patch("winebox.routers.wines.checkin.wine_parser") as mock_parser:
        mock_vision.is_available.return_value = False
        mock_ocr.extract_text = AsyncMock(return_value=wine_name)
        mock_parser.parse.return_value = {"name": wine_name}

        response = await client.post(
            "/api/wines/checkin",
            data={"quantity": "1"},
            files={"front_label": ("label.png", io.BytesIO(sample_image_bytes), "image/png")},
        )

    assert response.status_code == 201

    # Verify directly in database
    wine = await Wine.find_one(Wine.name == wine_name)
    assert wine is not None
    assert wine.xwines_id == xwine.xwines_id
    assert wine.enriched_fields is not None
    assert "winery" in wine.enriched_fields
    assert "region" in wine.enriched_fields
