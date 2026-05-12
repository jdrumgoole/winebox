"""Smoke tests for the regstack auth router mounted on WineBox.

These cover the parts of the regstack contract that the SPA, the admin
panel, and downstream WineBox code rely on. If regstack moves an
endpoint or changes a schema field, one of these breaks and we notice
before deployment.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests._regstack_helpers import create_access_token
from tests.conftest import _CACHED_TEST_PASSWORD_HASH, get_test_app
from winebox.models import User


@pytest_asyncio.fixture
async def fresh_client(init_test_db) -> AsyncGenerator[AsyncClient, None]:
    """Unauthenticated client; tests do their own login / register."""
    transport = ASGITransport(app=get_test_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_login_returns_bearer_token(fresh_client: AsyncClient) -> None:
    """POST /api/auth/login with valid creds → 200 + access_token JSON."""
    email = f"login-ok-{uuid.uuid4().hex[:8]}@example.com"
    await User(
        email=email,
        hashed_password=_CACHED_TEST_PASSWORD_HASH,
        is_active=True,
        is_verified=True,
        is_superuser=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ).insert()

    resp = await fresh_client.post(
        "/api/auth/login",
        json={"email": email, "password": "testpassword"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(fresh_client: AsyncClient) -> None:
    """A bad password is a 401 with a generic detail — anti-enumeration."""
    email = f"login-bad-{uuid.uuid4().hex[:8]}@example.com"
    await User(
        email=email,
        hashed_password=_CACHED_TEST_PASSWORD_HASH,
        is_active=True,
        is_verified=True,
        is_superuser=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ).insert()

    resp = await fresh_client.post(
        "/api/auth/login",
        json={"email": email, "password": "wrongpassword"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_id_key(fresh_client: AsyncClient) -> None:
    """The WineBox /me override emits `id` (string), not regstack's `_id`."""
    email = f"me-shape-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=email,
        hashed_password=_CACHED_TEST_PASSWORD_HASH,
        is_active=True,
        is_verified=True,
        is_superuser=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await user.insert()
    token = await create_access_token(data={"sub": email})

    resp = await fresh_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(user.id)
    assert "_id" not in body
    assert body["email"] == email
    assert body["is_admin"] is False


@pytest.mark.asyncio
async def test_forgot_password_always_202(fresh_client: AsyncClient) -> None:
    """POST /api/auth/forgot-password is 202 regardless of account existence."""
    resp = await fresh_client.post(
        "/api/auth/forgot-password",
        json={"email": "ghost@example.com"},
    )
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_change_password_requires_auth(fresh_client: AsyncClient) -> None:
    """Unauthenticated POST /api/auth/change-password → 401."""
    resp = await fresh_client.post(
        "/api/auth/change-password",
        json={"current_password": "x", "new_password": "y" * 10},
    )
    assert resp.status_code == 401
