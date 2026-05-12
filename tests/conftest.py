"""Pytest configuration and fixtures for WineBox tests with real MongoDB.

Database strategy: all xdist workers share a single database (test_winebox),
dropped by pytest_configure before workers start. Data accumulates across
tests just like production. Each test gets its own unique user so
user-scoped data is naturally isolated.
"""

import asyncio
import os
import uuid

from dotenv import load_dotenv

load_dotenv()  # Load .env so API keys etc. are available to tests

# Ensure tests never accidentally use the production database name.
# The actual test database is created per-worker in init_test_db fixture,
# but Settings() is loaded globally and must not trigger the safety guard.
if "WINEBOX_DATABASE" not in os.environ:
    os.environ["WINEBOX_DATABASE"] = "winebox_test"

# Tests always target the local Mongo, never the .env's Atlas URL —
# regstack reads `settings.mongodb_url` to build its own client, and a
# `.env` symlink intended for deploys would otherwise point regstack at
# production while xdist workers' user inserts hit localhost. Force the
# test value here regardless of what .env loaded.
os.environ["WINEBOX_MONGODB_URL"] = os.environ.get(
    "TEST_MONGODB_URL", "mongodb://localhost:27017"
)

# Disable slowapi rate limits for the test suite. The slowapi memory store
# is per-process, so a single xdist worker's tests share one bucket per
# endpoint. Otherwise tests like `test_supported_currencies` (which fires 9
# POST /api/prices) only fail under parallel execution when an unrelated
# test in the same worker has already consumed budget. Must be set BEFORE
# any winebox.* import so make_limiter() picks it up.
os.environ.setdefault("WINEBOX_RATE_LIMIT_DISABLED", "1")
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pymongo import AsyncMongoClient

from winebox.database import init_db
from winebox.models import User
from winebox.services.auth import get_password_hash
from tests._regstack_helpers import create_access_token

# Pre-compute password hash for test fixtures — Argon2 is deliberately slow
# (~38ms per call), and every test using the `client` fixture hashes the same
# string. Computing once per worker saves significant CPU time.
_CACHED_TEST_PASSWORD_HASH = get_password_hash("testpassword")


# MongoDB connection URL for tests (can be overridden with env var)
TEST_MONGODB_URL = os.environ.get("TEST_MONGODB_URL", "mongodb://localhost:27017")

# Shared database name for all xdist workers
SHARED_TEST_DB = "test_winebox"


def pytest_configure(config: pytest.Config) -> None:
    """Drop shared test database before xdist workers start.

    Runs only in the master/controller process (workers have 'workerinput').
    Uses sync MongoClient since pytest_configure is synchronous.
    """
    if not hasattr(config, "workerinput"):
        # Skip local-DB drop when running E2E against a remote target (OAT).
        # Remote E2E jobs don't need a local mongo at all.
        if os.environ.get("WINEBOX_TEST_URL"):
            return
        from pymongo import MongoClient

        url = os.environ.get("TEST_MONGODB_URL", "mongodb://localhost:27017")
        sync_client = MongoClient(url, serverSelectionTimeoutMS=2000)
        sync_client.drop_database(SHARED_TEST_DB)
        sync_client.close()


def pytest_unconfigure(config: pytest.Config) -> None:
    """Clean up test users from remote databases after all tests finish.

    Deletes users matching @test.example.com and all their data (wines,
    transactions, import batches, raw uploads). Only runs in the controller
    process and only when WINEBOX_DATABASE is set (remote testing against OAT).
    """
    if hasattr(config, "workerinput"):
        return  # Only run in controller, not workers

    db_name = os.environ.get("WINEBOX_DATABASE")
    mongo_url = os.environ.get("WINEBOX_MONGODB_URL")
    if not db_name or not mongo_url or db_name == "winebox_test":
        return  # Only clean up remote databases, not local test DB

    from pymongo import MongoClient

    try:
        client = MongoClient(mongo_url)
        db = client[db_name]

        # Find all test users
        test_users = list(db.users.find(
            {"email": {"$regex": r"@test\.example\.com$"}},
            {"_id": 1, "email": 1},
        ))

        if not test_users:
            client.close()
            return

        user_ids = [u["_id"] for u in test_users]
        emails = [u["email"] for u in test_users]

        # Collect batch_ids BEFORE deleting import_batches (raw_uploads links via batch_id)
        batch_ids = [
            b["_id"] for b in db.import_batches.find(
                {"owner_id": {"$in": user_ids}}, {"_id": 1},
            )
        ]

        # Delete all data owned by test users
        for collection in [
            "bottles", "cases", "wine_events",
            "wines", "transactions", "import_batches", "cellar_events",
        ]:
            result = db[collection].delete_many({"owner_id": {"$in": user_ids}})
            if result.deleted_count:
                print(f"  cleaned {collection}: {result.deleted_count:,} docs")

        # Also clean cellar_events with owner_id=None (from tests that don't set it)
        result = db.cellar_events.delete_many({"owner_id": None})
        if result.deleted_count:
            print(f"  cleaned cellar_events (owner_id=None): {result.deleted_count:,} docs")

        # cellars uses cellar_id, not owner_id
        result = db.cellars.delete_many({"cellar_id": {"$in": user_ids}})
        if result.deleted_count:
            print(f"  cleaned cellars: {result.deleted_count:,} docs")

        # raw_uploads links via batch_id (collected before import_batches were deleted)
        if batch_ids:
            result = db.raw_uploads.delete_many({"batch_id": {"$in": batch_ids}})
            if result.deleted_count:
                print(f"  cleaned raw_uploads: {result.deleted_count:,} docs")

        # Delete the test users themselves
        result = db.users.delete_many({"_id": {"$in": user_ids}})

        print(
            f"\nE2E cleanup: deleted {result.deleted_count} test users "
            f"from {db_name} ({', '.join(emails[:5])}{'...' if len(emails) > 5 else ''})",
        )
        client.close()
    except Exception as e:
        print(f"\nE2E cleanup warning: {e}")


