"""Explicit MongoDB index definitions and setup.

All indexes are defined here instead of being auto-managed by an ODM.
Run ensure_indexes() on startup or via a management command.
"""

import logging

from pymongo import ASCENDING, DESCENDING, TEXT, IndexModel
from pymongo.asynchronous.database import AsyncDatabase

logger = logging.getLogger(__name__)

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
        IndexModel([("wine_type_id", ASCENDING)]),
        IndexModel([("owner_id", ASCENDING), ("inventory.quantity", ASCENDING)]),
        IndexModel([("owner_id", ASCENDING), ("collection", ASCENDING)]),
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
        IndexModel([("expires_at", ASCENDING)]),
    ],
    "login_attempts": [
        IndexModel([("email", ASCENDING)]),
        IndexModel([("attempted_at", ASCENDING)]),
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

    for collection_name, index_models in INDEXES.items():
        collection = db[collection_name]
        try:
            await collection.create_indexes(index_models)
            logger.debug("Indexes ensured for %s", collection_name)
        except OperationFailure as e:
            if e.code == 86:  # IndexKeySpecsConflict
                logger.warning(
                    "Index conflict in %s, dropping and recreating: %s",
                    collection_name, e.details.get("errmsg", ""),
                )
                # Drop conflicting indexes and retry
                for model in index_models:
                    index_name = model.document.get("name")
                    if not index_name:
                        # Auto-generated name from key spec
                        parts = []
                        for field, direction in model.document["key"].items():
                            parts.append(f"{field}_{direction}")
                        index_name = "_".join(parts)
                    try:
                        await collection.drop_index(index_name)
                        logger.info("Dropped conflicting index %s.%s", collection_name, index_name)
                    except OperationFailure:
                        pass  # Index may not exist or already dropped
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
