"""Tests for case and bottle tracking with event sourcing."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_add_case_of_wine(client: AsyncClient) -> None:
    """Adding a case creates a Case record, N Bottle records, and N 'added' events."""
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

    # Verify case exists
    case_resp = await client.get(f"/api/cases/{case_id}")
    assert case_resp.status_code == 200
    case = case_resp.json()
    assert case["case_size"] == 12
    assert case["bottles_remaining"] == 12


@pytest.mark.asyncio
async def test_add_multiple_cases(client: AsyncClient) -> None:
    """Adding 2 cases creates 2 Case records and 24 Bottle records."""
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
    """Adding loose bottles creates Bottle records with no case_id."""
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

    # Verify bottles have no case_id
    bottles_resp = await client.get(f"/api/bottles?wine_id={data['wine_id']}")
    assert bottles_resp.status_code == 200
    bottles = bottles_resp.json()["bottles"]
    assert len(bottles) == 3
    assert all(b["case_id"] is None for b in bottles)


@pytest.mark.asyncio
async def test_bottle_is_immutable(client: AsyncClient) -> None:
    """Bottle records carry denormalised wine identity."""
    resp = await client.post("/api/bottles", json={
        "name": "Test Wine",
        "winery": "Test Winery",
        "vintage": 2020,
        "country": "France",
        "wine_type": "Red",
        "quantity": 1,
    })
    data = resp.json()
    bottles_resp = await client.get(f"/api/bottles?wine_id={data['wine_id']}")
    bottle = bottles_resp.json()["bottles"][0]

    assert bottle["name"] == "Test Wine"
    assert bottle["winery"] == "Test Winery"
    assert bottle["vintage"] == 2020
    assert bottle["country"] == "France"
    assert bottle["wine_type"] == "Red"


@pytest.mark.asyncio
async def test_remove_bottle_from_case(client: AsyncClient) -> None:
    """Removing a bottle creates a WineEvent and decrements case count."""
    # Create a case
    case_resp = await client.post("/api/cases", json={
        "name": "Test Case Wine",
        "case_size": 6,
        "num_cases": 1,
    })
    case_id = case_resp.json()["cases"][0]["id"]

    # Get a bottle from the case
    bottles_resp = await client.get(f"/api/cases/{case_id}")
    bottle_id = bottles_resp.json()["bottles"][0]["id"]

    # Remove it (drunk)
    event_resp = await client.post(f"/api/bottles/{bottle_id}/events", json={
        "event_type": "drunk",
        "tasting_notes": "Excellent with dinner",
    })
    assert event_resp.status_code == 200

    # Verify case now has 5 remaining
    case_resp2 = await client.get(f"/api/cases/{case_id}")
    assert case_resp2.json()["bottles_remaining"] == 5


@pytest.mark.asyncio
async def test_empty_case_retained(client: AsyncClient) -> None:
    """When all bottles leave a case, the case record is preserved."""
    case_resp = await client.post("/api/cases", json={
        "name": "Small Case Wine",
        "case_size": 2,
        "num_cases": 1,
    })
    case_id = case_resp.json()["cases"][0]["id"]
    bottles = (await client.get(f"/api/cases/{case_id}")).json()["bottles"]

    # Remove both bottles
    for bottle in bottles:
        await client.post(f"/api/bottles/{bottle['id']}/events", json={
            "event_type": "gifted",
            "gift_recipient": "Friend",
        })

    # Case still exists but is empty
    case_resp2 = await client.get(f"/api/cases/{case_id}")
    assert case_resp2.status_code == 200
    assert case_resp2.json()["bottles_remaining"] == 0
    assert case_resp2.json()["case_size"] == 2


@pytest.mark.asyncio
async def test_bottle_event_history(client: AsyncClient) -> None:
    """Bottle events create an audit trail."""
    resp = await client.post("/api/bottles", json={
        "name": "History Wine",
        "quantity": 1,
    })
    wine_id = resp.json()["wine_id"]
    bottles = (await client.get(f"/api/bottles?wine_id={wine_id}")).json()["bottles"]
    bottle_id = bottles[0]["id"]

    # Should have 'added' event
    events_resp = await client.get(f"/api/bottles/{bottle_id}/events")
    events = events_resp.json()["events"]
    assert len(events) == 1
    assert events[0]["event_type"] == "added"

    # Sell the bottle
    await client.post(f"/api/bottles/{bottle_id}/events", json={
        "event_type": "sold",
        "sale_price": 50.0,
        "buyer": "Wine Collector",
    })

    # Now has 2 events
    events_resp2 = await client.get(f"/api/bottles/{bottle_id}/events")
    events2 = events_resp2.json()["events"]
    assert len(events2) == 2
    assert events2[0]["event_type"] == "sold"  # Most recent first
    assert events2[0]["sale_price"] == 50.0


@pytest.mark.asyncio
async def test_vintage_must_be_4_digits(client: AsyncClient) -> None:
    """Vintage must be a 4-digit year (1000-2100)."""
    # Too short
    resp = await client.post("/api/bottles", json={
        "name": "Bad Vintage Wine",
        "vintage": 99,
        "quantity": 1,
    })
    assert resp.status_code == 422

    # Valid
    resp2 = await client.post("/api/bottles", json={
        "name": "Good Vintage Wine",
        "vintage": 2020,
        "quantity": 1,
    })
    assert resp2.status_code == 200


@pytest.mark.asyncio
async def test_breakage_event(client: AsyncClient) -> None:
    """Breakage event removes bottle from cellar with notes."""
    resp = await client.post("/api/bottles", json={
        "name": "Fragile Wine",
        "quantity": 1,
    })
    wine_id = resp.json()["wine_id"]
    bottles = (await client.get(f"/api/bottles?wine_id={wine_id}")).json()["bottles"]
    bottle_id = bottles[0]["id"]

    event_resp = await client.post(f"/api/bottles/{bottle_id}/events", json={
        "event_type": "breakage",
        "notes": "Dropped while moving to new rack",
    })
    assert event_resp.status_code == 200

    # Bottle's latest event should be breakage
    events = (await client.get(f"/api/bottles/{bottle_id}/events")).json()["events"]
    assert events[0]["event_type"] == "breakage"


# =========================================================================
# Case-level event tests
# =========================================================================


@pytest.mark.asyncio
async def test_sell_entire_case(client: AsyncClient) -> None:
    """Selling a case creates a case event and marks all bottles as sold."""
    case_resp = await client.post("/api/cases", json={
        "name": "Case Sale Wine",
        "winery": "Test Winery",
        "vintage": 2020,
        "case_size": 6,
        "num_cases": 1,
        "purchase_price": 120.0,
        "provenance": "Wine Merchant",
    })
    case_id = case_resp.json()["cases"][0]["id"]

    # Verify 6 bottles in cellar
    case_detail = (await client.get(f"/api/cases/{case_id}")).json()
    assert case_detail["bottles_remaining"] == 6

    # Sell the entire case
    event_resp = await client.post(f"/api/cases/{case_id}/events", json={
        "event_type": "sold",
        "sale_price": 180.0,
        "buyer": "Restaurant ABC",
        "notes": "Sold at 50% markup",
    })
    assert event_resp.status_code == 200
    result = event_resp.json()
    assert result["event_type"] == "sold"
    assert result["bottles_affected"] == 6

    # Case should now be empty
    case_detail2 = (await client.get(f"/api/cases/{case_id}")).json()
    assert case_detail2["bottles_remaining"] == 0
    assert case_detail2["case_size"] == 6  # Case still exists


@pytest.mark.asyncio
async def test_gift_entire_case(client: AsyncClient) -> None:
    """Gifting a case marks all bottles as gifted with recipient."""
    case_resp = await client.post("/api/cases", json={
        "name": "Gift Case Wine",
        "case_size": 3,
        "num_cases": 1,
    })
    case_id = case_resp.json()["cases"][0]["id"]

    event_resp = await client.post(f"/api/cases/{case_id}/events", json={
        "event_type": "gifted",
        "gift_recipient": "Birthday Friend",
    })
    assert event_resp.status_code == 200
    assert event_resp.json()["bottles_affected"] == 3

    # All bottles should be gone
    case_detail = (await client.get(f"/api/cases/{case_id}")).json()
    assert case_detail["bottles_remaining"] == 0


@pytest.mark.asyncio
async def test_case_breakage(client: AsyncClient) -> None:
    """Case dropped/destroyed marks all bottles as breakage."""
    case_resp = await client.post("/api/cases", json={
        "name": "Fragile Case Wine",
        "case_size": 12,
        "num_cases": 1,
    })
    case_id = case_resp.json()["cases"][0]["id"]

    event_resp = await client.post(f"/api/cases/{case_id}/events", json={
        "event_type": "breakage",
        "notes": "Dropped during delivery",
    })
    assert event_resp.status_code == 200
    assert event_resp.json()["bottles_affected"] == 12

    case_detail = (await client.get(f"/api/cases/{case_id}")).json()
    assert case_detail["bottles_remaining"] == 0


@pytest.mark.asyncio
async def test_sell_partial_case(client: AsyncClient) -> None:
    """Sell a case after removing some bottles — only remaining bottles affected."""
    case_resp = await client.post("/api/cases", json={
        "name": "Partial Case Wine",
        "case_size": 6,
        "num_cases": 1,
    })
    case_id = case_resp.json()["cases"][0]["id"]

    # Drink 2 bottles individually
    case_detail = (await client.get(f"/api/cases/{case_id}")).json()
    for bottle in case_detail["bottles"][:2]:
        await client.post(f"/api/bottles/{bottle['id']}/events", json={
            "event_type": "drunk",
            "tasting_notes": "Nice",
        })

    # Verify 4 remaining
    case_detail2 = (await client.get(f"/api/cases/{case_id}")).json()
    assert case_detail2["bottles_remaining"] == 4

    # Sell the rest of the case
    event_resp = await client.post(f"/api/cases/{case_id}/events", json={
        "event_type": "sold",
        "sale_price": 80.0,
        "buyer": "Wine Shop",
    })
    assert event_resp.json()["bottles_affected"] == 4  # Only the 4 remaining

    # Case fully empty now
    case_detail3 = (await client.get(f"/api/cases/{case_id}")).json()
    assert case_detail3["bottles_remaining"] == 0


@pytest.mark.asyncio
async def test_case_with_provenance(client: AsyncClient) -> None:
    """Case stores purchase info and provenance."""
    case_resp = await client.post("/api/cases", json={
        "name": "Provenance Wine",
        "winery": "Chateau Test",
        "vintage": 2018,
        "case_size": 12,
        "num_cases": 1,
        "purchase_price": 240.0,
        "provenance": "Berry Bros & Rudd",
    })
    case_id = case_resp.json()["cases"][0]["id"]

    case_detail = (await client.get(f"/api/cases/{case_id}")).json()
    assert case_detail["case_size"] == 12
    assert case_detail["purchase_price"] == 240.0
    assert case_detail["provenance"] == "Berry Bros & Rudd"


@pytest.mark.asyncio
async def test_sell_empty_case_no_effect(client: AsyncClient) -> None:
    """Selling an already-empty case affects 0 bottles."""
    case_resp = await client.post("/api/cases", json={
        "name": "Empty Case Wine",
        "case_size": 2,
        "num_cases": 1,
    })
    case_id = case_resp.json()["cases"][0]["id"]

    # Gift all bottles first
    await client.post(f"/api/cases/{case_id}/events", json={
        "event_type": "gifted",
        "gift_recipient": "Someone",
    })

    # Now try to sell the empty case
    event_resp = await client.post(f"/api/cases/{case_id}/events", json={
        "event_type": "sold",
        "sale_price": 0,
    })
    assert event_resp.status_code == 200
    assert event_resp.json()["bottles_affected"] == 0


@pytest.mark.asyncio
async def test_multiple_cases_independent(client: AsyncClient) -> None:
    """Two cases of the same wine are tracked independently."""
    case_resp = await client.post("/api/cases", json={
        "name": "Multi Case Wine",
        "case_size": 6,
        "num_cases": 2,
    })
    cases = case_resp.json()["cases"]
    case1_id = cases[0]["id"]
    case2_id = cases[1]["id"]

    # Sell case 1
    await client.post(f"/api/cases/{case1_id}/events", json={
        "event_type": "sold",
        "sale_price": 100.0,
    })

    # Case 1 empty, case 2 full
    c1 = (await client.get(f"/api/cases/{case1_id}")).json()
    c2 = (await client.get(f"/api/cases/{case2_id}")).json()
    assert c1["bottles_remaining"] == 0
    assert c2["bottles_remaining"] == 6
