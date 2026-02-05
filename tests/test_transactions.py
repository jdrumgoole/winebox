"""Tests for transaction history endpoints."""

import io

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_transactions_empty(client: AsyncClient) -> None:
    """Test listing transactions when empty."""
    response = await client.get("/api/transactions")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_transactions(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test listing transactions after check-in."""
    # Check in wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Test Wine", "quantity": "3"}
    await client.post("/api/wines/checkin", files=files, data=data)

    # List transactions
    response = await client.get("/api/transactions")
    assert response.status_code == 200

    transactions = response.json()
    assert len(transactions) == 1
    assert transactions[0]["transaction_type"] == "CHECK_IN"
    assert transactions[0]["quantity"] == 3


@pytest.mark.asyncio
async def test_filter_transactions_by_type(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test filtering transactions by type."""
    # Check in wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Test Wine", "quantity": "5"}
    checkin_response = await client.post("/api/wines/checkin", files=files, data=data)
    wine_id = checkin_response.json()["id"]

    # Check out some
    await client.post(f"/api/wines/{wine_id}/checkout", data={"quantity": "2"})

    # Filter by CHECK_IN
    response = await client.get("/api/transactions?transaction_type=CHECK_IN")
    assert response.status_code == 200
    transactions = response.json()
    assert len(transactions) == 1
    assert all(t["transaction_type"] == "CHECK_IN" for t in transactions)

    # Filter by CHECK_OUT
    response = await client.get("/api/transactions?transaction_type=CHECK_OUT")
    assert response.status_code == 200
    transactions = response.json()
    assert len(transactions) == 1
    assert all(t["transaction_type"] == "CHECK_OUT" for t in transactions)


@pytest.mark.asyncio
async def test_get_transaction_detail(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test getting a single transaction."""
    # Check in wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Test Wine", "quantity": "1"}
    await client.post("/api/wines/checkin", files=files, data=data)

    # Get transaction ID
    list_response = await client.get("/api/transactions")
    transaction_id = list_response.json()[0]["id"]

    # Get transaction detail
    response = await client.get(f"/api/transactions/{transaction_id}")
    assert response.status_code == 200

    transaction = response.json()
    assert transaction["id"] == transaction_id
    assert transaction["transaction_type"] == "CHECK_IN"


@pytest.mark.asyncio
async def test_get_transaction_not_found(client: AsyncClient) -> None:
    """Test getting a transaction that doesn't exist."""
    response = await client.get("/api/transactions/nonexistent-id")
    assert response.status_code == 404
