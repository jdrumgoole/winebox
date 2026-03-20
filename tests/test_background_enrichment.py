"""Tests for the background enrichment service."""

from unittest.mock import AsyncMock, patch

import pytest

from winebox.models import XWinesWine, Wine
from winebox.services.background_enrichment import (
    _enrichment_progress,
    clear_enrichment_progress,
    enrich_unenriched_wines,
    get_enrichment_progress,
)


def _make_xwines_wine(**kwargs: object) -> XWinesWine:
    """Create an XWinesWine without requiring Beanie DB initialization."""
    defaults = {
        "xwines_id": 0,
        "name": "",
        "wine_type": "Red",
        "winery_name": "",
        "avg_rating": 0.0,
        "rating_count": 0,
    }
    defaults.update(kwargs)
    return XWinesWine.model_construct(**defaults)


# ---------------------------------------------------------------------------
# Progress store helpers
# ---------------------------------------------------------------------------


def test_get_enrichment_progress_none() -> None:
    """Returns None when no enrichment is running."""
    assert get_enrichment_progress("nonexistent-owner") is None


def test_enrichment_progress_lifecycle() -> None:
    """Progress can be set and cleared."""
    owner = "test-owner-123"
    _enrichment_progress[owner] = {"phase": "enriching", "enriched": 5, "total": 10}

    progress = get_enrichment_progress(owner)
    assert progress is not None
    assert progress["phase"] == "enriching"
    assert progress["enriched"] == 5

    clear_enrichment_progress(owner)
    assert get_enrichment_progress(owner) is None


# ---------------------------------------------------------------------------
# enrich_unenriched_wines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_empty_set(init_test_db) -> None:
    """No unenriched wines returns zero counts."""
    from bson import ObjectId

    owner_id = ObjectId()
    result = await enrich_unenriched_wines(owner_id)

    assert result["total"] == 0
    assert result["enriched"] == 0
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_enrich_skips_already_enriched(init_test_db) -> None:
    """Wines with xwines_id set are not re-enriched."""
    from bson import ObjectId

    owner_id = ObjectId()

    # Create a wine that already has xwines_id
    wine = Wine(
        owner_id=owner_id,
        name="Already Enriched Wine",
        xwines_id=12345,
    )
    await wine.insert()

    result = await enrich_unenriched_wines(owner_id)
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_enrich_updates_wine_documents(init_test_db) -> None:
    """Unenriched wines are updated with X-Wines data."""
    from bson import ObjectId

    owner_id = ObjectId()

    # Create an unenriched wine
    wine = Wine(
        owner_id=owner_id,
        name="Chateau Margaux",
    )
    await wine.insert()

    # Mock the batch enrichment to return a match
    mock_xwine = _make_xwines_wine(
        xwines_id=100,
        name="Chateau Margaux",
        winery_name="Chateau Margaux",
        wine_type="Red",
        region_name="Bordeaux",
        country="France",
        grapes="['Cabernet Sauvignon', 'Merlot']",
    )

    with patch(
        "winebox.services.background_enrichment._find_best_xwines_matches_batch",
        new_callable=AsyncMock,
        return_value={"Chateau Margaux": mock_xwine},
    ):
        result = await enrich_unenriched_wines(owner_id)

    assert result["total"] == 1
    assert result["enriched"] == 1
    assert result["failed"] == 0

    # Verify the wine was updated
    updated_wine = await Wine.get(wine.id)
    assert updated_wine.xwines_id == 100
    assert updated_wine.winery == "Chateau Margaux"
    assert updated_wine.region == "Bordeaux"
    assert updated_wine.country == "France"
    assert "winery" in updated_wine.enriched_fields
    assert "region" in updated_wine.enriched_fields


@pytest.mark.asyncio
async def test_enrich_preserves_existing_fields(init_test_db) -> None:
    """Existing wine fields are not overwritten by enrichment."""
    from bson import ObjectId

    owner_id = ObjectId()

    # Create a wine with some fields already set
    wine = Wine(
        owner_id=owner_id,
        name="Chateau Margaux",
        region="My Custom Region",
    )
    await wine.insert()

    mock_xwine = _make_xwines_wine(
        xwines_id=100,
        name="Chateau Margaux",
        winery_name="Chateau Margaux",
        region_name="Bordeaux",
        country="France",
    )

    with patch(
        "winebox.services.background_enrichment._find_best_xwines_matches_batch",
        new_callable=AsyncMock,
        return_value={"Chateau Margaux": mock_xwine},
    ):
        result = await enrich_unenriched_wines(owner_id)

    assert result["enriched"] == 1

    updated_wine = await Wine.get(wine.id)
    # Region should be preserved (not overwritten)
    assert updated_wine.region == "My Custom Region"
    # Winery should be filled
    assert updated_wine.winery == "Chateau Margaux"


@pytest.mark.asyncio
async def test_enrich_progress_callback(init_test_db) -> None:
    """Progress callback is invoked after each batch."""
    from bson import ObjectId

    owner_id = ObjectId()

    # Create a couple of unenriched wines
    for i in range(3):
        await Wine(owner_id=owner_id, name=f"Wine {i}").insert()

    callback_calls = []

    with patch(
        "winebox.services.background_enrichment._find_best_xwines_matches_batch",
        new_callable=AsyncMock,
        return_value={f"Wine {i}": None for i in range(3)},
    ):
        await enrich_unenriched_wines(
            owner_id,
            progress_callback=lambda enriched, total: callback_calls.append((enriched, total)),
        )

    # Callback should have been called at least once
    assert len(callback_calls) >= 1
    # Last call should have total=3
    assert callback_calls[-1][1] == 3


@pytest.mark.asyncio
async def test_enrich_sets_progress_store(init_test_db) -> None:
    """Progress store is updated during enrichment."""
    from bson import ObjectId

    owner_id = ObjectId()
    owner_str = str(owner_id)

    await Wine(owner_id=owner_id, name="Test Wine").insert()

    with patch(
        "winebox.services.background_enrichment._find_best_xwines_matches_batch",
        new_callable=AsyncMock,
        return_value={"Test Wine": None},
    ):
        await enrich_unenriched_wines(owner_id)

    # After completion, progress should be "done"
    progress = get_enrichment_progress(owner_str)
    assert progress is not None
    assert progress["phase"] == "done"

    # Clean up
    clear_enrichment_progress(owner_str)