# Create a test-specific app to avoid lifespan conflicts
def create_test_app():
    """Create a FastAPI app configured for testing (no database lifespan).

    Mounts the regstack auth router explicitly — the production app does
    this inside its lifespan, which doesn't run for ASGI test clients.
    """
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse, RedirectResponse

    from winebox import __version__
    from winebox.auth.regstack_setup import build_regstack
    from winebox.config import settings

    # Empty lifespan for testing - we manage the database ourselves
    @asynccontextmanager
    async def test_lifespan(app: FastAPI):
        yield

    test_app = FastAPI(
        title="WineBox Test",
        version=__version__,
        lifespan=test_lifespan,
    )

    # Copy routes from main_app FIRST so the override `/api/auth/me`
    # registered there wins over regstack's own /me when both match.
    from winebox.main import app as main_app, SecurityHeadersMiddleware

    for route in main_app.routes:
        test_app.routes.append(route)

    # Now mount regstack — for paths the main app already serves (notably
    # the /me override), FastAPI tries routes in registration order, so the
    # main-app-side handler is matched first and these regstack handlers
    # become dead aliases. That's fine.
    rs = build_regstack()
    test_app.include_router(rs.router, prefix=rs.config.api_prefix)

    # Add security headers middleware (same as main app)
    test_app.add_middleware(SecurityHeadersMiddleware)

    # Add health check
    @test_app.get("/health", tags=["Health"])
    async def health_check() -> JSONResponse:
        return JSONResponse(
            content={
                "status": "healthy",
                "version": __version__,
                "app_name": settings.app_name,
            }
        )

    @test_app.get("/", tags=["Root"])
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/static/index.html")

    return test_app


# Get or create test app (singleton for test session)
_test_app = None

