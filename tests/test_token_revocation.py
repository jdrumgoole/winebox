"""Tests for token revocation in auth service and endpoints."""

import pytest
from httpx import AsyncClient

from winebox.services.auth import create_access_token, get_current_user, get_password_hash, revoke_token

# Pre-compute password hash — Argon2 is deliberately slow (~38ms per call)
_HASH_TESTPASS = get_password_hash("testpass")


@pytest.mark.asyncio
class TestRevokeTokenService:
    """Tests for revoke_token() in auth service."""

    async def test_revoke_token_returns_true(self, init_test_db):
        """Valid token revocation succeeds."""
        token = create_access_token(data={"sub": "test@example.com"})
        result = await revoke_token(token)
        assert result is True

    async def test_revoke_invalid_jwt_returns_false(self, init_test_db):
        """Garbage string handled gracefully."""
        result = await revoke_token("not-a-valid-jwt-token")
        assert result is False

    async def test_revoke_token_without_jti(self, init_test_db):
        """JWT missing jti claim handled (our tokens always have jti, but test edge case)."""
        import jwt
        from winebox.config import settings
        from winebox.services.auth import ALGORITHM
        from datetime import datetime, timedelta, timezone

        # Create a token without jti
        expire = datetime.now(timezone.utc) + timedelta(hours=1)
        token = jwt.encode(
            {"sub": "test@example.com", "exp": expire},
            settings.secret_key,
            algorithm=ALGORITHM,
        )
        result = await revoke_token(token)
        assert result is False


@pytest.mark.asyncio
class TestRevokedTokenRejection:
    """Tests for revoked token being rejected by get_current_user."""

    async def test_get_current_user_rejects_revoked(self, init_test_db):
        """Revoked token returns None from get_current_user."""
        from winebox.models.user import User

        # Create user first
        user = User(
            email="revoke-test@example.com",
            hashed_password=_HASH_TESTPASS,
            is_active=True,
            is_verified=True,
            is_superuser=False,
        )
        await user.insert()

        token = create_access_token(data={"sub": "revoke-test@example.com"})

        # Before revocation, user should be found
        found_user = await get_current_user(token)
        assert found_user is not None
        assert found_user.email == "revoke-test@example.com"

        # Revoke the token
        await revoke_token(token)

        # After revocation, should return None
        found_user = await get_current_user(token)
        assert found_user is None


@pytest.mark.asyncio
class TestLogoutRevokesToken:
    """Tests for logout endpoint revoking tokens."""

    async def test_logout_revokes_token(self, init_test_db):
        """Revoking a token via revoke_token makes get_current_user reject it."""
        from winebox.models.user import User
        user = User(
            email="logout-test@example.com",
            hashed_password=_HASH_TESTPASS,
            is_active=True,
            is_verified=True,
            is_superuser=False,
        )
        await user.insert()

        token = create_access_token(data={"sub": "logout-test@example.com"})

        # Token works before revocation
        found = await get_current_user(token)
        assert found is not None

        # Revoke (simulating logout)
        result = await revoke_token(token, user_id=str(user.id), reason="logout")
        assert result is True

        # Token rejected after revocation
        found = await get_current_user(token)
        assert found is None

    async def test_password_change_revokes_token(self, client: AsyncClient):
        """PUT /api/auth/password then reuse old token -> 401."""
        response = await client.put(
            "/api/auth/password",
            json={
                "current_password": "testpassword",
                "new_password": "newpassword123",
            },
        )
        assert response.status_code == 200

        # Old token should be revoked
        response = await client.get("/api/auth/me")
        assert response.status_code == 401
