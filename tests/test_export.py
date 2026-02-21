"""Tests for data export endpoints."""

import csv
import io
import json

import pytest
import yaml
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_export_wines_json_empty(client: AsyncClient) -> None:
    """Test exporting wines in JSON format when cellar is empty."""
    response = await client.get("/api/export/wines?format=json")
    assert response.status_code == 200

    data = response.json()
    assert "wines" in data
    assert "export_info" in data
    assert data["wines"] == []
    assert data["export_info"]["total_count"] == 0
    assert data["export_info"]["format"] == "json"


@pytest.mark.asyncio
async def test_export_wines_csv_empty(client: AsyncClient) -> None:
    """Test exporting wines in CSV format when cellar is empty."""
    response = await client.get("/api/export/wines?format=csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=winebox_wines_" in response.headers["content-disposition"]
    assert ".csv" in response.headers["content-disposition"]

    # Parse CSV
    content = response.content.decode("utf-8")
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)

    # Should have header row only
    assert len(rows) == 1
    assert "id" in rows[0]
    assert "name" in rows[0]


@pytest.mark.asyncio
async def test_export_wines_xlsx_empty(client: AsyncClient) -> None:
    """Test exporting wines in Excel format when cellar is empty."""
    response = await client.get("/api/export/wines?format=xlsx")
    assert response.status_code == 200
    assert (
        response.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment; filename=winebox_wines_" in response.headers["content-disposition"]
    assert ".xlsx" in response.headers["content-disposition"]

    # Should have content (at least header row in xlsx format)
    assert len(response.content) > 0


@pytest.mark.asyncio
async def test_export_wines_yaml_empty(client: AsyncClient) -> None:
    """Test exporting wines in YAML format when cellar is empty."""
    response = await client.get("/api/export/wines?format=yaml")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-yaml"
    assert "attachment; filename=winebox_wines_" in response.headers["content-disposition"]
    assert ".yaml" in response.headers["content-disposition"]

    # Parse YAML
    data = yaml.safe_load(response.content.decode("utf-8"))
    assert "wines" in data
    assert "export_info" in data
    assert data["wines"] == []


@pytest.mark.asyncio
async def test_export_wines_json_with_data(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test exporting wines in JSON format with data."""
    # Create a wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Test Wine",
        "winery": "Test Winery",
        "vintage": "2020",
        "grape_variety": "Cabernet Sauvignon",
        "region": "Napa Valley",
        "country": "United States",
        "quantity": "3",
    }
    await client.post("/api/wines/checkin", files=files, data=data)

    # Export wines
    response = await client.get("/api/export/wines?format=json")
    assert response.status_code == 200

    export_data = response.json()
    assert export_data["export_info"]["total_count"] == 1
    assert len(export_data["wines"]) == 1
    assert export_data["wines"][0]["name"] == "Test Wine"
    assert export_data["wines"][0]["winery"] == "Test Winery"
    assert export_data["wines"][0]["vintage"] == 2020


@pytest.mark.asyncio
async def test_export_wines_csv_with_data(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test exporting wines in CSV format with data."""
    # Create a wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Export Test Wine",
        "winery": "Export Winery",
        "vintage": "2021",
        "country": "France",
        "quantity": "5",
    }
    await client.post("/api/wines/checkin", files=files, data=data)

    # Export wines
    response = await client.get("/api/export/wines?format=csv")
    assert response.status_code == 200

    # Parse CSV
    content = response.content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["name"] == "Export Test Wine"
    assert rows[0]["winery"] == "Export Winery"
    assert rows[0]["vintage"] == "2021"
    assert rows[0]["country"] == "France"
    assert rows[0]["quantity"] == "5"


@pytest.mark.asyncio
async def test_export_wines_filter_in_stock(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test exporting wines with in_stock filter."""
    # Create two wines
    files1 = {
        "front_label": ("test1.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data1 = {"name": "In Stock Wine", "quantity": "5"}
    await client.post("/api/wines/checkin", files=files1, data=data1)

    files2 = {
        "front_label": ("test2.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data2 = {"name": "Out Of Stock Wine", "quantity": "1"}
    checkin_response = await client.post("/api/wines/checkin", files=files2, data=data2)
    wine_id = checkin_response.json()["id"]

    # Checkout the second wine to make it out of stock
    await client.post(f"/api/wines/{wine_id}/checkout", data={"quantity": "1"})

    # Export only in-stock wines
    response = await client.get("/api/export/wines?format=json&in_stock=true")
    assert response.status_code == 200

    export_data = response.json()
    assert export_data["export_info"]["total_count"] == 1
    assert export_data["export_info"]["filters_applied"]["in_stock"] is True
    assert len(export_data["wines"]) == 1
    assert export_data["wines"][0]["name"] == "In Stock Wine"


@pytest.mark.asyncio
async def test_export_wines_filter_country(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test exporting wines with country filter."""
    # Create wines from different countries
    files1 = {
        "front_label": ("test1.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data1 = {"name": "French Wine", "country": "France", "quantity": "1"}
    await client.post("/api/wines/checkin", files=files1, data=data1)

    files2 = {
        "front_label": ("test2.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data2 = {"name": "Italian Wine", "country": "Italy", "quantity": "1"}
    await client.post("/api/wines/checkin", files=files2, data=data2)

    # Export only French wines
    response = await client.get("/api/export/wines?format=json&country=France")
    assert response.status_code == 200

    export_data = response.json()
    assert export_data["export_info"]["filters_applied"]["country"] == "France"
    assert len(export_data["wines"]) == 1
    assert export_data["wines"][0]["name"] == "French Wine"


@pytest.mark.asyncio
async def test_export_wines_exclude_blends_and_scores(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test exporting wines without blends and scores."""
    # Create a wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Simple Wine", "quantity": "1"}
    await client.post("/api/wines/checkin", files=files, data=data)

    # Export without blends and scores
    response = await client.get("/api/export/wines?format=json&include_blends=false&include_scores=false")
    assert response.status_code == 200

    export_data = response.json()
    # For JSON format, these keys should be removed
    wine = export_data["wines"][0]
    assert "grape_blends" not in wine
    assert "scores" not in wine


# Transaction export tests


@pytest.mark.asyncio
async def test_export_transactions_json_empty(client: AsyncClient) -> None:
    """Test exporting transactions in JSON format when no transactions exist."""
    response = await client.get("/api/export/transactions?format=json")
    assert response.status_code == 200

    data = response.json()
    assert "transactions" in data
    assert "export_info" in data
    assert data["transactions"] == []
    assert data["export_info"]["total_count"] == 0
    assert data["export_info"]["format"] == "json"


@pytest.mark.asyncio
async def test_export_transactions_csv_empty(client: AsyncClient) -> None:
    """Test exporting transactions in CSV format when no transactions exist."""
    response = await client.get("/api/export/transactions?format=csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=winebox_transactions_" in response.headers["content-disposition"]

    # Parse CSV
    content = response.content.decode("utf-8")
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)

    # Should have header row only
    assert len(rows) == 1
    assert "id" in rows[0]
    assert "wine_id" in rows[0]
    assert "transaction_type" in rows[0]


@pytest.mark.asyncio
async def test_export_transactions_with_data(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test exporting transactions with actual data."""
    # Create a wine (which creates a CHECK_IN transaction)
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Transaction Test Wine", "quantity": "5"}
    checkin_response = await client.post("/api/wines/checkin", files=files, data=data)
    wine_id = checkin_response.json()["id"]

    # Checkout some wine (creates a CHECK_OUT transaction)
    await client.post(f"/api/wines/{wine_id}/checkout", data={"quantity": "2"})

    # Export transactions
    response = await client.get("/api/export/transactions?format=json")
    assert response.status_code == 200

    export_data = response.json()
    assert export_data["export_info"]["total_count"] == 2

    # Should have both CHECK_IN and CHECK_OUT
    transaction_types = [t["transaction_type"] for t in export_data["transactions"]]
    assert "CHECK_IN" in transaction_types
    assert "CHECK_OUT" in transaction_types


@pytest.mark.asyncio
async def test_export_transactions_csv_with_data(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test exporting transactions in CSV format with data."""
    # Create a wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "CSV Export Wine", "quantity": "3"}
    await client.post("/api/wines/checkin", files=files, data=data)

    # Export transactions
    response = await client.get("/api/export/transactions?format=csv")
    assert response.status_code == 200

    # Parse CSV
    content = response.content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["transaction_type"] == "CHECK_IN"
    assert rows[0]["quantity"] == "3"
    assert rows[0]["wine_name"] == "CSV Export Wine"


@pytest.mark.asyncio
async def test_export_transactions_filter_type(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test exporting transactions with transaction_type filter."""
    # Create and checkout wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Filter Test Wine", "quantity": "5"}
    checkin_response = await client.post("/api/wines/checkin", files=files, data=data)
    wine_id = checkin_response.json()["id"]

    await client.post(f"/api/wines/{wine_id}/checkout", data={"quantity": "1"})

    # Export only CHECK_OUT transactions
    response = await client.get("/api/export/transactions?format=json&transaction_type=CHECK_OUT")
    assert response.status_code == 200

    export_data = response.json()
    assert export_data["export_info"]["filters_applied"]["transaction_type"] == "CHECK_OUT"
    assert len(export_data["transactions"]) == 1
    assert export_data["transactions"][0]["transaction_type"] == "CHECK_OUT"


@pytest.mark.asyncio
async def test_export_transactions_filter_wine_id(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test exporting transactions with wine_id filter."""
    # Create two wines
    files1 = {
        "front_label": ("test1.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    checkin1 = await client.post("/api/wines/checkin", files=files1, data={"name": "Wine 1", "quantity": "1"})
    wine1_id = checkin1.json()["id"]

    files2 = {
        "front_label": ("test2.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    await client.post("/api/wines/checkin", files=files2, data={"name": "Wine 2", "quantity": "1"})

    # Export transactions for wine 1 only
    response = await client.get(f"/api/export/transactions?format=json&wine_id={wine1_id}")
    assert response.status_code == 200

    export_data = response.json()
    assert len(export_data["transactions"]) == 1
    assert export_data["transactions"][0]["wine_id"] == wine1_id


@pytest.mark.asyncio
async def test_export_transactions_without_wine_details(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test exporting transactions without wine details."""
    # Create a wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    await client.post("/api/wines/checkin", files=files, data={"name": "No Details Wine", "quantity": "1"})

    # Export without wine details
    response = await client.get("/api/export/transactions?format=json&include_wine_details=false")
    assert response.status_code == 200

    export_data = response.json()
    # Should not include wine details
    txn = export_data["transactions"][0]
    assert "wine" not in txn or txn.get("wine") is None


@pytest.mark.asyncio
async def test_export_transactions_xlsx(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test exporting transactions in Excel format."""
    # Create a wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    await client.post("/api/wines/checkin", files=files, data={"name": "Excel Test Wine", "quantity": "2"})

    response = await client.get("/api/export/transactions?format=xlsx")
    assert response.status_code == 200
    assert (
        response.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment; filename=winebox_transactions_" in response.headers["content-disposition"]
    assert len(response.content) > 0


@pytest.mark.asyncio
async def test_export_transactions_yaml(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test exporting transactions in YAML format."""
    # Create a wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    await client.post("/api/wines/checkin", files=files, data={"name": "YAML Test Wine", "quantity": "1"})

    response = await client.get("/api/export/transactions?format=yaml")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-yaml"

    # Parse YAML
    data = yaml.safe_load(response.content.decode("utf-8"))
    assert "transactions" in data
    assert "export_info" in data
    assert len(data["transactions"]) == 1


# Authentication tests


@pytest.mark.asyncio
async def test_export_wines_requires_auth(unauthenticated_client: AsyncClient) -> None:
    """Test that wine export requires authentication."""
    response = await unauthenticated_client.get("/api/export/wines")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_export_transactions_requires_auth(unauthenticated_client: AsyncClient) -> None:
    """Test that transaction export requires authentication."""
    response = await unauthenticated_client.get("/api/export/transactions")
    assert response.status_code == 401
