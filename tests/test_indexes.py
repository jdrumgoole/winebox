"""Tests for explicit MongoDB index setup.

Verifies that ensure_indexes creates all defined indexes without conflicts.
"""

import pytest

from winebox.db.indexes import INDEXES, ensure_indexes


@pytest.mark.asyncio
async def test_ensure_indexes_creates_indexes(init_test_db) -> None:
    """Verify ensure_indexes creates all defined indexes."""
    from winebox.database import get_database

    db = get_database()
    await ensure_indexes(db)

    # Verify the wines collection has more than just the _id index
    indexes = await db["wines"].index_information()
    assert len(indexes) > 1, "wines collection should have indexes beyond _id"


@pytest.mark.asyncio
async def test_ensure_indexes_idempotent(init_test_db) -> None:
    """Calling ensure_indexes twice should not error."""
    from winebox.database import get_database

    db = get_database()
    await ensure_indexes(db)
    await ensure_indexes(db)  # Should not raise


def test_all_collections_have_indexes() -> None:
    """Every collection in INDEXES dict should have at least one index defined."""
    for collection_name, index_models in INDEXES.items():
        assert len(index_models) > 0, f"{collection_name} has no indexes defined"


def test_expected_collections_present() -> None:
    """Verify all model collections have index definitions."""
    expected = {
        "users",
        "wines",
        "transactions",
        "wine_types",
        "grape_varieties",
        "regions",
        "classifications",
        "xwines_wines",
        "xwines_metadata",
        "revoked_tokens",
        "login_attempts",
        "import_batches",
        "raw_uploads",
    }
    assert set(INDEXES.keys()) == expected
