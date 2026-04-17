"""Tests for the wine price tracker API.

Covers CRUD operations, photo upload/download, validation, pagination,
data isolation, overflow archival to history, and multi-source support.
"""

import io
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from winebox.models.wine_price import WinePrice, WinePriceHistory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_price(
    client: AsyncClient,
    *,
    wine_name: str = "Château Test",
    vintage: str = "2020",
    wine_type: str = "Red",
    price: str = "12.99",
    currency: str = "EUR",
    capture_type: str = "bottle",
    photo: tuple | None = None,
    **extra,
) -> dict:
    """Helper to create a price capture and return the JSON response."""
    data = {
        "capture_type": capture_type,
        "wine_name": wine_name,
        "vintage": vintage,
        "wine_type": wine_type,
        "price": price,
        "currency": currency,
    }
    for k, v in extra.items():
        if v is not None:
            data[k] = str(v)
    files = {}
    if photo:
        files["photo"] = photo
    response = await client.post("/api/prices", data=data, files=files or None)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_price_returns_wine_document(client: AsyncClient) -> None:
    """Creating a price should return a WinePrice document with one entry."""
    body = await _create_price(client)
    assert body["wine_name"] == "Château Test"
    assert body["vintage"] == 2020
    assert body["wine_type"] == "Red"
    assert len(body["prices"]) == 1
    assert body["prices"][0]["price"] == 12.99
    assert body["prices"][0]["currency"] == "EUR"
    assert body["prices"][0]["source"] == "price_capture_app"
    assert body["id"]


@pytest.mark.asyncio
async def test_create_price_with_all_fields(client: AsyncClient) -> None:
    """All metadata fields should be stored in the price entry."""
    name = f"Domaine Test {uuid.uuid4().hex[:6]}"
    body = await _create_price(
        client,
        wine_name=name,
        vintage="2015",
        wine_type="Red",
        price="1500.00",
        currency="USD",
        notes="Airport duty-free",
        shop_name="Le Caviste",
        town_city="Paris",
        state_county="Île-de-France",
        country="France",
        capture_type="shelf",
    )
    entry = body["prices"][0]
    assert entry["price"] == 1500.00
    assert entry["currency"] == "USD"
    assert entry["notes"] == "Airport duty-free"
    assert entry["capture_type"] == "shelf"
    assert body["prices"][0]["location"]["shop_name"] == "Le Caviste"
    assert body["prices"][0]["location"]["country"] == "France"


@pytest.mark.asyncio
async def test_create_price_with_coordinates(client: AsyncClient) -> None:
    """GPS coordinates should be stored in the price entry."""
    name = f"Coords Wine {uuid.uuid4().hex[:6]}"
    body = await _create_price(
        client,
        wine_name=name,
        latitude=48.8566,
        longitude=2.3522,
        accuracy_metres=15.0,
    )
    coords = body["prices"][0]["coordinates"]
    assert coords["latitude"] == 48.8566
    assert coords["longitude"] == 2.3522
    assert coords["accuracy_metres"] == 15.0


