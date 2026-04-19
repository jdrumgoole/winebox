#!/usr/bin/env python3
"""Migrate existing Wine.inventory data to Bottle + BottleEvent records.

For each Wine record with quantity > 0:
- If case_size is set: create a Case + N Bottles linked to it
- If no case_size: create N loose Bottles
- Create 'added' WineEvent for each Bottle

This is idempotent — wines that already have bottles are skipped.

Usage:
    uv run python scripts/migrate_to_bottles.py --database winebox_oat
    uv run python scripts/migrate_to_bottles.py --database winebox --dry-run
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()
load_dotenv("secrets.env")

logger = logging.getLogger(__name__)


async def migrate(database: str, dry_run: bool = False) -> None:
    """Run the migration."""
    from pymongo import AsyncMongoClient

    url = os.environ.get("WINEBOX_MONGODB_URL")
    if not url:
        print("ERROR: WINEBOX_MONGODB_URL not set", file=sys.stderr)
        sys.exit(1)

    client = AsyncMongoClient(url)
    db = client[database]

    wines_col = db["wines"]
    cases_col = db["cases"]
    bottles_col = db["bottles"]
    events_col = db["wine_events"]

    # Find wines with quantity > 0 that don't already have bottles
    wines_cursor = wines_col.find({"inventory.quantity": {"$gt": 0}})
    wines = await wines_cursor.to_list(length=None)

    print(f"Found {len(wines)} wines with quantity > 0 in '{database}'")

    total_bottles = 0
    total_cases = 0
    skipped = 0

    for wine in wines:
        wine_id = wine["_id"]
        owner_id = wine["owner_id"]
        quantity = wine["inventory"]["quantity"]
        case_size = wine.get("inventory", {}).get("case_size")

        # Check if bottles already exist for this wine
        existing = await bottles_col.count_documents({"wine_id": wine_id})
        if existing > 0:
            skipped += 1
            continue

        now = wine.get("created_at", datetime.now(timezone.utc))
        name = wine.get("name", "Unknown")

        if dry_run:
            if case_size:
                print(f"  [DRY RUN] {name}: {quantity} bottles in case of {case_size}")
            else:
                print(f"  [DRY RUN] {name}: {quantity} loose bottles")
            total_bottles += quantity
            if case_size:
                total_cases += 1
            continue

        # Build bottle documents
        bottle_docs = []
        event_docs = []
        case_id = None

        if case_size and case_size > 0:
            # Create a case
            case_doc = {
                "_id": ObjectId(),
                "owner_id": owner_id,
                "wine_id": wine_id,
                "case_size": case_size,
                "purchase_date": wine.get("purchase_date"),
                "created_at": now,
            }
            await cases_col.insert_one(case_doc)
            case_id = case_doc["_id"]
            total_cases += 1

        for _ in range(quantity):
            bottle_id = ObjectId()
            bottle_docs.append({
                "_id": bottle_id,
                "owner_id": owner_id,
                "wine_id": wine_id,
                "case_id": case_id,
                "name": name,
                "winery": wine.get("winery"),
                "vintage": wine.get("vintage"),
                "grape_variety": wine.get("grape_variety"),
                "country": wine.get("country"),
                "region": wine.get("region"),
                "wine_type": wine.get("wine_type"),
                "created_at": now,
            })
            event_docs.append({
                "_id": ObjectId(),
                "bottle_id": bottle_id,
                "owner_id": owner_id,
                "scope": "bottle",
                "event_type": "added",
                "event_date": now,
                "created_at": now,
            })

        if bottle_docs:
            await bottles_col.insert_many(bottle_docs)
            await events_col.insert_many(event_docs)
            total_bottles += len(bottle_docs)

    await client.close()

    print(f"\nMigration {'preview' if dry_run else 'complete'}:")
    print(f"  Bottles created: {total_bottles}")
    print(f"  Cases created: {total_cases}")
    print(f"  Wines skipped (already have bottles): {skipped}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate Wine.inventory to Bottles")
    parser.add_argument("--database", required=True, help="Database name (e.g. winebox_oat)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(migrate(args.database, args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
