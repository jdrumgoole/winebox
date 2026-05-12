"""Tests for the cellar-inventory breakdown service.

Pins the contract that `WineWithInventory.inventory` carries a full
case-vs-loose decomposition on every surface — cellar list, search,
wine list, wine detail, wine update — so the UI never has to fall
back to just `quantity`.

Met wines go through the same schema but never get the breakdown
service called on them (they have no cellar rows), so they rely on
the schema defaults `cases=[]` and `loose_bottles=0`.
"""

import io
import uuid

import pytest
from httpx import AsyncClient


async def _add_case(client: AsyncClient, *, name: str, case_size: int, num_cases: int = 1,
                    provenance: str | None = None, purchase_price: float | None = None) -> dict:
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


async def _add_loose(client: AsyncClient, *, name: str, quantity: int) -> dict:
    resp = await client.post("/api/bottles", json={
        "name": name,
        "quantity": quantity,
        "wine_type": "Red",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


def _inv(wine: dict) -> dict:
    inv = wine.get("inventory")
    assert inv is not None, f"wine {wine.get('name')} missing inventory: {wine}"
    return inv


@pytest.mark.asyncio
async def test_cellar_list_carries_case_breakdown(client: AsyncClient) -> None:
    """A wine with a case-of-12 + 3 loose bottles reports both."""
    name = f"Mixed Wine {uuid.uuid4().hex[:6]}"
    await _add_case(client, name=name, case_size=12, provenance="Berry Bros", purchase_price=420.0)
    await _add_loose(client, name=name, quantity=3)

    resp = await client.get("/api/cellar")
    assert resp.status_code == 200
    wines = [w for w in resp.json() if w["name"] == name]
    assert len(wines) == 1, f"expected exactly one wine named {name}"
    inv = _inv(wines[0])

    assert inv["quantity"] == 15
    assert inv["loose_bottles"] == 3
    assert len(inv["cases"]) == 1
    case = inv["cases"][0]
    assert case["case_size"] == 12
    assert case["bottles_remaining"] == 12
    assert case["provenance"] == "Berry Bros"
    assert case["purchase_price"] == 420.0
    assert case["cellar_item_id"]
    # Legacy `case_size` scalar mirrors the first case.
    assert inv["case_size"] == 12


@pytest.mark.asyncio
async def test_two_cases_same_wine_appear_separately(client: AsyncClient) -> None:
    """Two cases of the same wine with different provenance stay distinct."""
    name = f"Two Cases {uuid.uuid4().hex[:6]}"
    await _add_case(client, name=name, case_size=12, provenance="Berry Bros")
    await _add_case(client, name=name, case_size=6, provenance="Lay & Wheeler")

    resp = await client.get("/api/cellar")
    assert resp.status_code == 200
    wine = next(w for w in resp.json() if w["name"] == name)
    inv = _inv(wine)

    assert inv["quantity"] == 18
    assert inv["loose_bottles"] == 0
    assert len(inv["cases"]) == 2
    provs = sorted(c["provenance"] for c in inv["cases"])
    assert provs == ["Berry Bros", "Lay & Wheeler"]


@pytest.mark.asyncio
async def test_search_results_carry_breakdown(client: AsyncClient) -> None:
    """The Search endpoint must include the same breakdown as the cellar list."""
    name = f"Search Case {uuid.uuid4().hex[:6]}"
    await _add_case(client, name=name, case_size=12, provenance="Majestic")

    resp = await client.get(f"/api/search?q={name}")
    assert resp.status_code == 200
    hits = [w for w in resp.json() if w["name"] == name]
    assert hits, f"search didn't return {name}"
    inv = _inv(hits[0])
    assert inv["quantity"] == 12
    assert inv["loose_bottles"] == 0
    assert len(inv["cases"]) == 1
    assert inv["cases"][0]["provenance"] == "Majestic"


@pytest.mark.asyncio
async def test_wines_list_endpoint_carries_breakdown(client: AsyncClient) -> None:
    """GET /api/wines (the generic list) also carries the breakdown."""
    name = f"Wines List {uuid.uuid4().hex[:6]}"
    await _add_loose(client, name=name, quantity=2)

    resp = await client.get("/api/wines")
    assert resp.status_code == 200
    wine = next(w for w in resp.json() if w["name"] == name)
    inv = _inv(wine)
    assert inv["quantity"] == 2
    assert inv["loose_bottles"] == 2
    assert inv["cases"] == []


@pytest.mark.asyncio
async def test_wine_detail_carries_breakdown(client: AsyncClient) -> None:
    """GET /api/wines/{id} must also carry the breakdown (same contract)."""
    name = f"Wine Detail {uuid.uuid4().hex[:6]}"
    await _add_case(client, name=name, case_size=6, provenance="Vintners")

    # Find the wine id via the cellar list.
    list_resp = await client.get("/api/cellar")
    wine_id = next(w["id"] for w in list_resp.json() if w["name"] == name)

    resp = await client.get(f"/api/wines/{wine_id}")
    assert resp.status_code == 200
    inv = _inv(resp.json())
    assert inv["quantity"] == 6
    assert len(inv["cases"]) == 1
    assert inv["cases"][0]["case_size"] == 6
    assert inv["cases"][0]["provenance"] == "Vintners"


@pytest.mark.asyncio
async def test_met_wine_returns_empty_breakdown_shape(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """Met wines have no cellar rows, so `cases=[]` and `loose_bottles=0`.

    The contract is that *every* `WineWithInventory` response has those
    fields — the frontend should never need to check `if inventory.cases`.
    """
    files = {"front_label": ("front.png", io.BytesIO(sample_image_bytes), "image/png")}
    name = f"Met Only {uuid.uuid4().hex[:6]}"
    resp = await client.post("/api/wines/met", data={"name": name}, files=files)
    assert resp.status_code == 201

    met = await client.get("/api/met")
    assert met.status_code == 200
    wine = next((w for w in met.json() if w["name"] == name), None)
    assert wine is not None
    inv = _inv(wine)
    assert inv["quantity"] == 0
    assert inv["loose_bottles"] == 0
    assert inv["cases"] == []


@pytest.mark.asyncio
async def test_breakdown_scoped_by_owner(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """User B must never see User A's cases in B's breakdown.

    Defence in depth: `attach_breakdowns` filters by owner_id before it
    queries CellarItem, and CellarItem.find is owner-scoped in the
    service. This pins that contract.
    """
    name = f"Shared Name {uuid.uuid4().hex[:6]}"
    await _add_case(client, name=name, case_size=12, provenance="Owner A only")

    from datetime import datetime, timezone
    from httpx import ASGITransport
    from tests.conftest import get_test_app, _CACHED_TEST_PASSWORD_HASH
    from tests._regstack_helpers import create_access_token
    from winebox.models import User

    other_email = f"b-{uuid.uuid4().hex[:8]}@example.com"
    await User(
        email=other_email, hashed_password=_CACHED_TEST_PASSWORD_HASH,
        is_active=True, is_verified=True, is_superuser=False,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    ).insert()
    other_token = await create_access_token(data={"sub": other_email})
    async with AsyncClient(
        transport=ASGITransport(app=get_test_app()),
        base_url="http://test",
        headers={"Authorization": f"Bearer {other_token}"},
    ) as client_b:
        resp = await client_b.get(f"/api/search?q={name}")
        assert resp.status_code == 200
        assert resp.json() == []  # B sees nothing; no provenance leak
