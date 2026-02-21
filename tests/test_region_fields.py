"""Tests for sub_region, appellation, and classification fields."""

import io

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_checkin_with_region_fields(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """Test checking in a wine with sub_region, appellation, and classification."""
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Clos de Vougeot",
        "winery": "Domaine Leroy",
        "vintage": "2018",
        "region": "Burgundy",
        "sub_region": "Côte de Nuits",
        "appellation": "Vougeot",
        "country": "France",
        "classification": "Grand Cru",
        "quantity": "1",
    }

    response = await client.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201

    wine = response.json()
    assert wine["name"] == "Clos de Vougeot"
    assert wine["region"] == "Burgundy"
    assert wine["sub_region"] == "Côte de Nuits"
    assert wine["appellation"] == "Vougeot"
    assert wine["classification"] == "Grand Cru"
    assert wine["country"] == "France"


@pytest.mark.asyncio
async def test_checkin_without_region_fields(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """Test that new fields default to None when not provided."""
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Simple Wine",
        "quantity": "1",
    }

    response = await client.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201

    wine = response.json()
    assert wine["name"] == "Simple Wine"
    assert wine["sub_region"] is None
    assert wine["appellation"] is None
    assert wine["classification"] is None


@pytest.mark.asyncio
async def test_wine_detail_includes_region_fields(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """Test that wine detail response includes the new fields."""
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Barolo Riserva",
        "region": "Piedmont",
        "sub_region": "Langhe",
        "appellation": "Barolo",
        "classification": "DOCG",
        "country": "Italy",
        "quantity": "1",
    }

    checkin_response = await client.post(
        "/api/wines/checkin", files=files, data=data
    )
    assert checkin_response.status_code == 201
    wine_id = checkin_response.json()["id"]

    # Fetch wine detail
    detail_response = await client.get(f"/api/wines/{wine_id}")
    assert detail_response.status_code == 200

    wine = detail_response.json()
    assert wine["sub_region"] == "Langhe"
    assert wine["appellation"] == "Barolo"
    assert wine["classification"] == "DOCG"


@pytest.mark.asyncio
async def test_update_wine_region_fields(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """Test updating wine with new region fields via PUT."""
    # Create a wine first
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Test Update Wine",
        "region": "Bordeaux",
        "quantity": "1",
    }

    checkin_response = await client.post(
        "/api/wines/checkin", files=files, data=data
    )
    assert checkin_response.status_code == 201
    wine_id = checkin_response.json()["id"]

    # Update with new fields
    update_response = await client.put(
        f"/api/wines/{wine_id}",
        json={
            "sub_region": "Médoc",
            "appellation": "Pauillac",
            "classification": "Premier Grand Cru Classé",
        },
    )
    assert update_response.status_code == 200

    wine = update_response.json()
    assert wine["sub_region"] == "Médoc"
    assert wine["appellation"] == "Pauillac"
    assert wine["classification"] == "Premier Grand Cru Classé"


@pytest.mark.asyncio
async def test_search_by_sub_region(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """Test that search finds wines by sub_region."""
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Gevrey-Chambertin Wine",
        "sub_region": "Côte de Nuits",
        "quantity": "1",
    }
    await client.post("/api/wines/checkin", files=files, data=data)

    # Search by sub_region text
    response = await client.get("/api/search?q=Côte de Nuits")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) >= 1
    assert any(w["sub_region"] == "Côte de Nuits" for w in wines)


@pytest.mark.asyncio
async def test_search_by_appellation(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """Test that search finds wines by appellation."""
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Pomerol Treasure",
        "appellation": "Pomerol",
        "quantity": "1",
    }
    await client.post("/api/wines/checkin", files=files, data=data)

    # Search by appellation text
    response = await client.get("/api/search?q=Pomerol")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) >= 1
    assert any(w["appellation"] == "Pomerol" for w in wines)


@pytest.mark.asyncio
async def test_scan_response_includes_region_fields(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """Test that scan response includes sub_region, appellation, and classification keys."""
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }

    response = await client.post("/api/wines/scan", files=files)
    assert response.status_code == 200

    result = response.json()
    parsed = result["parsed"]
    # The keys should exist in the parsed response (values may be None)
    assert "sub_region" in parsed
    assert "appellation" in parsed
    assert "classification" in parsed
