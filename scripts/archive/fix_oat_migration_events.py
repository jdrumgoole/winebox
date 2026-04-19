#!/usr/bin/env python3
"""Fix OAT migration data: move bottle_events → wine_events with scope field.

The initial migration ran with a buggy script that wrote events to the
'bottle_events' collection without a 'scope' field. This script moves
those documents to 'wine_events' and adds scope: "bottle".

Usage:
    uv run python scripts/fix_oat_migration_events.py --database winebox_oat
    uv run python scripts/fix_oat_migration_events.py --database winebox_oat --dry-run
"""

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()
load_dotenv("secrets.env")


async def fix_events(database: str, dry_run: bool = False) -> None:
    """Move documents from bottle_events to wine_events, adding scope field."""
    from pymongo import AsyncMongoClient

    url = os.environ.get("WINEBOX_MONGODB_URL")
    if not url:
        print("ERROR: WINEBOX_MONGODB_URL not set", file=sys.stderr)
        sys.exit(1)

    client = AsyncMongoClient(url)
    db = client[database]

    old_col = db["bottle_events"]
    new_col = db["wine_events"]

    # Count documents in old collection
    old_count = await old_col.count_documents({})
    new_count = await new_col.count_documents({})
    print(f"Database: {database}")
    print(f"  bottle_events: {old_count} documents")
    print(f"  wine_events: {new_count} documents")

    if old_count == 0:
        print("Nothing to migrate — bottle_events is empty.")
        await client.close()
        return

    if dry_run:
        print(f"\n[DRY RUN] Would move {old_count} documents from bottle_events → wine_events")
        print(f"[DRY RUN] Would add scope: 'bottle' to each document")
        print(f"[DRY RUN] Would drop bottle_events collection")
        await client.close()
        return

    # Fetch all documents from old collection
    docs = await old_col.find({}).to_list(length=None)

    # Add scope field to each
    for doc in docs:
        if "scope" not in doc:
            doc["scope"] = "bottle"

    # Check for duplicates (by _id) in new collection
    existing_ids = set()
    if new_count > 0:
        existing = await new_col.find({}, {"_id": 1}).to_list(length=None)
        existing_ids = {d["_id"] for d in existing}

    new_docs = [d for d in docs if d["_id"] not in existing_ids]
    skipped = len(docs) - len(new_docs)

    if new_docs:
        await new_col.insert_many(new_docs)
        print(f"\nMoved {len(new_docs)} documents to wine_events")
    if skipped:
        print(f"Skipped {skipped} documents (already in wine_events)")

    # Drop old collection
    await old_col.drop()
    print("Dropped bottle_events collection")

    # Also fix any wine_events documents missing scope field
    result = await new_col.update_many(
        {"scope": {"$exists": False}},
        {"$set": {"scope": "bottle"}},
    )
    if result.modified_count > 0:
        print(f"Added scope: 'bottle' to {result.modified_count} existing wine_events documents")

    await client.close()
    print("\nDone.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix OAT migration events")
    parser.add_argument("--database", required=True, help="Database name")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    asyncio.run(fix_events(args.database, args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
