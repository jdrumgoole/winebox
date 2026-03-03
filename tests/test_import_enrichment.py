"""Tests for X-Wines enrichment during CSV/spreadsheet import."""

from unittest.mock import AsyncMock, patch

import pytest
from beanie import PydanticObjectId

from winebox.models import Wine, XWinesWine
from winebox.models.import_batch import ImportBatch, ImportStatus
from winebox.services.import_service.processor import process_import_batch


# ---------------------------------------------------------------------------
# Helper: insert an X-Wines reference wine
# ---------------------------------------------------------------------------


async def _insert_xwines_wine(**kwargs) -> XWinesWine:
    """Insert an XWinesWine with sensible defaults."""
    defaults = {
        "xwines_id": 600,
        "name": "Import Test Wine",
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
    await _insert_xwines_wine()

    owner_id = PydanticObjectId()
    batch = _make_batch(
        owner_id=owner_id,
        rows=[{"Wine Name": "Import Test Wine"}],
        mapping={"Wine Name": "name"},
    )
    await batch.insert()

    result = await process_import_batch(batch, owner_id)

    assert result.status == ImportStatus.COMPLETED
    assert result.wines_created == 1

    wine = await Wine.find_one(Wine.name == "Import Test Wine")
    assert wine is not None
    assert wine.winery == "Import Winery"
    assert wine.grape_variety == "Pinot Noir"
    assert wine.region == "Burgundy"
    assert wine.country == "France"
    assert wine.alcohol_percentage == 12.5
    assert wine.xwines_id == 600
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
    await _insert_xwines_wine()

    owner_id = PydanticObjectId()
    batch = _make_batch(
        owner_id=owner_id,
        rows=[{
            "Wine Name": "Import Test Wine",
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

    wine = await Wine.find_one(Wine.name == "Import Test Wine")
    assert wine is not None

    # CSV values preserved
    assert wine.grape_variety == "Chardonnay"
    assert wine.region == "Napa Valley"

    # Empty fields still enriched
    assert wine.winery == "Import Winery"
    assert wine.country == "France"
    assert wine.xwines_id == 600

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
        "winebox.services.import_service.processor.enrich_parsed_with_xwines",
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