def get_test_app():
    """Get the test app singleton."""
    global _test_app
    if _test_app is None:
        _test_app = create_test_app()
    return _test_app


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use the default event loop policy."""
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="session")
async def mongo_client():
    """Create a MongoDB client for testing.

    Session-scoped: one client per xdist worker process.
    """
    client = AsyncMongoClient(
        TEST_MONGODB_URL,
        maxPoolSize=10,
        minPoolSize=1,
    )
    yield client
    await client.close()


@pytest_asyncio.fixture(scope="session")
async def init_test_db(mongo_client):
    """Initialize shared test database across all xdist workers.

    The database was dropped by pytest_configure in the controller process.
    ensure_indexes() is idempotent — first worker creates them, others
    find them already present.

    Also brings up the embedded regstack instance against `SHARED_TEST_DB`
    so auth endpoints in tests resolve through regstack just like
    production. We have to override the live Settings before
    `build_regstack()` runs, because regstack snapshots the database name
    at construction time.
    """
    await init_db(mongo_client=mongo_client, mongodb_database=SHARED_TEST_DB)

    from winebox.auth.regstack_setup import build_regstack, reset_regstack
    from winebox.config import settings as _settings

    # Pin regstack at the shared test DB regardless of what the
    # environment-driven settings defaulted to.
    _settings._config.database.mongodb_database = SHARED_TEST_DB
    reset_regstack()
    rs = build_regstack()
    await rs.backend.install_schema()

    from winebox.database import get_database

    yield get_database()
    # No per-worker cleanup: database is dropped at the start of the next run


@pytest_asyncio.fixture
async def isolated_db(mongo_client):
    """Isolated database for tests that purge all data.

    Creates a throwaway database, switches both the WineBox connection
    AND the regstack singleton to point at it, runs the test, then
    restores the shared connection / singleton. Also forces a rebuild
    of the test ASGI app so its mounted regstack routes resolve through
    the new instance. Safe because xdist runs tests sequentially within
    a worker.
    """
    db_name = f"test_winebox_isolated_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    await init_db(
        mongo_client=mongo_client, mongodb_database=db_name, skip_indexes=True
    )

    from winebox.auth.regstack_setup import build_regstack, reset_regstack
    from winebox.config import settings as _settings

    # Override the database name on the live settings so build_regstack()
    # below targets the isolated DB. We restore on teardown.
    saved_db_name = _settings._config.database.mongodb_database
    _settings._config.database.mongodb_database = db_name

    reset_regstack()
    iso_rs = build_regstack()
    await iso_rs.backend.install_schema()

    # Invalidate the test-app singleton so its included regstack router is
    # rebuilt against `iso_rs`.
    global _test_app
    saved_test_app = _test_app
    _test_app = None

    from winebox.database import get_database

    try:
        yield get_database()
    finally:
        # Restore the shared DB, singleton, and cached test app.
        _settings._config.database.mongodb_database = saved_db_name
        await mongo_client.drop_database(db_name)
        await init_db(
            mongo_client=mongo_client,
            mongodb_database=SHARED_TEST_DB,
            skip_indexes=True,
        )
        reset_regstack()
        build_regstack()
        _test_app = saved_test_app


@pytest.fixture
def test_user_email():
    """Generate a unique email for each test's user.

    Function-scoped so each test gets its own user. Fixtures that need
    the current test user's email should depend on this fixture.
    """
    return f"test-{uuid.uuid4().hex[:8]}@example.com"


@pytest_asyncio.fixture(scope="function")
async def client(init_test_db, test_user_email) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client with a unique authenticated user."""
    test_user = User(
        email=test_user_email,
        hashed_password=_CACHED_TEST_PASSWORD_HASH,
        is_active=True,
        is_verified=True,
        is_superuser=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await test_user.insert()

    access_token = await create_access_token(data={"sub": test_user_email})

    # Use test app instead of main app
    app = get_test_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {access_token}"}
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def admin_client(init_test_db) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client with an admin user."""
    admin_email = f"admin_{uuid.uuid4().hex[:8]}@test.example.com"
    admin_user = User(
        email=admin_email,
        hashed_password=_CACHED_TEST_PASSWORD_HASH,
        is_active=True,
        is_verified=True,
        is_superuser=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await admin_user.insert()

    access_token = await create_access_token(data={"sub": admin_email})
    app = get_test_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {access_token}"}
    ) as ac:
        yield ac


@pytest.fixture
def temp_image_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test images."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_image_bytes() -> bytes:
    """Create sample image bytes for testing."""
    # Create a minimal valid PNG (1x1 pixel, red)
    # PNG header and minimal IHDR, IDAT, IEND chunks
    png_data = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D,  # IHDR length
        0x49, 0x48, 0x44, 0x52,  # IHDR
        0x00, 0x00, 0x00, 0x01,  # width: 1
        0x00, 0x00, 0x00, 0x01,  # height: 1
        0x08, 0x02,  # bit depth: 8, color type: RGB
        0x00, 0x00, 0x00,  # compression, filter, interlace
        0x90, 0x77, 0x53, 0xDE,  # CRC
        0x00, 0x00, 0x00, 0x0C,  # IDAT length
        0x49, 0x44, 0x41, 0x54,  # IDAT
        0x08, 0xD7, 0x63, 0xF8, 0xFF, 0xFF, 0x3F, 0x00,  # compressed data
        0x05, 0xFE, 0x02, 0xFE,  # CRC
        0xA3, 0x1A, 0x8D, 0xEB,  # CRC
        0x00, 0x00, 0x00, 0x00,  # IEND length
        0x49, 0x45, 0x4E, 0x44,  # IEND
        0xAE, 0x42, 0x60, 0x82,  # CRC
    ])
    return png_data


@pytest.fixture
def test_user(test_user_email) -> dict:
    """Return test user credentials."""
    return {
        "email": test_user_email,
        "password": "testpassword",
    }


@pytest_asyncio.fixture
async def auth_headers(test_user, init_test_db) -> dict:
    """Return authorization headers for the test user.

    Inserts the user record on demand so the token's `sub` (user_id)
    resolves to a real account in the regstack user lookup.
    """
    existing = await User.find_one({"email": test_user["email"]})
    if existing is None:
        await User(
            email=test_user["email"],
            hashed_password=_CACHED_TEST_PASSWORD_HASH,
            is_active=True,
            is_verified=True,
            is_superuser=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ).insert()
    access_token = await create_access_token(data={"sub": test_user["email"]})
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture(scope="function")
async def unauthenticated_client(init_test_db) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client without authentication."""
    app = get_test_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as ac:
        yield ac
