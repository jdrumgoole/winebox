#!/usr/bin/env python3
"""One-off MongoDB migration: rewrite transaction_type values.

``TransactionType`` was renamed ``CHECK_IN``/``CHECK_OUT`` →
``ADDED``/``REMOVED`` so the names match the UI actions (Record /
Remove) and align with ``CellarEventType.ADDED``. Existing Transaction
documents still store the old string values; this script rewrites them.

Idempotent:
  - Docs with the old values get updated.
  - Docs already using the new values are untouched.

Usage::

    uv run python scripts/migrate_transaction_type_values.py \\
        --database winebox-oat

``WINEBOX_MONGODB_URL`` is required.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from pymongo import AsyncMongoClient

logger = logging.getLogger(__name__)


VALUE_MAP: dict[str, str] = {
    "CHECK_IN": "ADDED",
    "CHECK_OUT": "REMOVED",
}


async def migrate(url: str, db_name: str, dry_run: bool) -> None:
    client = AsyncMongoClient(url)
    try:
        col = client[db_name]["transactions"]
        for old, new in VALUE_MAP.items():
            pending = await col.count_documents({"transaction_type": old})
            already = await col.count_documents({"transaction_type": new})
            logger.info(
                "%s.transactions: %d docs with %s, %d with %s",
                db_name, pending, old, already, new,
            )
            if dry_run or pending == 0:
                continue
            result = await col.update_many(
                {"transaction_type": old},
                {"$set": {"transaction_type": new}},
            )
            logger.info(
                "  rewrote %s → %s on %d docs",
                old, new, result.modified_count,
            )
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--database", required=True, help="MongoDB database name.")
    parser.add_argument("--dry-run", action="store_true")
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
