"""Rename a MongoDB database by copying all collections to a new name.

MongoDB doesn't support renaming databases directly, so this script:
1. Lists all collections in the source database
2. Copies each collection to the target database (document by document)
3. Verifies document counts match
4. Optionally drops the source database

Usage:
    uv run python scripts/rename_mongodb_database.py \
        --url "mongodb+srv://...@shared.2t22cum.mongodb.net" \
        --source winebox-oat \
        --target winebox_oat

    # Add --drop-source to remove the old database after successful copy
    uv run python scripts/rename_mongodb_database.py \
        --url "mongodb+srv://..." \
        --source winebox-oat \
        --target winebox_oat \
        --drop-source
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


def copy_database(url: str, source: str, target: str, drop_source: bool) -> None:
    print(f"Connecting to MongoDB...")
    client: MongoClient = MongoClient(url)

    try:
        client.admin.command("ping")
    except ConnectionFailure:
        print("Error: Could not connect to MongoDB.")
        sys.exit(1)

    source_db = client[source]
    target_db = client[target]

    collections = source_db.list_collection_names()
    if not collections:
        print(f"Error: Source database '{source}' has no collections.")
        sys.exit(1)

    # Check target doesn't already have data
    target_collections = target_db.list_collection_names()
    if target_collections:
        print(f"Warning: Target database '{target}' already has collections:")
        for name in target_collections:
            count = target_db[name].count_documents({})
            print(f"  {name}: {count} documents")
        response = input("Continue and overwrite? [y/N] ")
        if response.lower() != "y":
            print("Aborted.")
            sys.exit(0)

    print(f"\nSource: {source} ({len(collections)} collections)")
    print(f"Target: {target}")
    print(f"Collections: {', '.join(sorted(collections))}")
    print()

    total_copied = 0
    errors = []

    for i, name in enumerate(sorted(collections), 1):
        source_col = source_db[name]
        target_col = target_db[name]
        source_count = source_col.count_documents({})

        print(f"[{i}/{len(collections)}] {name} ({source_count:,} documents)...", end=" ", flush=True)

        if source_count == 0:
            print("empty, skipping")
            continue

        # Copy indexes first (excluding _id which is automatic)
        indexes = source_col.index_information()
        for idx_name, idx_info in indexes.items():
            if idx_name == "_id_":
                continue
            keys = idx_info["key"]
            opts = {k: v for k, v in idx_info.items() if k not in ("key", "v", "ns")}
            try:
                target_col.create_index(keys, **opts)
            except Exception as e:
                print(f"\n  Warning: Could not create index {idx_name}: {e}")

        # Copy documents in batches
        batch_size = 1000
        copied = 0
        cursor = source_col.find({}, batch_size=batch_size)
        batch = []

        for doc in cursor:
            batch.append(doc)
            if len(batch) >= batch_size:
                target_col.insert_many(batch, ordered=False)
                copied += len(batch)
                batch = []

        if batch:
            target_col.insert_many(batch, ordered=False)
            copied += len(batch)

        # Verify
        target_count = target_col.count_documents({})
        if target_count == source_count:
            print(f"ok ({copied:,} copied)")
            total_copied += copied
        else:
            msg = f"{name}: source={source_count}, target={target_count}"
            errors.append(msg)
            print(f"MISMATCH ({msg})")

    print(f"\nCopied {total_copied:,} documents across {len(collections)} collections.")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for err in errors:
            print(f"  - {err}")
        print("\nNot dropping source database due to errors.")
        sys.exit(1)

    if drop_source:
        print(f"\nDropping source database '{source}'...")
        client.drop_database(source)
        print("Done.")
    else:
        print(f"\nSource database '{source}' retained. Pass --drop-source to remove it.")

    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy a MongoDB database to a new name."
    )
    parser.add_argument("--url", required=True, help="MongoDB connection string")
    parser.add_argument("--source", required=True, help="Source database name")
    parser.add_argument("--target", required=True, help="Target database name")
    parser.add_argument(
        "--drop-source",
        action="store_true",
        help="Drop the source database after successful copy",
    )
    args = parser.parse_args()

    if args.source == args.target:
        print("Error: Source and target must be different.")
        sys.exit(1)

    copy_database(args.url, args.source, args.target, args.drop_source)


if __name__ == "__main__":
    main()
