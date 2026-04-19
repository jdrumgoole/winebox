"""Wine search service — filter construction + query execution.

Previously inlined in ``routers/search.py``. Moving it here lets the
router stay focused on HTTP binding, and puts the two cross-collection
joins (cellar-items for storage/provenance filter, transactions for
check-in/-out date filter) next to each other rather than interleaved
with parameter parsing.

Also replaces the pattern where every search fired a probe ``$text``
query to detect whether the MongoDB text index exists (mongomock in
tests doesn't support it). The result is now cached for the process
lifetime — mongomock or real MongoDB doesn't switch capabilities mid-run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from winebox.db import PyObjectId
from winebox.models import Transaction, TransactionType, Wine
from winebox.models.cellar import CellarItem
from winebox.models.wine import WineCollection
from winebox.services.rate_limit import MAX_USER_RESULTSET

# Lazy-initialised capability cache. None until first probe.
_text_index_available: bool | None = None


async def _has_text_index() -> bool:
    """Return True if the current MongoDB connection supports ``$text``.

    Cached on first call — mongomock doesn't grow a text index halfway
    through a test run, and a real MongoDB doesn't lose one.
    """
    global _text_index_available
    if _text_index_available is None:
        try:
            await Wine.find({"$text": {"$search": "capability-probe"}}).limit(1).to_list()
            _text_index_available = True
        except Exception:
            _text_index_available = False
    return _text_index_available


def _reset_text_index_cache() -> None:
    """Test hook — forces the next search to re-probe text-index support."""
    global _text_index_available
    _text_index_available = None


@dataclass(frozen=True)
class WineSearchFilters:
    """Search parameters. Mirrors the router's Query params."""

    q: str | None = None
    vintage: int | None = None
    grape: str | None = None
    winery: str | None = None
    region: str | None = None
    country: str | None = None
    checked_in_after: datetime | None = None
    checked_in_before: datetime | None = None
    checked_out_after: datetime | None = None
    checked_out_before: datetime | None = None
    in_stock: bool | None = None
    collection: WineCollection | None = None
    storage: str | None = None
    provenance: str | None = None
    wine_type: str | None = None
    price_tier: str | None = None
    enriched: str | None = None


def _regex_conditions(q: str) -> list[dict[str, Any]]:
    """Fallback $or clause used when the text index isn't available."""
    pat = re.compile(re.escape(q), re.IGNORECASE)
    return [
        {"name": {"$regex": pat}},
        {"winery": {"$regex": pat}},
        {"region": {"$regex": pat}},
        {"sub_region": {"$regex": pat}},
        {"appellation": {"$regex": pat}},
        {"country": {"$regex": pat}},
        {"grape_variety": {"$regex": pat}},
        {"front_label_text": {"$regex": pat}},
        {"back_label_text": {"$regex": pat}},
        {"custom_fields_text": {"$regex": pat}},
    ]


async def _resolve_storage_provenance_ids(
    owner_id: PyObjectId,
    storage: str | None,
    provenance: str | None,
) -> set[Any] | None:
    """Return the set of wine IDs that match the storage/provenance filter.

    Returns None if no filter is active. An empty set means "no wines match".
    """
    if not (storage or provenance):
        return None

    cellar_query: dict[str, Any] = {"cellar_id": owner_id}
    if storage == "case":
        cellar_query["item_type"] = "case"
    elif storage == "loose":
        cellar_query["item_type"] = "bottle"

    if provenance:
        cellar_query["provenance"] = {
            "$regex": re.compile(re.escape(provenance), re.IGNORECASE)
        }

    cellar_col = CellarItem.get_pymongo_collection()
    items = await cellar_col.find(
        cellar_query, {"wine.wine_id": 1}
    ).to_list(length=MAX_USER_RESULTSET)
    return {item["wine"]["wine_id"] for item in items if item.get("wine")}


