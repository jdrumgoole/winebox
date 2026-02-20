"""Pytest configuration and fixtures for WineBox tests with real MongoDB."""

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator
import tempfile
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from beanie import init_beanie
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from winebox.database import get_document_models
from winebox.models import User
from winebox.services.auth import get_password_hash, create_access_token


# MongoDB connection URL for tests (can be overridden with env var)
TEST_MONGODB_URL = os.environ.get("TEST_MONGODB_URL", "mongodb://localhost:27017")


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
    from winebox.main import app as main_app

    # Copy all routes
    for route in main_app.routes:
        test_app.routes.append(route)

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


@pytest_asyncio.fixture(scope="function")
async def mongo_client():
    """Create a MongoDB client for testing.

    Function-scoped to avoid event loop issues with pytest-xdist.
    Motor manages its own connection pool internally, so connections
    are reused at the driver level even with function-scoped fixtures.
    """
    client = AsyncIOMotorClient(
        TEST_MONGODB_URL,
        maxPoolSize=10,
        minPoolSize=1,
    )
    yield client
    client.close()


@pytest_asyncio.fixture(scope="function")
async def init_test_db(mongo_client):
    """Initialize Beanie with a unique test database.

    Creates a unique database for each test function and drops it after the test.
    The MongoDB client connection is reused across tests within each worker.
    """
    # Create unique database name for this test
    db_name = f"test_winebox_{uuid.uuid4().hex[:8]}"
    db = mongo_client[db_name]

    await init_beanie(
        database=db,
        document_models=get_document_models(),
    )
    yield db

    # Cleanup: drop the entire test database
    await mongo_client.drop_database(db_name)


@pytest_asyncio.fixture(scope="function")
async def client(init_test_db) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client with overridden database and auth."""
    # Create a test user
    test_user = User(
        email="test@example.com",
        hashed_password=get_password_hash("testpassword"),
        is_active=True,
        is_verified=True,
        is_superuser=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    await test_user.insert()

    # Create auth token with email as subject
    access_token = create_access_token(data={"sub": "test@example.com"})

    # Use test app instead of main app
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
def test_user() -> dict:
    """Return test user credentials."""
    return {
        "email": "test@example.com",
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
