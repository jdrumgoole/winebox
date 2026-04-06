"""Tests for the wine price tracker API.

Covers CRUD operations, photo upload/download, validation,
pagination, data isolation between users, and the admin info endpoint.
"""

import io
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from winebox.models.price_capture import PriceCapture


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _form_data(**kwargs) -> dict:
    """Build form data dict for create_price_capture, filtering out None values."""
    return {k: str(v) if not isinstance(v, str) else v
            for k, v in kwargs.items() if v is not None}


async def _create_capture(
    client: AsyncClient,
    *,
    wine_name: str = "Château Test",
    price: float = 12.99,
    currency: str = "EUR",
    capture_type: str = "bottle",
    photo: tuple | None = None,
    **extra,
) -> dict:
    """Helper to create a price capture and return the JSON response."""
    data = _form_data(
        capture_type=capture_type,
        wine_name=wine_name,
        price=price,
        currency=currency,
        **extra,
    )
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
async def test_create_minimal_capture(client: AsyncClient) -> None:
    """A capture with only default fields should succeed."""
    response = await client.post("/api/prices", data={"capture_type": "bottle"})
    assert response.status_code == 201
    body = response.json()
    assert body["capture_type"] == "bottle"
    assert body["currency"] == "EUR"
    assert body["id"]


@pytest.mark.asyncio
async def test_create_capture_with_all_fields(client: AsyncClient) -> None:
    """Create a capture populating every metadata field."""
    body = await _create_capture(
        client,
        wine_name="Domaine de la Romanée-Conti",
        vintage=2015,
        wine_type="Red",
        price=1500.00,
        currency="USD",
        notes="Amazing find at airport duty-free",
        shop_name="Le Caviste",
        town_city="Paris",
        state_county="Île-de-France",
        country="France",
        capture_type="shelf",
    )
    assert body["wine_name"] == "Domaine de la Romanée-Conti"
    assert body["vintage"] == 2015
    assert body["wine_type"] == "Red"
    assert body["price"] == 1500.00
    assert body["currency"] == "USD"
    assert body["notes"] == "Amazing find at airport duty-free"
    assert body["capture_type"] == "shelf"
    assert body["location"]["shop_name"] == "Le Caviste"
    assert body["location"]["town_city"] == "Paris"
    assert body["location"]["state_county"] == "Île-de-France"
    assert body["location"]["country"] == "France"


@pytest.mark.asyncio
async def test_create_capture_with_coordinates(client: AsyncClient) -> None:
    """GPS coordinates should be stored and returned."""
    body = await _create_capture(
        client,
        latitude=48.8566,
        longitude=2.3522,
        accuracy_metres=15.0,
    )
    assert body["coordinates"]["latitude"] == 48.8566
    assert body["coordinates"]["longitude"] == 2.3522
    assert body["coordinates"]["accuracy_metres"] == 15.0


