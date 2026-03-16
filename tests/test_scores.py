"""Tests for wine score endpoints."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone

from winebox.models import User, Wine
from winebox.models.wine import ScoreEntry


@pytest_asyncio.fixture
async def wine_with_scores(client, init_test_db):
    """Create a wine with scores for testing."""
    user = await User.find_one(User.email == "test@example.com")
    wine = Wine(
        name="Château Margaux",
        vintage=2015,
        winery="Château Margaux",
        wine_type="red",
        country="France",
        region="Bordeaux",
        owner_id=user.id,
        quantity=3,
        scores=[
            ScoreEntry(
                id="score-1",
                source="Wine Spectator",
                score=95,
                score_type="100_point",
                reviewer="James Suckling",
                notes="Excellent vintage",
                created_at=datetime.now(timezone.utc),
            ),
            ScoreEntry(
                id="score-2",
                source="Robert Parker",
                score=17,
                score_type="20_point",
                reviewer="Robert Parker",
                created_at=datetime.now(timezone.utc),
            ),
        ],
    )
    await wine.insert()
    return wine


@pytest_asyncio.fixture
async def wine_no_scores(client, init_test_db):
    """Create a wine without scores."""
    user = await User.find_one(User.email == "test@example.com")
    wine = Wine(
        name="Test Wine",
        vintage=2020,
        winery="Test Winery",
        wine_type="white",
        country="France",
        owner_id=user.id,
        quantity=1,
    )
    await wine.insert()
    return wine


class TestGetWineScores:
    """Tests for GET /{wine_id}/scores."""

    @pytest.mark.asyncio
    async def test_get_scores(self, client, wine_with_scores):
        wine_id = str(wine_with_scores.id)
        resp = await client.get(f"/api/wines/{wine_id}/scores")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["scores"]) == 2
        assert data["wine_id"] == wine_id
        assert data["average_score"] is not None

    @pytest.mark.asyncio
    async def test_get_scores_empty(self, client, wine_no_scores):
        wine_id = str(wine_no_scores.id)
        resp = await client.get(f"/api/wines/{wine_id}/scores")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["scores"]) == 0
        assert data["average_score"] is None

    @pytest.mark.asyncio
    async def test_get_scores_not_found(self, client):
        resp = await client.get("/api/wines/000000000000000000000000/scores")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_scores_invalid_id(self, client):
        resp = await client.get("/api/wines/bad-id/scores")
        assert resp.status_code == 404


class TestAddWineScore:
    """Tests for POST /{wine_id}/scores."""

    @pytest.mark.asyncio
    async def test_add_score(self, client, wine_no_scores):
        wine_id = str(wine_no_scores.id)
        resp = await client.post(
            f"/api/wines/{wine_id}/scores",
            json={
                "source": "Wine Advocate",
                "score": 92,
                "score_type": "100_point",
                "reviewer": "Lisa Perrotti-Brown",
                "notes": "Good structure",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["source"] == "Wine Advocate"
        assert data["score"] == 92
        assert data["score_type"] == "100_point"
        assert data["normalized_score"] is not None

    @pytest.mark.asyncio
    async def test_add_score_invalid_type(self, client, wine_no_scores):
        wine_id = str(wine_no_scores.id)
        resp = await client.post(
            f"/api/wines/{wine_id}/scores",
            json={
                "source": "Custom",
                "score": 8,
                "score_type": "10_point",
            },
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_add_score_wine_not_found(self, client):
        resp = await client.post(
            "/api/wines/000000000000000000000000/scores",
            json={
                "source": "Test",
                "score": 90,
                "score_type": "100_point",
            },
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_add_score_5_star(self, client, wine_no_scores):
        wine_id = str(wine_no_scores.id)
        resp = await client.post(
            f"/api/wines/{wine_id}/scores",
            json={
                "source": "Vivino",
                "score": 4,
                "score_type": "5_star",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["score_type"] == "5_star"


class TestUpdateWineScore:
    """Tests for PUT /{wine_id}/scores/{score_id}."""

    @pytest.mark.asyncio
    async def test_update_score(self, client, wine_with_scores):
        wine_id = str(wine_with_scores.id)
        resp = await client.put(
            f"/api/wines/{wine_id}/scores/score-1",
            json={"score": 97, "notes": "Updated review"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] == 97
        assert data["notes"] == "Updated review"

    @pytest.mark.asyncio
    async def test_update_score_not_found(self, client, wine_with_scores):
        wine_id = str(wine_with_scores.id)
        resp = await client.put(
            f"/api/wines/{wine_id}/scores/nonexistent",
            json={"score": 90},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_score_invalid_type(self, client, wine_with_scores):
        wine_id = str(wine_with_scores.id)
        resp = await client.put(
            f"/api/wines/{wine_id}/scores/score-1",
            json={"score_type": "invalid"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_update_score_wine_not_found(self, client):
        resp = await client.put(
            "/api/wines/000000000000000000000000/scores/score-1",
            json={"score": 90},
        )
        assert resp.status_code == 404


class TestDeleteWineScore:
    """Tests for DELETE /{wine_id}/scores/{score_id}."""

    @pytest.mark.asyncio
    async def test_delete_score(self, client, wine_with_scores):
        wine_id = str(wine_with_scores.id)
        resp = await client.delete(f"/api/wines/{wine_id}/scores/score-1")
        assert resp.status_code == 204

        # Verify score was removed
        resp = await client.get(f"/api/wines/{wine_id}/scores")
        assert len(resp.json()["scores"]) == 1

    @pytest.mark.asyncio
    async def test_delete_score_not_found(self, client, wine_with_scores):
        wine_id = str(wine_with_scores.id)
        resp = await client.delete(f"/api/wines/{wine_id}/scores/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_score_wine_not_found(self, client):
        resp = await client.delete("/api/wines/000000000000000000000000/scores/score-1")
        assert resp.status_code == 404
