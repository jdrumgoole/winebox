"""Tests for X-Wines enrichment during CSV/spreadsheet import."""

import random
from unittest.mock import AsyncMock, patch

import pytest
from beanie import PydanticObjectId

from winebox.models import Wine, XWinesWine
from winebox.models.import_batch import ImportBatch, ImportStatus
from winebox.services.import_service.processor import (
    process_import_batch,
    process_import_batch_streaming,
)


# ---------------------------------------------------------------------------
# Helper: insert an X-Wines reference wine
# ---------------------------------------------------------------------------


async def _insert_xwines_wine(**kwargs) -> XWinesWine:
    """Insert an XWinesWine with sensible defaults.

    Uses a random xwines_id and a unique name to avoid collisions
    with XWinesWine documents from other tests in a shared database.
    """
    unique_suffix = random.randint(900_000, 999_999)
    defaults = {
        "xwines_id": unique_suffix,
        "name": f"ImportTestWine Zinfandel Reserve {unique_suffix}",
        "wine_type": "Red",
        "winery_name": "Import Winery",
        "country": "France",
        "country_code": "FR",
        "region_name": "Burgundy",
        "grapes": "['Pinot Noir']",
        "abv": 12.5,
        "avg_rating": 4.0,
        "rating_count": 150,
    }
    defaults.update(kwargs)
    xwine = XWinesWine(**defaults)
    await xwine.insert()
    return xwine


def _make_batch(owner_id: PydanticObjectId, rows: list[dict], mapping: dict) -> ImportBatch:
    """Create an ImportBatch document (unsaved) with the given rows and mapping."""
    return ImportBatch(
        owner_id=owner_id,
        filename="test.csv",
        file_type="csv",
        status=ImportStatus.MAPPED,
        column_mapping=mapping,
        headers=list(mapping.keys()),
        rows=rows,
        row_count=len(rows),
    )


# ---------------------------------------------------------------------------
# Test: import enriches empty fields from X-Wines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_enriches_empty_fields(init_test_db) -> None:
    """Import a wine with only a name — X-Wines should fill empty fields."""
    xwine = await _insert_xwines_wine()
    wine_name = xwine.name

    owner_id = PydanticObjectId()
    batch = _make_batch(
        owner_id=owner_id,
        rows=[{"Wine Name": wine_name}],
        mapping={"Wine Name": "name"},
    )
    await batch.insert()

    result = await process_import_batch(batch, owner_id)

    assert result.status == ImportStatus.COMPLETED
    assert result.wines_created == 1

    wine = await Wine.find_one(Wine.name == wine_name)
    assert wine is not None
    assert wine.winery == "Import Winery"
    assert wine.grape_variety == "Pinot Noir"
    assert wine.region == "Burgundy"
    assert wine.country == "France"
    assert wine.alcohol_percentage == 12.5
    assert wine.xwines_id == xwine.xwines_id
    assert wine.enriched_fields is not None
    assert "winery" in wine.enriched_fields
    assert "grape_variety" in wine.enriched_fields
    assert "region" in wine.enriched_fields
    assert "country" in wine.enriched_fields
    assert "alcohol_percentage" in wine.enriched_fields


# ---------------------------------------------------------------------------
# Test: import preserves CSV-provided values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_preserves_csv_values(init_test_db) -> None:
    """CSV-provided grape and region should NOT be overwritten by X-Wines."""
    xwine = await _insert_xwines_wine()
    wine_name = xwine.name

    owner_id = PydanticObjectId()
    batch = _make_batch(
        owner_id=owner_id,
        rows=[{
            "Wine Name": wine_name,
            "Grape": "Chardonnay",
            "Region": "Napa Valley",
        }],
        mapping={
            "Wine Name": "name",
            "Grape": "grape_variety",
            "Region": "region",
        },
    )
    await batch.insert()

    result = await process_import_batch(batch, owner_id)

    assert result.wines_created == 1

    wine = await Wine.find_one(Wine.name == wine_name)
    assert wine is not None

    # CSV values preserved
    assert wine.grape_variety == "Chardonnay"
    assert wine.region == "Napa Valley"

    # Empty fields still enriched
    assert wine.winery == "Import Winery"
    assert wine.country == "France"
    assert wine.xwines_id == xwine.xwines_id

    # Only truly enriched fields listed
    assert "grape_variety" not in wine.enriched_fields
    assert "region" not in wine.enriched_fields
    assert "winery" in wine.enriched_fields
    assert "country" in wine.enriched_fields