@pytest.mark.asyncio
async def test_create_price_with_photo(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """A photo upload should produce a photo_url in the entry."""
    name = f"Photo Wine {uuid.uuid4().hex[:6]}"
    photo = ("label.png", io.BytesIO(sample_image_bytes), "image/png")
    body = await _create_price(client, wine_name=name, photo=photo)
    assert body["prices"][0]["photo_url"] is not None
    assert body["prices"][0]["photo_url"].startswith("/api/prices/photos/")


@pytest.mark.asyncio
async def test_second_price_appends_to_same_wine(client: AsyncClient) -> None:
    """Adding a second price for the same wine should append, not create new."""
    name = f"Append Wine {uuid.uuid4().hex[:6]}"
    body1 = await _create_price(client, wine_name=name, price="10.00")
    body2 = await _create_price(client, wine_name=name, price="12.00")

    assert body1["id"] == body2["id"]
    assert len(body2["prices"]) == 2
    assert body2["prices"][0]["price"] == 10.00
    assert body2["prices"][1]["price"] == 12.00


@pytest.mark.asyncio
async def test_different_vintage_creates_separate_doc(client: AsyncClient) -> None:
    """Different vintages of the same wine should be separate documents."""
    name = f"Vintage Wine {uuid.uuid4().hex[:6]}"
    body1 = await _create_price(client, wine_name=name, vintage="2018", price="10.00")
    body2 = await _create_price(client, wine_name=name, vintage="2019", price="12.00")

    assert body1["id"] != body2["id"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_capture_type_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/prices",
        data={"capture_type": "crate", "wine_name": "X", "price": "10"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_wine_name_required(client: AsyncClient) -> None:
    response = await client.post(
        "/api/prices", data={"capture_type": "bottle", "price": "10"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_price_required(client: AsyncClient) -> None:
    response = await client.post(
        "/api/prices", data={"capture_type": "bottle", "wine_name": "X"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_wine_name_too_long_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/prices",
        data={"capture_type": "bottle", "wine_name": "A" * 501, "price": "10"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_notes_too_long_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/prices",
        data={"capture_type": "bottle", "wine_name": "X", "price": "10", "notes": "N" * 2001},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_photo_content_type_rejected(client: AsyncClient) -> None:
    fake_pdf = ("doc.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")
    response = await client.post(
        "/api/prices",
        data={"capture_type": "bottle", "wine_name": "X", "price": "10"},
        files={"photo": fake_pdf},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_photo_too_large_rejected(client: AsyncClient) -> None:
    big_photo = ("huge.png", io.BytesIO(b"\x00" * (10 * 1024 * 1024 + 1)), "image/png")
    response = await client.post(
        "/api/prices",
        data={"capture_type": "bottle", "wine_name": "X", "price": "10"},
        files={"photo": big_photo},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_prices_empty(client: AsyncClient) -> None:
    response = await client.get("/api/prices")
    assert response.status_code == 200
    # May contain entries from other tests but shouldn't error
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_list_prices_returns_user_wines(client: AsyncClient) -> None:
    """Only wines where the user contributed prices should appear."""
    name = f"List Wine {uuid.uuid4().hex[:6]}"
    await _create_price(client, wine_name=name, price="10.00")

    response = await client.get("/api/prices")
    assert response.status_code == 200
    summaries = response.json()
    names = {s["wine_name"] for s in summaries}
    assert name in names

    # Check summary fields
    match = next(s for s in summaries if s["wine_name"] == name)
    assert match["price_count"] >= 1
    assert match["latest_price"] is not None


@pytest.mark.asyncio
async def test_list_prices_limit_capped(client: AsyncClient) -> None:
    response = await client.get("/api/prices?limit=500")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Get single
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_wine_price_by_id(client: AsyncClient) -> None:
    name = f"Get Wine {uuid.uuid4().hex[:6]}"
    created = await _create_price(client, wine_name=name)
    response = await client.get(f"/api/prices/{created['id']}")
    assert response.status_code == 200
    assert response.json()["wine_name"] == name
    assert len(response.json()["prices"]) >= 1


@pytest.mark.asyncio
async def test_get_nonexistent_returns_404(client: AsyncClient) -> None:
    from bson import ObjectId
    response = await client.get(f"/api/prices/{ObjectId()}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Delete entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_price_entry(client: AsyncClient) -> None:
    name = f"Delete Wine {uuid.uuid4().hex[:6]}"
    created = await _create_price(client, wine_name=name)
    wine_id = created["id"]

    response = await client.delete(f"/api/prices/{wine_id}/entries/0")
    assert response.status_code == 204

    # Wine document should be gone (was the only entry)
    response = await client.get(f"/api/prices/{wine_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_entry_keeps_others(client: AsyncClient) -> None:
    name = f"KeepOthers Wine {uuid.uuid4().hex[:6]}"
    await _create_price(client, wine_name=name, price="10.00")
    body = await _create_price(client, wine_name=name, price="20.00")
    wine_id = body["id"]

    # Delete first entry
    response = await client.delete(f"/api/prices/{wine_id}/entries/0")
    assert response.status_code == 204

    # Second entry should remain
    response = await client.get(f"/api/prices/{wine_id}")
    assert response.status_code == 200
    assert len(response.json()["prices"]) == 1
    assert response.json()["prices"][0]["price"] == 20.00


@pytest.mark.asyncio
async def test_delete_entry_removes_photo(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    name = f"PhotoDel Wine {uuid.uuid4().hex[:6]}"
    photo = ("label.png", io.BytesIO(sample_image_bytes), "image/png")
    created = await _create_price(client, wine_name=name, photo=photo)
    photo_url = created["prices"][0]["photo_url"]

    # Photo accessible
    response = await client.get(photo_url)
    assert response.status_code == 200

    # Delete entry
    response = await client.delete(f"/api/prices/{created['id']}/entries/0")
    assert response.status_code == 204

    # Photo gone
    response = await client.get(photo_url)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_entry_returns_404(client: AsyncClient) -> None:
    from bson import ObjectId
    response = await client.delete(f"/api/prices/{ObjectId()}/entries/0")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_out_of_range_index_returns_404(client: AsyncClient) -> None:
    name = f"OOB Wine {uuid.uuid4().hex[:6]}"
    created = await _create_price(client, wine_name=name)
    response = await client.delete(f"/api/prices/{created['id']}/entries/99")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Photo access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_photo(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    name = f"PhotoGet Wine {uuid.uuid4().hex[:6]}"
    photo = ("label.png", io.BytesIO(sample_image_bytes), "image/png")
    created = await _create_price(client, wine_name=name, photo=photo)
    response = await client.get(created["prices"][0]["photo_url"])
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_photo_path_traversal_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/prices/photos/..%2F..%2Fetc%2Fpasswd")
    assert response.status_code in (400, 404)


@pytest.mark.asyncio
async def test_photo_nonexistent_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/prices/photos/nonexistent.png")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Data isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_other_user_cannot_delete_entry(
    client: AsyncClient, init_test_db
) -> None:
    """User B should not be able to delete User A's price entry."""
    name = f"Protected Wine {uuid.uuid4().hex[:6]}"
    created = await _create_price(client, wine_name=name)

    from winebox.models import User
    from winebox.services.auth import create_access_token
    from tests.conftest import get_test_app, _CACHED_TEST_PASSWORD_HASH

    other_email = f"other-{uuid.uuid4().hex[:8]}@example.com"
    other_user = User(
        email=other_email,
        hashed_password=_CACHED_TEST_PASSWORD_HASH,
        is_active=True,
        is_verified=True,
        is_superuser=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await other_user.insert()
    other_token = create_access_token(data={"sub": other_email})
    app = get_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {other_token}"},
    ) as other_client:
        response = await other_client.delete(f"/api/prices/{created['id']}/entries/0")
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_other_user_cannot_access_photo(
    client: AsyncClient, sample_image_bytes: bytes, init_test_db
) -> None:
    """User B should not be able to download User A's photo."""
    name = f"PhotoIso Wine {uuid.uuid4().hex[:6]}"
    photo = ("label.png", io.BytesIO(sample_image_bytes), "image/png")
    created = await _create_price(client, wine_name=name, photo=photo)

    from winebox.models import User
    from winebox.services.auth import create_access_token
    from tests.conftest import get_test_app, _CACHED_TEST_PASSWORD_HASH

    other_email = f"other-{uuid.uuid4().hex[:8]}@example.com"
    other_user = User(
        email=other_email,
        hashed_password=_CACHED_TEST_PASSWORD_HASH,
        is_active=True,
        is_verified=True,
        is_superuser=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await other_user.insert()
    other_token = create_access_token(data={"sub": other_email})
    app = get_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {other_token}"},
    ) as other_client:
        response = await other_client.get(created["prices"][0]["photo_url"])
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_two_users_contribute_to_same_wine(
    client: AsyncClient, init_test_db
) -> None:
    """Two users adding prices for the same wine share one document."""
    name = f"Shared Wine {uuid.uuid4().hex[:6]}"
    body1 = await _create_price(client, wine_name=name, price="10.00")

    from winebox.models import User
    from winebox.services.auth import create_access_token
    from tests.conftest import get_test_app, _CACHED_TEST_PASSWORD_HASH

    other_email = f"other-{uuid.uuid4().hex[:8]}@example.com"
    other_user = User(
        email=other_email,
        hashed_password=_CACHED_TEST_PASSWORD_HASH,
        is_active=True,
        is_verified=True,
        is_superuser=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await other_user.insert()
    other_token = create_access_token(data={"sub": other_email})
    app = get_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {other_token}"},
    ) as other_client:
        body2 = await _create_price(other_client, wine_name=name, price="15.00")

    # Same document, two entries
    assert body1["id"] == body2["id"]
    assert len(body2["prices"]) == 2


@pytest.mark.asyncio
async def test_get_wine_price_redacts_other_users_pii(
    client: AsyncClient, sample_image_bytes: bytes, init_test_db
) -> None:
    """User B fetching a shared wine_price must not see User A's PII.

    Crowdsourced WinePrice docs are read by every contributor, so non-owner
    fields (owner_id, GPS coords, town/state, notes, photo URL) must be
    redacted while aggregate fields (price, currency, shop name, country)
    stay visible.
    """
    name = f"PIITest Wine {uuid.uuid4().hex[:6]}"
    photo = ("label.png", io.BytesIO(sample_image_bytes), "image/png")
    body_a = await _create_price(
        client,
        wine_name=name,
        price="10.00",
        notes="My private tasting notes",
        shop_name="Vintners Cellar",
        town_city="Dublin",
        state_county="Leinster",
        country="Ireland",
        latitude="53.3498",
        longitude="-6.2603",
        accuracy_metres="5.0",
        photo=photo,
    )

    # User A sees their own data fully
    a_entry = body_a["prices"][0]
    assert a_entry["owner_id"] is not None
    assert a_entry["coordinates"] is not None
    assert a_entry["coordinates"]["latitude"] == 53.3498
    assert a_entry["notes"] == "My private tasting notes"
    assert a_entry["photo_url"] is not None
    assert a_entry["location"]["town_city"] == "Dublin"
    assert a_entry["location"]["state_county"] == "Leinster"
    assert a_entry["location"]["shop_name"] == "Vintners Cellar"  # always visible
    assert a_entry["location"]["country"] == "Ireland"  # always visible

    # User B fetches the same wine_price — must see redacted version
    from winebox.models import User
    from winebox.services.auth import create_access_token
    from tests.conftest import get_test_app, _CACHED_TEST_PASSWORD_HASH

    other_email = f"other-{uuid.uuid4().hex[:8]}@example.com"
    other_user = User(
        email=other_email,
        hashed_password=_CACHED_TEST_PASSWORD_HASH,
        is_active=True,
        is_verified=True,
        is_superuser=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await other_user.insert()
    other_token = create_access_token(data={"sub": other_email})
    app = get_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {other_token}"},
    ) as other_client:
        resp = await other_client.get(f"/api/prices/{body_a['id']}")
        assert resp.status_code == 200
        b_entry = resp.json()["prices"][0]

    # Sensitive fields redacted for non-owner
    assert b_entry["owner_id"] is None
    assert b_entry["coordinates"] is None
    assert b_entry["notes"] is None
    assert b_entry["photo_url"] is None
    assert b_entry["location"]["town_city"] is None
    assert b_entry["location"]["state_county"] is None
    # Aggregate fields still visible — price comparison must keep working
    assert b_entry["price"] == 10.00
    assert b_entry["currency"] == "EUR"
    assert b_entry["location"]["shop_name"] == "Vintners Cellar"
    assert b_entry["location"]["country"] == "Ireland"


# ---------------------------------------------------------------------------
# Authentication required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_create_rejected(
    unauthenticated_client: AsyncClient,
) -> None:
    response = await unauthenticated_client.post(
        "/api/prices",
        data={"capture_type": "bottle", "wine_name": "X", "price": "10"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_list_rejected(
    unauthenticated_client: AsyncClient,
) -> None:
    response = await unauthenticated_client.get("/api/prices")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Overflow & history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overflow_archives_to_history(client: AsyncClient) -> None:
    """Adding a 21st price should archive the oldest to wine_prices_history."""
    name = f"Overflow Wine {uuid.uuid4().hex[:6]}"

    # Add 21 prices
    for i in range(21):
        body = await _create_price(
            client,
            wine_name=name,
            price=str(10.0 + i),
        )

    # Should have exactly 20 entries in the document
    assert len(body["prices"]) == 20

    # First entry should be the second price (index 1), not the first (index 0)
    assert body["prices"][0]["price"] == 11.0

    # The oldest (price 10.0) should be in history
    wine_id = body["id"]
    response = await client.get(f"/api/prices/{wine_id}/history")
    assert response.status_code == 200
    history = response.json()
    assert len(history) >= 1
    assert any(h["price"] == 10.0 for h in history)


@pytest.mark.asyncio
async def test_history_endpoint_empty_when_no_overflow(client: AsyncClient) -> None:
    name = f"NoOverflow Wine {uuid.uuid4().hex[:6]}"
    body = await _create_price(client, wine_name=name, price="10.00")
    response = await client.get(f"/api/prices/{body['id']}/history")
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# Currency support
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supported_currencies(client: AsyncClient) -> None:
    for currency in ("EUR", "GBP", "USD", "CHF", "AUD", "NZD", "CAD", "JPY", "ZAR"):
        name = f"Currency {currency} {uuid.uuid4().hex[:6]}"
        body = await _create_price(
            client, wine_name=name, price="9.99", currency=currency,
        )
        assert body["prices"][0]["currency"] == currency
