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

    @pytest.mark.asyncio
    async def test_register_password_too_short(self, client: AsyncClient):
        """Test that registration rejects passwords shorter than 6 characters."""
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "shortpw@example.com",
                "password": "12345",
            },
        )

        assert response.status_code == 422
        body = response.json()
        assert "6 characters" in str(body)

    @pytest.mark.asyncio
    async def test_register_password_minimum_length_accepted(self, client: AsyncClient, mock_email_service):
        """Test that registration accepts passwords of exactly 6 characters."""
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "minpw@example.com",
                "password": "abcdef",
            },
        )

        assert response.status_code in [200, 201]


class TestEmailVerification:
    """Tests for email verification flow."""

    @pytest.mark.asyncio
    async def test_verify_token_succeeds(self, client: AsyncClient, mock_email_service):
        """Test that a verification token generated at registration actually works."""
        import jwt
        from winebox.auth.users import UserManager

        # Register a new user
        reg_resp = await client.post(
            "/api/auth/register",
            json={"email": "verify_test@example.com", "password": "securepassword123"},
        )
        assert reg_resp.status_code in [200, 201]
        user_id = reg_resp.json()["id"]

        # Generate a verification token (same way fastapi-users does internally)
        import time
        token = jwt.encode(
            {
                "sub": user_id,
                "email": "verify_test@example.com",
                "aud": "fastapi-users:verify",
                "exp": int(time.time()) + 3600,
            },
            UserManager.verification_token_secret,
            algorithm="HS256",
        )

        # Verify the token via the API
        verify_resp = await client.post(
            "/api/auth/verify",
            json={"token": token},
        )
        assert verify_resp.status_code == 200, (
            f"Verification failed with {verify_resp.status_code}: {verify_resp.json()}"
        )

    @pytest.mark.asyncio
    async def test_verify_bad_token_rejected(self, client: AsyncClient):
        """Test that an invalid token is rejected."""
        verify_resp = await client.post(
            "/api/auth/verify",
            json={"token": "invalid.token.here"},
        )
        assert verify_resp.status_code == 400
        assert verify_resp.json()["detail"] == "VERIFY_USER_BAD_TOKEN"

    @pytest.mark.asyncio
    async def test_parse_id_returns_objectid_not_coroutine(self):
        """Regression test: parse_id must be sync, not async.

        fastapi-users' verify() method calls parse_id() without await.
        If parse_id is async, it returns a coroutine that never equals
        the user's ObjectId, causing all verifications to fail.
        """
        import asyncio
        import inspect
        from winebox.auth.users import UserManager

        manager = UserManager.__new__(UserManager)
        result = manager.parse_id("507f1f77bcf86cd799439011")

        # Must NOT be a coroutine
        assert not asyncio.iscoroutine(result), (
            "parse_id must be synchronous — fastapi-users calls it without await"
        )
        assert not inspect.isawaitable(result), (
            "parse_id must not return an awaitable"
        )


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

    @pytest.mark.asyncio
    async def test_change_password_too_short(
        self, client: AsyncClient, auth_headers
    ):
        """Test that password change rejects new passwords shorter than 6 characters."""
        response = await client.put(
            "/api/auth/password",
            headers=auth_headers,
            json={
                "current_password": "testpassword123",
                "new_password": "short",
            },
        )

        assert response.status_code == 422
        body = response.json()
        assert "6 characters" in str(body)


class TestAccountLockout:
    """Tests for account lockout after failed login attempts."""

    @pytest.mark.asyncio
    async def test_login_locked_after_five_failures(self, client: AsyncClient, test_user):
        """5 wrong passwords -> 6th returns 429."""
        for _ in range(5):
            await client.post(
                "/api/auth/token",
                data={"username": test_user["email"], "password": "wrong"},
            )

        # 6th attempt should be locked
        response = await client.post(
            "/api/auth/token",
            data={"username": test_user["email"], "password": "wrong"},
        )
        assert response.status_code == 429

    @pytest.mark.asyncio
    async def test_successful_login_clears_attempts(self, client: AsyncClient, test_user):
        """Success resets failure counter."""
        # Record 4 failures (below threshold)
        for _ in range(4):
            await client.post(
                "/api/auth/token",
                data={"username": test_user["email"], "password": "wrong"},
            )

        # Successful login should clear attempts
        response = await client.post(
            "/api/auth/token",
            data={"username": test_user["email"], "password": test_user["password"]},
        )
        assert response.status_code == 200

        # Now 5 more failures should be needed to lock
        for _ in range(4):
            await client.post(
                "/api/auth/token",
                data={"username": test_user["email"], "password": "wrong"},
            )

        # Should not be locked yet (only 4 failures since clear)
        response = await client.post(
            "/api/auth/token",
            data={"username": test_user["email"], "password": test_user["password"]},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_lockout_includes_retry_after(self, client: AsyncClient, test_user):
        """Response has Retry-After header."""
        for _ in range(5):
            await client.post(
                "/api/auth/token",
                data={"username": test_user["email"], "password": "wrong"},
            )

        response = await client.post(
            "/api/auth/token",
            data={"username": test_user["email"], "password": "wrong"},
        )
        assert response.status_code == 429
        assert "retry-after" in response.headers
