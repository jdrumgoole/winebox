"""Explicit MongoDB index definitions and setup.

All indexes are defined here instead of being auto-managed by an ODM.
Run ensure_indexes() on startup or via a management command.
"""

import logging

from pymongo import ASCENDING, DESCENDING, TEXT, IndexModel
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.operations import SearchIndexModel

logger = logging.getLogger(__name__)

# Atlas Search index definitions.
# These require MongoDB Atlas (not available on standalone mongod).
ATLAS_SEARCH_INDEXES: dict[str, list[SearchIndexModel]] = {
    "xwines_wines": [
        SearchIndexModel(
            definition={
                "mappings": {
                    "dynamic": False,
                    "fields": {
                        "name": {"type": "string", "analyzer": "lucene.standard"},
                        "winery_name": {"type": "string", "analyzer": "lucene.standard"},
                        "wine_type": {"type": "string", "analyzer": "lucene.keyword"},
                        "country_code": {"type": "string", "analyzer": "lucene.keyword"},
                        "region_name": {"type": "string", "analyzer": "lucene.standard"},
                        "rating_count": {"type": "number"},
                    },
                },
            },
            name="xwines_search",
        ),
    ],
}

# Index definitions per collection.
# Each entry is a list of pymongo.IndexModel objects.
INDEXES: dict[str, list[IndexModel]] = {
    "users": [
        IndexModel([("email", ASCENDING)], unique=True),
    ],
    "wines": [
        IndexModel([("owner_id", ASCENDING)]),
        IndexModel([("name", ASCENDING)]),
        IndexModel([("winery", ASCENDING)]),
        IndexModel([("vintage", ASCENDING)]),
        IndexModel([("country", ASCENDING)]),
        IndexModel([("wine_type", ASCENDING)]),
        IndexModel([("owner_id", ASCENDING), ("inventory.quantity", ASCENDING)]),
        IndexModel([("owner_id", ASCENDING), ("collection", ASCENDING)]),
        IndexModel([("owner_id", ASCENDING), ("collection", ASCENDING), ("inventory.quantity", ASCENDING)]),
        IndexModel([("owner_id", ASCENDING), ("xwines_id", ASCENDING)]),
        IndexModel(
            [
                ("name", TEXT),
                ("winery", TEXT),
                ("region", TEXT),
                ("sub_region", TEXT),
                ("appellation", TEXT),
                ("country", TEXT),
                ("front_label_text", TEXT),
                ("custom_fields_text", TEXT),
            ]
        ),
    ],
    "transactions": [
        IndexModel([("owner_id", ASCENDING)]),
        IndexModel([("wine_id", ASCENDING)]),
        IndexModel([("transaction_type", ASCENDING)]),
        IndexModel([("transaction_date", ASCENDING)]),
        IndexModel([("owner_id", ASCENDING), ("transaction_date", DESCENDING)]),
        IndexModel([("owner_id", ASCENDING), ("removal_reason", ASCENDING), ("transaction_date", DESCENDING)]),
    ],
    "wine_types": [
        IndexModel([("type_id", ASCENDING)]),
    ],
    "grape_varieties": [
        IndexModel([("name", ASCENDING)], unique=True),
        IndexModel([("color", ASCENDING)]),
    ],
    "regions": [
        IndexModel([("name", ASCENDING)]),
        IndexModel([("level", ASCENDING)]),
        IndexModel([("parent_id", ASCENDING)]),
        IndexModel([("country", ASCENDING)]),
        IndexModel([("path", ASCENDING)]),
    ],
    "classifications": [
        IndexModel([("name", ASCENDING)]),
        IndexModel([("country", ASCENDING)]),
        IndexModel([("system", ASCENDING)]),
    ],
    "xwines_wines": [
        IndexModel([("xwines_id", ASCENDING)], unique=True),
        IndexModel([("name", ASCENDING)]),
        IndexModel([("wine_type", ASCENDING)]),
        IndexModel([("country_code", ASCENDING)]),
        IndexModel([("winery_name", ASCENDING)]),
        IndexModel([("rating_count", ASCENDING)]),
        IndexModel([("name", TEXT), ("winery_name", TEXT)]),
        IndexModel([("name", ASCENDING), ("rating_count", DESCENDING)]),
    ],
    "xwines_metadata": [
        IndexModel([("key", ASCENDING)], unique=True),
    ],
    "revoked_tokens": [
        IndexModel([("jti", ASCENDING)], unique=True),
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
    ],
    "login_attempts": [
        IndexModel([("email", ASCENDING)]),
        IndexModel([("attempted_at", ASCENDING)], expireAfterSeconds=86400),
        IndexModel([("email", ASCENDING), ("failed", ASCENDING), ("attempted_at", ASCENDING)]),
    ],
    "import_batches": [
        IndexModel([("owner_id", ASCENDING)]),
    ],
    "raw_uploads": [
        IndexModel([("batch_id", ASCENDING), ("index", ASCENDING)]),
    ],
    "xwines_prices": [
        IndexModel([("xwines_id", ASCENDING), ("vintage", ASCENDING)], unique=True),
        IndexModel([("xwines_id", ASCENDING)]),  # For lookups without vintage
    ],
    # Cellar — one document per physical item (case or bottle)
    "cellars": [
        IndexModel([("cellar_id", ASCENDING)]),
        IndexModel([("cellar_id", ASCENDING), ("item_type", ASCENDING)]),
        IndexModel([("cellar_id", ASCENDING), ("wine.wine_id", ASCENDING)]),
        IndexModel([("import_batch_id", ASCENDING)]),
    ],
    "cellar_events": [
        IndexModel([("cellar_id", ASCENDING), ("cellar_item_id", ASCENDING)]),
        IndexModel([("cellar_id", ASCENDING), ("event_date", DESCENDING)]),
        IndexModel([("cellar_id", ASCENDING), ("event_type", ASCENDING)]),
        IndexModel([("import_batch_id", ASCENDING)]),
        # Phase 4 — match Transaction's query patterns once readers move
        # off Transaction (4d). Both indexes use owner_id (the new mirror
        # of cellar_id) so future code that thinks in owners doesn't have
        # to translate.
        IndexModel([("owner_id", ASCENDING), ("event_date", DESCENDING)]),
        IndexModel([("owner_id", ASCENDING), ("wine_id", ASCENDING), ("event_date", DESCENDING)]),
    ],
    "wine_prices": [
        IndexModel(
            [("wine_name", ASCENDING), ("vintage", ASCENDING), ("wine_type", ASCENDING)],
            unique=True,
        ),
        IndexModel([("prices.owner_id", ASCENDING)]),
        IndexModel([("wine_name", ASCENDING)]),
        IndexModel([("updated_at", DESCENDING)]),
    ],
    "wine_prices_history": [
        IndexModel([("wine_name", ASCENDING), ("vintage", ASCENDING), ("wine_type", ASCENDING)]),
        IndexModel([("archived_at", DESCENDING)]),
        IndexModel([("owner_id", ASCENDING)]),
    ],
}


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create all indexes, handling conflicts with existing indexes.

    If an index exists with the same name but different options (e.g. a
    non-unique index that should now be unique), the old index is dropped
    and recreated.

    Args:
        db: The async pymongo database instance.
    """
    from pymongo.errors import OperationFailure

    # Drop non-TTL indexes that are being replaced by TTL versions.
    # MongoDB cannot convert a regular index to TTL in-place.
    ttl_migrations = [
        ("revoked_tokens", "expires_at_1"),
        ("login_attempts", "attempted_at_1"),
    ]
    for coll_name, idx_name in ttl_migrations:
        try:
            coll = db[coll_name]
            existing = await coll.index_information()
            if idx_name in existing and "expireAfterSeconds" not in existing[idx_name]:
                await coll.drop_index(idx_name)
                logger.info("Dropped non-TTL index %s.%s for TTL migration", coll_name, idx_name)
        except Exception:
            pass  # Collection may not exist yet

    for collection_name, index_models in INDEXES.items():
        collection = db[collection_name]
        try:
            await collection.create_indexes(index_models)
            logger.debug("Indexes ensured for %s", collection_name)
        except OperationFailure as e:
            if e.code in (85, 86):  # IndexOptionsConflict, IndexKeySpecsConflict
                logger.warning(
                    "Index conflict in %s, dropping and recreating: %s",
                    collection_name, e.details.get("errmsg", ""),
                )
                # Drop conflicting indexes by their actual names in the database
                existing = await collection.index_information()
                for model in index_models:
                    model_key = model.document["key"]
                    is_text = any(v == "text" for _, v in model_key.items())

                    for existing_name, existing_info in existing.items():
                        if existing_name == "_id_":
                            continue
                        existing_key = existing_info["key"]
                        existing_is_text = any(k == "_fts" for k, _ in existing_key)

                        # Text indexes: only one per collection, so any existing
                        # text index conflicts with the new one
                        if is_text and existing_is_text:
                            try:
                                await collection.drop_index(existing_name)
                                logger.info("Dropped conflicting text index %s.%s", collection_name, existing_name)
                            except OperationFailure:
                                pass
                            break
                        # Non-text: match by key spec
                        if not is_text and dict(existing_key) == dict(model_key):
                            try:
                                await collection.drop_index(existing_name)
                                logger.info("Dropped conflicting index %s.%s", collection_name, existing_name)
                            except OperationFailure:
                                pass
                            break
                # Retry creation
                try:
                    await collection.create_indexes(index_models)
                    logger.info("Indexes recreated for %s", collection_name)
                except Exception:
                    logger.exception("Failed to recreate indexes for %s", collection_name)
            else:
                logger.exception("Failed to create indexes for %s", collection_name)
        except Exception:
            logger.exception("Failed to create indexes for %s", collection_name)

    # --- Atlas Search indexes (only available on MongoDB Atlas) ---
    for collection_name, search_models in ATLAS_SEARCH_INDEXES.items():
        collection = db[collection_name]
        for model in search_models:
            search_name = model.document.get("name", "unknown")
            try:
                # Check if the search index already exists
                existing = []
                async for idx in await collection.list_search_indexes(name=search_name):
                    existing.append(idx)
                if existing:
                    logger.debug("Atlas Search index '%s' already exists on %s", search_name, collection_name)
                    continue
                await collection.create_search_index(model)
                logger.info("Created Atlas Search index '%s' on %s", search_name, collection_name)
            except Exception as e:
                # Silently skip on non-Atlas deployments (e.g. local mongod, CI)
                logger.debug(
                    "Atlas Search index '%s' on %s skipped (not Atlas?): %s",
                    search_name, collection_name, e,
                )
