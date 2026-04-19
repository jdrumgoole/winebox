"""Phase 4c: backfill transactions → cellar_events.

Covers the migration script's key invariants:
- Every Transaction produces exactly one CellarEvent per run.
- Re-running the script is a no-op (idempotency via
  `migrated_from_transaction_id`).
- Transactions we *can* link back to a CellarItem get the case snapshot;
  ones we can't get `item_type="bottle"` with cellar_item_id=None.
- Event types are mapped from (transaction_type, removal_reason).
- A `--since` cutoff skips older rows.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from scripts.migrations import migrate_transactions_to_cellar_events as mig


@pytest.mark.asyncio
async def test_backfill_matches_cellaritem_and_is_idempotent(isolated_db) -> None:
    """A Transaction with a matching CellarItem → enriched event; re-run no-ops."""
    from winebox.models import Transaction, TransactionType
    from winebox.models.cellar import CellarItem, EmbeddedWine
    from winebox.models.cellar_event import CellarEvent
    from winebox.models.wine import Wine, WineCollection
    from winebox.models.wine import InventoryInfo as WineInventoryInfo

    owner_id = isolated_db["cellars"].database.client.get_io_loop  # placeholder to satisfy type checker
    owner = isolated_db  # not used; keep fixture activated
    now = datetime.now(timezone.utc)

    # Seed a wine + a case-type CellarItem + a legacy-shaped Transaction.
    wine = Wine(
        owner_id=mig.ObjectId(),  # pretend owner
        collection=WineCollection.CELLAR,
        name=f"Mig {uuid.uuid4().hex[:6]}",
        inventory=WineInventoryInfo(quantity=12, case_size=12, updated_at=now),
    )
    await wine.insert()

    case = CellarItem(
        cellar_id=wine.owner_id,
        item_type="case",
        wine=EmbeddedWine(wine_id=wine.id, name=wine.name),
        quantity=12,
        case_size=12,
        provenance="Berry Bros",
        purchase_price=420.0,
        created_at=now,
    )
    await case.insert()

    tx = Transaction(
        owner_id=wine.owner_id,
        wine_id=wine.id,
        transaction_type=TransactionType.ADDED,
        quantity=12,
        transaction_date=now,
    )
    await tx.insert()

    # Run the migration against this test DB.
    db_name = isolated_db.name
    mongo_url = os.environ.get("TEST_MONGODB_URL", "mongodb://localhost:27017")

    totals = await mig.migrate(
        db_name=db_name, mongo_url=mongo_url,
        dry_run=False, batch_size=100, since=None,
    )
    assert totals["considered"] >= 1
    assert totals["inserted"] >= 1

    # The new event is present, enriched with case snapshot + denormalised ids.
    event = await CellarEvent.find_one({"migrated_from_transaction_id": tx.id})
    assert event is not None
    assert event.cellar_item_id == case.id
    assert event.item_type == "case"
    assert event.case_size_at_event == 12
    assert event.provenance_at_event == "Berry Bros"
    assert event.wine_id == wine.id
    assert event.owner_id == wine.owner_id
    assert event.event_type.value == "added"

    # Re-run: idempotent — no new events.
    events_before = await CellarEvent.find({"wine_id": wine.id}).to_list()
    totals2 = await mig.migrate(
        db_name=db_name, mongo_url=mongo_url,
        dry_run=False, batch_size=100, since=None,
    )
    events_after = await CellarEvent.find({"wine_id": wine.id}).to_list()
    assert len(events_after) == len(events_before)
    assert totals2["skipped_already_migrated"] >= 1


@pytest.mark.asyncio
async def test_backfill_unlinked_row_is_bottle_with_no_cellar_item(isolated_db) -> None:
    """A Transaction with no matching CellarItem → `item_type="bottle"`,
    `cellar_item_id=None`. The `legacy` item_type was retired once
    production was migrated onto the per-row `cellars` collection."""
    from winebox.models import Transaction, TransactionType, RemovalReason
    from winebox.models.cellar_event import CellarEvent
    from winebox.models.wine import Wine, WineCollection
    from winebox.models.wine import InventoryInfo as WineInventoryInfo

    now = datetime.now(timezone.utc)
    wine = Wine(
        owner_id=mig.ObjectId(),
        collection=WineCollection.CELLAR,
        name=f"LegacyMig {uuid.uuid4().hex[:6]}",
        inventory=WineInventoryInfo(quantity=0, updated_at=now),
    )
    await wine.insert()

    tx = Transaction(
        owner_id=wine.owner_id,
        wine_id=wine.id,
        transaction_type=TransactionType.REMOVED,
        quantity=1,
        removal_reason=RemovalReason.DRINK,
        tasting_notes="Remembered fondly.",
        transaction_date=now,
    )
    await tx.insert()

    db_name = isolated_db.name
    mongo_url = os.environ.get("TEST_MONGODB_URL", "mongodb://localhost:27017")

    await mig.migrate(
        db_name=db_name, mongo_url=mongo_url,
        dry_run=False, batch_size=100, since=None,
    )

    event = await CellarEvent.find_one({"migrated_from_transaction_id": tx.id})
    assert event is not None
    assert event.cellar_item_id is None
    assert event.item_type == "bottle"
    assert event.event_type.value == "drunk"
    assert event.removal_reason is not None and event.removal_reason.value == "DRINK"
    assert event.tasting_notes == "Remembered fondly."
    assert event.wine_id == wine.id
    assert event.owner_id == wine.owner_id


@pytest.mark.asyncio
async def test_backfill_dry_run_writes_nothing(isolated_db) -> None:
    """`--dry-run` reports counts without inserting any events."""
    from winebox.models import Transaction, TransactionType
    from winebox.models.cellar_event import CellarEvent
    from winebox.models.wine import Wine, WineCollection
    from winebox.models.wine import InventoryInfo as WineInventoryInfo

    now = datetime.now(timezone.utc)
    wine = Wine(
        owner_id=mig.ObjectId(),
        collection=WineCollection.CELLAR,
        name=f"DryRun {uuid.uuid4().hex[:6]}",
        inventory=WineInventoryInfo(quantity=1, updated_at=now),
    )
    await wine.insert()
    tx = Transaction(
        owner_id=wine.owner_id, wine_id=wine.id,
        transaction_type=TransactionType.ADDED, quantity=1,
        transaction_date=now,
    )
    await tx.insert()

    db_name = isolated_db.name
    mongo_url = os.environ.get("TEST_MONGODB_URL", "mongodb://localhost:27017")

    totals = await mig.migrate(
        db_name=db_name, mongo_url=mongo_url,
        dry_run=True, batch_size=100, since=None,
    )
    assert totals["inserted"] == 0  # no writes under --dry-run

    event = await CellarEvent.find_one({"migrated_from_transaction_id": tx.id})
    assert event is None


@pytest.mark.asyncio
async def test_backfill_since_filter_skips_old_rows(isolated_db) -> None:
    """`--since` lets incremental re-runs process only recent transactions."""
    from winebox.models import Transaction, TransactionType
    from winebox.models.cellar_event import CellarEvent
    from winebox.models.wine import Wine, WineCollection
    from winebox.models.wine import InventoryInfo as WineInventoryInfo

    long_ago = datetime(2024, 1, 1, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)

    wine = Wine(
        owner_id=mig.ObjectId(),
        collection=WineCollection.CELLAR,
        name=f"Since {uuid.uuid4().hex[:6]}",
        inventory=WineInventoryInfo(quantity=0, updated_at=now),
    )
    await wine.insert()

    old_tx = Transaction(
        owner_id=wine.owner_id, wine_id=wine.id,
        transaction_type=TransactionType.ADDED, quantity=1,
        transaction_date=long_ago,
    )
    new_tx = Transaction(
        owner_id=wine.owner_id, wine_id=wine.id,
        transaction_type=TransactionType.REMOVED, quantity=1,
        transaction_date=now,
    )
    await old_tx.insert()
    await new_tx.insert()

    db_name = isolated_db.name
    mongo_url = os.environ.get("TEST_MONGODB_URL", "mongodb://localhost:27017")

    cutoff = now - timedelta(hours=1)
    await mig.migrate(
        db_name=db_name, mongo_url=mongo_url,
        dry_run=False, batch_size=100, since=cutoff,
    )

    # Only the recent transaction was migrated.
    old_event = await CellarEvent.find_one({"migrated_from_transaction_id": old_tx.id})
    new_event = await CellarEvent.find_one({"migrated_from_transaction_id": new_tx.id})
    assert old_event is None
    assert new_event is not None
