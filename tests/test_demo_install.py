"""Tests for demo/sample wine installation and removal.

Seeds synthetic X-Wines reference data so the demo installer has wines
to select from. Uses the local test database.
"""

import asyncio

import pytest
import pytest_asyncio
from httpx import AsyncClient

from winebox.database import get_database


@pytest_asyncio.fixture(autouse=True)
async def seed_xwines(init_test_db):
    """Seed synthetic xwines reference data.

    ``xwines_wines`` is shared across all xdist workers (it's reference
    data, not user data). Previously this fixture also ran a teardown
    that deleted every doc with ``xwines_id >= 900000`` — fine in
    isolation, racy under xdist because one worker's teardown would
    wipe another worker's seed mid-test. We now write idempotently on
    setup and leave the rows in place; the shared test database is
    dropped before the next run.
    """
    db = get_database()
    col = db["xwines_wines"]

    countries = ["France", "Italy", "Spain", "Australia", "USA",
                 "Portugal", "Germany", "New Zealand", "Argentina", "Chile"]
    types = ["Red", "White", "Rosé", "Sparkling"]
    grapes = ["Cabernet Sauvignon", "Merlot", "Pinot Noir", "Chardonnay",
              "Sauvignon Blanc", "Riesling", "Tempranillo", "Nebbiolo"]

    docs = [
        {
            "xwines_id": 900000 + i,
            "name": f"Test {grapes[i % len(grapes)]} {2015 + (i % 8)}",
            "wine_type": types[i % len(types)],
            "country_code": countries[i % len(countries)][:2].upper(),
            "country": countries[i % len(countries)],
            "region_name": f"Region {i % 15}",
            "winery_name": f"Domaine {i % 30}",
            "avg_rating": 3.0 + (i % 20) / 10,
            "rating_count": 50 + i * 3,
            "abv": 11.5 + (i % 6),
        }
        for i in range(600)
    ]
    try:
        await col.insert_many(docs, ordered=False)
    except Exception:
        pass  # Ignore duplicates from parallel workers

    yield


async def _wait_for_install(client: AsyncClient, timeout: int = 30) -> dict:
    """Poll demo status until install completes."""
    for _ in range(timeout * 2):
        resp = await client.get("/api/demo/status")
        status = resp.json()
        if status["installed"] and status["wine_count"] > 0:
            return status
        await asyncio.sleep(0.5)
    raise TimeoutError("Demo install did not complete")


async def _ensure_no_demo(client: AsyncClient) -> None:
    """Remove demo data if present."""
    status = (await client.get("/api/demo/status")).json()
    if status["installed"]:
        await client.delete("/api/demo/remove")


@pytest.mark.asyncio
async def test_install_demo_wines(client: AsyncClient) -> None:
    """Test that demo wines can be installed and appear in cellar."""
    await _ensure_no_demo(client)

    resp = await client.post("/api/demo/install")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0

    status = await _wait_for_install(client)
    assert status["wine_count"] > 0
    assert status["bottle_count"] > 0

    wines_resp = await client.get("/api/wines")
    wines = wines_resp.json()
    demo_wines = [w for w in wines if w.get("custom_fields", {}).get("_demo") == "true"]
    assert len(demo_wines) > 0

    await client.delete("/api/demo/remove")


@pytest.mark.asyncio
async def test_remove_demo_preserves_real_wines(client: AsyncClient) -> None:
    """Test that removing demo wines doesn't affect real wines."""
    await _ensure_no_demo(client)

    import csv
    import io

    csv_data = io.StringIO()
    writer = csv.writer(csv_data)
    writer.writerow(["Name", "Country"])
    writer.writerow(["My Permanent Wine", "France"])
    csv_bytes = csv_data.getvalue().encode()

    files = {"file": ("wines.csv", io.BytesIO(csv_bytes), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    batch_id = upload_resp.json()["batch_id"]
    await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": {"Name": "name", "Country": "country"}},
    )
    await client.post(f"/api/import/{batch_id}/process", json={})

    install_resp = await client.post("/api/demo/install")
    assert install_resp.status_code == 200, f"Install failed: {install_resp.json()}"
    await _wait_for_install(client)

    remove_resp = await client.delete("/api/demo/remove")
    assert remove_resp.status_code == 200
    assert remove_resp.json()["wines_removed"] > 0

    wines_resp = await client.get("/api/wines")
    names = {w["name"] for w in wines_resp.json()}
    assert "My Permanent Wine" in names


@pytest.mark.asyncio
async def test_install_twice_blocked(client: AsyncClient) -> None:
    """Test that installing demo wines twice returns 409."""
    await _ensure_no_demo(client)

    resp1 = await client.post("/api/demo/install")
    assert resp1.status_code == 200
    await _wait_for_install(client)

    resp2 = await client.post("/api/demo/install")
    assert resp2.status_code == 409

    await client.delete("/api/demo/remove")


@pytest.mark.asyncio
async def test_demo_creates_transactions(client: AsyncClient) -> None:
    """Test that demo wines create ADDED transactions."""
    await _ensure_no_demo(client)

    await client.post("/api/demo/install")
    await _wait_for_install(client)

    txn_resp = await client.get("/api/transactions?limit=100")
    transactions = txn_resp.json()
    assert len(transactions) > 0
    assert any(t["transaction_type"] == "ADDED" for t in transactions)

    await client.delete("/api/demo/remove")
