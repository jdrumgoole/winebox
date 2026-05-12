"""HTTP-level tests for the admin /api/users pagination contract.

The admin panel runs as a separate FastAPI app (winebox.admin.main:app),
so we mount its routers onto a slim test app and drive it through
AsyncClient — same pattern as the main-app `client` fixture in conftest.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from winebox import __version__
from tests._regstack_helpers import create_access_token
from winebox.admin.routers import admin as admin_router_module
from winebox.admin.routers import auth as admin_auth_module
from winebox.models import User
from winebox.services.auth import get_password_hash


def _build_admin_test_app() -> FastAPI:
    """Mount the admin routers onto a lifespan-free test app."""

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        yield

    app = FastAPI(title="WineBox Admin Test", version=__version__, lifespan=_lifespan)
    app.include_router(admin_router_module.router, prefix="/api")
    app.include_router(admin_auth_module.router, prefix="/api/auth")
    return app


@pytest_asyncio.fixture
async def admin_http_client(isolated_db) -> AsyncGenerator[tuple[AsyncClient, User], None]:
    """Yield (admin client, admin user) against an isolated database.

    These tests assert on `total_users` and on stable page windows, so they
    need a database that other parallel tests cannot mutate underneath them.
    """
    admin_email = f"admin-pagination-{uuid.uuid4().hex[:8]}@test.example.com"
    admin_user = User(
        email=admin_email,
        hashed_password=get_password_hash("testpassword"),
        is_active=True,
        is_verified=True,
        is_superuser=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await admin_user.insert()

    token = await create_access_token(data={"sub": admin_email})
    transport = ASGITransport(app=_build_admin_test_app())
    async with AsyncClient(
        transport=transport,
        base_url="http://admin-test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client, admin_user


async def _seed_users(prefix: str, count: int) -> list[User]:
    """Insert ``count`` users with millisecond-spaced created_at values.

    BSON datetime is millisecond precision, so spacing by milliseconds
    avoids ties; the endpoint also tie-breaks on ``_id`` for safety.
    """
    users: list[User] = []
    base = datetime.now(timezone.utc)
    for i in range(count):
        u = User(
            email=f"{prefix}-{i}-{uuid.uuid4().hex[:6]}@test.example.com",
            hashed_password=get_password_hash("testpassword"),
            is_active=True,
            is_verified=True,
            is_superuser=False,
            created_at=base + timedelta(milliseconds=i + 1),
            updated_at=base,
        )
        await u.insert()
        users.append(u)
    return users


@pytest.mark.asyncio
async def test_pagination_metadata_present(
    admin_http_client: tuple[AsyncClient, User],
) -> None:
    client, _admin = admin_http_client
    await _seed_users("page-meta", 3)

    resp = await client.get("/api/users", params={"skip": 0, "limit": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Echoes the pagination params and includes a full count.
    assert body["skip"] == 0
    assert body["limit"] == 2
    # Isolated DB: 1 admin + 3 seeded = exactly 4.
    assert body["total_users"] == 4
    # And the page itself respects the limit.
    assert len(body["users"]) == 2


@pytest.mark.asyncio
async def test_skip_advances_window(
    admin_http_client: tuple[AsyncClient, User],
) -> None:
    client, _admin = admin_http_client
    await _seed_users("page-skip", 5)

    page1 = (await client.get("/api/users", params={"skip": 0, "limit": 2})).json()
    page2 = (await client.get("/api/users", params={"skip": 2, "limit": 2})).json()
    page3 = (await client.get("/api/users", params={"skip": 4, "limit": 2})).json()

    ids1 = {u["id"] for u in page1["users"]}
    ids2 = {u["id"] for u in page2["users"]}
    ids3 = {u["id"] for u in page3["users"]}

    # Different windows must not overlap.
    assert ids1.isdisjoint(ids2)
    assert ids2.isdisjoint(ids3)
    assert ids1.isdisjoint(ids3)
    # And together they cover all 6 users (1 admin + 5 seeded).
    assert len(ids1 | ids2 | ids3) == 6


@pytest.mark.asyncio
async def test_limit_capped_at_max_page_size(
    admin_http_client: tuple[AsyncClient, User],
) -> None:
    client, _admin = admin_http_client
    # MAX_PAGE_SIZE is 200; anything above must be rejected.
    resp = await client.get("/api/users", params={"skip": 0, "limit": 9999})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_negative_skip_rejected(
    admin_http_client: tuple[AsyncClient, User],
) -> None:
    client, _admin = admin_http_client
    resp = await client.get("/api/users", params={"skip": -1, "limit": 10})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_skip_past_end_returns_empty_page(
    admin_http_client: tuple[AsyncClient, User],
) -> None:
    client, _admin = admin_http_client
    # Skip past the only user (the admin) — must return an empty page
    # without raising, so the UI can snap back to a valid offset.
    resp = await client.get("/api/users", params={"skip": 50, "limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["users"] == []
    assert body["total_users"] == 1  # just the admin in the isolated DB
