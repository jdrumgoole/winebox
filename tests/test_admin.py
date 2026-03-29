"""Tests for admin panel endpoints."""

import io
import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from winebox.models import User
from winebox.services.auth import create_access_token, get_password_hash

# Pre-compute password hashes — Argon2 is deliberately slow (~38ms per call)
_HASH_ADMIN = get_password_hash("adminpassword")
_HASH_USER = get_password_hash("userpassword")
_HASH_PASSWORD1 = get_password_hash("password1")
_HASH_PASSWORD2 = get_password_hash("password2")
_HASH_PASSWORD3 = get_password_hash("password3")


@pytest_asyncio.fixture(scope="function")
async def admin_client(init_test_db):
    """Create an authenticated admin client."""
    from tests.conftest import get_test_app

    admin_email = f"admin-{uuid.uuid4().hex[:8]}@example.com"

    # Create admin user
    admin_user = User(
        email=admin_email,
        hashed_password=_HASH_ADMIN,
        is_active=True,
        is_verified=True,
        is_superuser=True,  # This is an admin
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    await admin_user.insert()
    token = create_access_token(data={"sub": admin_email})

    app = get_test_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def regular_user_client(init_test_db):
    """Create an authenticated regular (non-admin) client."""
    from tests.conftest import get_test_app

    user_email = f"user-{uuid.uuid4().hex[:8]}@example.com"

    # Create regular user
    user = User(
        email=user_email,
        hashed_password=_HASH_USER,
        is_active=True,
        is_verified=True,
        is_superuser=False,  # Not an admin
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    await user.insert()
    token = create_access_token(data={"sub": user_email})

    app = get_test_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def populated_admin_client(init_test_db, sample_image_bytes):
    """Create admin client with some users and wines."""
    from tests.conftest import get_test_app

    uid = uuid.uuid4().hex[:8]
    admin_email = f"admin-{uid}@example.com"
    user1_email = f"user1-{uid}@example.com"
    user2_email = f"user2-{uid}@example.com"
    inactive_email = f"inactive-{uid}@example.com"

    # Create admin user
    admin_user = User(
        email=admin_email,
        hashed_password=_HASH_ADMIN,
        is_active=True,
        is_verified=True,
        is_superuser=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    await admin_user.insert()

    # Create regular user 1
    user1 = User(
        email=user1_email,
        hashed_password=_HASH_PASSWORD1,
        is_active=True,
        is_verified=True,
        is_superuser=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    await user1.insert()

    # Create regular user 2 (unverified)
    user2 = User(
        email=user2_email,
        hashed_password=_HASH_PASSWORD2,
        is_active=True,
        is_verified=False,  # Not verified
        is_superuser=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    await user2.insert()

    # Create inactive user
    user3 = User(
        email=inactive_email,
        hashed_password=_HASH_PASSWORD3,
        is_active=False,  # Inactive
        is_verified=True,
        is_superuser=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    await user3.insert()

    admin_token = create_access_token(data={"sub": admin_email})
    user1_token = create_access_token(data={"sub": user1_email})

    app = get_test_app()

    # Check in some wines for user1
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {user1_token}"},
    ) as user1_client:
        files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
        data = {"name": "User1 Wine", "quantity": "5"}
        await user1_client.post("/api/wines/checkin", files=files, data=data)

    # Return admin client with email info attached
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as admin_client:
        # Attach emails for test assertions
        admin_client._test_emails = {
            "admin": admin_email,
            "user1": user1_email,
            "user2": user2_email,
            "inactive": inactive_email,
        }
        yield admin_client


@pytest.fixture
def sample_image_bytes() -> bytes:
    """Create sample image bytes for testing."""
    png_data = bytes([
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
    return png_data


# =============================================================================
# ADMIN ACCESS CONTROL TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_admin_users_endpoint_requires_admin(regular_user_client) -> None:
    """Test that regular users cannot access admin endpoints."""
    response = await regular_user_client.get("/admin/api/users")
    assert response.status_code == 403
    assert "Admin privileges required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_admin_stats_endpoint_requires_admin(regular_user_client) -> None:
    """Test that regular users cannot access admin stats endpoint."""
    response = await regular_user_client.get("/admin/api/stats")
    assert response.status_code == 403
    assert "Admin privileges required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_admin_can_access_users_endpoint(admin_client) -> None:
    """Test that admin users can access the users endpoint."""
    response = await admin_client.get("/admin/api/users")
    assert response.status_code == 200
    data = response.json()
    assert "users" in data
    assert "total_users" in data


@pytest.mark.asyncio
async def test_admin_can_access_stats_endpoint(admin_client) -> None:
    """Test that admin users can access the stats endpoint."""
    response = await admin_client.get("/admin/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert "users" in data
    assert "wines" in data


# =============================================================================
# ADMIN STATS TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_admin_stats_shows_correct_user_counts(populated_admin_client) -> None:
    """Test that admin stats show correct user counts."""
    response = await populated_admin_client.get("/admin/api/stats")
    assert response.status_code == 200

    data = response.json()
    users = data["users"]

    # We have at least 4 users total: 1 admin + 3 regular
    assert users["total"] >= 4
    # At least 3 active (admin + user1 + user2)
    assert users["active"] >= 3
    # At least 3 verified (admin + user1 + inactive)
    assert users["verified"] >= 3
    # At least 1 admin
    assert users["admins"] >= 1


@pytest.mark.asyncio
async def test_admin_stats_shows_correct_wine_counts(populated_admin_client) -> None:
    """Test that admin stats show correct wine counts."""
    response = await populated_admin_client.get("/admin/api/stats")
    assert response.status_code == 200

    data = response.json()
    wines = data["wines"]

    # We checked in at least 1 wine with 5 bottles
    assert wines["in_stock"] >= 1
    assert wines["total_bottles"] >= 5


# =============================================================================
# ADMIN USERS LIST TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_admin_users_list_includes_all_users(populated_admin_client) -> None:
    """Test that admin users list includes all users."""
    response = await populated_admin_client.get("/admin/api/users")
    assert response.status_code == 200

    data = response.json()
    users = data["users"]

    # We have at least 4 users total
    assert len(users) >= 4
    assert data["total_users"] >= 4

    # Verify all expected users are present
    emails = [user["email"] for user in users]
    expected_emails = populated_admin_client._test_emails
    assert expected_emails["admin"] in emails
    assert expected_emails["user1"] in emails
    assert expected_emails["user2"] in emails
    assert expected_emails["inactive"] in emails


@pytest.mark.asyncio
async def test_admin_users_list_shows_cellar_sizes(populated_admin_client) -> None:
    """Test that admin users list shows correct cellar sizes."""
    response = await populated_admin_client.get("/admin/api/users")
    assert response.status_code == 200

    data = response.json()
    users = data["users"]

    expected_emails = populated_admin_client._test_emails

    # Find user1 who has wines
    user1 = next((u for u in users if u["email"] == expected_emails["user1"]), None)
    assert user1 is not None
    assert user1["cellar_size"] == 5

    # Admin and other users should have 0 bottles
    admin = next((u for u in users if u["email"] == expected_emails["admin"]), None)
    assert admin is not None
    assert admin["cellar_size"] == 0


@pytest.mark.asyncio
async def test_admin_users_list_shows_correct_status_flags(populated_admin_client) -> None:
    """Test that admin users list shows correct status flags."""
    response = await populated_admin_client.get("/admin/api/users")
    assert response.status_code == 200

    data = response.json()
    users = data["users"]

    expected_emails = populated_admin_client._test_emails

    # Admin user
    admin = next((u for u in users if u["email"] == expected_emails["admin"]), None)
    assert admin["is_superuser"] is True
    assert admin["is_active"] is True
    assert admin["is_verified"] is True

    # Unverified user
    user2 = next((u for u in users if u["email"] == expected_emails["user2"]), None)
    assert user2["is_superuser"] is False
    assert user2["is_active"] is True
    assert user2["is_verified"] is False

    # Inactive user
    inactive = next((u for u in users if u["email"] == expected_emails["inactive"]), None)
    assert inactive["is_superuser"] is False
    assert inactive["is_active"] is False
    assert inactive["is_verified"] is True


@pytest.mark.asyncio
async def test_admin_users_list_includes_timestamps(populated_admin_client) -> None:
    """Test that admin users list includes created_at timestamps."""
    response = await populated_admin_client.get("/admin/api/users")
    assert response.status_code == 200

    data = response.json()
    users = data["users"]

    for user in users:
        assert "created_at" in user
        assert user["created_at"] is not None


# =============================================================================
# UNAUTHENTICATED ACCESS TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_admin_endpoints_require_authentication(unauthenticated_client) -> None:
    """Test that admin endpoints require authentication."""
    response = await unauthenticated_client.get("/admin/api/users")
    assert response.status_code == 401

    response = await unauthenticated_client.get("/admin/api/stats")
    assert response.status_code == 401