# ---------------------------------------------------------------------------
# Test: no match means no enrichment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_no_match_no_enrichment(init_test_db) -> None:
    """Wine with no X-Wines match should have no enrichment metadata."""
    # No X-Wines data inserted

    owner_id = PydanticObjectId()
    batch = _make_batch(
        owner_id=owner_id,
        rows=[{"Wine Name": "Totally Unknown Wine ABCXYZ"}],
        mapping={"Wine Name": "name"},
    )
    await batch.insert()

    result = await process_import_batch(batch, owner_id)

    assert result.wines_created == 1

    wine = await Wine.find_one(Wine.name == "Totally Unknown Wine ABCXYZ")
    assert wine is not None
    assert wine.enriched_fields is None
    assert wine.xwines_id is None


# ---------------------------------------------------------------------------
# Test: enrichment failure is non-fatal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_enrichment_failure_nonfatal(init_test_db) -> None:
    """If X-Wines lookup raises an exception, the wine is still imported."""
    owner_id = PydanticObjectId()
    batch = _make_batch(
        owner_id=owner_id,
        rows=[{"Wine Name": "Some Wine"}],
        mapping={"Wine Name": "name"},
    )
    await batch.insert()

    with patch(
        "winebox.services.import_service.processor.enrich_batch_with_xwines",
        new_callable=AsyncMock,
        side_effect=RuntimeError("X-Wines service down"),
    ):
        result = await process_import_batch(batch, owner_id)

    assert result.status == ImportStatus.COMPLETED
    assert result.wines_created == 1

    wine = await Wine.find_one(Wine.name == "Some Wine")
    assert wine is not None
    # No enrichment metadata since the service failed
    assert wine.enriched_fields is None
    assert wine.xwines_id is None


# ---------------------------------------------------------------------------
# Test: multi-chunk pipeline processes all rows correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_multi_chunk_pipeline(init_test_db) -> None:
    """Import 120 rows (3 chunks of 50+50+20) — all should be created."""
    owner_id = PydanticObjectId()
    rows = [{"Wine Name": f"Pipeline Wine {i}"} for i in range(120)]
    batch = _make_batch(
        owner_id=owner_id,
        rows=rows,
        mapping={"Wine Name": "name"},
    )
    await batch.insert()

    with patch(
        "winebox.services.import_service.processor.enrich_batch_with_xwines",
        new_callable=AsyncMock,
    ):
        result = await process_import_batch(batch, owner_id)

    assert result.status == ImportStatus.COMPLETED
    assert result.wines_created == 120
    assert result.rows_skipped == 0
    assert result.errors == []

    count = await Wine.find(Wine.owner_id == owner_id).count()
    assert count == 120


# ---------------------------------------------------------------------------
# Test: streaming progress is monotonically increasing with multi-chunk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_streaming_progress_monotonic(init_test_db) -> None:
    """Streaming progress should be monotonically increasing even with pipeline."""
    owner_id = PydanticObjectId()
    rows = [{"Wine Name": f"Progress Wine {i}"} for i in range(75)]
    batch = _make_batch(
        owner_id=owner_id,
        rows=rows,
        mapping={"Wine Name": "name"},
    )
    await batch.insert()

    batch.status = ImportStatus.MAPPED
    await batch.save()

    events: list[dict] = []
    with patch(
        "winebox.services.import_service.processor.enrich_batch_with_xwines",
        new_callable=AsyncMock,
    ):
        async for progress in process_import_batch_streaming(batch, owner_id):
            events.append(progress)

    # Should have initial event + chunk events + final done event
    assert len(events) >= 3

    # Progress should be monotonically increasing
    for i in range(1, len(events)):
        assert events[i]["processed"] >= events[i - 1]["processed"]

    # Final event
    final = events[-1]
    assert final.get("done") is True
    assert final["wines_created"] == 75
    assert final["total"] == 75
