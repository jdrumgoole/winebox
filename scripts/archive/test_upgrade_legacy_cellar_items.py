"""Tests for the legacy-wines → CellarItems migration."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from bson import ObjectId

from scripts.archive import upgrade_legacy_cellar_items as mig


@pytest.mark.asyncio
async def test_orphan_wine_gets_bottle_cellar_item(isolated_db) -> None:
    """A cellar wine with inventory > 0 and no CellarItem → a new bottle CellarItem."""
    from winebox.models.wine import Wine, WineCollection, InventoryInfo as WineInventoryInfo

    now = datetime.now(timezone.utc)
    wine = Wine(
        owner_id=ObjectId(),
        collection=WineCollection.CELLAR,
        name=f"Orphan {uuid.uuid4().hex[:6]}",
        inventory=WineInventoryInfo(quantity=4, updated_at=now),
        created_at=now,
    )
    await wine.insert()

    db_name = isolated_db.name
    mongo_url = os.environ.get("TEST_MONGODB_URL", "mongodb://localhost:27017")
    totals = await mig.migrate(
        db_name=db_name, mongo_url=mongo_url,
        dry_run=False, batch_size=100,
    )
    assert totals["wines_considered"] >= 1
    assert totals["cellar_items_created"] >= 1

    items = await isolated_db["cellars"].find(
        {"cellar_id": wine.owner_id, "wine.wine_id": wine.id}
    ).to_list(length=None)
    assert len(items) == 1
    ci = items[0]
    assert ci["item_type"] == "bottle"
    assert ci["quantity"] == 4
    assert ci["wine"]["name"] == wine.name


@pytest.mark.asyncio
async def test_legacy_event_links_to_new_cellar_item(isolated_db) -> None:
    """A legacy CellarEvent gets `cellar_item_id` filled and `item_type=bottle`."""
    from winebox.models.wine import Wine, WineCollection, InventoryInfo as WineInventoryInfo
    from winebox.models.cellar_event import CellarEvent, CellarEventType

    now = datetime.now(timezone.utc)
    wine = Wine(
        owner_id=ObjectId(),
        collection=WineCollection.CELLAR,
        name=f"LegacyEvt {uuid.uuid4().hex[:6]}",
        inventory=WineInventoryInfo(quantity=2, updated_at=now),
        created_at=now,
    )
    await wine.insert()

    legacy_event = CellarEvent(
        cellar_id=wine.owner_id, owner_id=wine.owner_id, wine_id=wine.id,
        cellar_item_id=None,
        item_type="legacy",
        event_type=CellarEventType.DRUNK,
        quantity=1,
        event_date=now,
    )
    await legacy_event.insert()

    db_name = isolated_db.name
    mongo_url = os.environ.get("TEST_MONGODB_URL", "mongodb://localhost:27017")
    await mig.migrate(
        db_name=db_name, mongo_url=mongo_url,
        dry_run=False, batch_size=100,
    )

    # Event upgraded in place — `_id` unchanged.
    upgraded = await isolated_db["cellar_events"].find_one({"_id": legacy_event.id})
    assert upgraded is not None
    assert upgraded["item_type"] == "bottle"
    assert upgraded["cellar_item_id"] is not None

    # The linked CellarItem is the one the migration just created.
    ci = await isolated_db["cellars"].find_one({"_id": upgraded["cellar_item_id"]})
    assert ci is not None
    assert ci["wine"]["wine_id"] == wine.id


@pytest.mark.asyncio
async def test_legacy_event_with_no_wine_falls_back_to_bottle(isolated_db) -> None:
    """When the event's wine no longer exists, relabel to `bottle` only."""
    from winebox.models.cellar_event import CellarEvent, CellarEventType

    ghost_wine_id = ObjectId()
    legacy_event = CellarEvent(
        cellar_id=ObjectId(), owner_id=ObjectId(), wine_id=ghost_wine_id,
        cellar_item_id=None,
        item_type="legacy",
        event_type=CellarEventType.DRUNK,
        quantity=1,
        event_date=datetime.now(timezone.utc),
    )
    await legacy_event.insert()

    db_name = isolated_db.name
    mongo_url = os.environ.get("TEST_MONGODB_URL", "mongodb://localhost:27017")
    totals = await mig.migrate(
        db_name=db_name, mongo_url=mongo_url,
        dry_run=False, batch_size=100,
    )
    assert totals["legacy_events_relabelled_as_bottle"] >= 1

    upgraded = await isolated_db["cellar_events"].find_one({"_id": legacy_event.id})
    assert upgraded["item_type"] == "bottle"
    assert upgraded.get("cellar_item_id") is None  # no wine to link to


@pytest.mark.asyncio
async def test_migration_is_idempotent(isolated_db) -> None:
    """Re-running the migration changes nothing."""
    from winebox.models.wine import Wine, WineCollection, InventoryInfo as WineInventoryInfo

    now = datetime.now(timezone.utc)
    wine = Wine(
        owner_id=ObjectId(),
        collection=WineCollection.CELLAR,
        name=f"Idem {uuid.uuid4().hex[:6]}",
        inventory=WineInventoryInfo(quantity=1, updated_at=now),
        created_at=now,
    )
    await wine.insert()

    db_name = isolated_db.name
    mongo_url = os.environ.get("TEST_MONGODB_URL", "mongodb://localhost:27017")
    first = await mig.migrate(
        db_name=db_name, mongo_url=mongo_url, dry_run=False, batch_size=100,
    )
    assert first["cellar_items_created"] >= 1

    second = await mig.migrate(
        db_name=db_name, mongo_url=mongo_url, dry_run=False, batch_size=100,
    )
    # No more orphan wines after the first run; no more legacy events.
    assert second["cellar_items_created"] == 0
    assert second["legacy_events_considered"] == 0


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(isolated_db) -> None:
    """`--dry-run` reports counts but leaves the database untouched."""
    from winebox.models.wine import Wine, WineCollection, InventoryInfo as WineInventoryInfo

    now = datetime.now(timezone.utc)
    wine = Wine(
        owner_id=ObjectId(),
        collection=WineCollection.CELLAR,
        name=f"DryRun {uuid.uuid4().hex[:6]}",
        inventory=WineInventoryInfo(quantity=3, updated_at=now),
        created_at=now,
    )
    await wine.insert()

    db_name = isolated_db.name
    mongo_url = os.environ.get("TEST_MONGODB_URL", "mongodb://localhost:27017")
    await mig.migrate(
        db_name=db_name, mongo_url=mongo_url, dry_run=True, batch_size=100,
    )

    count = await isolated_db["cellars"].count_documents(
        {"cellar_id": wine.owner_id, "wine.wine_id": wine.id}
    )
    assert count == 0  # nothing written during dry-run
