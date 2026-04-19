"""Phase 4a/4b: CellarEvent is a superset of Transaction.

The dual-write window (4b) expects every check-in/check-out to produce
one Transaction *and* one CellarEvent per debited source, with the new
denormalised + snapshot fields populated. These tests pin the contract
before Phase 4d swaps readers onto CellarEvent.
"""

import io
import uuid

import pytest
from bson import ObjectId
from httpx import AsyncClient

from winebox.models import Transaction
from winebox.models.cellar_event import CellarEvent, CellarEventType


async def _record_cases(
    client: AsyncClient, *, name: str, case_size: int, num_cases: int = 1,
    provenance: str | None = None,
) -> dict:
    payload = {"name": name, "case_size": case_size, "num_cases": num_cases, "wine_type": "Red"}
    if provenance:
        payload["provenance"] = provenance
    resp = await client.post("/api/cases", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _record_loose(client: AsyncClient, *, name: str, quantity: int) -> dict:
    resp = await client.post("/api/bottles", json={"name": name, "quantity": quantity, "wine_type": "Red"})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _get_wine(client: AsyncClient, name: str) -> dict:
    resp = await client.get("/api/cellar")
    return next(w for w in resp.json() if w["name"] == name)


@pytest.mark.asyncio
async def test_record_wine_writes_enriched_added_event(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """Recording a case populates wine_id / owner_id / case snapshot on the ADDED event."""
    name = f"Added {uuid.uuid4().hex[:6]}"
    await _record_cases(client, name=name, case_size=12, provenance="Berry Bros")

    wine = await _get_wine(client, name)
    events = await CellarEvent.find(
        {"wine_id": ObjectId(wine["id"]), "event_type": CellarEventType.ADDED.value}
    ).to_list()
    assert events, "no ADDED event created"
    event = events[0]
    assert event.owner_id is not None
    assert event.wine_id == ObjectId(wine["id"])
    assert event.item_type == "case"
    assert event.case_size_at_event == 12
    assert event.provenance_at_event == "Berry Bros"


@pytest.mark.asyncio
async def test_record_loose_added_event_has_no_case_snapshot(client: AsyncClient) -> None:
    """A loose-bottle ADDED event has wine_id + owner_id but null case snapshot."""
    name = f"Loose {uuid.uuid4().hex[:6]}"
    await _record_loose(client, name=name, quantity=3)

    wine = await _get_wine(client, name)
    event = await CellarEvent.find_one(
        {"wine_id": ObjectId(wine["id"]), "event_type": CellarEventType.ADDED.value}
    )
    assert event is not None
    assert event.item_type == "bottle"
    assert event.case_size_at_event is None
    assert event.provenance_at_event is None
    assert event.wine_id == ObjectId(wine["id"])


@pytest.mark.asyncio
async def test_checkout_writes_enriched_removal_event(client: AsyncClient) -> None:
    """Specific-case debit produces one DRUNK event with case snapshot + reason."""
    name = f"Checkout {uuid.uuid4().hex[:6]}"
    await _record_cases(client, name=name, case_size=6, provenance="Vintners")
    wine = await _get_wine(client, name)
    case = wine["inventory"]["cases"][0]

    resp = await client.post(
        f"/api/wines/{wine['id']}/checkout",
        data={
            "quantity": "2",
            "cellar_item_id": case["cellar_item_id"],
            "removal_reason": "DRINK",
            "tasting_notes": "Lovely with lamb.",
        },
    )
    assert resp.status_code == 200

    event = await CellarEvent.find_one(
        {
            "cellar_item_id": ObjectId(case["cellar_item_id"]),
            "event_type": CellarEventType.DRUNK.value,
        }
    )
    assert event is not None
    assert event.quantity == 2
    assert event.wine_id == ObjectId(wine["id"])
    assert event.owner_id is not None
    assert event.removal_reason is not None and event.removal_reason.value == "DRINK"
    assert event.tasting_notes == "Lovely with lamb."
    assert event.case_size_at_event == 6
    assert event.provenance_at_event == "Vintners"
    assert event.item_type == "case"


@pytest.mark.asyncio
async def test_sold_checkout_populates_sale_price_usd_and_reason(client: AsyncClient) -> None:
    """A SELL debit maps to event_type=SOLD and populates both price fields."""
    name = f"Sale {uuid.uuid4().hex[:6]}"
    await _record_cases(client, name=name, case_size=6, provenance="Majestic")
    wine = await _get_wine(client, name)
    case = wine["inventory"]["cases"][0]

    resp = await client.post(
        f"/api/wines/{wine['id']}/checkout",
        data={
            "quantity": "3",
            "cellar_item_id": case["cellar_item_id"],
            "removal_reason": "SELL",
            "sale_price_usd": "150.00",
        },
    )
    assert resp.status_code == 200

    event = await CellarEvent.find_one(
        {
            "cellar_item_id": ObjectId(case["cellar_item_id"]),
            "event_type": CellarEventType.SOLD.value,
        }
    )
    assert event is not None
    assert event.removal_reason is not None and event.removal_reason.value == "SELL"
    # Both names populated so readers on either field keep working.
    assert event.sale_price == 150.00
    assert event.sale_price_usd == 150.00


@pytest.mark.asyncio
async def test_checkout_still_writes_one_transaction_and_one_event_per_source(
    client: AsyncClient
) -> None:
    """Dual-write contract: one Transaction + one CellarEvent when the debit
    hits exactly one physical source. Phase 4d will flip the UI to read
    CellarEvent; until then the two must be parallel."""
    name = f"Parallel {uuid.uuid4().hex[:6]}"
    await _record_loose(client, name=name, quantity=4)
    wine = await _get_wine(client, name)

    before_txs = await Transaction.find(
        {"wine_id": ObjectId(wine["id"]), "transaction_type": "REMOVED"}
    ).to_list()
    before_events = await CellarEvent.find(
        {"wine_id": ObjectId(wine["id"]), "event_type": CellarEventType.DRUNK.value}
    ).to_list()

    resp = await client.post(
        f"/api/wines/{wine['id']}/checkout",
        data={"quantity": "2", "removal_reason": "DRINK"},
    )
    assert resp.status_code == 200

    after_txs = await Transaction.find(
        {"wine_id": ObjectId(wine["id"]), "transaction_type": "REMOVED"}
    ).to_list()
    after_events = await CellarEvent.find(
        {"wine_id": ObjectId(wine["id"]), "event_type": CellarEventType.DRUNK.value}
    ).to_list()

    assert len(after_txs) == len(before_txs) + 1
    assert len(after_events) == len(before_events) + 1
