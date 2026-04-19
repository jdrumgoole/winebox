"""Phase 5 — exports carry case-level detail.

Pins the new contract:

- CSV/XLSX (default `cases_as_rows=True`) emits one row per case plus a
  loose-remainder row, each carrying the new `item_type`, `case_size`,
  `bottles_in_case_remaining`, `provenance`, `purchase_price`,
  `purchase_date` columns.
- CSV with `cases_as_rows=False` keeps the legacy one-row-per-wine
  shape so existing importers keep round-tripping.
- JSON (and YAML) inject `inventory.cases` and `inventory.loose_bottles`
  alongside the aggregate `quantity`.
- Transaction CSV/XLSX gains `item_type` + `case_size_at_event` +
  `provenance_at_event`; case-sourced removals populate them, loose or
  legacy removals leave them empty.
"""

from __future__ import annotations

import csv
import io
import json
import uuid

import pytest
from httpx import AsyncClient


async def _add_case(
    client: AsyncClient, *, name: str, case_size: int, num_cases: int = 1,
    provenance: str | None = None, purchase_price: float | None = None,
) -> None:
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


async def _add_loose(client: AsyncClient, *, name: str, quantity: int) -> None:
    resp = await client.post("/api/bottles", json={
        "name": name, "quantity": quantity, "wine_type": "Red",
    })
    assert resp.status_code == 200, resp.text


def _csv_rows(body: bytes) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    headers = reader.fieldnames or []
    return headers, list(reader)


@pytest.mark.asyncio
async def test_csv_export_default_emits_per_case_rows(client: AsyncClient) -> None:
    """Default `cases_as_rows=True` spills mixed inventory across rows."""
    name = f"Flat {uuid.uuid4().hex[:6]}"
    await _add_case(
        client, name=name, case_size=12, provenance="Berry Bros",
        purchase_price=420.0,
    )
    await _add_loose(client, name=name, quantity=3)

    resp = await client.get("/api/export/wines?format=csv")
    assert resp.status_code == 200
    headers, rows = _csv_rows(resp.content)

    # New columns added; old columns still present.
    for col in ("item_type", "case_size", "bottles_in_case_remaining",
                "provenance", "purchase_price", "purchase_date"):
        assert col in headers, f"missing column {col} in {headers}"

    wine_rows = [r for r in rows if r["name"] == name]
    assert len(wine_rows) == 2, f"expected 2 rows for {name}, got {len(wine_rows)}: {wine_rows}"

    case_row = next(r for r in wine_rows if r["item_type"] == "case")
    loose_row = next(r for r in wine_rows if r["item_type"] == "bottle")

    assert case_row["case_size"] == "12"
    assert case_row["bottles_in_case_remaining"] == "12"
    assert case_row["provenance"] == "Berry Bros"
    assert case_row["purchase_price"] == "420.0"
    assert case_row["quantity"] == "12"  # row-level quantity is that row's contribution

    assert loose_row["case_size"] == ""
    assert loose_row["provenance"] == ""
    assert loose_row["quantity"] == "3"


@pytest.mark.asyncio
async def test_csv_export_opt_out_collapses_to_single_row(client: AsyncClient) -> None:
    """`cases_as_rows=False` keeps today's one-row-per-wine shape for back-compat importers."""
    name = f"Collapsed {uuid.uuid4().hex[:6]}"
    await _add_case(client, name=name, case_size=12, provenance="Majestic")
    await _add_loose(client, name=name, quantity=3)

    resp = await client.get("/api/export/wines?format=csv&cases_as_rows=false")
    assert resp.status_code == 200
    _, rows = _csv_rows(resp.content)
    wine_rows = [r for r in rows if r["name"] == name]
    assert len(wine_rows) == 1
    # Aggregate quantity, no case detail on the single row.
    assert wine_rows[0]["quantity"] == "15"
    assert wine_rows[0]["item_type"] == ""
    assert wine_rows[0]["case_size"] == ""


@pytest.mark.asyncio
async def test_json_export_includes_inventory_breakdown(client: AsyncClient) -> None:
    """Hierarchical JSON carries cases[] + loose_bottles alongside quantity."""
    name = f"JsonFlat {uuid.uuid4().hex[:6]}"
    await _add_case(client, name=name, case_size=6, provenance="Vintners")
    await _add_loose(client, name=name, quantity=2)

    resp = await client.get("/api/export/wines?format=json")
    assert resp.status_code == 200
    body = resp.json()
    wine = next(w for w in body["wines"] if w["name"] == name)
    inv = wine["inventory"]
    assert inv["quantity"] == 8
    assert inv["loose_bottles"] == 2
    assert isinstance(inv["cases"], list) and len(inv["cases"]) == 1
    c = inv["cases"][0]
    assert c["case_size"] == 6
    assert c["bottles_remaining"] == 6
    assert c["provenance"] == "Vintners"
    assert c["cellar_item_id"]


