"""Read CellarEvent as TransactionResponse.

Phase 4d of the cases-first-class plan. After the PR-3 enrichment,
`CellarEvent` carries every field Transaction ever did plus the
case-context snapshots. This service is the compatibility layer that
lets the existing transactions-shaped API response keep working
unchanged while the underlying store flips from `transactions` to
`cellar_events`.

One-way mapping — we never synthesise a `Transaction` row from an
event; we only produce `TransactionResponse` dicts (or Pydantic
models) for the API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from bson import ObjectId

from winebox.models.cellar_event import CellarEvent, CellarEventType
from winebox.models.transaction import RemovalReason, TransactionType
from winebox.schemas.transaction import TransactionResponse, WineBasicInfo


# Inverse of the map in services.cellar_debit + the backfill script.
# `ADDED` is the only non-removal event; everything else maps to REMOVED
# with a matching reason.
_EVENT_TO_TX_TYPE: dict[CellarEventType, TransactionType] = {
    CellarEventType.ADDED: TransactionType.ADDED,
    CellarEventType.DRUNK: TransactionType.REMOVED,
    CellarEventType.SOLD: TransactionType.REMOVED,
    CellarEventType.GIFTED: TransactionType.REMOVED,
    CellarEventType.BREAKAGE: TransactionType.REMOVED,
    CellarEventType.OTHER: TransactionType.REMOVED,
}

_EVENT_TO_REMOVAL_REASON: dict[CellarEventType, Optional[RemovalReason]] = {
    CellarEventType.ADDED: None,
    CellarEventType.DRUNK: RemovalReason.DRINK,
    CellarEventType.SOLD: RemovalReason.SELL,
    CellarEventType.GIFTED: RemovalReason.GIFT,
    # Transaction.RemovalReason has no BREAKAGE enum value — bucket
    # breakage events as OTHER so the existing UI categorisation keeps
    # working. The event itself keeps the richer `event_type` if a
    # future UI wants to distinguish.
    CellarEventType.BREAKAGE: RemovalReason.OTHER,
    CellarEventType.OTHER: RemovalReason.OTHER,
}


def event_to_transaction_response(
    event: CellarEvent,
    *,
    wine: Optional[WineBasicInfo] = None,
) -> TransactionResponse:
    """Project a CellarEvent onto the TransactionResponse shape.

    When `wine` is provided it's stamped onto the response so the
    existing list endpoint's "wine: {id, name, vintage, winery}"
    embed keeps working without an extra round-trip.
    """
    # CellarEvent may still have legacy rows where the enum was a raw
    # string — treat both defensively.
    event_type = event.event_type
    if not isinstance(event_type, CellarEventType):
        event_type = CellarEventType(event_type)

    tx_type = _EVENT_TO_TX_TYPE.get(event_type, TransactionType.REMOVED)
    # Trust the source event's `removal_reason` field as-is: when the
    # caller omitted a reason on checkout the event was written with
    # removal_reason=None, and old clients expect the API to preserve
    # that. Fall back to the event_type mapping only for
    # event_type=ADDED (which has no reason) and for legacy/backfilled
    # rows that predate the `removal_reason` field (best-effort inference).
    if event.removal_reason is not None:
        reason: Optional[RemovalReason] = event.removal_reason
    elif event_type == CellarEventType.ADDED:
        reason = None
    elif event_type in (CellarEventType.BREAKAGE, CellarEventType.OTHER):
        # BREAKAGE has no Transaction-era enum; OTHER inferred as-is.
        reason = _EVENT_TO_REMOVAL_REASON.get(event_type)
    else:
        reason = None
    # `wine_id` might be None on legacy pre-Phase-4 events that were
    # written before the denormalised field existed. Keep the column
    # populated with an empty string rather than blow up the schema.
    wine_id_str = str(event.wine_id) if event.wine_id is not None else ""

    return TransactionResponse(
        id=str(event.id),
        wine_id=wine_id_str,
        transaction_type=tx_type,
        quantity=event.quantity,
        notes=event.notes,
        transaction_date=event.event_date,
        created_at=event.created_at,
        wine=wine,
        removal_reason=reason,
        tasting_notes=event.tasting_notes,
        sale_price_usd=event.sale_price_usd if event.sale_price_usd is not None else event.sale_price,
        gift_recipient=event.gift_recipient,
        removal_notes=event.removal_notes,
        item_type=event.item_type,
        case_size_at_event=event.case_size_at_event,
        provenance_at_event=event.provenance_at_event,
    )


def build_event_query(
    owner_id: ObjectId,
    *,
    transaction_type: Optional[TransactionType] = None,
    wine_id: Optional[ObjectId] = None,
    removal_reason: Optional[RemovalReason] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build a Mongo filter on `cellar_events` that matches the same
    semantics as the old transactions-router filters."""
    # Owner scoping first. Prefer `owner_id` (populated on every new
    # write); fall back to `cellar_id` for events written before 4a.
    query: dict[str, Any] = {"$or": [{"owner_id": owner_id}, {"cellar_id": owner_id}]}

    and_clauses: list[dict[str, Any]] = []
    if transaction_type == TransactionType.ADDED:
        and_clauses.append({"event_type": CellarEventType.ADDED.value})
    elif transaction_type == TransactionType.REMOVED:
        and_clauses.append({"event_type": {"$ne": CellarEventType.ADDED.value}})
    if wine_id is not None:
        and_clauses.append({"wine_id": wine_id})
    if removal_reason is not None:
        and_clauses.append({"removal_reason": removal_reason.value})
    if date_from is not None:
        and_clauses.append({"event_date": {"$gte": date_from}})
    if date_to is not None:
        and_clauses.append({"event_date": {"$lte": date_to}})

    if and_clauses:
        query = {"$and": [query, *and_clauses]}
    return query


