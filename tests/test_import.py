"""Integration tests for import endpoints."""

import csv
import io

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
    assert batches[0]["filename"] == "wines.csv"


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
