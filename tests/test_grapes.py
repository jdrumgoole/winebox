"""Tests for wine grape blend endpoints."""

import pytest
import pytest_asyncio

from winebox.models import GrapeVariety, User, Wine
from winebox.models.wine import GrapeBlendEntry


@pytest_asyncio.fixture
async def grape_varieties(client, init_test_db):
    """Create grape varieties for testing."""
    cab = await GrapeVariety.find_one({"name": "Cabernet Sauvignon"})
    if not cab:
        cab = GrapeVariety(name="Cabernet Sauvignon", color="red", category="international")
        await cab.insert()
    merlot = await GrapeVariety.find_one({"name": "Merlot"})
    if not merlot:
        merlot = GrapeVariety(name="Merlot", color="red", category="international")
        await merlot.insert()
    return {"cab": cab, "merlot": merlot}


@pytest_asyncio.fixture
async def wine_with_grapes(client, init_test_db, grape_varieties, test_user_email):
    """Create a wine with grape blend."""
    user = await User.find_one({"email": test_user_email})
    wine = Wine(
        name="Bordeaux Blend",
        vintage=2018,
        winery="Test Winery",
        wine_type="red",
        country="France",
        owner_id=user.id,
        quantity=2,
        grape_blends=[
            GrapeBlendEntry(
                grape_variety_id=str(grape_varieties["cab"].id),
                grape_name="Cabernet Sauvignon",
                percentage=60,
                color="red",
            ),
            GrapeBlendEntry(
                grape_variety_id=str(grape_varieties["merlot"].id),
                grape_name="Merlot",
                percentage=40,
                color="red",
            ),
        ],
    )
    await wine.insert()
    return wine


@pytest_asyncio.fixture
async def wine_no_grapes(client, init_test_db, test_user_email):
    """Create a wine without grape blend."""
    user = await User.find_one({"email": test_user_email})
    wine = Wine(
        name="Mystery Wine",
        vintage=2020,
        winery="Unknown",
        wine_type="red",
        country="France",
        owner_id=user.id,
        quantity=1,
    )
    await wine.insert()
    return wine


class TestGetWineGrapes:
    """Tests for GET /{wine_id}/grapes."""

    @pytest.mark.asyncio
    async def test_get_grapes(self, client, wine_with_grapes):
        wine_id = str(wine_with_grapes.id)
        resp = await client.get(f"/api/wines/{wine_id}/grapes")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["grapes"]) == 2
        assert data["total_percentage"] == 100

    @pytest.mark.asyncio
    async def test_get_grapes_empty(self, client, wine_no_grapes):
        wine_id = str(wine_no_grapes.id)
        resp = await client.get(f"/api/wines/{wine_id}/grapes")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["grapes"]) == 0
        assert data["total_percentage"] is None

    @pytest.mark.asyncio
    async def test_get_grapes_not_found(self, client):
        resp = await client.get("/api/wines/000000000000000000000000/grapes")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_grapes_invalid_id(self, client):
        resp = await client.get("/api/wines/bad-id/grapes")
        assert resp.status_code == 404


class TestSetWineGrapes:
    """Tests for POST /{wine_id}/grapes."""

    @pytest.mark.asyncio
    async def test_set_grapes(self, client, wine_no_grapes, grape_varieties):
        wine_id = str(wine_no_grapes.id)
        cab_id = str(grape_varieties["cab"].id)
        merlot_id = str(grape_varieties["merlot"].id)
        resp = await client.post(
            f"/api/wines/{wine_id}/grapes",
            json={
                "grapes": [
                    {"grape_variety_id": cab_id, "percentage": 70},
                    {"grape_variety_id": merlot_id, "percentage": 30},
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["grapes"]) == 2
        assert data["total_percentage"] == 100

    @pytest.mark.asyncio
    async def test_set_grapes_replaces_existing(self, client, wine_with_grapes, grape_varieties):
        wine_id = str(wine_with_grapes.id)
        cab_id = str(grape_varieties["cab"].id)
        resp = await client.post(
            f"/api/wines/{wine_id}/grapes",
            json={
                "grapes": [
                    {"grape_variety_id": cab_id, "percentage": 100},
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["grapes"]) == 1

    @pytest.mark.asyncio
    async def test_set_grapes_invalid_variety(self, client, wine_no_grapes):
        wine_id = str(wine_no_grapes.id)
        resp = await client.post(
            f"/api/wines/{wine_id}/grapes",
            json={
                "grapes": [
                    {"grape_variety_id": "000000000000000000000000", "percentage": 100},
                ]
            },
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_set_grapes_wine_not_found(self, client, grape_varieties):
        cab_id = str(grape_varieties["cab"].id)
        resp = await client.post(
            "/api/wines/000000000000000000000000/grapes",
            json={
                "grapes": [
                    {"grape_variety_id": cab_id, "percentage": 100},
                ]
            },
        )
        assert resp.status_code == 404
