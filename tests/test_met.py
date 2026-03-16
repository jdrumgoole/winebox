"""Tests for 'Wines I Have Met' feature — recording and listing met wines."""

import io

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_record_met_wine(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test recording a wine the user has encountered."""
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Met Wine",
        "winery": "Met Winery",
        "vintage": "2021",
        "country": "France",
    }

    response = await client.post("/api/wines/met", files=files, data=data)
    assert response.status_code == 201

    wine = response.json()
    assert wine["name"] == "Met Wine"
    assert wine["collection"] == "met"
    assert wine["inventory"]["quantity"] == 0
    assert wine["added_to_cellar"] is False


@pytest.mark.asyncio
async def test_record_met_wine_minimal(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test recording a met wine with only a label image."""
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    response = await client.post("/api/wines/met", files=files)
    assert response.status_code == 201

    wine = response.json()
    assert wine["collection"] == "met"
    assert wine["inventory"]["quantity"] == 0


@pytest.mark.asyncio
async def test_list_met_wines(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test listing met wines only returns met wines."""
    # Create a met wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Met Only Wine"}
    await client.post("/api/wines/met", files=files, data=data)

    # Create a cellar wine via checkin
    files2 = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data2 = {"name": "Cellar Wine", "quantity": "1"}
    await client.post("/api/wines/checkin", files=files2, data=data2)

    # List met wines
    response = await client.get("/api/met")
    assert response.status_code == 200
    met_wines = response.json()
    assert len(met_wines) == 1
    assert met_wines[0]["name"] == "Met Only Wine"
    assert met_wines[0]["collection"] == "met"


@pytest.mark.asyncio
async def test_met_summary(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test met summary endpoint."""
    # Create a met wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Summary Wine", "country": "Italy"}
    await client.post("/api/wines/met", files=files, data=data)

    response = await client.get("/api/met/summary")
    assert response.status_code == 200
    summary = response.json()
    assert summary["total_met"] == 1
    assert summary["added_to_cellar"] == 0
    assert "Italy" in summary["by_country"]


@pytest.mark.asyncio
async def test_met_wine_not_in_cellar_list(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Met wines should not appear in cellar inventory."""
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Not In Cellar"}
    await client.post("/api/wines/met", files=files, data=data)

    response = await client.get("/api/cellar")
    assert response.status_code == 200
    cellar_wines = response.json()
    assert len(cellar_wines) == 0


@pytest.mark.asyncio
async def test_list_wines_collection_filter(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test that list_wines supports collection filter."""
    # Create one met and one cellar wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    await client.post("/api/wines/met", files=files, data={"name": "Met Wine"})
    files2 = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    await client.post("/api/wines/checkin", files=files2, data={"name": "Cellar Wine", "quantity": "1"})

    # Filter for cellar only
    response = await client.get("/api/wines?collection=cellar")
    assert response.status_code == 200
    wines = response.json()
    assert all(w["collection"] == "cellar" for w in wines)
    assert len(wines) == 1

    # Filter for met only
    response = await client.get("/api/wines?collection=met")
    assert response.status_code == 200
    wines = response.json()
    assert all(w["collection"] == "met" for w in wines)
    assert len(wines) == 1
