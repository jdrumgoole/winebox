"""Backfill: create `CellarEvent` rows mirroring every `Transaction`.

Phase 4c of the cases-first-class plan. Before 4d flips the activity feed
and transaction APIs to read `CellarEvent`, every existing `Transaction`
must have an equivalent `CellarEvent` so history doesn't disappear.

Approach:

- Iterate `transactions` in chunks. For each row, check whether a matching
  `CellarEvent` already exists (keyed by `migrated_from_transaction_id`).
  If it does, skip — the script is **idempotent**, safe to re-run.
- Otherwise, try to find the concrete `CellarItem` the Transaction
  corresponds to. Matching heuristic: same owner + wine + quantity +
  item was created close in time to the Transaction's
  `transaction_date` (most Transactions were written right after the
  CellarItem was created). When a match is found, snapshot its
  `case_size` and `provenance` onto the event.
- When no match is found (truly legacy rows that predate the CellarItem
  split), insert with `cellar_item_id=None`, `item_type="legacy"` so
  the activity-feed renderer can label it "(historic — pre-cases)".

Run against winebox-oat first to confirm counts:

    uv run python scripts/migrations/migrate_transactions_to_cellar_events.py \\
        --database winebox-oat --dry-run

Then without `--dry-run`, then repeat on the production database.

CLI flags:
  --database NAME   The Mongo database to migrate (default: env
                    WINEBOX_DATABASE).
  --mongodb-url URL Override Mongo URL (default: env WINEBOX_MONGODB_URL).
  --dry-run         Print planned inserts, don't write.
  --batch-size N    Transaction chunk size (default: 500).
  --since ISO       Only migrate Transactions on/after this ISO datetime
                    (useful for incremental re-runs).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from bson import ObjectId
from pymongo import AsyncMongoClient

LOG = logging.getLogger("migrate_tx_to_cellar_events")

# Map (transaction_type, removal_reason) → cellar_event.event_type.
_TX_TO_EVENT_TYPE: dict[tuple[str, Optional[str]], str] = {
    # CHECK_IN / ADDED (both legacy and current names) → added
    ("CHECK_IN", None): "added",
    ("ADDED", None): "added",
    # Removals
    ("CHECK_OUT", "DRINK"): "drunk",
    ("REMOVED", "DRINK"): "drunk",
    ("CHECK_OUT", "SELL"): "sold",
    ("REMOVED", "SELL"): "sold",
    ("CHECK_OUT", "GIFT"): "gifted",
    ("REMOVED", "GIFT"): "gifted",
    ("CHECK_OUT", "OTHER"): "other",
    ("REMOVED", "OTHER"): "other",
    # Removal with no reason → generic "other"
    ("CHECK_OUT", None): "other",
    ("REMOVED", None): "other",
}


def _event_type_for(tx: dict) -> str:
    """Derive the CellarEvent.event_type from a Transaction row."""
    tx_type = tx.get("transaction_type")
    reason = tx.get("removal_reason")
    return _TX_TO_EVENT_TYPE.get((tx_type, reason), "other")


async def _find_matching_cellar_item(
    cellar_col: Any, tx: dict, window: timedelta
) -> Optional[dict]:
    """Best-effort match: same owner, same wine, created within `window`
    of the transaction date. Used for snapshot fields; not required.
    """
    tx_date = tx.get("transaction_date") or tx.get("created_at")
    if not tx_date:
        return None
    # Prefer items with exactly this quantity; fall back to any item for
    # this wine within the window.
    owner_id = tx["owner_id"]
    wine_id = tx["wine_id"]
    lo = tx_date - window
    hi = tx_date + window

    exact = await cellar_col.find_one({
        "cellar_id": owner_id,
        "wine.wine_id": wine_id,
        "quantity": tx.get("quantity", 0),
        "created_at": {"$gte": lo, "$lte": hi},
    })
    if exact is not None:
        return exact
    return await cellar_col.find_one({
        "cellar_id": owner_id,
        "wine.wine_id": wine_id,
        "created_at": {"$gte": lo, "$lte": hi},
    })


async def migrate(
    *,
    db_name: str,
    mongo_url: str,
    dry_run: bool,
    batch_size: int,
    since: Optional[datetime],
) -> dict[str, int]:
    """Run the migration, return summary counts.

    Counts:
    - ``considered`` transactions scanned
    - ``skipped_already_migrated`` — an event with matching
      `migrated_from_transaction_id` already exists
    - ``matched_with_cellar_item`` — an event we'd insert linked to a
      resolved CellarItem (snapshotting case_size/provenance)
    - ``legacy_unlinked`` — an event we'd insert with no CellarItem link
      (item_type="legacy")
    - ``inserted`` — events actually written (equals
      matched_with_cellar_item + legacy_unlinked when not --dry-run)
    """
    client = AsyncMongoClient(mongo_url)
    try:
        db = client[db_name]
        tx_col = db["transactions"]
        events_col = db["cellar_events"]
        cellars_col = db["cellars"]

        # Only consider transactions that aren't already mirrored.
        query: dict = {}
        if since is not None:
            query["transaction_date"] = {"$gte": since}

        totals = {
            "considered": 0,
            "skipped_already_migrated": 0,
            "matched_with_cellar_item": 0,
            "legacy_unlinked": 0,
            "inserted": 0,
        }

        window = timedelta(hours=1)
        cursor = tx_col.find(query).batch_size(batch_size)
        to_insert: list[dict] = []

        async for tx in cursor:
            totals["considered"] += 1

            tx_id = tx["_id"]
            # Idempotency: skip if we already migrated this row.
            already = await events_col.find_one(
                {"migrated_from_transaction_id": tx_id},
                projection={"_id": 1},
            )
            if already is not None:
                totals["skipped_already_migrated"] += 1
                continue

            event_type = _event_type_for(tx)
            matched = await _find_matching_cellar_item(cellars_col, tx, window)

            doc: dict[str, Any] = {
                "cellar_id": tx["owner_id"],
                "owner_id": tx["owner_id"],
                "wine_id": tx["wine_id"],
                "event_type": event_type,
                "quantity": tx.get("quantity", 1),
                "event_date": tx.get("transaction_date") or tx.get("created_at"),
                "created_at": datetime.now(timezone.utc),
                "notes": tx.get("notes"),
                "tasting_notes": tx.get("tasting_notes"),
                "sale_price": tx.get("sale_price_usd"),
                "sale_price_usd": tx.get("sale_price_usd"),
                "gift_recipient": tx.get("gift_recipient"),
                "removal_reason": tx.get("removal_reason"),
                "removal_notes": tx.get("removal_notes"),
                # Audit trail: every Phase-4-backfilled row carries this so
                # a second run of the script is a no-op.
                "migrated_from_transaction_id": tx_id,
            }

            if matched is not None:
                doc["cellar_item_id"] = matched["_id"]
                doc["item_type"] = matched.get("item_type", "bottle")
                if matched.get("item_type") == "case":
                    doc["case_size_at_event"] = matched.get("case_size")
                    doc["provenance_at_event"] = matched.get("provenance")
                totals["matched_with_cellar_item"] += 1
            else:
                doc["cellar_item_id"] = None
                doc["item_type"] = "legacy"
                totals["legacy_unlinked"] += 1

            to_insert.append(doc)

            if len(to_insert) >= batch_size:
                if not dry_run:
                    await events_col.insert_many(to_insert, ordered=False)
                    totals["inserted"] += len(to_insert)
                to_insert = []

        if to_insert:
            if not dry_run:
                await events_col.insert_many(to_insert, ordered=False)
                totals["inserted"] += len(to_insert)

        return totals
    finally:
        await client.close()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.environ.get("WINEBOX_DATABASE"),
                        help="Mongo database name (default: $WINEBOX_DATABASE)")
    parser.add_argument("--mongodb-url", default=os.environ.get("WINEBOX_MONGODB_URL"),
                        help="Mongo connection URL (default: $WINEBOX_MONGODB_URL)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print planned inserts, don't write.")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--since", type=str, default=None,
                        help="Only migrate Transactions on/after this ISO datetime.")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if not args.database:
        print("error: --database is required (or set WINEBOX_DATABASE)", file=sys.stderr)
        return 2
    if not args.mongodb_url:
        print("error: --mongodb-url is required (or set WINEBOX_MONGODB_URL)", file=sys.stderr)
        return 2
    since: Optional[datetime] = None
    if args.since:
        since = datetime.fromisoformat(args.since)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

    LOG.info(
        "Backfilling cellar_events from transactions in %s (dry_run=%s, batch_size=%d, since=%s)",
        args.database, args.dry_run, args.batch_size, since.isoformat() if since else "—",
    )
    totals = asyncio.run(migrate(
        db_name=args.database,
        mongo_url=args.mongodb_url,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        since=since,
    ))
    for key, value in totals.items():
        LOG.info("  %-28s %d", key, value)
    if args.dry_run:
        LOG.info("(dry run — no writes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
