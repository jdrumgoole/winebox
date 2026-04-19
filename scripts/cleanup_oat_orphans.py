"""Delete orphan test data from the OAT database.

Finds all owner_ids/cellar_ids that don't correspond to a real user
and deletes their data across all collections.

Usage:
    uv run python scripts/cleanup_oat_orphans.py --url "$WINEBOX_MONGODB_URL" --database winebox_oat
    uv run python scripts/cleanup_oat_orphans.py --url "$WINEBOX_MONGODB_URL" --database winebox_oat --dry-run
"""

import argparse
import signal
import sys

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure


def handle_sigint(sig: int, frame: object) -> None:
    print("\nAborted.")
    sys.exit(130)


signal.signal(signal.SIGINT, handle_sigint)


# Collections keyed by owner_id
OWNER_ID_COLLECTIONS = [
    "bottles",
    "cases",
    "cellar_events",
    "import_batches",
    "transactions",
    "wine_events",
    "wines",
]


def cleanup(url: str, database: str, dry_run: bool) -> None:
    print(f"Connecting to MongoDB...")
    client: MongoClient = MongoClient(url)

    try:
        client.admin.command("ping")
    except ConnectionFailure:
        print("Error: Could not connect to MongoDB.")
        sys.exit(1)

    db = client[database]

    # Get real user IDs
    real_user_ids = set(u["_id"] for u in db.users.find({}, {"_id": 1}))
    print(f"Real users: {len(real_user_ids)}")

    # Find orphan owner_ids across all owner_id collections
    all_orphan_ids: set = set()
    for col_name in OWNER_ID_COLLECTIONS:
        col = db[col_name]
        owner_ids = set(col.distinct("owner_id"))
        orphans = owner_ids - real_user_ids
        if orphans:
            all_orphan_ids.update(orphans)

    # Also find orphan cellar_ids (cellars collection uses cellar_id, not owner_id)
    cellar_ids = set(db.cellars.distinct("cellar_id"))
    orphan_cellar_ids = cellar_ids - real_user_ids

    # Find orphan import batch IDs for raw_uploads cleanup
    real_batch_ids = set(b["_id"] for b in db.import_batches.find({}, {"_id": 1}))
    all_batch_ids = set(db.raw_uploads.distinct("batch_id"))
    orphan_batch_ids = all_batch_ids - real_batch_ids

    print(f"Orphan owner_ids: {len(all_orphan_ids)}")
    print(f"Orphan cellar_ids: {len(orphan_cellar_ids)}")
    print(f"Orphan batch_ids: {len(orphan_batch_ids)}")

    if not all_orphan_ids and not orphan_cellar_ids and not orphan_batch_ids:
        print("No orphan data found.")
        client.close()
        return

    orphan_id_list = list(all_orphan_ids)
    total_deleted = 0

    # Delete from owner_id collections
    for col_name in OWNER_ID_COLLECTIONS:
        col = db[col_name]
        count = col.count_documents({"owner_id": {"$in": orphan_id_list}})
        if count == 0:
            continue
        if dry_run:
            print(f"  [DRY RUN] {col_name}: would delete {count:,} documents")
        else:
            result = col.delete_many({"owner_id": {"$in": orphan_id_list}})
            print(f"  {col_name}: deleted {result.deleted_count:,} documents")
            total_deleted += result.deleted_count

    # Delete orphan cellars
    if orphan_cellar_ids:
        orphan_cellar_list = list(orphan_cellar_ids)
        count = db.cellars.count_documents({"cellar_id": {"$in": orphan_cellar_list}})
        if count > 0:
            if dry_run:
                print(f"  [DRY RUN] cellars: would delete {count:,} documents")
            else:
                result = db.cellars.delete_many({"cellar_id": {"$in": orphan_cellar_list}})
                print(f"  cellars: deleted {result.deleted_count:,} documents")
                total_deleted += result.deleted_count

    # Delete orphan raw_uploads
    if orphan_batch_ids:
        orphan_batch_list = list(orphan_batch_ids)
        count = db.raw_uploads.count_documents({"batch_id": {"$in": orphan_batch_list}})
        if count > 0:
            if dry_run:
                print(f"  [DRY RUN] raw_uploads: would delete {count:,} documents")
            else:
                result = db.raw_uploads.delete_many({"batch_id": {"$in": orphan_batch_list}})
                print(f"  raw_uploads: deleted {result.deleted_count:,} documents")
                total_deleted += result.deleted_count

    if dry_run:
        print("\nDry run complete — no data was deleted.")
    else:
        print(f"\nDeleted {total_deleted:,} orphan documents total.")

    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up orphan test data from OAT database.")
    parser.add_argument("--url", required=True, help="MongoDB connection string")
    parser.add_argument("--database", required=True, help="Database name")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    args = parser.parse_args()

    cleanup(args.url, args.database, args.dry_run)


if __name__ == "__main__":
    main()
