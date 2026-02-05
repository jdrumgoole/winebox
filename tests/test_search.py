"""Tests for search endpoints."""

import io

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_search_empty(client: AsyncClient) -> None:
    """Test search with no wines."""
    response = await client.get("/api/search")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_search_by_text(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test full-text search."""
    # Check in wines
    for name in ["Chateau Margaux", "Opus One", "Silver Oak"]:
        files = {
            "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
        }
        data = {"name": name, "quantity": "1"}
        await client.post("/api/wines/checkin", files=files, data=data)

    # Search for "Chateau"
    response = await client.get("/api/search?q=Chateau")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["name"] == "Chateau Margaux"


@pytest.mark.asyncio
async def test_search_by_vintage(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test search by vintage year."""
    # Check in wines with different vintages
    for vintage in [2018, 2019, 2020]:
        files = {
            "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
        }
        data = {"name": f"Wine {vintage}", "vintage": str(vintage), "quantity": "1"}
        await client.post("/api/wines/checkin", files=files, data=data)

    # Search for 2019 vintage
    response = await client.get("/api/search?vintage=2019")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["vintage"] == 2019


@pytest.mark.asyncio
async def test_search_by_grape(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test search by grape variety."""
    # Check in wines with different grapes
    grapes = ["Cabernet Sauvignon", "Merlot", "Pinot Noir"]
    for i, grape in enumerate(grapes):
        files = {
            "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
        }
        data = {"name": f"Wine {i}", "grape_variety": grape, "quantity": "1"}
        await client.post("/api/wines/checkin", files=files, data=data)

    # Search for Cabernet
    response = await client.get("/api/search?grape=Cabernet")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["grape_variety"] == "Cabernet Sauvignon"


@pytest.mark.asyncio
async def test_search_by_region(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test search by wine region."""
    # Check in wines from different regions
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Test Wine", "region": "Napa Valley", "quantity": "1"}
    await client.post("/api/wines/checkin", files=files, data=data)

    # Search for Napa
    response = await client.get("/api/search?region=Napa")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["region"] == "Napa Valley"


@pytest.mark.asyncio
async def test_search_by_country(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test search by country."""
    # Check in wines from different countries
    countries = ["France", "Italy", "United States"]
    for i, country in enumerate(countries):
        files = {
            "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
        }
        data = {"name": f"Wine {i}", "country": country, "quantity": "1"}
        await client.post("/api/wines/checkin", files=files, data=data)

    # Search for France
    response = await client.get("/api/search?country=France")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["country"] == "France"


@pytest.mark.asyncio
async def test_search_in_stock_filter(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test search with in_stock filter."""
    # Check in two wines
    for i in range(2):
        files = {
            "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
        }
        data = {"name": f"Wine {i}", "quantity": "2"}
        await client.post("/api/wines/checkin", files=files, data=data)

    # Check out all of first wine
    list_response = await client.get("/api/wines")
    wine_id = list_response.json()[0]["id"]
    await client.post(f"/api/wines/{wine_id}/checkout", data={"quantity": "2"})

    # Search for in stock only
    response = await client.get("/api/search?in_stock=true")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["inventory"]["quantity"] > 0


@pytest.mark.asyncio
async def test_search_combined_filters(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test search with multiple filters."""
    # Check in wines
    data_sets = [
        {"name": "Wine A", "vintage": "2019", "country": "France"},
        {"name": "Wine B", "vintage": "2019", "country": "Italy"},
        {"name": "Wine C", "vintage": "2020", "country": "France"},
    ]
    for data in data_sets:
        files = {
            "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
        }
        data["quantity"] = "1"
        await client.post("/api/wines/checkin", files=files, data=data)

    # Search for 2019 French wine
    response = await client.get("/api/search?vintage=2019&country=France")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["name"] == "Wine A"
