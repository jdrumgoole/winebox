"""Tests for case-aware checkout (Phase 3).

Before this phase the checkout endpoint blindly debited Wine.inventory,
which silently threw away the user's case-level bookkeeping whenever a
wine had mixed inventory. This suite pins the new contract:

- When the client passes `cellar_item_id`, only that row is debited
  (cases keep their provenance; loose bottles stay loose).
- When omitted, the server drains loose bottles first then the oldest
  case. Back-compat for clients that don't know about case picking.
- Insufficient source → 422 with a clear message.
- Bad id / cross-user id → 404 (uniform, no existence leak).
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from bson import ObjectId
from httpx import ASGITransport, AsyncClient


async def _record_cases(
    client: AsyncClient,
    *,
    name: str,
    case_size: int,
    num_cases: int = 1,
    provenance: str | None = None,
    purchase_price: float | None = None,
) -> dict:
    payload = {
        "name": name,
        "case_size": case_size,
        "num_cases": num_cases,
        "wine_type": "Red",
    }
    if provenance is not None:
        payload["provenance"] = provenance
    if purchase_price is not None:
        payload["purchase_price"] = purchase_price
    resp = await client.post("/api/cases", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _record_loose(client: AsyncClient, *, name: str, quantity: int) -> dict:
    resp = await client.post("/api/bottles", json={
        "name": name,
        "quantity": quantity,
        "wine_type": "Red",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _get_wine(client: AsyncClient, name: str) -> dict:
    resp = await client.get("/api/cellar")
    assert resp.status_code == 200
    return next(w for w in resp.json() if w["name"] == name)


@pytest.mark.asyncio
async def test_specific_case_debit_only_touches_that_case(client: AsyncClient) -> None:
    """Removing 2 from a named case decrements only that case, not loose or another case."""
    name = f"Specific {uuid.uuid4().hex[:6]}"
    await _record_cases(client, name=name, case_size=12, provenance="Berry Bros")
    await _record_cases(client, name=name, case_size=6, provenance="Lay & Wheeler")
    await _record_loose(client, name=name, quantity=3)

    wine = await _get_wine(client, name)
    inv = wine["inventory"]
    assert inv["quantity"] == 21
    berry = next(c for c in inv["cases"] if c["provenance"] == "Berry Bros")
    lay = next(c for c in inv["cases"] if c["provenance"] == "Lay & Wheeler")

    # Debit 2 from the Berry Bros case explicitly.
    resp = await client.post(
        f"/api/wines/{wine['id']}/checkout",
        data={
            "quantity": "2",
            "cellar_item_id": berry["cellar_item_id"],
            "removal_reason": "DRINK",
        },
    )
    assert resp.status_code == 200, resp.text

    # Aggregate dropped by 2; only the Berry Bros case lost 2 bottles.
    wine_after = await _get_wine(client, name)
    inv_after = wine_after["inventory"]
    assert inv_after["quantity"] == 19
    berry_after = next(c for c in inv_after["cases"] if c["provenance"] == "Berry Bros")
    lay_after = next(c for c in inv_after["cases"] if c["provenance"] == "Lay & Wheeler")
    assert berry_after["bottles_remaining"] == 10
    assert lay_after["bottles_remaining"] == 6  # untouched
    assert inv_after["loose_bottles"] == 3       # untouched


@pytest.mark.asyncio
async def test_specific_case_over_quantity_returns_422(client: AsyncClient) -> None:
    """Requesting more than the chosen case has → 422, source left alone."""
    name = f"Overask {uuid.uuid4().hex[:6]}"
    await _record_cases(client, name=name, case_size=6, provenance="Vintners")

    wine = await _get_wine(client, name)
    case = wine["inventory"]["cases"][0]

    resp = await client.post(
        f"/api/wines/{wine['id']}/checkout",
        data={"quantity": "7", "cellar_item_id": case["cellar_item_id"]},
    )
    assert resp.status_code == 422
    assert "6" in resp.json()["detail"]
    assert "7" in resp.json()["detail"]

    # Source untouched.
    wine_after = await _get_wine(client, name)
    assert wine_after["inventory"]["quantity"] == 6
    assert wine_after["inventory"]["cases"][0]["bottles_remaining"] == 6


@pytest.mark.asyncio
async def test_specific_case_malformed_id_returns_404(client: AsyncClient) -> None:
    """A garbled cellar_item_id should 404, not 500."""
    name = f"Malformed {uuid.uuid4().hex[:6]}"
    await _record_cases(client, name=name, case_size=6)
    wine = await _get_wine(client, name)

    resp = await client.post(
        f"/api/wines/{wine['id']}/checkout",
        data={"quantity": "1", "cellar_item_id": "not-a-valid-objectid"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_specific_case_wrong_wine_returns_404(client: AsyncClient) -> None:
    """A cellar_item_id for a different wine must 404 (uniform 'not found').

    Pins the defence against using the checkout endpoint to enumerate
    another wine's or another user's cellar-item ids.
    """
    name_a = f"OtherA {uuid.uuid4().hex[:6]}"
    name_b = f"OtherB {uuid.uuid4().hex[:6]}"
    await _record_cases(client, name=name_a, case_size=6)
    await _record_cases(client, name=name_b, case_size=6)

    wine_a = await _get_wine(client, name_a)
    wine_b = await _get_wine(client, name_b)
    b_case = wine_b["inventory"]["cases"][0]

    # Try to debit B's case via A's wine endpoint.
    resp = await client.post(
        f"/api/wines/{wine_a['id']}/checkout",
        data={"quantity": "1", "cellar_item_id": b_case["cellar_item_id"]},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_fallback_debits_loose_before_cases(client: AsyncClient) -> None:
    """No `cellar_item_id` + mixed inventory → loose first, case untouched."""
    name = f"Fallback {uuid.uuid4().hex[:6]}"
    await _record_cases(client, name=name, case_size=12, provenance="Preserve Me")
    await _record_loose(client, name=name, quantity=3)

    wine = await _get_wine(client, name)

    resp = await client.post(
        f"/api/wines/{wine['id']}/checkout",
        data={"quantity": "2"},  # no cellar_item_id
    )
    assert resp.status_code == 200

    wine_after = await _get_wine(client, name)
    inv = wine_after["inventory"]
    assert inv["quantity"] == 13
    assert inv["loose_bottles"] == 1          # 3 loose - 2 = 1
    assert inv["cases"][0]["bottles_remaining"] == 12  # case preserved


@pytest.mark.asyncio
async def test_fallback_spills_into_case_when_loose_runs_out(client: AsyncClient) -> None:
    """Fallback that exceeds loose-bottle supply drains into the case.

    Ordering contract: loose first (2 here), then the oldest case.
    """
    name = f"Spill {uuid.uuid4().hex[:6]}"
    await _record_cases(client, name=name, case_size=12, provenance="Cellar Co")
    await _record_loose(client, name=name, quantity=2)

    wine = await _get_wine(client, name)

    resp = await client.post(
        f"/api/wines/{wine['id']}/checkout",
        data={"quantity": "5"},  # 2 loose + 3 from the case
    )
    assert resp.status_code == 200

    wine_after = await _get_wine(client, name)
    inv = wine_after["inventory"]
    assert inv["quantity"] == 9
    assert inv["loose_bottles"] == 0
    assert inv["cases"][0]["bottles_remaining"] == 9  # 12 - 3


@pytest.mark.asyncio
async def test_cross_user_cellar_item_returns_404(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """User B trying to debit User A's case via B's own wine → 404."""
    from tests.conftest import get_test_app, _CACHED_TEST_PASSWORD_HASH
    from tests._regstack_helpers import create_access_token
    from winebox.models import User

    # User A creates a case.
    name_a = f"UserA {uuid.uuid4().hex[:6]}"
    await _record_cases(client, name=name_a, case_size=6)
    wine_a = await _get_wine(client, name_a)
    a_case_id = wine_a["inventory"]["cases"][0]["cellar_item_id"]

    # Spin up a second user and give them their own wine.
    other_email = f"crossuser-{uuid.uuid4().hex[:8]}@example.com"
    await User(
        email=other_email, hashed_password=_CACHED_TEST_PASSWORD_HASH,
        is_active=True, is_verified=True, is_superuser=False,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    ).insert()
    token = await create_access_token(data={"sub": other_email})
    async with AsyncClient(
        transport=ASGITransport(app=get_test_app()),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client_b:
        name_b = f"UserB {uuid.uuid4().hex[:6]}"
        await _record_cases(client_b, name=name_b, case_size=6)
        wine_b = await _get_wine(client_b, name_b)

        resp = await client_b.post(
            f"/api/wines/{wine_b['id']}/checkout",
            data={"quantity": "1", "cellar_item_id": a_case_id},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_wine_with_no_cellar_items_returns_422(
    client: AsyncClient
) -> None:
    """A Wine without any CellarItem rows must fail the checkout cleanly.

    The legacy production shape (Wine.inventory without a per-row
    cellars entry) was retired by the `upgrade_legacy_cellar_items`
    migration, and the previous service-level fallback that synthesised
    a `legacy`-typed event was removed. A wine that reaches this state
    post-migration is a bug, not a supported path — surface a 422 so
    it's visible instead of silently diverging Wine.inventory from the
    event log.
    """
    from datetime import datetime, timezone
    from bson import ObjectId as _OID

    from winebox.models import Wine
    from winebox.models.wine import WineCollection
    from winebox.models.wine import InventoryInfo as WineInventoryInfo

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    owner_id = _OID(me.json()["id"])

    wine = Wine(
        owner_id=owner_id,
        collection=WineCollection.CELLAR,
        name=f"NoCellarItems {uuid.uuid4().hex[:6]}",
        inventory=WineInventoryInfo(
            quantity=5, case_size=None,
            updated_at=datetime.now(timezone.utc),
        ),
    )
    await wine.insert()

    resp = await client.post(
        f"/api/wines/{wine.id}/checkout",
        data={"quantity": "2", "removal_reason": "DRINK"},
    )
    assert resp.status_code == 422
    assert "Available: 0" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_specific_case_records_cellar_event_only(
    client: AsyncClient
) -> None:
    """A specific-case debit writes one CellarEvent (with the case
    snapshot + tasting notes) and zero new Transaction rows. Phase 4e
    contract: the legacy `transactions` collection is read-only.
    """
    from winebox.models import Transaction
    from winebox.models.cellar_event import CellarEvent

    name = f"Events {uuid.uuid4().hex[:6]}"
    await _record_cases(client, name=name, case_size=6, provenance="EventCo")
    wine = await _get_wine(client, name)
    case = wine["inventory"]["cases"][0]

    txs_before = await Transaction.find(
        {"wine_id": ObjectId(wine["id"]), "transaction_type": "REMOVED"}
    ).to_list()

    resp = await client.post(
        f"/api/wines/{wine['id']}/checkout",
        data={
            "quantity": "2",
            "cellar_item_id": case["cellar_item_id"],
            "removal_reason": "DRINK",
            "tasting_notes": "Decanted 30 min, plum and tobacco.",
        },
    )
    assert resp.status_code == 200

    txs_after = await Transaction.find(
        {"wine_id": ObjectId(wine["id"]), "transaction_type": "REMOVED"}
    ).to_list()
    # Phase 4e: no new Transaction row.
    assert len(txs_after) == len(txs_before)

    events = await CellarEvent.find(
        {"cellar_item_id": ObjectId(case["cellar_item_id"]), "event_type": "drunk"}
    ).to_list()
    matched = [e for e in events if e.quantity == 2]
    assert matched, "expected a DRUNK event for this case with quantity=2"
    e = matched[0]
    assert e.tasting_notes == "Decanted 30 min, plum and tobacco."
    assert e.case_size_at_event == 6
    assert e.provenance_at_event == "EventCo"
