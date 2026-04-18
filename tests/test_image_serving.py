"""Tests for the auth-gated /api/images/{filename} endpoint.

The endpoint replaced an unauthenticated `app.mount(StaticFiles)` mount,
so these tests pin three properties:

1. Owners can fetch their own images.
2. A request from a different user — even with a valid filename — must
   return 404 (not 403, to avoid confirming the file exists).
3. Path traversal, missing files, and unauthenticated requests are all
   handled safely.
"""

import io
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from winebox.models import User
from winebox.services.auth import create_access_token, get_password_hash


_HASH = get_password_hash("imgtestpw")


@pytest_asyncio.fixture
async def two_clients(init_test_db):
    """Two authenticated clients backed by two different real users."""
    from tests.conftest import get_test_app

    email_a = f"img-a-{uuid.uuid4().hex[:8]}@example.com"
    email_b = f"img-b-{uuid.uuid4().hex[:8]}@example.com"
    for email in (email_a, email_b):
        await User(
            email=email,
            hashed_password=_HASH,
            is_active=True,
            is_verified=True,
            is_superuser=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ).insert()

    app = get_test_app()
    transport = ASGITransport(app=app)
    token_a = create_access_token(data={"sub": email_a})
    token_b = create_access_token(data={"sub": email_b})
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token_a}"},
    ) as client_a:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {token_b}"},
        ) as client_b:
            yield client_a, client_b


@pytest.fixture
def sample_image_bytes() -> bytes:
    """Minimal valid PNG (1x1 pixel)."""
    return bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
        0x00, 0x00, 0x00, 0x0D,
        0x49, 0x48, 0x44, 0x52,
        0x00, 0x00, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x01,
        0x08, 0x02,
        0x00, 0x00, 0x00,
        0x90, 0x77, 0x53, 0xDE,
        0x00, 0x00, 0x00, 0x0C,
        0x49, 0x44, 0x41, 0x54,
        0x08, 0xD7, 0x63, 0xF8, 0xFF, 0xFF, 0x3F, 0x00,
        0x05, 0xFE, 0x02, 0xFE,
        0xA3, 0x1A, 0x8D, 0xEB,
        0x00, 0x00, 0x00, 0x00,
        0x49, 0x45, 0x4E, 0x44,
        0xAE, 0x42, 0x60, 0x82,
    ])


async def _record_wine_with_image(
    client: AsyncClient, sample_image_bytes: bytes, name: str
) -> str:
    """Record a wine with a front-label image and return the image filename."""
    files = {"front_label": ("front.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": name, "quantity": "1"}
    resp = await client.post("/api/wines/record", files=files, data=data)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    image_path = body.get("front_label_image_path")
    assert image_path, f"expected an image path in response, got {body}"
    return image_path


@pytest.mark.asyncio
async def test_owner_can_fetch_own_image(two_clients, sample_image_bytes):
    """The user who recorded the wine can fetch its image."""
    client_a, _ = two_clients
    filename = await _record_wine_with_image(client_a, sample_image_bytes, "Owned Wine")

    resp = await client_a.get(f"/api/images/{filename}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    # Must not be cached by shared proxies — image is private to this user.
    assert "private" in resp.headers.get("cache-control", "")
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_other_user_gets_404_not_403(two_clients, sample_image_bytes):
    """A second user with the exact filename gets 404, not 403.

    Returning 403 would confirm 'this file exists, you just can't see it',
    leaking that some other user owns it. 404 keeps the existence private.
    """
    client_a, client_b = two_clients
    filename = await _record_wine_with_image(client_a, sample_image_bytes, "Owner-only Wine")

    resp = await client_b.get(f"/api/images/{filename}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(unauthenticated_client, two_clients, sample_image_bytes):
    """No bearer token → 401, regardless of whether the file exists."""
    client_a, _ = two_clients
    filename = await _record_wine_with_image(client_a, sample_image_bytes, "Auth Required")

    resp = await unauthenticated_client.get(f"/api/images/{filename}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_nonexistent_filename_returns_404(two_clients):
    """A valid-looking but unknown filename returns 404."""
    client_a, _ = two_clients
    resp = await client_a.get(f"/api/images/{uuid.uuid4().hex}.png")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_path_traversal_returns_404(two_clients):
    """`..`, absolute paths, and slashes must not escape the storage root."""
    client_a, _ = two_clients
    for bad in (
        "../../../etc/passwd",
        "..%2F..%2Fetc%2Fpasswd",  # url-encoded variant
        "/etc/passwd",
        "%2Fetc%2Fpasswd",
    ):
        resp = await client_a.get(f"/api/images/{bad}")
        # Either 404 (we rejected it) or 401 (no auth on a path that hit a
        # different route) — but never 200, and never the contents of /etc/passwd.
        assert resp.status_code in (404, 401), f"unexpected {resp.status_code} for {bad!r}: {resp.text[:200]}"
        if resp.status_code == 200:
            assert b"root:" not in resp.content
