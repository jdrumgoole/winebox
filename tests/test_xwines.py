"""Tests for X-Wines dataset API endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from winebox.models import XWinesMetadata, XWinesWine


@pytest.mark.asyncio
async def test_xwines_search_empty(client: AsyncClient) -> None:
    """Test search with no X-Wines data."""
    response = await client.get("/api/xwines/search?q=merlot")
    assert response.status_code == 200
    data = response.json()
    assert data["results"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_xwines_search_query_too_short(client: AsyncClient) -> None:
    """Test search with query less than 2 characters."""
    response = await client.get("/api/xwines/search?q=a")
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_xwines_search_with_data(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test search with X-Wines data in database."""
    # Add test wines to database
    test_wines = [
        XWinesWine(
            id=1,
            name="Chateau Margaux",
            wine_type="Red",
            winery_name="Chateau Margaux",
            country="France",
            country_code="FR",
            region_name="Bordeaux",
            abv=13.5,
            avg_rating=4.5,
            rating_count=1000,
        ),
        XWinesWine(
            id=2,
            name="Opus One",
            wine_type="Red",
            winery_name="Opus One Winery",
            country="United States",
            country_code="US",
            region_name="Napa Valley",
            abv=14.0,
            avg_rating=4.7,
            rating_count=500,
        ),
        XWinesWine(
            id=3,
            name="Merlot Reserve",
            wine_type="Red",
            winery_name="Test Winery",
            country="Italy",
            country_code="IT",
            region_name="Tuscany",
            abv=13.0,
            avg_rating=3.8,
            rating_count=200,
        ),
    ]
    for wine in test_wines:
        db_session.add(wine)
    await db_session.commit()

    # Search for "Chateau"
    response = await client.get("/api/xwines/search?q=Chateau")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["results"]) == 1
    assert data["results"][0]["name"] == "Chateau Margaux"


