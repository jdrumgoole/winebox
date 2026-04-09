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
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
import tempfile
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pymongo import AsyncMongoClient

from winebox.database import init_db
from winebox.models import User
from winebox.services.auth import get_password_hash, create_access_token

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
        from pymongo import MongoClient

        url = os.environ.get("TEST_MONGODB_URL", "mongodb://localhost:27017")
        sync_client = MongoClient(url)
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

        # Delete all data owned by test users
        for collection in ["wines", "transactions", "import_batches", "raw_uploads", "cellars", "cellar_events"]:
            db[collection].delete_many({"owner_id": {"$in": user_ids}})

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
    """Create a FastAPI app configured for testing (no database lifespan)."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse, RedirectResponse
    from winebox import __version__
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

    # Copy routes from the main app
    from winebox.main import app as main_app, SecurityHeadersMiddleware

    # Copy all routes
    for route in main_app.routes:
        test_app.routes.append(route)

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
    """
    await init_db(mongo_client=mongo_client, mongodb_database=SHARED_TEST_DB)

    from winebox.database import get_database

    yield get_database()
    # No per-worker cleanup: database is dropped at the start of the next run


@pytest_asyncio.fixture
async def isolated_db(mongo_client):
    """Isolated database for tests that purge all data.

    Creates a throwaway database, switches the global to it,
    runs the test, then restores the shared database connection.
    Safe because xdist runs tests sequentially within a worker.
    """
    db_name = f"test_winebox_isolated_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    await init_db(
        mongo_client=mongo_client, mongodb_database=db_name, skip_indexes=True
    )

    from winebox.database import get_database

    yield get_database()
    await mongo_client.drop_database(db_name)
    # Restore the shared database connection
    await init_db(
        mongo_client=mongo_client, mongodb_database=SHARED_TEST_DB, skip_indexes=True
    )


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

    # Create auth token with email as subject
    access_token = create_access_token(data={"sub": test_user_email})

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

    access_token = create_access_token(data={"sub": admin_email})
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


@pytest.fixture
def auth_headers(test_user) -> dict:
    """Return authorization headers for the test user."""
    access_token = create_access_token(data={"sub": test_user["email"]})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def mock_email_service():
    """Mock email service to prevent actual email sending in tests."""
    with patch("winebox.auth.users.get_email_service") as mock:
        mock_service = AsyncMock()
        mock_service.send_verification_email = AsyncMock(return_value=True)
        mock_service.send_password_reset_email = AsyncMock(return_value=True)
        mock.return_value = mock_service
        yield mock_service


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
