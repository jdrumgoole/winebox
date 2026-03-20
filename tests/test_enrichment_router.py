"""Tests for the enrichment router endpoints."""

import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock

from winebox.models import User, Wine


@pytest_asyncio.fixture
async def unenriched_wines(client, init_test_db, test_user_email):
    """Create wines without xwines_id for enrichment testing."""
    user = await User.find_one({"email": test_user_email})
    wines = []
    for i in range(3):
        wine = Wine(
            name=f"Test Wine {i}",
            vintage=2020,
            winery="Test Winery",
            wine_type="red",
            country="France",
            owner_id=user.id,
            quantity=1,
        )
        await wine.insert()
        wines.append(wine)
    return wines


@pytest_asyncio.fixture
async def enriched_wines(client, init_test_db, test_user_email):
    """Create wines that are already enriched."""
    user = await User.find_one({"email": test_user_email})
    wines = []
    for i in range(2):
        wine = Wine(
            name=f"Enriched Wine {i}",
            vintage=2019,
            winery="Good Winery",
            wine_type="white",
            country="Italy",
            owner_id=user.id,
            quantity=1,
            xwines_id=1000 + i,
        )
        await wine.insert()
        wines.append(wine)
    return wines


class TestEnrichWines:
    """Tests for POST /enrich."""

    @pytest.mark.asyncio
    async def test_enrich_triggers_background_task(self, client, unenriched_wines):
        with patch(
            "winebox.routers.wines.enrichment.enrich_unenriched_wines",
            new_callable=AsyncMock,
        ):
            resp = await client.post("/api/wines/enrich")
            assert resp.status_code == 200
            data = resp.json()
            assert data["unenriched"] == 3
            assert "started" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_enrich_all_already_enriched(self, client, enriched_wines):
        resp = await client.post("/api/wines/enrich")
        assert resp.status_code == 200
        data = resp.json()
        assert data["unenriched"] == 0
        assert "already enriched" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_enrich_empty_cellar(self, client):
        resp = await client.post("/api/wines/enrich")
        assert resp.status_code == 200
        data = resp.json()
        assert data["unenriched"] == 0


class TestEnrichmentProgress:
    """Tests for GET /enrichment-progress."""

    @pytest.mark.asyncio
    async def test_progress_no_enrichment_running(self, client):
        with patch(
            "winebox.routers.wines.enrichment.get_enrichment_progress",
            return_value=None,
        ):
            resp = await client.get("/api/wines/enrichment-progress")
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")

    @pytest.mark.asyncio
    async def test_progress_returns_done(self, client):
        call_count = 0

        def mock_progress(owner_str):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"phase": "enriching", "enriched": 1, "total": 3}
            return {"phase": "done", "enriched": 3, "total": 3}

        with patch(
            "winebox.routers.wines.enrichment.get_enrichment_progress",
            side_effect=mock_progress,
        ), patch(
            "winebox.routers.wines.enrichment.clear_enrichment_progress",
        ):
            resp = await client.get("/api/wines/enrichment-progress")
            assert resp.status_code == 200
