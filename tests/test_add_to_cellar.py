"""Tests for adding a met wine to the cellar."""

import io

import pytest
from httpx import AsyncClient


async def _create_met_wine(
    client: AsyncClient,
    sample_image_bytes: bytes,
    name: str = "Test Met Wine",
    country: str = "France",
) -> dict:
    """Helper to create a met wine and return its JSON."""
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": name, "country": country}
    response = await client.post("/api/wines/met", files=files, data=data)
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_add_met_wine_to_cellar(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test adding a met wine to the cellar creates a cellar wine."""
    met = await _create_met_wine(client, sample_image_bytes)

    # Add to cellar with 6 bottles
    response = await client.post(
        f"/api/wines/{met['id']}/add-to-cellar",
        data={"quantity": "6"},
    )
    assert response.status_code == 201
    cellar_wine = response.json()

    assert cellar_wine["collection"] == "cellar"
    assert cellar_wine["inventory"]["quantity"] == 6
    assert cellar_wine["name"] == met["name"]
    assert cellar_wine["country"] == met["country"]

    # Met wine should now show added_to_cellar
    met_wines = (await client.get("/api/met")).json()
    assert len(met_wines) == 1
    assert met_wines[0]["added_to_cellar"] is True
    assert met_wines[0]["cellar_wine_id"] == cellar_wine["id"]


@pytest.mark.asyncio
async def test_add_met_wine_to_cellar_default_quantity(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test adding a met wine defaults to 1 bottle."""
    met = await _create_met_wine(client, sample_image_bytes)

    response = await client.post(f"/api/wines/{met['id']}/add-to-cellar")
    assert response.status_code == 201
    cellar_wine = response.json()
    assert cellar_wine["inventory"]["quantity"] == 1


@pytest.mark.asyncio
async def test_cannot_add_cellar_wine_to_cellar(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test that a cellar wine cannot be added to cellar again."""
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    response = await client.post("/api/wines/record", files=files, data={"name": "Cellar Wine", "quantity": "1"})
    cellar_wine = response.json()

    response = await client.post(f"/api/wines/{cellar_wine['id']}/add-to-cellar", data={"quantity": "1"})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_cannot_double_add_met_wine(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test that a met wine already added to cellar cannot be added again."""
    met = await _create_met_wine(client, sample_image_bytes)

    response = await client.post(f"/api/wines/{met['id']}/add-to-cellar", data={"quantity": "1"})
    assert response.status_code == 201

    response = await client.post(f"/api/wines/{met['id']}/add-to-cellar", data={"quantity": "1"})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_checkout_clears_met_link(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test that checking out all bottles clears the met wine's added_to_cellar flag."""
    met = await _create_met_wine(client, sample_image_bytes)

    # Add to cellar with 2 bottles
    response = await client.post(f"/api/wines/{met['id']}/add-to-cellar", data={"quantity": "2"})
    cellar_wine = response.json()

    # Check out 1 bottle — still linked
    await client.post(f"/api/wines/{cellar_wine['id']}/checkout", data={"quantity": "1"})
    met_wines = (await client.get("/api/met")).json()
    assert met_wines[0]["added_to_cellar"] is True

    # Check out last bottle — link should be cleared
    await client.post(f"/api/wines/{cellar_wine['id']}/checkout", data={"quantity": "1"})
    met_wines = (await client.get("/api/met")).json()
    assert met_wines[0]["added_to_cellar"] is False
    assert met_wines[0]["cellar_wine_id"] is None


@pytest.mark.asyncio
async def test_add_nonexistent_met_wine(client: AsyncClient) -> None:
    """Test adding a nonexistent wine returns 404."""
    response = await client.post("/api/wines/000000000000000000000000/add-to-cellar", data={"quantity": "1"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cellar_summary_excludes_met(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test that cellar summary does not count met wines."""
    await _create_met_wine(client, sample_image_bytes)

    response = await client.get("/api/cellar/summary")
    summary = response.json()
    assert summary["total_bottles"] == 0
    assert summary["unique_wines"] == 0
    assert summary["total_wines_tracked"] == 0
