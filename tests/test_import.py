"""Integration tests for import endpoints."""

import csv
import io
import json

import pytest
from httpx import AsyncClient
from openpyxl import Workbook


def _make_csv(headers: list[str], rows: list[list[str]]) -> bytes:
    """Helper to create CSV bytes."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return output.getvalue().encode("utf-8")


def _make_xlsx(headers: list[str], rows: list[list]) -> bytes:
    """Helper to create XLSX bytes."""
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_upload_csv(client: AsyncClient) -> None:
    """Test uploading a CSV file."""
    csv_data = _make_csv(
        ["Wine Name", "Winery", "Vintage", "Country"],
        [
            ["Chateau Margaux", "Margaux", "2015", "France"],
            ["Barolo", "Giacomo Conterno", "2018", "Italy"],
        ],
    )

    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    response = await client.post("/api/import/upload", files=files)
    assert response.status_code == 200

    data = response.json()
    assert data["row_count"] == 2
    assert "Wine Name" in data["headers"]
    assert data["suggested_mapping"]["Wine Name"] == "name"
    assert data["suggested_mapping"]["Winery"] == "winery"
    assert data["suggested_mapping"]["Vintage"] == "vintage"
    assert data["suggested_mapping"]["Country"] == "country"
    assert len(data["preview_rows"]) == 2


@pytest.mark.asyncio
async def test_upload_xlsx(client: AsyncClient) -> None:
    """Test uploading an XLSX file."""
    xlsx_data = _make_xlsx(
        ["Wine", "Producer", "Year"],
        [
            ["Sassicaia", "Tenuta San Guido", 2017],
        ],
    )

    files = {"file": ("wines.xlsx", io.BytesIO(xlsx_data), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    response = await client.post("/api/import/upload", files=files)
    assert response.status_code == 200

    data = response.json()
    assert data["row_count"] == 1
    assert data["suggested_mapping"]["Wine"] == "name"
    assert data["suggested_mapping"]["Producer"] == "winery"
    assert data["suggested_mapping"]["Year"] == "vintage"


@pytest.mark.asyncio
async def test_upload_invalid_type(client: AsyncClient) -> None:
    """Test rejection of unsupported file types."""
    files = {"file": ("data.txt", io.BytesIO(b"not a spreadsheet"), "text/plain")}
    response = await client.post("/api/import/upload", files=files)
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_set_column_mapping(client: AsyncClient) -> None:
    """Test setting column mapping on a batch."""
    csv_data = _make_csv(["Name", "Region"], [["Wine A", "Bordeaux"]])
    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    batch_id = upload_resp.json()["batch_id"]

    response = await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": {"Name": "name", "Region": "region"}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["suggested_mapping"]["Name"] == "name"


@pytest.mark.asyncio
async def test_mapping_requires_name(client: AsyncClient) -> None:
    """Test that mapping must include 'name'."""
    csv_data = _make_csv(["Region", "Vintage"], [["Bordeaux", "2020"]])
    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    batch_id = upload_resp.json()["batch_id"]

    response = await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": {"Region": "region", "Vintage": "vintage"}},
    )
    assert response.status_code == 400
    assert "name" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_full_import_workflow(client: AsyncClient) -> None:
    """Test the complete upload -> map -> process workflow."""
    csv_data = _make_csv(
        ["Wine Name", "Producer", "Year", "Country", "Qty"],
        [
            ["Chateau Margaux", "Margaux", "2015", "France", "3"],
            ["Barolo Riserva", "Conterno", "2018", "Italy", "2"],
        ],
    )

    # 1. Upload
    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    assert upload_resp.status_code == 200
    batch_id = upload_resp.json()["batch_id"]

    # 2. Set mapping
    mapping = {
        "Wine Name": "name",
        "Producer": "winery",
        "Year": "vintage",
        "Country": "country",
        "Qty": "quantity",
    }
    map_resp = await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": mapping},
    )
    assert map_resp.status_code == 200

    # 3. Process
    process_resp = await client.post(
        f"/api/import/{batch_id}/process",
        json={"skip_non_wine": True, "default_quantity": 1},
    )
    assert process_resp.status_code == 200

    result = process_resp.json()
    assert result["wines_created"] == 2
    assert result["rows_skipped"] == 0
    assert result["status"] == "completed"

    # 4. Verify wines exist in cellar
    wines_resp = await client.get("/api/wines")
    wines = wines_resp.json()
    names = {w["name"] for w in wines}
    assert "Chateau Margaux" in names
    assert "Barolo Riserva" in names

    # Verify quantities
    for w in wines:
        if w["name"] == "Chateau Margaux":
            assert w["inventory"]["quantity"] == 3
        elif w["name"] == "Barolo Riserva":
            assert w["inventory"]["quantity"] == 2


@pytest.mark.asyncio
async def test_import_skips_non_wine(client: AsyncClient) -> None:
    """Test that non-wine rows are skipped."""
    csv_data = _make_csv(
        ["Name", "Type"],
        [
            ["Chateau Margaux", "Red"],
            ["Jameson", "Whiskey"],
            ["Tanqueray", "Gin"],
            ["Barolo", "Red"],
        ],
    )

    # Upload
    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    batch_id = upload_resp.json()["batch_id"]

    # Map and process
    await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": {"Name": "name", "Type": "wine_type_id"}},
    )
    process_resp = await client.post(
        f"/api/import/{batch_id}/process",
        json={"skip_non_wine": True, "default_quantity": 1},
    )

    result = process_resp.json()
    assert result["wines_created"] == 2
    assert result["rows_skipped"] == 2


@pytest.mark.asyncio
async def test_import_custom_fields(client: AsyncClient) -> None:
    """Test that custom fields are preserved in imported wines."""
    csv_data = _make_csv(
        ["Name", "Cellar Location", "Purchase Price"],
        [
            ["Test Wine", "Rack 3A", "$50"],
        ],
    )

    # Upload
    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    batch_id = upload_resp.json()["batch_id"]

    # Map with custom fields
    await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": {
            "Name": "name",
            "Cellar Location": "custom:Cellar Location",
            "Purchase Price": "custom:Purchase Price",
        }},
    )
    process_resp = await client.post(
        f"/api/import/{batch_id}/process",
        json={"skip_non_wine": False, "default_quantity": 1},
    )

    result = process_resp.json()
    assert result["wines_created"] == 1

    # Verify custom fields on the wine
    wines_resp = await client.get("/api/wines")
    wine = wines_resp.json()[0]
    assert wine["custom_fields"] is not None
    assert wine["custom_fields"]["Cellar Location"] == "Rack 3A"
    assert wine["custom_fields"]["Purchase Price"] == "$50"


@pytest.mark.asyncio
async def test_list_batches(client: AsyncClient) -> None:
    """Test listing import batches."""
    csv_data = _make_csv(["Name"], [["Wine A"]])
    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    await client.post("/api/import/upload", files=files)

    response = await client.get("/api/import/batches")
    assert response.status_code == 200
    batches = response.json()
    assert len(batches) >= 1
    assert any(b["filename"] == "wines.csv" for b in batches)


@pytest.mark.asyncio
async def test_delete_batch(client: AsyncClient) -> None:
    """Test deleting an import batch."""
    csv_data = _make_csv(["Name"], [["Wine A"]])
    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    batch_id = upload_resp.json()["batch_id"]

    # Delete
    delete_resp = await client.delete(f"/api/import/batches/{batch_id}")
    assert delete_resp.status_code == 204

    # Verify gone
    get_resp = await client.get(f"/api/import/batches/{batch_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_import_requires_auth(unauthenticated_client: AsyncClient) -> None:
    """Test that import endpoints require authentication."""
    csv_data = _make_csv(["Name"], [["Wine A"]])
    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    response = await unauthenticated_client.post("/api/import/upload", files=files)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_process_stream_returns_progress(client: AsyncClient) -> None:
    """Test that the streaming endpoint sends SSE progress events."""
    csv_data = _make_csv(
        ["Wine Name", "Country"],
        [
            ["Chateau Margaux", "France"],
            ["Barolo Riserva", "Italy"],
            ["Rioja Gran Reserva", "Spain"],
        ],
    )

    # Upload
    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    assert upload_resp.status_code == 200
    batch_id = upload_resp.json()["batch_id"]

    # Set mapping
    await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": {"Wine Name": "name", "Country": "country"}},
    )

    # Process via streaming endpoint
    stream_resp = await client.post(
        f"/api/import/{batch_id}/process-stream",
        json={"skip_non_wine": True, "default_quantity": 1},
    )
    assert stream_resp.status_code == 200
    assert "text/event-stream" in stream_resp.headers["content-type"]

    # Parse SSE events from response body
    events = []
    for line in stream_resp.text.strip().split("\n\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))

    # Should have progress events for each row plus a final done event
    assert len(events) >= 2

    # Check intermediate progress events have expected fields
    for event in events:
        assert "processed" in event
        assert "total" in event
        assert "wines_created" in event
        assert "rows_skipped" in event

    # Progress should be monotonically increasing
    for i in range(1, len(events)):
        assert events[i]["processed"] >= events[i - 1]["processed"]

    # Final event should be done
    final = events[-1]
    assert final.get("done") is True
    assert final["wines_created"] == 3
    assert final["total"] == 3
    assert final["status"] == "completed"


@pytest.mark.asyncio
async def test_process_stream_already_processed(client: AsyncClient) -> None:
    """Test that streaming a completed batch returns an error."""
    csv_data = _make_csv(["Name"], [["Wine A"]])
    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    batch_id = upload_resp.json()["batch_id"]

    # Map and process normally first
    await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": {"Name": "name"}},
    )
    await client.post(f"/api/import/{batch_id}/process", json={})

    # Try streaming again — should fail
    stream_resp = await client.post(f"/api/import/{batch_id}/process-stream", json={})
    assert stream_resp.status_code == 400


# ---------------------------------------------------------------------------
# Tests for client-parsed CSV upload endpoints (upload-parsed + rows)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_parsed_creates_batch(client: AsyncClient) -> None:
    """Test that upload-parsed creates a batch with headers and preview."""
    response = await client.post(
        "/api/import/upload-parsed",
        json={
            "filename": "wines.csv",
            "headers": ["Wine Name", "Winery", "Vintage"],
            "preview_rows": [
                {"Wine Name": "Margaux", "Winery": "Ch. Margaux", "Vintage": "2015"},
                {"Wine Name": "Barolo", "Winery": "Conterno", "Vintage": "2018"},
            ],
            "row_count": 100,
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert data["batch_id"]
    assert data["filename"] == "wines.csv"
    assert data["row_count"] == 100
    assert data["headers"] == ["Wine Name", "Winery", "Vintage"]
    assert len(data["preview_rows"]) == 2
    assert data["suggested_mapping"]["Wine Name"] == "name"
    assert data["suggested_mapping"]["Winery"] == "winery"
    assert data["suggested_mapping"]["Vintage"] == "vintage"


@pytest.mark.asyncio
async def test_upload_parsed_rejects_too_many_rows(client: AsyncClient) -> None:
    """Test that row_count > 10000 is rejected."""
    response = await client.post(
        "/api/import/upload-parsed",
        json={
            "filename": "huge.csv",
            "headers": ["Name"],
            "preview_rows": [{"Name": "Wine A"}],
            "row_count": 10001,
        },
    )
    assert response.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_append_rows_to_batch(client: AsyncClient) -> None:
    """Test appending row chunks to a batch."""
    # Create batch via upload-parsed
    upload_resp = await client.post(
        "/api/import/upload-parsed",
        json={
            "filename": "wines.csv",
            "headers": ["Name", "Country"],
            "preview_rows": [{"Name": "Wine A", "Country": "France"}],
            "row_count": 3,
        },
    )
    batch_id = upload_resp.json()["batch_id"]

    # Append first chunk with clear=true
    resp1 = await client.post(
        f"/api/import/{batch_id}/rows?clear=true",
        json={"rows": [{"Name": "Wine A", "Country": "France"}]},
    )
    assert resp1.status_code == 200
    assert resp1.json()["rows_added"] == 1

    # Append second chunk (no clear)
    resp2 = await client.post(
        f"/api/import/{batch_id}/rows",
        json={
            "rows": [
                {"Name": "Wine B", "Country": "Italy"},
                {"Name": "Wine C", "Country": "Spain"},
            ]
        },
    )
    assert resp2.status_code == 200
    assert resp2.json()["rows_added"] == 2


@pytest.mark.asyncio
async def test_append_rows_clear_first_chunk(client: AsyncClient) -> None:
    """Test that ?clear=true replaces existing rows instead of appending."""
    upload_resp = await client.post(
        "/api/import/upload-parsed",
        json={
            "filename": "wines.csv",
            "headers": ["Name"],
            "preview_rows": [{"Name": "Wine A"}],
            "row_count": 2,
        },
    )
    batch_id = upload_resp.json()["batch_id"]

    # Add some rows
    await client.post(
        f"/api/import/{batch_id}/rows",
        json={"rows": [{"Name": "Old Wine 1"}, {"Name": "Old Wine 2"}]},
    )

    # Clear and replace with new rows
    await client.post(
        f"/api/import/{batch_id}/rows?clear=true",
        json={"rows": [{"Name": "New Wine"}]},
    )

    # Map and process to verify only the new row is used
    await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": {"Name": "name"}},
    )
    process_resp = await client.post(
        f"/api/import/{batch_id}/process",
        json={"skip_non_wine": False, "default_quantity": 1},
    )
    result = process_resp.json()
    assert result["wines_created"] == 1

    # Verify only the new wine exists
    wines_resp = await client.get("/api/wines")
    names = {w["name"] for w in wines_resp.json()}
    assert "New Wine" in names
    assert "Old Wine 1" not in names
    assert "Old Wine 2" not in names


@pytest.mark.asyncio
async def test_append_rows_wrong_status(client: AsyncClient) -> None:
    """Test that rows cannot be appended to a completed batch."""
    # Create and fully process a batch via the original upload path
    csv_data = _make_csv(["Name"], [["Wine A"]])
    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    batch_id = upload_resp.json()["batch_id"]

    await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": {"Name": "name"}},
    )
    await client.post(f"/api/import/{batch_id}/process", json={})

    # Try to append rows to completed batch
    resp = await client.post(
        f"/api/import/{batch_id}/rows",
        json={"rows": [{"Name": "Wine B"}]},
    )
    assert resp.status_code == 400
    assert "Cannot add rows" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_full_workflow_parsed_upload(client: AsyncClient) -> None:
    """Test end-to-end: upload-parsed -> rows -> mapping -> process."""
    # 1. Upload parsed metadata
    upload_resp = await client.post(
        "/api/import/upload-parsed",
        json={
            "filename": "wines.csv",
            "headers": ["Wine Name", "Country", "Qty"],
            "preview_rows": [
                {"Wine Name": "Margaux", "Country": "France", "Qty": "3"},
            ],
            "row_count": 2,
        },
    )
    assert upload_resp.status_code == 200
    batch_id = upload_resp.json()["batch_id"]

    # 2. Upload rows in chunks
    resp = await client.post(
        f"/api/import/{batch_id}/rows?clear=true",
        json={
            "rows": [
                {"Wine Name": "Margaux", "Country": "France", "Qty": "3"},
                {"Wine Name": "Barolo", "Country": "Italy", "Qty": "2"},
            ]
        },
    )
    assert resp.status_code == 200

    # 3. Set mapping
    map_resp = await client.post(
        f"/api/import/{batch_id}/mapping",
        json={
            "mapping": {
                "Wine Name": "name",
                "Country": "country",
                "Qty": "quantity",
            }
        },
    )
    assert map_resp.status_code == 200

    # 4. Process
    process_resp = await client.post(
        f"/api/import/{batch_id}/process",
        json={"skip_non_wine": True, "default_quantity": 1},
    )
    assert process_resp.status_code == 200
    result = process_resp.json()
    assert result["wines_created"] == 2
    assert result["status"] == "completed"

    # 5. Verify wines in cellar
    wines_resp = await client.get("/api/wines")
    wines = wines_resp.json()
    names = {w["name"] for w in wines}
    assert "Margaux" in names
    assert "Barolo" in names

    # Verify quantities
    for w in wines:
        if w["name"] == "Margaux":
            assert w["inventory"]["quantity"] == 3
        elif w["name"] == "Barolo":
            assert w["inventory"]["quantity"] == 2


@pytest.mark.asyncio
async def test_upload_parsed_requires_auth(unauthenticated_client: AsyncClient) -> None:
    """Test that upload-parsed requires authentication."""
    response = await unauthenticated_client.post(
        "/api/import/upload-parsed",
        json={
            "filename": "wines.csv",
            "headers": ["Name"],
            "preview_rows": [{"Name": "Wine A"}],
            "row_count": 1,
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_append_rows_requires_auth(unauthenticated_client: AsyncClient) -> None:
    """Test that appending rows requires authentication."""
    response = await unauthenticated_client.post(
        "/api/import/fake-id/rows",
        json={"rows": [{"Name": "Wine A"}]},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_case_size_multiplies_quantity(client: AsyncClient) -> None:
    """Test that case_size multiplies quantity to compute total bottles."""
    csv_data = _make_csv(
        ["Wine Name", "Cases", "Case Size"],
        [
            ["Bordeaux Blend", "2", "12"],
            ["Single Case", "1", "6"],
        ],
    )

    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    batch_id = upload_resp.json()["batch_id"]

    await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": {
            "Wine Name": "name",
            "Cases": "quantity",
            "Case Size": "case_size",
        }},
    )
    process_resp = await client.post(
        f"/api/import/{batch_id}/process",
        json={"skip_non_wine": False, "default_quantity": 1},
    )
    assert process_resp.json()["wines_created"] == 2

    wines_resp = await client.get("/api/wines")
    wines = {w["name"]: w for w in wines_resp.json()}
    assert wines["Bordeaux Blend"]["inventory"]["quantity"] == 24  # 2 * 12
    assert wines["Single Case"]["inventory"]["quantity"] == 6  # 1 * 6


@pytest.mark.asyncio
async def test_case_size_without_quantity(client: AsyncClient) -> None:
    """Test that case_size alone uses default quantity of 1 case."""
    csv_data = _make_csv(
        ["Wine Name", "Bottles per Case"],
        [["Rioja Reserva", "6"]],
    )

    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    batch_id = upload_resp.json()["batch_id"]

    await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": {
            "Wine Name": "name",
            "Bottles per Case": "case_size",
        }},
    )
    process_resp = await client.post(
        f"/api/import/{batch_id}/process",
        json={"skip_non_wine": False, "default_quantity": 1},
    )
    assert process_resp.json()["wines_created"] == 1

    wines_resp = await client.get("/api/wines")
    wine = wines_resp.json()[0]
    assert wine["inventory"]["quantity"] == 6  # 1 (default) * 6


@pytest.mark.asyncio
async def test_undo_import(client: AsyncClient) -> None:
    """Test that undo import deletes wines and marks batch as rolled back."""
    csv_data = _make_csv(
        ["Name", "Country"],
        [
            ["Wine Alpha", "France"],
            ["Wine Beta", "Italy"],
            ["Wine Gamma", "Spain"],
        ],
    )

    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    batch_id = upload_resp.json()["batch_id"]

    await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": {"Name": "name", "Country": "country"}},
    )
    process_resp = await client.post(
        f"/api/import/{batch_id}/process",
        json={"skip_non_wine": False, "default_quantity": 1},
    )
    assert process_resp.json()["wines_created"] == 3

    # Verify wines exist
    wines_resp = await client.get("/api/wines")
    assert len(wines_resp.json()) == 3

    # Undo import
    undo_resp = await client.delete(f"/api/import/batches/{batch_id}/wines")
    assert undo_resp.status_code == 200
    undo_result = undo_resp.json()
    assert undo_result["wines_deleted"] == 3
    assert undo_result["status"] == "rolled_back"

    # Verify wines are gone
    wines_resp = await client.get("/api/wines")
    assert len(wines_resp.json()) == 0

    # Verify batch is marked as rolled_back
    batch_resp = await client.get(f"/api/import/batches/{batch_id}")
    assert batch_resp.json()["status"] == "rolled_back"


@pytest.mark.asyncio
async def test_undo_import_only_completed_or_processing(client: AsyncClient) -> None:
    """Test that undo is only allowed on completed or processing batches."""
    csv_data = _make_csv(["Name"], [["Wine A"]])
    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    batch_id = upload_resp.json()["batch_id"]

    # Try to undo an uploaded (not completed/processing) batch
    undo_resp = await client.delete(f"/api/import/batches/{batch_id}/wines")
    assert undo_resp.status_code == 400
    assert "Only completed or in-progress" in undo_resp.json()["detail"]


@pytest.mark.asyncio
async def test_skip_duplicates(client: AsyncClient) -> None:
    """Test that skip_duplicates skips wines already in cellar."""
    # First import: add 2 wines
    csv_data = _make_csv(
        ["Name", "Winery", "Vintage"],
        [
            ["Margaux", "Chateau Margaux", "2015"],
            ["Barolo", "Conterno", "2018"],
        ],
    )
    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    batch_id = upload_resp.json()["batch_id"]

    await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": {"Name": "name", "Winery": "winery", "Vintage": "vintage"}},
    )
    process_resp = await client.post(
        f"/api/import/{batch_id}/process",
        json={"skip_non_wine": False, "default_quantity": 1, "skip_duplicates": False},
    )
    assert process_resp.json()["wines_created"] == 2

    # Second import: same 2 wines + 1 new, with skip_duplicates=True
    csv_data2 = _make_csv(
        ["Name", "Winery", "Vintage"],
        [
            ["Margaux", "Chateau Margaux", "2015"],  # duplicate
            ["Barolo", "Conterno", "2018"],            # duplicate
            ["Brunello", "Biondi Santi", "2016"],      # new
        ],
    )
    files2 = {"file": ("wines2.csv", io.BytesIO(csv_data2), "text/csv")}
    upload_resp2 = await client.post("/api/import/upload", files=files2)
    batch_id2 = upload_resp2.json()["batch_id"]

    await client.post(
        f"/api/import/{batch_id2}/mapping",
        json={"mapping": {"Name": "name", "Winery": "winery", "Vintage": "vintage"}},
    )
    process_resp2 = await client.post(
        f"/api/import/{batch_id2}/process",
        json={"skip_non_wine": False, "default_quantity": 1, "skip_duplicates": True},
    )
    result2 = process_resp2.json()
    assert result2["wines_created"] == 1  # only Brunello
    assert result2["rows_skipped"] == 2   # Margaux + Barolo skipped

    # Verify total wines: 2 original + 1 new = 3
    wines_resp = await client.get("/api/wines")
    assert len(wines_resp.json()) == 3


@pytest.mark.asyncio
async def test_skip_duplicates_false_allows_duplicates(client: AsyncClient) -> None:
    """Test that skip_duplicates=False imports duplicates."""
    csv_data = _make_csv(["Name"], [["Same Wine"]])

    # First import
    files = {"file": ("wines.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    batch_id = upload_resp.json()["batch_id"]
    await client.post(f"/api/import/{batch_id}/mapping", json={"mapping": {"Name": "name"}})
    await client.post(f"/api/import/{batch_id}/process", json={"skip_duplicates": False})

    # Second import, same wine, skip_duplicates=False
    files2 = {"file": ("wines2.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp2 = await client.post("/api/import/upload", files=files2)
    batch_id2 = upload_resp2.json()["batch_id"]
    await client.post(f"/api/import/{batch_id2}/mapping", json={"mapping": {"Name": "name"}})
    process_resp = await client.post(f"/api/import/{batch_id2}/process", json={"skip_duplicates": False})
    assert process_resp.json()["wines_created"] == 1  # imported despite being duplicate

    wines_resp = await client.get("/api/wines")
    assert len(wines_resp.json()) == 2  # both copies exist
