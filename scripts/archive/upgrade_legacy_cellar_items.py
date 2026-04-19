"""Migrate legacy cellar wines onto the per-item CellarItem store.

Some production accounts pre-date the `cellars` collection entirely —
their wines live only as `Wine.inventory.quantity` aggregates, with no
matching `CellarItem` rows. The Phase-4 readers can cope thanks to a
`legacy`-typed fallback, but keeping that fallback around means two
code paths and a "legacy" item_type that leaks into events.

This script retires both:

1. For every in-stock wine in the cellar collection that has no
   CellarItem rows, insert a `bottle`-typed CellarItem with
   `quantity = Wine.inventory.quantity`, stamped with
   `created_at = Wine.created_at` so the Transaction → CellarEvent
   backfill heuristic can still match events by time if re-run.

2. For every `CellarEvent` with `item_type == "legacy"`, try to link
   it to a CellarItem for the same owner/wine (preferring one whose
   `created_at` is closest to the event's `event_date`). If a CellarItem
   is found, set `cellar_item_id` and `item_type` accordingly. If none
   can be found (e.g. the event refers to a wine that was fully
   consumed and deleted), just relabel to `"bottle"` — callers that
   branched on `"legacy"` will no longer have to.

Idempotent: re-runs are no-ops. `--dry-run` prints planned changes
without writing.

CLI:
  --database NAME       (default: $WINEBOX_DATABASE)
  --mongodb-url URL     (default: $WINEBOX_MONGODB_URL)
  --dry-run             Print plan, don't write.
  --batch-size N        Wine/event chunk size (default: 500).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from pymongo import AsyncMongoClient

LOG = logging.getLogger("upgrade_legacy_cellar_items")


def _embedded_wine_from(wine: dict) -> dict:
    """Shape matching `winebox.models.cellar.EmbeddedWine`."""
    return {
        "wine_id": wine["_id"],
        "name": wine.get("name", "Unknown"),
        "winery": wine.get("winery"),
        "vintage": wine.get("vintage"),
        "grape_variety": wine.get("grape_variety"),
        "country": wine.get("country"),
        "region": wine.get("region"),
        "wine_type": wine.get("wine_type"),
        "estimated_price_low": wine.get("estimated_price_low"),
        "estimated_price_high": wine.get("estimated_price_high"),
        "price_tier": wine.get("price_tier"),
    }


async def _find_orphan_wines(db: Any) -> list[dict]:
    """Wines with inventory > 0 whose owner has no CellarItem for this wine."""
    # Use an $lookup-based pipeline so we can identify orphans in one pass.
    pipeline = [
        {"$match": {
            "collection": "cellar",
            "inventory.quantity": {"$gt": 0},
        }},
        {"$lookup": {
            "from": "cellars",
            "let": {"owner_id": "$owner_id", "wine_id": "$_id"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$cellar_id", "$$owner_id"]},
                    {"$eq": ["$wine.wine_id", "$$wine_id"]},
                ]}}},
                {"$project": {"_id": 1}},
                {"$limit": 1},
            ],
            "as": "existing_items",
        }},
        {"$match": {"existing_items": {"$size": 0}}},
        {"$project": {"existing_items": 0}},
    ]
    cursor = await db["wines"].aggregate(pipeline)
    return await cursor.to_list(length=None)


async def _best_matching_cellar_item(
    cellar_col: Any, owner_id: ObjectId, wine_id: ObjectId,
    event_date: Optional[datetime],
) -> Optional[dict]:
    """Return the CellarItem closest in created_at to event_date."""
    items = await cellar_col.find(
        {"cellar_id": owner_id, "wine.wine_id": wine_id},
    ).to_list(length=None)
    if not items:
        return None
    if event_date is None:
        return items[0]

    def _delta(item: dict) -> float:
        ci_date = item.get("created_at") or datetime.min.replace(tzinfo=timezone.utc)
        if ci_date.tzinfo is None:
            ci_date = ci_date.replace(tzinfo=timezone.utc)
        ed = event_date if event_date.tzinfo else event_date.replace(tzinfo=timezone.utc)
        return abs((ci_date - ed).total_seconds())

    return min(items, key=_delta)


async def migrate(
    *, db_name: str, mongo_url: str, dry_run: bool, batch_size: int,
) -> dict[str, int]:
    client = AsyncMongoClient(mongo_url)
    try:
        db = client[db_name]
        wines_col = db["wines"]
        cellar_col = db["cellars"]
        events_col = db["cellar_events"]

        totals = {
            "wines_considered": 0,
            "cellar_items_created": 0,
            "legacy_events_considered": 0,
            "legacy_events_linked_to_cellar_item": 0,
            "legacy_events_relabelled_as_bottle": 0,
        }

        # --- Step 1: synthesise CellarItems for orphan wines ----------------
        orphans = await _find_orphan_wines(db)
        totals["wines_considered"] = len(orphans)

        new_items: list[dict] = []
        for wine in orphans:
            qty = int((wine.get("inventory") or {}).get("quantity") or 0)
            if qty <= 0:
                continue
            created_at = wine.get("created_at") or datetime.now(timezone.utc)
            new_items.append({
                "_id": ObjectId(),
                "cellar_id": wine["owner_id"],
                "item_type": "bottle",
                "wine": _embedded_wine_from(wine),
                "quantity": qty,
                "case_size": None,
                "purchase_price": None,
                "purchase_date": None,
                "provenance": None,
                "import_batch_id": None,
                "created_at": created_at,
                "updated_at": datetime.now(timezone.utc),
            })

            if len(new_items) >= batch_size:
                if not dry_run:
                    await cellar_col.insert_many(new_items, ordered=False)
                totals["cellar_items_created"] += len(new_items)
                new_items = []

        if new_items:
            if not dry_run:
                await cellar_col.insert_many(new_items, ordered=False)
            totals["cellar_items_created"] += len(new_items)

        # --- Step 2: retire legacy CellarEvents ----------------------------
        cursor = events_col.find({"item_type": "legacy"}).batch_size(batch_size)
        async for event in cursor:
            totals["legacy_events_considered"] += 1

            owner_id = event.get("owner_id") or event.get("cellar_id")
            wine_id = event.get("wine_id")
            match = None
            if owner_id is not None and wine_id is not None:
                match = await _best_matching_cellar_item(
                    cellar_col, owner_id, wine_id, event.get("event_date"),
                )

            if match is not None:
                update = {
                    "cellar_item_id": match["_id"],
                    "item_type": match.get("item_type", "bottle"),
                }
                totals["legacy_events_linked_to_cellar_item"] += 1
            else:
                update = {"item_type": "bottle"}
                totals["legacy_events_relabelled_as_bottle"] += 1

            if not dry_run:
                await events_col.update_one({"_id": event["_id"]}, {"$set": update})

        return totals
    finally:
        await client.close()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", default=os.environ.get("WINEBOX_DATABASE"))
    p.add_argument("--mongodb-url", default=os.environ.get("WINEBOX_MONGODB_URL"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--batch-size", type=int, default=500)
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args(argv)


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

    LOG.info(
        "Upgrading legacy wines in %s (dry_run=%s, batch_size=%d)",
        args.database, args.dry_run, args.batch_size,
    )
    totals = asyncio.run(migrate(
        db_name=args.database, mongo_url=args.mongodb_url,
        dry_run=args.dry_run, batch_size=args.batch_size,
    ))
    for key, value in totals.items():
        LOG.info("  %-40s %d", key, value)
    if args.dry_run:
        LOG.info("(dry run — no writes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
