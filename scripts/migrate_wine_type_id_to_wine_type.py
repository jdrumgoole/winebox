#!/usr/bin/env python3
"""One-off MongoDB migration: rename ``wine_type_id`` → ``wine_type``.

The field on the ``wines`` collection was historically named
``wine_type_id`` — misleading, because its values are plain tokens
("red", "white", "rose", …), not ObjectId references. The Python
attribute was renamed to ``wine_type`` to match the denormalised copy
already on ``cellars.wine.wine_type``; this script realigns any
existing MongoDB documents so reads don't silently lose the value.

Idempotent:
  - Documents that still have ``wine_type_id`` get it renamed.
  - Documents that already have ``wine_type`` are left alone.
  - An unused ``wine_type_id`` index, if present, is dropped.

Usage::

    uv run python scripts/migrate_wine_type_id_to_wine_type.py \\
        --database winebox-oat

The ``WINEBOX_MONGODB_URL`` environment variable is required. Set
``--database`` explicitly — defaulting to production is a recipe for a
bad day.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Iterable

from pymongo import AsyncMongoClient

logger = logging.getLogger(__name__)


# Collections and indexes that historically referenced the old field name.
COLLECTIONS: tuple[str, ...] = ("wines",)
OLD_INDEX_NAMES: tuple[str, ...] = (
    "wine_type_id_1",
    "owner_id_1_wine_type_id_1",
)


async def _rename_field(client: AsyncMongoClient, db_name: str, collection: str) -> int:
    """Rename the field on all docs in ``collection``. Returns docs modified."""
    col = client[db_name][collection]
    result = await col.update_many(
        {"wine_type_id": {"$exists": True}},
        {"$rename": {"wine_type_id": "wine_type"}},
    )
    return result.modified_count


async def _drop_stale_indexes(
    client: AsyncMongoClient, db_name: str, collection: str, names: Iterable[str]
) -> list[str]:
    """Drop any indexes with legacy names. Returns the names that were dropped."""
    col = client[db_name][collection]
    existing = {doc["name"] async for doc in (await col.list_indexes())}
    dropped: list[str] = []
    for name in names:
        if name in existing:
            await col.drop_index(name)
            dropped.append(name)
    return dropped


async def migrate(url: str, db_name: str, dry_run: bool) -> None:
    client = AsyncMongoClient(url)
    try:
        for collection in COLLECTIONS:
            col = client[db_name][collection]
            pending = await col.count_documents({"wine_type_id": {"$exists": True}})
            already = await col.count_documents({"wine_type": {"$exists": True}})
            logger.info(
                "%s.%s: %d docs with wine_type_id, %d already have wine_type",
                db_name, collection, pending, already,
            )
            if dry_run:
                continue
            if pending:
                modified = await _rename_field(client, db_name, collection)
                logger.info("  renamed wine_type_id → wine_type on %d docs", modified)
            dropped = await _drop_stale_indexes(client, db_name, collection, OLD_INDEX_NAMES)
            for name in dropped:
                logger.info("  dropped stale index %s", name)
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--database",
        required=True,
        help="MongoDB database name (e.g. winebox-oat, winebox).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without modifying the database.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    url = os.environ.get("WINEBOX_MONGODB_URL")
    if not url:
        print("Error: WINEBOX_MONGODB_URL is not set.", file=sys.stderr)
        return 1

    asyncio.run(migrate(url=url, db_name=args.database, dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