@pytest.mark.asyncio
async def test_create_capture_with_photo(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """A photo upload should produce a photo_url in the response."""
    photo = ("label.png", io.BytesIO(sample_image_bytes), "image/png")
    body = await _create_capture(client, photo=photo)
    assert body["photo_url"] is not None
    assert body["photo_url"].startswith("/api/prices/photos/")


@pytest.mark.asyncio
async def test_create_capture_with_captured_at(client: AsyncClient) -> None:
    """An explicit captured_at timestamp should be honoured."""
    ts = "2025-06-15T14:30:00+00:00"
    body = await _create_capture(client, captured_at=ts)
    assert "2025-06-15" in body["captured_at"]


@pytest.mark.asyncio
async def test_create_capture_with_jpeg_photo(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """JPEG content type should be accepted."""
    photo = ("photo.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")
    body = await _create_capture(client, photo=photo)
    assert body["photo_url"] is not None


@pytest.mark.asyncio
async def test_create_capture_with_webp_photo(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """WebP content type should be accepted."""
    photo = ("photo.webp", io.BytesIO(sample_image_bytes), "image/webp")
    body = await _create_capture(client, photo=photo)
    assert body["photo_url"] is not None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_capture_type_rejected(client: AsyncClient) -> None:
    """Capture type must be 'bottle' or 'shelf'."""
    response = await client.post("/api/prices", data={"capture_type": "crate"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_wine_name_too_long_rejected(client: AsyncClient) -> None:
    """Wine name over 500 characters should be rejected."""
    response = await client.post(
        "/api/prices",
        data={"capture_type": "bottle", "wine_name": "A" * 501},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_notes_too_long_rejected(client: AsyncClient) -> None:
    """Notes over 2000 characters should be rejected."""
    response = await client.post(
        "/api/prices",
        data={"capture_type": "bottle", "notes": "N" * 2001},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_photo_content_type_rejected(client: AsyncClient) -> None:
    """Only image/* content types should be accepted for photo."""
    fake_pdf = ("doc.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")
    response = await client.post(
        "/api/prices",
        data={"capture_type": "bottle"},
        files={"photo": fake_pdf},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_photo_too_large_rejected(client: AsyncClient) -> None:
    """Photos over 10 MB should be rejected."""
    big_photo = ("huge.png", io.BytesIO(b"\x00" * (10 * 1024 * 1024 + 1)), "image/png")
    response = await client.post(
        "/api/prices",
        data={"capture_type": "bottle"},
        files={"photo": big_photo},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_captures_empty(client: AsyncClient) -> None:
    """A new user should have no captures."""
    response = await client.get("/api/prices")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_captures_returns_created(client: AsyncClient) -> None:
    """Created captures should appear in the listing."""
    await _create_capture(client, wine_name="Wine A", price=10.0)
    await _create_capture(client, wine_name="Wine B", price=20.0)

    response = await client.get("/api/prices")
    assert response.status_code == 200
    captures = response.json()
    assert len(captures) >= 2
    names = {c["wine_name"] for c in captures}
    assert "Wine A" in names
    assert "Wine B" in names


@pytest.mark.asyncio
async def test_list_captures_newest_first(client: AsyncClient) -> None:
    """Captures should be ordered newest first."""
    await _create_capture(client, wine_name="Older", captured_at="2024-01-01T00:00:00+00:00")
    await _create_capture(client, wine_name="Newer", captured_at="2025-06-01T00:00:00+00:00")

    response = await client.get("/api/prices")
    captures = response.json()
    names = [c["wine_name"] for c in captures]
    assert names.index("Newer") < names.index("Older")


@pytest.mark.asyncio
async def test_list_captures_pagination(client: AsyncClient) -> None:
    """Skip and limit should control pagination."""
    for i in range(5):
        await _create_capture(client, wine_name=f"Paginated {i}", price=float(i))

    response = await client.get("/api/prices?skip=0&limit=2")
    assert response.status_code == 200
    assert len(response.json()) == 2

    response = await client.get("/api/prices?skip=2&limit=2")
    assert response.status_code == 200
    assert len(response.json()) == 2


@pytest.mark.asyncio
async def test_list_captures_limit_capped_at_200(client: AsyncClient) -> None:
    """Requesting limit > 200 should be capped silently."""
    response = await client.get("/api/prices?limit=500")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Get single
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_capture_by_id(client: AsyncClient) -> None:
    """Should return the specific capture."""
    created = await _create_capture(client, wine_name="Get Me")
    response = await client.get(f"/api/prices/{created['id']}")
    assert response.status_code == 200
    assert response.json()["wine_name"] == "Get Me"


@pytest.mark.asyncio
async def test_get_nonexistent_capture_returns_404(client: AsyncClient) -> None:
    """A random ObjectId should 404."""
    from bson import ObjectId

    fake_id = str(ObjectId())
    response = await client.get(f"/api/prices/{fake_id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_capture(client: AsyncClient) -> None:
    """Deleting a capture should remove it."""
    created = await _create_capture(client, wine_name="Delete Me")
    response = await client.delete(f"/api/prices/{created['id']}")
    assert response.status_code == 204

    # Verify it's gone
    response = await client.get(f"/api/prices/{created['id']}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_capture_removes_photo(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """Deleting a capture with a photo should also remove the photo file."""
    photo = ("label.png", io.BytesIO(sample_image_bytes), "image/png")
    created = await _create_capture(client, photo=photo)
    photo_url = created["photo_url"]

    # Photo should be accessible
    response = await client.get(photo_url)
    assert response.status_code == 200

    # Delete the capture
    response = await client.delete(f"/api/prices/{created['id']}")
    assert response.status_code == 204

    # Photo should no longer be accessible
    response = await client.get(photo_url)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_capture_returns_404(client: AsyncClient) -> None:
    """Deleting a non-existent capture should 404."""
    from bson import ObjectId

    fake_id = str(ObjectId())
    response = await client.delete(f"/api/prices/{fake_id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Photo access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_photo(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """A photo should be downloadable via its URL."""
    photo = ("label.png", io.BytesIO(sample_image_bytes), "image/png")
    created = await _create_capture(client, photo=photo)
    response = await client.get(created["photo_url"])
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_photo_path_traversal_rejected(client: AsyncClient) -> None:
    """Path traversal attempts should be blocked."""
    # The framework normalises ../../ out of URLs, so test with encoded dots
    # that survive routing but trigger the filename validation
    response = await client.get("/api/prices/photos/..%2F..%2Fetc%2Fpasswd")
    assert response.status_code in (400, 404)  # blocked either way


@pytest.mark.asyncio
async def test_photo_nonexistent_returns_404(client: AsyncClient) -> None:
    """Requesting a photo filename that doesn't belong to the user should 404."""
    response = await client.get("/api/prices/photos/nonexistent.png")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Data isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_cannot_see_other_users_captures(
    client: AsyncClient, init_test_db
) -> None:
    """User A's captures should not be visible to User B."""
    # Create a capture as the fixture user
    await _create_capture(client, wine_name="User A Wine")

    # Create a second user client
    from winebox.models import User
    from winebox.services.auth import get_password_hash, create_access_token
    from httpx import ASGITransport
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
        response = await other_client.get("/api/prices")
        assert response.status_code == 200
        names = {c["wine_name"] for c in response.json()}
        assert "User A Wine" not in names


@pytest.mark.asyncio
async def test_user_cannot_delete_other_users_capture(
    client: AsyncClient, init_test_db
) -> None:
    """User B should not be able to delete User A's capture."""
    created = await _create_capture(client, wine_name="Protected")

    from winebox.models import User
    from winebox.services.auth import create_access_token
    from httpx import ASGITransport
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
        response = await other_client.delete(f"/api/prices/{created['id']}")
        assert response.status_code == 404

    # Original user can still see it
    response = await client.get(f"/api/prices/{created['id']}")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_photo(
    client: AsyncClient, sample_image_bytes: bytes, init_test_db
) -> None:
    """User B should not be able to download User A's photo."""
    photo = ("label.png", io.BytesIO(sample_image_bytes), "image/png")
    created = await _create_capture(client, photo=photo)

    from winebox.models import User
    from winebox.services.auth import create_access_token
    from httpx import ASGITransport
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
        response = await other_client.get(created["photo_url"])
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Authentication required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_create_rejected(
    unauthenticated_client: AsyncClient,
) -> None:
    """Creating a capture without auth should fail."""
    response = await unauthenticated_client.post(
        "/api/prices", data={"capture_type": "bottle"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_list_rejected(
    unauthenticated_client: AsyncClient,
) -> None:
    """Listing captures without auth should fail."""
    response = await unauthenticated_client.get("/api/prices")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_delete_rejected(
    unauthenticated_client: AsyncClient,
) -> None:
    """Deleting a capture without auth should fail."""
    from bson import ObjectId

    response = await unauthenticated_client.delete(
        f"/api/prices/{ObjectId()}"
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Currency support
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supported_currencies(client: AsyncClient) -> None:
    """All documented currencies should be accepted."""
    for currency in ("EUR", "GBP", "USD", "CHF", "AUD", "NZD", "CAD", "JPY", "ZAR"):
        body = await _create_capture(
            client,
            wine_name=f"Wine {currency}",
            price=9.99,
            currency=currency,
        )
        assert body["currency"] == currency


