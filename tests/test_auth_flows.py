"""Tests for authentication flows with fastapi-users."""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from winebox.main import app


@pytest.fixture
def mock_email_service():
    """Mock email service to prevent actual email sending."""
    with patch("winebox.auth.users.get_email_service") as mock:
        mock_service = AsyncMock()
        mock_service.send_verification_email = AsyncMock(return_value=True)
        mock_service.send_password_reset_email = AsyncMock(return_value=True)
        mock.return_value = mock_service
        yield mock_service


class TestRegistration:
    """Tests for user registration flow."""

    @pytest.mark.asyncio
    async def test_register_new_user(self, client: AsyncClient, mock_email_service):
        """Test registering a new user."""
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "securepassword123",
            },
        )

        # Registration may return 201 or 200 depending on fastapi-users version
        assert response.status_code in [200, 201]

        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient, test_user):
        """Test registering with an existing email."""
        response = await client.post(
            "/api/auth/register",
            json={
                "email": test_user["email"],  # Duplicate email
                "password": "securepassword123",
            },
        )

        assert response.status_code == 400
        assert "already" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, client: AsyncClient):
        """Test registering with an invalid email."""
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "not-an-email",
                "password": "securepassword123",
            },
        )

        assert response.status_code == 422  # Validation error


class TestLogin:
    """Tests for user login flow."""

    @pytest.mark.asyncio
    async def test_login_with_email(self, client: AsyncClient, test_user):
        """Test login with email."""
        response = await client.post(
            "/api/auth/token",
            data={
                "username": test_user["email"],  # OAuth2 uses 'username' field
                "password": test_user["password"],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_invalid_password(self, client: AsyncClient, test_user):
        """Test login with invalid password."""
        response = await client.post(
            "/api/auth/token",
            data={
                "username": test_user["email"],
                "password": "wrongpassword",
            },
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Test login with nonexistent email."""
        response = await client.post(
            "/api/auth/token",
            data={
                "username": "nonexistent@example.com",
                "password": "anypassword",
            },
        )

        assert response.status_code == 401


class TestForgotPassword:
    """Tests for forgot password flow."""

    @pytest.mark.asyncio
    async def test_forgot_password_existing_email(
        self, client: AsyncClient, test_user, mock_email_service
    ):
        """Test forgot password with existing email."""
        response = await client.post(
            "/api/auth/forgot-password",
            json={"email": test_user["email"]},
        )

        # Returns 202 Accepted (doesn't reveal if email exists)
        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_forgot_password_nonexistent_email(
        self, client: AsyncClient, mock_email_service
    ):
        """Test forgot password with nonexistent email."""
        response = await client.post(
            "/api/auth/forgot-password",
            json={"email": "nonexistent@example.com"},
        )

        # Still returns 202 for security (doesn't reveal if email exists)
        assert response.status_code == 202


class TestCurrentUser:
    """Tests for current user endpoint."""

    @pytest.mark.asyncio
    async def test_get_me_authenticated(self, client: AsyncClient, auth_headers):
        """Test getting current user info when authenticated."""
        response = await client.get("/api/auth/me", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "email" in data
        assert "is_active" in data
        assert "is_verified" in data
    @pytest.mark.asyncio
    async def test_get_me_unauthenticated(self, unauthenticated_client: AsyncClient):
        """Test getting current user info when not authenticated."""
        response = await unauthenticated_client.get("/api/auth/me")

        assert response.status_code == 401


class TestPasswordChange:
    """Tests for password change flow."""

    @pytest.mark.asyncio
    async def test_change_password(self, client: AsyncClient, auth_headers, test_user):
        """Test changing password with correct current password."""
        response = await client.put(
            "/api/auth/password",
            headers=auth_headers,
            json={
                "current_password": test_user["password"],
                "new_password": "newpassword123",
            },
        )

        assert response.status_code == 200
        assert "success" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_change_password_wrong_current(
        self, client: AsyncClient, auth_headers
    ):
        """Test changing password with wrong current password."""
        response = await client.put(
            "/api/auth/password",
            headers=auth_headers,
            json={
                "current_password": "wrongpassword",
                "new_password": "newpassword123",
            },
        )

        assert response.status_code == 400