async def _resolve_transaction_date_ids(
    owner_id: PyObjectId,
    filters: WineSearchFilters,
) -> set[Any] | None:
    """Return the set of wine IDs touched by transactions in the given window.

    When check-in and check-out date ranges are both supplied, the result
    is the intersection. Returns None if neither filter is active.
    """
    result: set[Any] | None = None

    def _date_range(after: datetime | None, before: datetime | None) -> dict[str, Any]:
        rng: dict[str, Any] = {}
        if after is not None:
            rng["$gte"] = after
        if before is not None:
            rng["$lte"] = before
        return rng

    if filters.checked_in_after or filters.checked_in_before:
        q = {
            "owner_id": owner_id,
            "transaction_type": TransactionType.ADDED,
            "transaction_date": _date_range(filters.checked_in_after, filters.checked_in_before),
        }
        txns = await Transaction.find(q).to_list(length=MAX_USER_RESULTSET)
        result = {t.wine_id for t in txns}

    if filters.checked_out_after or filters.checked_out_before:
        q = {
            "owner_id": owner_id,
            "transaction_type": TransactionType.REMOVED,
            "transaction_date": _date_range(filters.checked_out_after, filters.checked_out_before),
        }
        txns = await Transaction.find(q).to_list(length=MAX_USER_RESULTSET)
        checkout_ids = {t.wine_id for t in txns}
        result = checkout_ids if result is None else result & checkout_ids

    return result


def _apply_scalar_filters(conditions: dict[str, Any], filters: WineSearchFilters) -> None:
    """Add exact/partial-match conditions for scalar filter parameters."""
    if filters.vintage:
        conditions["vintage"] = filters.vintage
    if filters.grape:
        conditions["grape_variety"] = {
            "$regex": re.compile(re.escape(filters.grape), re.IGNORECASE)
        }
    if filters.winery:
        conditions["winery"] = {
            "$regex": re.compile(re.escape(filters.winery), re.IGNORECASE)
        }
    if filters.region:
        conditions["region"] = {
            "$regex": re.compile(re.escape(filters.region), re.IGNORECASE)
        }
    if filters.country:
        conditions["country"] = {
            "$regex": re.compile(re.escape(filters.country), re.IGNORECASE)
        }
    if filters.wine_type:
        conditions["wine_type"] = filters.wine_type
    if filters.price_tier:
        conditions["price_tier"] = filters.price_tier

    if filters.enriched == "yes":
        conditions["xwines_id"] = {"$ne": None}
    elif filters.enriched == "no":
        conditions["xwines_id"] = None

    if filters.in_stock is True:
        conditions["inventory.quantity"] = {"$gt": 0}
    elif filters.in_stock is False:
        conditions["inventory.quantity"] = {"$lte": 0}


async def search_wines(
    owner_id: PyObjectId,
    filters: WineSearchFilters,
    skip: int,
    limit: int,
) -> list[Wine]:
    """Search wines for ``owner_id`` using ``filters`` and pagination.

    Returns raw ``Wine`` documents — the router wraps them in
    ``WineWithInventory`` for the response.
    """
    conditions: dict[str, Any] = {"owner_id": owner_id}

    if filters.collection:
        conditions["collection"] = filters.collection.value

    use_text_search = False
    if filters.q:
        if await _has_text_index():
            conditions["$text"] = {"$search": filters.q}
            use_text_search = True
        else:
            conditions["$or"] = _regex_conditions(filters.q)

    _apply_scalar_filters(conditions, filters)

    # Narrow by the cellar-side filter (storage type / provenance).
    cellar_ids = await _resolve_storage_provenance_ids(
        owner_id, filters.storage, filters.provenance
    )
    if cellar_ids is not None:
        if not cellar_ids:
            return []
        conditions["_id"] = {"$in": list(cellar_ids)}

    # Narrow by transaction date ranges. Intersect with any existing _id filter
    # from the cellar side.
    txn_ids = await _resolve_transaction_date_ids(owner_id, filters)
    if txn_ids is not None:
        if not txn_ids:
            return []
        existing_ids = conditions.get("_id", {}).get("$in") if isinstance(conditions.get("_id"), dict) else None
        if existing_ids is not None:
            conditions["_id"] = {"$in": list(set(existing_ids) & txn_ids)}
            if not conditions["_id"]["$in"]:
                return []
        else:
            conditions["_id"] = {"$in": list(txn_ids)}

    query = Wine.find(conditions).skip(skip).limit(limit)
    if use_text_search:
        query = query.sort([("score", {"$meta": "textScore"}), ("created_at", -1)])
    else:
        query = query.sort([("created_at", -1)])

    return await query.to_list()
