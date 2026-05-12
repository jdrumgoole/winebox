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

from pymongo import AsyncMongoClient

LEGACY_COLLECTIONS = ("revoked_tokens", "login_attempts")


async def _main(database: str, confirm: bool) -> int:
    mongo_url = os.environ.get("WINEBOX_MONGODB_URL")
    if not mongo_url:
        print("ERROR: WINEBOX_MONGODB_URL is not set in the environment.", file=sys.stderr)
        return 2

    client = AsyncMongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    try:
        db = client[database]
        existing = await db.list_collection_names()

        targets = [c for c in LEGACY_COLLECTIONS if c in existing]
        if not targets:
            print(f"Nothing to do: no legacy auth collections in {database!r}.")
            return 0

        for name in targets:
            count = await db[name].estimated_document_count()
            print(f"  {database}.{name}: ~{count} documents")

        if not confirm:
            print("\nDry run. Re-run with --confirm to drop the listed collections.")
            return 0

        for name in targets:
            await db.drop_collection(name)
            print(f"Dropped {database}.{name}")
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