@pytest.mark.asyncio
async def test_xwines_search_by_winery(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test search matches winery name."""
    wine = XWinesWine(
        id=1,
        name="Reserve Red",
        wine_type="Red",
        winery_name="Silver Oak Cellars",
        country="United States",
        country_code="US",
        avg_rating=4.2,
        rating_count=300,
    )
    db_session.add(wine)
    await db_session.commit()

    # Search for winery name
    response = await client.get("/api/xwines/search?q=Silver%20Oak")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["results"][0]["winery"] == "Silver Oak Cellars"


@pytest.mark.asyncio
async def test_xwines_search_with_filters(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test search with wine_type and country filters."""
    wines = [
        XWinesWine(
            id=1,
            name="Test Red Wine",
            wine_type="Red",
            country="France",
            country_code="FR",
            avg_rating=4.0,
            rating_count=100,
        ),
        XWinesWine(
            id=2,
            name="Test White Wine",
            wine_type="White",
            country="France",
            country_code="FR",
            avg_rating=4.0,
            rating_count=100,
        ),
    ]
    for wine in wines:
        db_session.add(wine)
    await db_session.commit()

    # Search with wine_type filter
    response = await client.get("/api/xwines/search?q=Test&wine_type=Red")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["results"][0]["wine_type"] == "Red"


@pytest.mark.asyncio
async def test_xwines_get_wine_detail(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test getting full wine details."""
    wine = XWinesWine(
        id=12345,
        name="Test Wine",
        wine_type="Red",
        elaborate="100%",
        grapes='["Cabernet Sauvignon"]',
        harmonize="Beef, Lamb",
        abv=14.5,
        body="Full-bodied",
        acidity="Medium",
        country="France",
        country_code="FR",
        region_name="Bordeaux",
        winery_name="Test Winery",
        avg_rating=4.3,
        rating_count=250,
    )
    db_session.add(wine)
    await db_session.commit()

    response = await client.get("/api/xwines/wines/12345")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == 12345
    assert data["name"] == "Test Wine"
    assert data["wine_type"] == "Red"
    assert data["body"] == "Full-bodied"
    assert data["harmonize"] == "Beef, Lamb"


@pytest.mark.asyncio
async def test_xwines_get_wine_not_found(client: AsyncClient) -> None:
    """Test getting a non-existent wine."""
    response = await client.get("/api/xwines/wines/99999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_xwines_stats_empty(client: AsyncClient) -> None:
    """Test stats endpoint with no data."""
    response = await client.get("/api/xwines/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["wine_count"] == 0
    assert data["rating_count"] == 0
    assert data["source"] == "https://github.com/rogerioxavier/X-Wines"


@pytest.mark.asyncio
async def test_xwines_stats_with_data(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test stats endpoint with data."""
    # Add wines
    for i in range(5):
        wine = XWinesWine(
            id=i + 1,
            name=f"Wine {i}",
            wine_type="Red",
            avg_rating=4.0,
            rating_count=100,
        )
        db_session.add(wine)

    # Add metadata
    metadata = [
        XWinesMetadata(key="version", value="test"),
        XWinesMetadata(key="rating_count", value="500"),
        XWinesMetadata(key="import_date", value="2024-01-15T10:30:00"),
    ]
    for m in metadata:
        db_session.add(m)

    await db_session.commit()

    response = await client.get("/api/xwines/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["wine_count"] == 5
    assert data["rating_count"] == 500
    assert data["version"] == "test"


@pytest.mark.asyncio
async def test_xwines_types_endpoint(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test listing wine types."""
    wines = [
        XWinesWine(id=1, name="Red Wine", wine_type="Red"),
        XWinesWine(id=2, name="White Wine", wine_type="White"),
        XWinesWine(id=3, name="Another Red", wine_type="Red"),
        XWinesWine(id=4, name="Rosé Wine", wine_type="Rosé"),
    ]
    for wine in wines:
        db_session.add(wine)
    await db_session.commit()

    response = await client.get("/api/xwines/types")
    assert response.status_code == 200
    types = response.json()
    assert len(types) == 3  # Red, White, Rosé (deduplicated)
    assert "Red" in types
    assert "White" in types
    assert "Rosé" in types


@pytest.mark.asyncio
async def test_xwines_countries_endpoint(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test listing countries with wine counts."""
    wines = [
        XWinesWine(id=1, name="Wine 1", wine_type="Red", country="France", country_code="FR"),
        XWinesWine(id=2, name="Wine 2", wine_type="Red", country="France", country_code="FR"),
        XWinesWine(id=3, name="Wine 3", wine_type="White", country="Italy", country_code="IT"),
    ]
    for wine in wines:
        db_session.add(wine)
    await db_session.commit()

    response = await client.get("/api/xwines/countries")
    assert response.status_code == 200
    countries = response.json()
    assert len(countries) == 2

    # France should be first (more wines)
    france = next((c for c in countries if c["code"] == "FR"), None)
    assert france is not None
    assert france["count"] == 2

    italy = next((c for c in countries if c["code"] == "IT"), None)
    assert italy is not None
    assert italy["count"] == 1


@pytest.mark.asyncio
async def test_xwines_search_ordering(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test search results are ordered by popularity then rating."""
    wines = [
        XWinesWine(
            id=1,
            name="Popular Wine",
            wine_type="Red",
            avg_rating=4.0,
            rating_count=1000,
        ),
        XWinesWine(
            id=2,
            name="Quality Wine",
            wine_type="Red",
            avg_rating=4.9,
            rating_count=100,
        ),
        XWinesWine(
            id=3,
            name="Unknown Wine",
            wine_type="Red",
            avg_rating=3.5,
            rating_count=10,
        ),
    ]
    for wine in wines:
        db_session.add(wine)
    await db_session.commit()

    response = await client.get("/api/xwines/search?q=Wine")
    assert response.status_code == 200
    data = response.json()
    results = data["results"]

    # Popular wine should be first (highest rating_count)
    assert results[0]["name"] == "Popular Wine"
    # Quality wine second (high rating, lower count)
    assert results[1]["name"] == "Quality Wine"
    # Unknown wine last
    assert results[2]["name"] == "Unknown Wine"
