"""Tests for wine management endpoints."""

import io

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    """Test the health check endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


@pytest.mark.asyncio
async def test_root_redirects_to_web_interface(client: AsyncClient) -> None:
    """Test that root URL redirects to the web interface."""
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 307  # Temporary redirect
    assert response.headers["location"] == "/static/index.html"


@pytest.mark.asyncio
async def test_checkin_wine(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test checking in a wine."""
    # Create form data with image
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Test Wine",
        "winery": "Test Winery",
        "vintage": "2020",
        "grape_variety": "Cabernet Sauvignon",
        "region": "Napa Valley",
        "country": "United States",
        "quantity": "2",
    }

    response = await client.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201

    wine = response.json()
    assert wine["name"] == "Test Wine"
    assert wine["winery"] == "Test Winery"
    assert wine["vintage"] == 2020
    assert wine["inventory"]["quantity"] == 2


@pytest.mark.asyncio
async def test_checkin_wine_minimal(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test checking in a wine with minimal data."""
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "quantity": "1",
    }

    response = await client.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201

    wine = response.json()
    # Should have auto-detected or default name
    assert wine["name"] is not None
    assert wine["inventory"]["quantity"] == 1


@pytest.mark.asyncio
async def test_list_wines_empty(client: AsyncClient) -> None:
    """Test listing wines when cellar is empty."""
    response = await client.get("/api/wines")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_wines(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test listing wines after check-in."""
    # Check in a wine first
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Test Wine",
        "quantity": "1",
    }
    await client.post("/api/wines/checkin", files=files, data=data)

    # List wines
    response = await client.get("/api/wines")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["name"] == "Test Wine"


@pytest.mark.asyncio
async def test_get_wine_detail(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test getting wine details."""
    # Check in a wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Test Wine",
        "quantity": "3",
    }
    checkin_response = await client.post("/api/wines/checkin", files=files, data=data)
    wine_id = checkin_response.json()["id"]

    # Get wine details
    response = await client.get(f"/api/wines/{wine_id}")
    assert response.status_code == 200

    wine = response.json()
    assert wine["name"] == "Test Wine"
    assert wine["inventory"]["quantity"] == 3
    assert len(wine["transactions"]) == 1
    assert wine["transactions"][0]["transaction_type"] == "CHECK_IN"


@pytest.mark.asyncio
async def test_get_wine_not_found(client: AsyncClient) -> None:
    """Test getting a wine that doesn't exist."""
    response = await client.get("/api/wines/nonexistent-id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_wine(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test updating wine metadata."""
    # Check in a wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Original Name", "quantity": "1"}
    checkin_response = await client.post("/api/wines/checkin", files=files, data=data)
    wine_id = checkin_response.json()["id"]

    # Update wine
    response = await client.put(
        f"/api/wines/{wine_id}",
        json={"name": "Updated Name", "vintage": 2019}
    )
    assert response.status_code == 200

    wine = response.json()
    assert wine["name"] == "Updated Name"
    assert wine["vintage"] == 2019


@pytest.mark.asyncio
async def test_checkout_wine(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test checking out wine."""
    # Check in wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Test Wine", "quantity": "5"}
    checkin_response = await client.post("/api/wines/checkin", files=files, data=data)
    wine_id = checkin_response.json()["id"]

    # Check out 2 bottles
    checkout_data = {"quantity": "2", "notes": "Dinner party"}
    response = await client.post(f"/api/wines/{wine_id}/checkout", data=checkout_data)
    assert response.status_code == 200

    wine = response.json()
    assert wine["inventory"]["quantity"] == 3


@pytest.mark.asyncio
async def test_checkout_exceeds_stock(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test checking out more than available stock."""
    # Check in wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Test Wine", "quantity": "2"}
    checkin_response = await client.post("/api/wines/checkin", files=files, data=data)
    wine_id = checkin_response.json()["id"]

    # Try to check out more than available
    checkout_data = {"quantity": "5"}
    response = await client.post(f"/api/wines/{wine_id}/checkout", data=checkout_data)
    assert response.status_code == 400
    assert "Not enough bottles" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_wine(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test deleting a wine."""
    # Check in wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Test Wine", "quantity": "1"}
    checkin_response = await client.post("/api/wines/checkin", files=files, data=data)
    wine_id = checkin_response.json()["id"]

    # Delete wine
    response = await client.delete(f"/api/wines/{wine_id}")
    assert response.status_code == 204

    # Verify deletion
    response = await client.get(f"/api/wines/{wine_id}")
    assert response.status_code == 404
