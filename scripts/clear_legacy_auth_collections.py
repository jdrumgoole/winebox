"""One-shot helper to drop pre-regstack auth collections.

Before the regstack migration, WineBox owned `revoked_tokens` (per-token
JWT blacklist) and `login_attempts` (failed-login lockout). regstack now
owns the equivalents — `token_blacklist` and its own `login_attempts`
with a different document shape. Leaving the legacy collections in place
causes TTL index conflicts when regstack's `install_schema()` runs.

This script DOES NOT touch the `users` collection — winebox and regstack
share that one and the existing user records remain valid.

Usage::

    uv run python scripts/clear_legacy_auth_collections.py \
        --database winebox_oat \
        --confirm

`--confirm` is required; without it, the script lists what *would* be
dropped and exits.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv
from pymongo import AsyncMongoClient

load_dotenv()  # Pick up WINEBOX_MONGODB_URL from a project-local .env.

LEGACY_COLLECTIONS = ("revoked_tokens", "login_attempts")

# Legacy indexes on the SHARED users collection. WineBox pre-regstack
# created an unnamed unique index on email (which Mongo named ``email_1``)
# in ``winebox.db.indexes``. regstack's ``install_schema()`` tries to
# create ``email_unique`` over the same key and Mongo raises
# IndexOptionsConflict — the collection isn't dropped (existing users
# must be preserved), but the legacy index has to go.
LEGACY_USERS_INDEXES = ("email_1",)


async def _main(database: str, confirm: bool) -> int:
    mongo_url = os.environ.get("WINEBOX_MONGODB_URL")
    if not mongo_url:
        print("ERROR: WINEBOX_MONGODB_URL is not set in the environment.", file=sys.stderr)
        return 2

    client = AsyncMongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    try:
        db = client[database]
        existing = await db.list_collection_names()

        coll_targets = [c for c in LEGACY_COLLECTIONS if c in existing]
        idx_targets: list[str] = []
        if "users" in existing:
            users_indexes = await db.users.index_information()
            idx_targets = [name for name in LEGACY_USERS_INDEXES if name in users_indexes]

        if not coll_targets and not idx_targets:
            print(f"Nothing to do: no legacy auth state in {database!r}.")
            return 0

        for name in coll_targets:
            count = await db[name].estimated_document_count()
            print(f"  drop collection {database}.{name}: ~{count} documents")
        for name in idx_targets:
            print(f"  drop index {database}.users.{name}")

        if not confirm:
            print("\nDry run. Re-run with --confirm to drop the listed items.")
            return 0

        for name in coll_targets:
            await db.drop_collection(name)
            print(f"Dropped collection {database}.{name}")
        for name in idx_targets:
            await db.users.drop_index(name)
            print(f"Dropped index {database}.users.{name}")
        return 0
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        required=True,
        help="Database to drop legacy auth collections from (e.g. winebox_oat).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually drop the collections. Without this flag, performs a dry run.",
    )
    args = parser.parse_args()

    if args.database == "winebox" and not os.environ.get("WINEBOX_ALLOW_PROD_LEGACY_DROP"):
        print(
            "ERROR: dropping legacy auth collections from the production database "
            "requires WINEBOX_ALLOW_PROD_LEGACY_DROP=1 in the environment.",
            file=sys.stderr,
        )
        return 2

    return asyncio.run(_main(args.database, args.confirm))


if __name__ == "__main__":
    sys.exit(main())
