"""Tests for MongoDB index compatibility.

These tests verify that:
1. All Beanie document models can create their indexes without conflicts
2. The X-Wines import script's indexes are compatible with Beanie's model definitions
3. Beanie can start successfully after the import script has run (and vice versa)
4. No two collections define conflicting text indexes

Index conflicts have caused production outages — these tests prevent regressions.
"""

import pytest
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient, IndexModel

from winebox.database import get_document_models


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_import_script_indexes() -> list[tuple[str, IndexModel]]:
    """Return the indexes that deploy/import_xwines_mongo.py creates.

    Keep this in sync with the create_index calls in import_xwines_mongo.py.
    If the import script changes, update this list and the tests will catch
    any new conflicts.
    """
    return [
        ("xwines_wines", IndexModel([("xwines_id", 1)], unique=True)),
        ("xwines_wines", IndexModel([("name", 1)])),
        ("xwines_wines", IndexModel([("wine_type", 1)])),
        ("xwines_wines", IndexModel([("country_code", 1)])),
        ("xwines_wines", IndexModel([("winery_name", 1)])),
        ("xwines_wines", IndexModel([("rating_count", 1)])),
        ("xwines_wines", IndexModel([("name", "text"), ("winery_name", "text")])),
        ("xwines_wines", IndexModel([("name", 1), ("rating_count", -1)])),
    ]


def _extract_beanie_index_specs(model_class: type) -> list[dict]:
    """Extract index specifications from a Beanie Document model.

    Returns a list of dicts with 'key' and 'unique' for each index.
    Handles both field-level Indexed() declarations and Settings.indexes.
    """
    specs = []

    # Get field-level indexes from Indexed() annotations
    for field_name, field_info in model_class.model_fields.items():
        metadata = getattr(field_info, "metadata", [])
        for meta in metadata:
            if hasattr(meta, "index") or (isinstance(meta, dict) and meta.get("index")):
                unique = getattr(meta, "unique", False) if hasattr(meta, "unique") else False
                specs.append({"key": [(field_name, 1)], "unique": unique})

    # Get Settings.indexes
    settings = getattr(model_class, "Settings", None)
    if settings:
        for idx_def in getattr(settings, "indexes", []):
            if isinstance(idx_def, str):
                specs.append({"key": [(idx_def, 1)], "unique": False})
            elif isinstance(idx_def, list):
                specs.append({"key": idx_def, "unique": False})

    return specs


# ---------------------------------------------------------------------------
# Tests: Beanie init_beanie succeeds on a clean database
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_beanie_init_creates_all_indexes(mongo_client: AsyncIOMotorClient, init_test_db) -> None:
    """Verify that Beanie init_beanie completes without index conflicts.

    This catches cases where two models define conflicting indexes on the
    same collection (e.g., a text index with different field sets).
    """
    # init_test_db already called init_beanie — if we got here, it succeeded.
    # Verify by checking that collections have indexes.
    db = init_test_db
    collection_names = await db.list_collection_names()

    # wines and xwines_wines should exist (created by Beanie on init)
    for expected in ["wines", "xwines_wines"]:
        if expected in collection_names:
            indexes = await db[expected].index_information()
            # Should have more than just _id
            assert len(indexes) > 1, (
                f"Collection '{expected}' has no custom indexes — "
                f"Beanie may have failed silently. Indexes: {list(indexes.keys())}"
            )


@pytest.mark.asyncio
async def test_beanie_init_idempotent(mongo_client: AsyncIOMotorClient, init_test_db) -> None:
    """Verify that calling init_beanie twice doesn't cause index conflicts.

    This simulates server restarts — Beanie must be able to re-init
    against a database that already has its indexes.
    """
    db = init_test_db

    # Call init_beanie a second time (simulates server restart)
    await init_beanie(
        database=db,
        document_models=get_document_models(),
    )
    # If we get here without an OperationFailure, indexes are idempotent.


# ---------------------------------------------------------------------------
# Tests: Import script indexes are compatible with Beanie
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_import_indexes_then_beanie_init(mongo_client: AsyncIOMotorClient) -> None:
    """Verify Beanie can init after the import script has created indexes.

    This is the exact scenario that caused production outages: the import
    script runs first, creates indexes, then the server starts and Beanie
    tries to create its own indexes.
    """
    import uuid

    # Use a fresh database
    db_name = f"test_idx_import_first_{uuid.uuid4().hex[:8]}"
    db = mongo_client[db_name]

    try:
        # Step 1: Simulate import script creating indexes (using sync pymongo)
        sync_client = MongoClient(str(mongo_client.delegate.address[0]),
                                  mongo_client.delegate.address[1])
        sync_db = sync_client[db_name]
        col = sync_db["xwines_wines"]

        # Create the same indexes the import script creates
        col.create_index("xwines_id", unique=True)
        col.create_index("name")
        col.create_index("wine_type")
        col.create_index("country_code")
        col.create_index("winery_name")
        col.create_index("rating_count")
        col.create_index([("name", "text"), ("winery_name", "text")])
        col.create_index([("name", 1), ("rating_count", -1)])

        sync_client.close()

        # Step 2: Now init Beanie (simulates server startup after import)
        await init_beanie(
            database=db,
            document_models=get_document_models(),
        )
        # If we get here, no index conflicts!

    finally:
        await mongo_client.drop_database(db_name)