async def list_events_as_transactions(
    owner_id: ObjectId,
    *,
    skip: int = 0,
    limit: int = 100,
    transaction_type: Optional[TransactionType] = None,
    wine_id: Optional[ObjectId] = None,
    removal_reason: Optional[RemovalReason] = None,
    attach_wine_info: bool = True,
) -> list[TransactionResponse]:
    """Return TransactionResponse rows synthesised from CellarEvent.

    Replaces `Transaction.find(...)` in the list endpoint. When
    `attach_wine_info` is True, does a single bulk Wine lookup and
    decorates each row with `wine: {id, name, vintage, winery}`.
    """
    from winebox.models import Wine

    query = build_event_query(
        owner_id,
        transaction_type=transaction_type,
        wine_id=wine_id,
        removal_reason=removal_reason,
    )
    events = await (
        CellarEvent.find(query)
        .sort([("event_date", -1)])
        .skip(skip).limit(limit).to_list()
    )

    wine_map: dict[ObjectId, WineBasicInfo] = {}
    if attach_wine_info and events:
        wine_ids = list({e.wine_id for e in events if e.wine_id is not None})
        if wine_ids:
            wines = await Wine.find({"_id": {"$in": wine_ids}}).to_list()
            for w in wines:
                wine_map[w.id] = WineBasicInfo(
                    id=str(w.id), name=w.name, vintage=w.vintage, winery=w.winery,
                )

    return [
        event_to_transaction_response(
            e, wine=(wine_map.get(e.wine_id) if e.wine_id else None),
        )
        for e in events
    ]


async def get_event_as_transaction(
    owner_id: ObjectId, transaction_id: str,
    *,
    attach_wine_info: bool = True,
) -> Optional[TransactionResponse]:
    """Single-row fetch for the `GET /api/transactions/{id}` endpoint.

    `transaction_id` is the CellarEvent's `_id` under the hood — the
    API keeps the parameter name for backward compatibility.
    """
    from winebox.models import Wine

    try:
        event_id = ObjectId(transaction_id)
    except Exception:
        return None

    event = await CellarEvent.find_one({
        "_id": event_id,
        "$or": [{"owner_id": owner_id}, {"cellar_id": owner_id}],
    })
    if event is None:
        return None

    wine_info: Optional[WineBasicInfo] = None
    if attach_wine_info and event.wine_id is not None:
        w = await Wine.find_one({"_id": event.wine_id})
        if w is not None:
            wine_info = WineBasicInfo(
                id=str(w.id), name=w.name, vintage=w.vintage, winery=w.winery,
            )

    return event_to_transaction_response(event, wine=wine_info)


async def list_wine_transactions(
    wine_id: ObjectId, owner_id: ObjectId,
) -> list[TransactionResponse]:
    """History rows for the wine-detail modal.

    Returns newest-first, without `wine` embed (the caller already has
    the wine context). Used by `routers/wines/crud.py:get_wine`.
    """
    events = await (
        CellarEvent.find({
            "wine_id": wine_id,
            "$or": [{"owner_id": owner_id}, {"cellar_id": owner_id}],
        })
        .sort([("event_date", -1)])
        .to_list()
    )
    return [event_to_transaction_response(e) for e in events]