@pytest.mark.asyncio
async def test_transaction_export_carries_case_snapshot(client: AsyncClient) -> None:
    """Transaction CSV gains item_type + case_size_at_event + provenance_at_event.

    When a checkout comes from a named case, the export row reflects
    which case it was — even if the case is later fully consumed and
    deleted (the snapshot lives on the event, not on the live case).
    """
    name = f"TxCase {uuid.uuid4().hex[:6]}"
    await _add_case(client, name=name, case_size=6, provenance="Berry Bros")
    # Fetch the case id to target a specific source.
    cellar_resp = await client.get("/api/cellar")
    wine = next(w for w in cellar_resp.json() if w["name"] == name)
    case_id = wine["inventory"]["cases"][0]["cellar_item_id"]

    checkout = await client.post(
        f"/api/wines/{wine['id']}/checkout",
        data={"quantity": "1", "cellar_item_id": case_id, "removal_reason": "DRINK"},
    )
    assert checkout.status_code == 200

    resp = await client.get("/api/export/transactions?format=csv")
    assert resp.status_code == 200
    headers, rows = _csv_rows(resp.content)
    for col in ("item_type", "case_size_at_event", "provenance_at_event"):
        assert col in headers

    this_wine_rows = [r for r in rows if r["wine_name"] == name and r["transaction_type"] == "REMOVED"]
    assert this_wine_rows, f"no removed-transaction rows for {name}"
    removal = this_wine_rows[0]
    assert removal["item_type"] == "case"
    assert removal["case_size_at_event"] == "6"
    assert removal["provenance_at_event"] == "Berry Bros"


@pytest.mark.asyncio
async def test_loose_only_wine_exports_as_single_row(client: AsyncClient) -> None:
    """A wine with only loose bottles exports as one row (`item_type=bottle`)."""
    name = f"OnlyLoose {uuid.uuid4().hex[:6]}"
    await _add_loose(client, name=name, quantity=4)

    resp = await client.get("/api/export/wines?format=csv")
    assert resp.status_code == 200
    _, rows = _csv_rows(resp.content)
    wine_rows = [r for r in rows if r["name"] == name]
    assert len(wine_rows) == 1
    assert wine_rows[0]["item_type"] == "bottle"
    assert wine_rows[0]["quantity"] == "4"
    assert wine_rows[0]["case_size"] == ""


@pytest.mark.asyncio
async def test_csv_collapsed_roundtrip_preserves_totals(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """Collapsed-export → re-import → same wine count + same aggregate quantities.

    Full per-case roundtrip (importing per-case rows and merging them
    into one wine) is a follow-up — today's importer treats each CSV
    row as a new wine, so the default `cases_as_rows=True` is for
    display, not roundtrip. Users doing round-trip should pass
    `cases_as_rows=false`, which this test exercises.
    """
    name1 = f"Roundtrip {uuid.uuid4().hex[:6]}"
    name2 = f"Roundtrip {uuid.uuid4().hex[:6]}"
    await _add_case(client, name=name1, case_size=12, provenance="Majestic")
    await _add_loose(client, name=name2, quantity=5)

    # Export collapsed.
    exp_resp = await client.get("/api/export/wines?format=csv&cases_as_rows=false")
    assert exp_resp.status_code == 200
    exported_csv = exp_resp.content

    # Wipe the cellar.
    del_resp = await client.delete("/api/wines/all")
    assert del_resp.status_code == 200

    # Re-import.
    upload = await client.post(
        "/api/import/upload",
        files={"file": ("roundtrip.csv", exported_csv, "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    batch_id = upload.json()["batch_id"]

    # Map the columns we care about.
    mapping = {
        "name": "name", "winery": "winery", "vintage": "vintage",
        "country": "country", "region": "region", "wine_type": "wine_type",
        "quantity": "quantity",
    }
    map_resp = await client.post(
        f"/api/import/{batch_id}/mapping", json={"mapping": mapping},
    )
    assert map_resp.status_code == 200

    process = await client.post(
        f"/api/import/{batch_id}/process",
        json={"skip_duplicates": False},
    )
    assert process.status_code == 200

    # Verify: two wines, aggregate quantities preserved.
    cellar = await client.get("/api/cellar")
    assert cellar.status_code == 200
    cell = cellar.json()
    wine1 = next((w for w in cell if w["name"] == name1), None)
    wine2 = next((w for w in cell if w["name"] == name2), None)
    assert wine1 is not None and wine2 is not None
    assert wine1["inventory"]["quantity"] == 12
    assert wine2["inventory"]["quantity"] == 5
