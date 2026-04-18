"""Demo data service: curated sample wines for new users.

Pulls real wines from the ``xwines_wines`` reference collection so the demo
cellar looks authentic. All demo wines are tagged with
``custom_fields._demo = "true"`` so they can be removed cleanly without
touching the user's real wines.

The router in :mod:`winebox.routers.demo` is a thin HTTP wrapper around
this module.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId

from winebox.database import get_database
from winebox.db import PyObjectId
from winebox.models.cellar import CellarItem, EmbeddedWine
from winebox.models.cellar_event import CellarEvent, CellarEventType
from winebox.models.transaction import Transaction, TransactionType
from winebox.models.wine import InventoryInfo, Wine

logger = logging.getLogger(__name__)

DEMO_TAG = {"_demo": "true"}
DEMO_WINE_COUNT = 500

_TYPE_TARGETS = {
    "Red": 250,
    "White": 120,
    "Rosé": 30,
    "Sparkling": 50,
    "Dessert": 25,
    "Fortified": 25,
}

_TYPE_MAP = {
    "Red": "red",
    "White": "white",
    "Rosé": "rose",
    "Sparkling": "sparkling",
    "Dessert": "dessert",
    "Fortified": "fortified",
}

_CHECKOUT_NOTES = [
    "Tuesday night pasta dinner",
    "Summer barbecue with friends",
    "Picnic at the park",
    "Birthday celebration",
    "Date night",
    "Holiday dinner",
    "Book club meeting",
    "Housewarming gift",
    "Friday night in",
    "Sunday roast",
    "Dinner party",
    "Cheese and wine evening",
    "Celebration dinner",
    "Weekend lunch",
    "Just because",
]

_PROVENANCE_SOURCES = [
    "Berry Bros & Rudd",
    "Majestic Wine",
    "The Wine Society",
    "Laithwaites",
    "Corney & Barrow",
    "Justerini & Brooks",
    "Tanners Wines",
    "Averys of Bristol",
    "Lay & Wheeler",
    "Direct from winery",
    "Auction",
    "Wine fair",
]

# Per-user progress snapshot updated by the background install task and
# polled by the SSE endpoint. Keyed by str(owner_id). Best-effort in-process
# state — surviving a restart is not a requirement.
_install_progress: dict[str, dict[str, Any]] = {}


class DemoAlreadyInstalledError(Exception):
    """Raised when a user tries to install demo data on top of existing demo data."""


class NoReferenceDataError(Exception):
    """Raised when the X-Wines reference dataset is not loaded."""


@dataclass(frozen=True)
class DemoStatus:
    installed: bool
    wine_count: int
    bottle_count: int


@dataclass(frozen=True)
class RemovalResult:
    wines_removed: int
    transactions_removed: int


def _parse_grapes(grapes_str: str | None) -> str | None:
    """Parse X-Wines grapes field into a primary grape name."""
    if not grapes_str:
        return None
    try:
        parsed = ast.literal_eval(grapes_str)
        if isinstance(parsed, list) and parsed:
            return str(parsed[0])
    except (ValueError, SyntaxError):
        pass
    stripped = grapes_str.strip()
    if stripped and not stripped.startswith("["):
        return stripped
    return None


def _parse_vintages(vintages_str: str | None) -> list[int]:
    """Parse X-Wines vintages field into a list of ints."""
    if not vintages_str:
        return []
    try:
        parsed = ast.literal_eval(vintages_str)
        if isinstance(parsed, list):
            return [int(v) for v in parsed if v]
    except (ValueError, SyntaxError):
        pass
    return []


async def select_demo_wines() -> list[dict[str, Any]]:
    """Select diverse wines from ``xwines_wines`` for the demo cellar.

    Stratifies by wine type, prefers popular wines (high rating_count),
    and picks a random vintage for each wine. Batches in an estimated
    price range from ``xwines_prices`` when available.
    """
    db = get_database()
    xwines_col = db["xwines_wines"]
    prices_col = db["xwines_prices"]

    selected: list[dict[str, Any]] = []

    for wine_type, target in _TYPE_TARGETS.items():
        cursor = xwines_col.find(
            {"wine_type": wine_type, "rating_count": {"$gte": 25}},
            {
                "xwines_id": 1, "name": 1, "wine_type": 1, "grapes": 1,
                "abv": 1, "country": 1, "region_name": 1, "winery_name": 1,
                "avg_rating": 1, "rating_count": 1, "vintages": 1,
            },
        ).sort([("rating_count", -1)]).limit(target * 3)

        candidates = await cursor.to_list(length=target * 3)
        random.shuffle(candidates)
        chosen = candidates[:target]

        for doc in chosen:
            vintages = _parse_vintages(doc.get("vintages"))
            vintage = random.choice(vintages) if vintages else None
            quantity = random.choices([1, 2, 3, 6, 12], weights=[30, 25, 20, 15, 10])[0]

            # Wines with quantity 6 or 12 become cases
            case_size = None
            provenance = None
            purchase_price = None
            if quantity in (6, 12):
                case_size = quantity
                provenance = random.choice(_PROVENANCE_SOURCES)
                purchase_price = round(random.uniform(40, 300), 2)

            wine_data: dict[str, Any] = {
                "name": doc["name"],
                "winery": doc.get("winery_name"),
                "vintage": vintage,
                "grape_variety": _parse_grapes(doc.get("grapes")),
                "region": doc.get("region_name"),
                "country": doc.get("country"),
                "alcohol_percentage": doc.get("abv"),
                "wine_type": _TYPE_MAP.get(wine_type, "red"),
                "xwines_id": doc.get("xwines_id"),
                "quantity": quantity,
                "case_size": case_size,
                "provenance": provenance,
                "purchase_price": purchase_price,
            }
            selected.append(wine_data)

    # Batch price lookup
    xwines_ids = [w["xwines_id"] for w in selected if w.get("xwines_id")]
    if xwines_ids:
        price_cursor = prices_col.find(
            {"xwines_id": {"$in": xwines_ids}, "vintage": None},
            {"_id": 0, "xwines_id": 1, "price_low_usd": 1, "price_high_usd": 1, "price_tier": 1},
        )
        price_map: dict[int, dict] = {
            doc["xwines_id"]: doc async for doc in price_cursor
        }
        for wine_data in selected:
            xid = wine_data.get("xwines_id")
            if xid and xid in price_map:
                p = price_map[xid]
                wine_data["estimated_price_low"] = p.get("price_low_usd")
                wine_data["estimated_price_high"] = p.get("price_high_usd")
                wine_data["price_tier"] = p.get("price_tier")

    random.shuffle(selected)
    return selected[:DEMO_WINE_COUNT]


async def _flush_wine_batch(
    owner_id: PyObjectId,
    wine_batch: list[Wine],
    batch_meta: list[tuple[int, datetime, int | None, str | None, float | None]],
) -> None:
    """Insert a batch of wines with their transactions, cellar items, and events."""
    await Wine.insert_many(wine_batch)

    txn_batch = [
        Transaction(
            owner_id=owner_id,
            wine_id=w.id,
            transaction_type=TransactionType.ADDED,
            quantity=q,
            transaction_date=ca,
            created_at=ca,
        )
        for w, (q, ca, _cs, _prov, _pp) in zip(wine_batch, batch_meta)
    ]
    await Transaction.insert_many(txn_batch)

    cellar_items: list[CellarItem] = []
    cellar_events: list[CellarEvent] = []

    for w, (q, ca, case_size, provenance, purchase_price) in zip(wine_batch, batch_meta):
        embedded = EmbeddedWine(
            wine_id=w.id, name=w.name, winery=w.winery,
            vintage=w.vintage, grape_variety=w.grape_variety,
            country=w.country, region=w.region, wine_type=w.wine_type,
            estimated_price_low=w.estimated_price_low,
            estimated_price_high=w.estimated_price_high,
            price_tier=w.price_tier,
        )

        item_id = ObjectId()
        if case_size and case_size > 0:
            cellar_items.append(CellarItem(
                id=item_id, cellar_id=owner_id, item_type="case",
                wine=embedded, quantity=q, case_size=case_size,
                purchase_price=purchase_price, purchase_date=ca,
                provenance=provenance, created_at=ca, updated_at=ca,
            ))
            cellar_events.append(CellarEvent(
                cellar_id=owner_id, cellar_item_id=item_id,
                item_type="case", event_type=CellarEventType.ADDED,
                quantity=q, event_date=ca, created_at=ca,
            ))
        else:
            cellar_items.append(CellarItem(
                id=item_id, cellar_id=owner_id, item_type="bottle",
                wine=embedded, quantity=q,
                created_at=ca, updated_at=ca,
            ))
            cellar_events.append(CellarEvent(
                cellar_id=owner_id, cellar_item_id=item_id,
                item_type="bottle", event_type=CellarEventType.ADDED,
                quantity=q, event_date=ca, created_at=ca,
            ))

    if cellar_items:
        await CellarItem.insert_many(cellar_items)
        await CellarEvent.insert_many(cellar_events)


async def install_demo_data(owner_id: PyObjectId, sample_wines: list[dict[str, Any]]) -> None:
    """Background task: insert demo wines and update in-memory progress.

    Clients poll :func:`get_install_progress` to observe.
    """
    owner_str = str(owner_id)
    total = len(sample_wines)
    now = datetime.now(timezone.utc)
    wines_created = 0
    total_bottles = 0
    countries: set[str] = set()
    wine_types: set[str] = set()
    checkout_candidates: list[tuple[Any, int]] = []

    _install_progress[owner_str] = {
        "phase": "loading",
        "created": 0,
        "total": total,
    }

    BATCH_SIZE = 50
    wine_batch: list[Wine] = []
    batch_meta: list[tuple[int, datetime, int | None, str | None, float | None]] = []

    for i, wine_data in enumerate(sample_wines):
        data = dict(wine_data)
        quantity = data.pop("quantity", 1)
        xwines_id = data.pop("xwines_id", None)
        case_size = data.pop("case_size", None)
        provenance = data.pop("provenance", None)
        purchase_price = data.pop("purchase_price", None)

        days_ago = total - i
        created_at = now - timedelta(days=days_ago)

        wine_id = ObjectId()
        wine = Wine(
            id=wine_id,
            owner_id=owner_id,
            custom_fields=DEMO_TAG,
            xwines_id=xwines_id,
            created_at=created_at,
            updated_at=created_at,
            inventory=InventoryInfo(quantity=quantity, updated_at=created_at),
            **data,
        )
        wine_batch.append(wine)
        batch_meta.append((quantity, created_at, case_size, provenance, purchase_price))

        total_bottles += quantity
        if data.get("country"):
            countries.add(data["country"])
        if data.get("wine_type"):
            wine_types.add(data["wine_type"])

        if quantity >= 3:
            checkout_candidates.append((wine_id, quantity))

        if len(wine_batch) >= BATCH_SIZE:
            await _flush_wine_batch(owner_id, wine_batch, batch_meta)
            wines_created += len(wine_batch)
            wine_batch.clear()
            batch_meta.clear()

            _install_progress[owner_str] = {
                "phase": "loading",
                "created": wines_created,
                "total": total,
            }

    if wine_batch:
        await _flush_wine_batch(owner_id, wine_batch, batch_meta)
        wines_created += len(wine_batch)

    # Create checkout transactions in batch for a realistic history
    checkout_count = min(len(checkout_candidates), max(20, total // 10))
    random.shuffle(checkout_candidates)
    checkout_txns: list[Transaction] = []
    wine_updates: list[tuple[Any, int, datetime]] = []

    for wine_id, max_qty in checkout_candidates[:checkout_count]:
        qty = random.randint(1, max(1, max_qty - 1))
        notes = random.choice(_CHECKOUT_NOTES)
        checkout_date = now - timedelta(days=random.randint(1, 60))

        checkout_txns.append(Transaction(
            owner_id=owner_id,
            wine_id=wine_id,
            transaction_type=TransactionType.REMOVED,
            quantity=qty,
            notes=notes,
            transaction_date=checkout_date,
            created_at=checkout_date,
        ))
        wine_updates.append((wine_id, qty, checkout_date))
        total_bottles -= qty

    if checkout_txns:
        await Transaction.insert_many(checkout_txns)
        wines_col = Wine.get_pymongo_collection()
        for wine_id, qty, checkout_date in wine_updates:
            await wines_col.update_one(
                {"_id": wine_id},
                {"$inc": {"inventory.quantity": -qty},
                 "$set": {"inventory.updated_at": checkout_date, "updated_at": checkout_date}},
            )

    _install_progress[owner_str] = {
        "phase": "done",
        "created": wines_created,
        "total": total,
        "bottles": total_bottles,
        "countries": len(countries),
        "wine_types": len(wine_types),
    }

    logger.info(
        "Demo data installed for user %s: %d wines, %d bottles",
        owner_id, wines_created, total_bottles,
    )


async def start_install(owner_id: PyObjectId) -> int:
    """Kick off a background demo install for ``owner_id``.

    Returns the number of sample wines queued. Raises
    :class:`DemoAlreadyInstalledError` if the user already has demo data,
    or :class:`NoReferenceDataError` if the X-Wines dataset is empty.
    """
    existing = await Wine.find_one(
        {"owner_id": owner_id, "custom_fields._demo": "true"}
    )
    if existing:
        raise DemoAlreadyInstalledError()

    sample_wines = await select_demo_wines()
    if not sample_wines:
        raise NoReferenceDataError()

    asyncio.create_task(install_demo_data(owner_id, sample_wines))
    return len(sample_wines)


def get_install_progress(owner_id: PyObjectId) -> dict[str, Any] | None:
    """Return the current install progress snapshot, or None if idle."""
    return _install_progress.get(str(owner_id))


def pop_install_progress(owner_id: PyObjectId) -> None:
    """Clear the stored install progress for ``owner_id`` (no-op if absent)."""
    _install_progress.pop(str(owner_id), None)


async def get_demo_status(owner_id: PyObjectId) -> DemoStatus:
    """Return the demo-data status for ``owner_id``."""
    demo_wines = await Wine.find(
        {"owner_id": owner_id, "custom_fields._demo": "true"}
    ).to_list()

    bottle_count = sum(w.inventory.quantity for w in demo_wines)

    return DemoStatus(
        installed=len(demo_wines) > 0,
        wine_count=len(demo_wines),
        bottle_count=bottle_count,
    )


async def remove_demo_wines(owner_id: PyObjectId) -> RemovalResult:
    """Remove all demo-tagged wines and their history for ``owner_id``.

    Real user wines (untagged) are not touched.
    """
    demo_wines = await Wine.find(
        {"owner_id": owner_id, "custom_fields._demo": "true"}
    ).to_list()

    if not demo_wines:
        return RemovalResult(wines_removed=0, transactions_removed=0)

    demo_wine_ids = [w.id for w in demo_wines]

    cellar_col = CellarItem.get_pymongo_collection()
    event_col = CellarEvent.get_pymongo_collection()

    demo_items = await cellar_col.find(
        {"cellar_id": owner_id, "wine.wine_id": {"$in": demo_wine_ids}},
        {"_id": 1},
    ).to_list(length=None)
    demo_item_ids = [item["_id"] for item in demo_items]

    if demo_item_ids:
        await event_col.delete_many(
            {"cellar_id": owner_id, "cellar_item_id": {"$in": demo_item_ids}}
        )
    await cellar_col.delete_many(
        {"cellar_id": owner_id, "wine.wine_id": {"$in": demo_wine_ids}}
    )

    txn_result = await Transaction.get_pymongo_collection().delete_many(
        {"owner_id": owner_id, "wine_id": {"$in": demo_wine_ids}}
    )

    wine_result = await Wine.get_pymongo_collection().delete_many(
        {"owner_id": owner_id, "custom_fields._demo": "true"}
    )

    logger.info(
        "Demo data removed for user %s: %d wines, %d transactions, %d cellar items",
        owner_id, wine_result.deleted_count, txn_result.deleted_count,
        len(demo_item_ids),
    )

    return RemovalResult(
        wines_removed=wine_result.deleted_count,
        transactions_removed=txn_result.deleted_count,
    )
