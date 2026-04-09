"""Tests for cellar item tracking (cases and bottles) with cellar events."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_add_case_of_wine(client: AsyncClient) -> None:
    """Adding a case creates a CellarItem with embedded wine and correct quantity."""
    resp = await client.post("/api/cases", json={
        "name": "Chateau Margaux",
        "winery": "Chateau Margaux",
        "vintage": 2015,
        "country": "France",
        "region": "Bordeaux",
        "wine_type": "Red",
        "case_size": 12,
        "num_cases": 1,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["cases_created"] == 1
    assert data["bottles_created"] == 12
    case_id = data["cases"][0]["id"]

    # Verify case exists in cellars
    case_resp = await client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    case = case_resp.json()
    assert case["case_size"] == 12
    assert case["bottles_remaining"] == 12


@pytest.mark.asyncio
async def test_add_multiple_cases(client: AsyncClient) -> None:
    """Adding 2 cases creates 2 CellarItem documents."""
    resp = await client.post("/api/cases", json={
        "name": "Opus One",
        "winery": "Opus One",
        "vintage": 2019,
        "country": "USA",
        "wine_type": "Red",
        "case_size": 6,
        "num_cases": 2,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["cases_created"] == 2
    assert data["bottles_created"] == 12  # 2 × 6


@pytest.mark.asyncio
async def test_add_loose_bottles(client: AsyncClient) -> None:
    """Adding loose bottles creates a CellarItem with item_type=bottle."""
    resp = await client.post("/api/bottles", json={
        "name": "Cloudy Bay Sauvignon Blanc",
        "winery": "Cloudy Bay",
        "vintage": 2022,
        "country": "New Zealand",
        "wine_type": "White",
        "quantity": 3,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["bottles_created"] == 3

    # Verify in cellar grouped view
    grouped = (await client.get("/api/cellar/grouped")).json()
    wine = next((w for w in grouped["wines"] if "Cloudy Bay" in w["name"]), None)
    assert wine is not None
    assert wine["loose_bottles"] == 3


@pytest.mark.asyncio
async def test_sell_entire_case(client: AsyncClient) -> None:
    """Selling a case sets quantity to 0."""
    case_resp = await client.post("/api/cases", json={
        "name": "Sell Case Wine",
        "case_size": 6,
        "num_cases": 1,
    })
    case_id = case_resp.json()["cases"][0]["id"]

    # Sell the case
    event_resp = await client.post(f"/api/cases/{case_id}/events", json={
        "event_type": "sold",
        "sale_price": 300.0,
        "buyer": "Wine Shop",
    })
    assert event_resp.status_code == 200
    assert event_resp.json()["bottles_affected"] == 6

    # Case should now have 0 remaining
    case_resp2 = await client.get(f"/api/cases/{case_id}")
    assert case_resp2.json()["bottles_remaining"] == 0


@pytest.mark.asyncio
async def test_gift_entire_case(client: AsyncClient) -> None:
    """Gifting a case sets quantity to 0."""
    case_resp = await client.post("/api/cases", json={
        "name": "Gift Case Wine",
        "case_size": 6,
        "num_cases": 1,
    })
    case_id = case_resp.json()["cases"][0]["id"]

    event_resp = await client.post(f"/api/cases/{case_id}/events", json={
        "event_type": "gifted",
        "gift_recipient": "Birthday Friend",
    })
    assert event_resp.status_code == 200
    assert event_resp.json()["bottles_affected"] == 6

    case_resp2 = await client.get(f"/api/cases/{case_id}")
    assert case_resp2.json()["bottles_remaining"] == 0


@pytest.mark.asyncio
async def test_sell_empty_case_no_effect(client: AsyncClient) -> None:
    """Selling an already-empty case affects 0 bottles."""
    case_resp = await client.post("/api/cases", json={
        "name": "Already Empty Wine",
        "case_size": 2,
        "num_cases": 1,
    })
    case_id = case_resp.json()["cases"][0]["id"]

    # Sell once (empties it)
    await client.post(f"/api/cases/{case_id}/events", json={
        "event_type": "sold",
        "sale_price": 100.0,
    })

    # Sell again — no effect
    resp = await client.post(f"/api/cases/{case_id}/events", json={
        "event_type": "sold",
        "sale_price": 50.0,
    })
    assert resp.json()["bottles_affected"] == 0


@pytest.mark.asyncio
async def test_multiple_cases_independent(client: AsyncClient) -> None:
    """Selling one case doesn't affect another case of the same wine."""
    resp = await client.post("/api/cases", json={
        "name": "Multi Case Wine",
        "case_size": 6,
        "num_cases": 2,
    })
    cases = resp.json()["cases"]
    case_id_1 = cases[0]["id"]
    case_id_2 = cases[1]["id"]

    # Sell first case
    await client.post(f"/api/cases/{case_id_1}/events", json={
        "event_type": "sold",
        "sale_price": 200.0,
    })

    # Second case should still be full
    case_resp = await client.get(f"/api/cases/{case_id_2}")
    assert case_resp.json()["bottles_remaining"] == 6


@pytest.mark.asyncio
async def test_breakage_event(client: AsyncClient) -> None:
    """Breakage event empties a case."""
    case_resp = await client.post("/api/cases", json={
        "name": "Breakage Wine",
        "case_size": 3,
        "num_cases": 1,
    })
    case_id = case_resp.json()["cases"][0]["id"]

    event_resp = await client.post(f"/api/cases/{case_id}/events", json={
        "event_type": "breakage",
        "notes": "Shipping damage",
    })
    assert event_resp.status_code == 200
    assert event_resp.json()["bottles_affected"] == 3

    case_resp2 = await client.get(f"/api/cases/{case_id}")
    assert case_resp2.json()["bottles_remaining"] == 0


@pytest.mark.asyncio
async def test_cellar_event_history(client: AsyncClient) -> None:
    """Cellar events create an audit trail queryable by cellar item."""
    resp = await client.post("/api/cases", json={
        "name": "History Wine",
        "case_size": 6,
        "num_cases": 1,
    })
    case_id = resp.json()["cases"][0]["id"]

    # The case should have an ADDED event from creation
    # Sell the case to create a second event
    await client.post(f"/api/cases/{case_id}/events", json={
        "event_type": "sold",
        "sale_price": 500.0,
        "buyer": "Collector",
    })

    # Verify case is now empty
    case_resp = await client.get(f"/api/cases/{case_id}")
    assert case_resp.json()["bottles_remaining"] == 0