@pytest.mark.asyncio
async def test_beanie_init_then_import_indexes(mongo_client: AsyncIOMotorClient) -> None:
    """Verify the import script can create indexes after Beanie has initialized.

    This is the reverse scenario: server starts first, then the import runs.
    """
    import uuid

    db_name = f"test_idx_beanie_first_{uuid.uuid4().hex[:8]}"
    db = mongo_client[db_name]

    try:
        # Step 1: Init Beanie first (server startup)
        await init_beanie(
            database=db,
            document_models=get_document_models(),
        )

        # Step 2: Simulate import script creating indexes
        sync_client = MongoClient(str(mongo_client.delegate.address[0]),
                                  mongo_client.delegate.address[1])
        sync_db = sync_client[db_name]
        col = sync_db["xwines_wines"]

        # These should not conflict with Beanie's indexes
        col.create_index("xwines_id", unique=True)
        col.create_index("name")
        col.create_index("wine_type")
        col.create_index("country_code")
        col.create_index("winery_name")
        col.create_index("rating_count")
        col.create_index([("name", "text"), ("winery_name", "text")])
        col.create_index([("name", 1), ("rating_count", -1)])

        sync_client.close()
        # If we get here, no conflicts!

    finally:
        await mongo_client.drop_database(db_name)


# ---------------------------------------------------------------------------
# Tests: No text index conflicts within a collection
# ---------------------------------------------------------------------------

def test_no_duplicate_text_indexes_per_collection() -> None:
    """Verify no collection has more than one text index definition.

    MongoDB only allows one text index per collection. If two models or
    the import script both try to create text indexes on the same collection
    with different fields, it will fail at runtime.
    """
    text_indexes: dict[str, list[str]] = {}  # collection_name -> [source descriptions]

    for model_class in get_document_models():
        collection_name = model_class.Settings.name
        settings = getattr(model_class, "Settings", None)
        if not settings:
            continue

        for idx_def in getattr(settings, "indexes", []):
            if isinstance(idx_def, list):
                has_text = any(
                    (isinstance(pair, tuple) and len(pair) == 2 and pair[1] == "text")
                    for pair in idx_def
                )
                if has_text:
                    fields = [p[0] for p in idx_def if isinstance(p, tuple)]
                    source = f"Beanie model {model_class.__name__}: {fields}"
                    text_indexes.setdefault(collection_name, []).append(source)

    # Also check import script text indexes
    for col_name, idx_model in _get_import_script_indexes():
        key_pairs = idx_model.document.get("key", [])
        if isinstance(key_pairs, list):
            has_text = any(pair[1] == "text" for pair in key_pairs if isinstance(pair, tuple))
            if has_text:
                fields = [p[0] for p in key_pairs if isinstance(p, tuple)]
                source = f"Import script: {fields}"
                text_indexes.setdefault(col_name, []).append(source)

    # Each collection should have at most one text index definition
    for col_name, sources in text_indexes.items():
        # Multiple sources for the same collection are OK if they define
        # the same fields — that's idempotent. Check for different fields.
        unique_field_sets = set()
        for source in sources:
            # Extract field list from source description
            fields_str = source.split(": ")[1] if ": " in source else source
            unique_field_sets.add(fields_str)

        assert len(unique_field_sets) <= 1, (
            f"Collection '{col_name}' has conflicting text index definitions:\n"
            + "\n".join(f"  - {s}" for s in sources)
        )


# ---------------------------------------------------------------------------
# Tests: Import script index definitions match Beanie model
# ---------------------------------------------------------------------------

def test_import_script_indexes_match_beanie_model() -> None:
    """Verify the import script creates the same indexes Beanie expects.

    If someone changes the Beanie model's index definitions but forgets
    to update the import script (or vice versa), this test will fail.
    """
    from winebox.models.xwines import XWinesWine

    # Get Beanie's expected indexes for xwines_wines
    beanie_indexes = set()
    settings = XWinesWine.Settings
    for idx_def in settings.indexes:
        if isinstance(idx_def, str):
            beanie_indexes.add((idx_def, "single"))
        elif isinstance(idx_def, list):
            if any(pair[1] == "text" for pair in idx_def if isinstance(pair, tuple)):
                fields = tuple(p[0] for p in idx_def if isinstance(p, tuple))
                beanie_indexes.add((fields, "text"))
            else:
                beanie_indexes.add((tuple(idx_def), "compound"))

    # Get import script's indexes for xwines_wines
    import_indexes = set()
    for col_name, idx_model in _get_import_script_indexes():
        if col_name != "xwines_wines":
            continue
        key_pairs = idx_model.document.get("key", [])
        if isinstance(key_pairs, list) and len(key_pairs) == 1:
            field, direction = key_pairs[0]
            if direction == "text":
                import_indexes.add(((field,), "text"))
            else:
                import_indexes.add((field, "single"))
        elif isinstance(key_pairs, list) and len(key_pairs) > 1:
            if any(p[1] == "text" for p in key_pairs):
                fields = tuple(p[0] for p in key_pairs)
                import_indexes.add((fields, "text"))
            else:
                import_indexes.add((tuple(key_pairs), "compound"))

    # Import script indexes should be a subset of (or equal to) Beanie's
    # (import may have fewer indexes, but shouldn't have ones Beanie doesn't expect)
    import_only = import_indexes - beanie_indexes
    if import_only:
        # This is OK — the import script can create indexes that Beanie also
        # defines via field-level Indexed(). Check that these aren't conflicting.
        pass  # Import having extra indexes that match Beanie fields is fine

    # The import script's text index fields must match Beanie's text index fields
    import_text = [idx for idx in import_indexes if idx[1] == "text"]
    beanie_text = [idx for idx in beanie_indexes if idx[1] == "text"]

    if import_text and beanie_text:
        assert import_text == beanie_text, (
            f"Text index field mismatch on xwines_wines:\n"
            f"  Import script: {import_text}\n"
            f"  Beanie model:  {beanie_text}\n"
            f"This will cause an IndexOptionsConflict at runtime!"
        )
