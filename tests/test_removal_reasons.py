"""Tests for wine removal reasons (DRINK, SELL, GIFT, OTHER)."""

import io

import pytest
from httpx import AsyncClient


async def _checkin_wine(client: AsyncClient, sample_image_bytes: bytes, name: str = "Test Wine", quantity: int = 5) -> str:
    """Helper to check in a wine and return its ID."""
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": name, "quantity": str(quantity)}
    response = await client.post("/api/wines/record", files=files, data=data)
    assert response.status_code in (200, 201)
    return response.json()["id"]


@pytest.mark.asyncio
async def test_removal_with_drink_reason(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test removing wine with DRINK reason and tasting notes."""
    wine_id = await _checkin_wine(client, sample_image_bytes)

    response = await client.post(
        f"/api/wines/{wine_id}/checkout",
        data={
            "quantity": "1",
            "removal_reason": "DRINK",
            "tasting_notes": "Lovely with Sunday roast",
        },
    )
    assert response.status_code == 200
    wine = response.json()
    assert wine["inventory"]["quantity"] == 4

    # Verify transaction stored with tasting_notes
    transactions = await client.get(f"/api/transactions?wine_id={wine_id}&transaction_type=CHECK_OUT")
    txn = transactions.json()[0]
    assert txn["removal_reason"] == "DRINK"
    assert txn["tasting_notes"] == "Lovely with Sunday roast"


@pytest.mark.asyncio
async def test_removal_with_sell_reason(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test removing wine with SELL reason and sale price."""
    wine_id = await _checkin_wine(client, sample_image_bytes)

    response = await client.post(
        f"/api/wines/{wine_id}/checkout",
        data={
            "quantity": "1",
            "removal_reason": "SELL",
            "sale_price_usd": "85.00",
        },
    )
    assert response.status_code == 200

    transactions = await client.get(f"/api/transactions?wine_id={wine_id}&transaction_type=CHECK_OUT")
    txn = transactions.json()[0]
    assert txn["removal_reason"] == "SELL"
    assert txn["sale_price_usd"] == 85.0


@pytest.mark.asyncio
async def test_removal_with_gift_reason(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test removing wine with GIFT reason and recipient."""
    wine_id = await _checkin_wine(client, sample_image_bytes)

    response = await client.post(
        f"/api/wines/{wine_id}/checkout",
        data={
            "quantity": "1",
            "removal_reason": "GIFT",
            "gift_recipient": "Sarah",
        },
    )
    assert response.status_code == 200

    transactions = await client.get(f"/api/transactions?wine_id={wine_id}&transaction_type=CHECK_OUT")
    txn = transactions.json()[0]
    assert txn["removal_reason"] == "GIFT"
    assert txn["gift_recipient"] == "Sarah"


@pytest.mark.asyncio
async def test_removal_with_other_reason(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test removing wine with OTHER reason and notes."""
    wine_id = await _checkin_wine(client, sample_image_bytes)

    response = await client.post(
        f"/api/wines/{wine_id}/checkout",
        data={
            "quantity": "1",
            "removal_reason": "OTHER",
            "removal_notes": "Cork was damaged",
        },
    )
    assert response.status_code == 200

    transactions = await client.get(f"/api/transactions?wine_id={wine_id}&transaction_type=CHECK_OUT")
    txn = transactions.json()[0]
    assert txn["removal_reason"] == "OTHER"
    assert txn["removal_notes"] == "Cork was damaged"


@pytest.mark.asyncio
async def test_sell_requires_price(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test that SELL reason requires sale_price_usd."""
    wine_id = await _checkin_wine(client, sample_image_bytes)

    response = await client.post(
        f"/api/wines/{wine_id}/checkout",
        data={
            "quantity": "1",
            "removal_reason": "SELL",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_gift_requires_recipient(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test that GIFT reason requires gift_recipient."""
    wine_id = await _checkin_wine(client, sample_image_bytes)

    response = await client.post(
        f"/api/wines/{wine_id}/checkout",
        data={
            "quantity": "1",
            "removal_reason": "GIFT",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_filter_by_removal_reason(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test filtering transactions by removal_reason."""
    wine_id = await _checkin_wine(client, sample_image_bytes)

    # Create transactions with different reasons
    await client.post(f"/api/wines/{wine_id}/checkout", data={"quantity": "1", "removal_reason": "DRINK"})
    await client.post(f"/api/wines/{wine_id}/checkout", data={"quantity": "1", "removal_reason": "SELL", "sale_price_usd": "50"})
    await client.post(f"/api/wines/{wine_id}/checkout", data={"quantity": "1", "removal_reason": "GIFT", "gift_recipient": "Bob"})

    # Filter by DRINK
    response = await client.get("/api/transactions?removal_reason=DRINK")
    assert response.status_code == 200
    txns = response.json()
    assert len(txns) == 1
    assert txns[0]["removal_reason"] == "DRINK"

    # Filter by SELL
    response = await client.get("/api/transactions?removal_reason=SELL")
    assert response.status_code == 200
    txns = response.json()
    assert len(txns) == 1
    assert txns[0]["removal_reason"] == "SELL"

    # Filter by GIFT
    response = await client.get("/api/transactions?removal_reason=GIFT")
    assert response.status_code == 200
    txns = response.json()
    assert len(txns) == 1
    assert txns[0]["removal_reason"] == "GIFT"


@pytest.mark.asyncio
async def test_legacy_checkout_backward_compat(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test that checkout without removal_reason works (backward compatibility)."""
    wine_id = await _checkin_wine(client, sample_image_bytes)

    response = await client.post(
        f"/api/wines/{wine_id}/checkout",
        data={"quantity": "1"},
    )
    assert response.status_code == 200

    transactions = await client.get(f"/api/transactions?wine_id={wine_id}&transaction_type=CHECK_OUT")
    txn = transactions.json()[0]
    assert txn["removal_reason"] is None
    assert txn["tasting_notes"] is None
    assert txn["sale_price_usd"] is None
    assert txn["gift_recipient"] is None
    assert txn["removal_notes"] is None


@pytest.mark.asyncio
async def test_drink_without_notes(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test DRINK reason without tasting notes (optional)."""
    wine_id = await _checkin_wine(client, sample_image_bytes)

    response = await client.post(
        f"/api/wines/{wine_id}/checkout",
        data={"quantity": "1", "removal_reason": "DRINK"},
    )
    assert response.status_code == 200

    transactions = await client.get(f"/api/transactions?wine_id={wine_id}&transaction_type=CHECK_OUT")
    txn = transactions.json()[0]
    assert txn["removal_reason"] == "DRINK"
    assert txn["tasting_notes"] is None


@pytest.mark.asyncio
async def test_other_without_notes(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test OTHER reason without removal notes (optional)."""
    wine_id = await _checkin_wine(client, sample_image_bytes)

    response = await client.post(
        f"/api/wines/{wine_id}/checkout",
        data={"quantity": "1", "removal_reason": "OTHER"},
    )
    assert response.status_code == 200

    transactions = await client.get(f"/api/transactions?wine_id={wine_id}&transaction_type=CHECK_OUT")
    txn = transactions.json()[0]
    assert txn["removal_reason"] == "OTHER"
    assert txn["removal_notes"] is None
