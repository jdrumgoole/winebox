"""Tests for RevokedToken model - JWT token blacklist."""

from datetime import datetime, timedelta, timezone

import pytest

from winebox.models.token_blacklist import RevokedToken


@pytest.mark.asyncio
class TestRevokeToken:
    """Tests for token revocation."""

    async def test_revoke_token_creates_document(self, init_test_db):
        """Document created with jti and expires_at."""
        expires = datetime.now(timezone.utc) + timedelta(hours=2)
        token = await RevokedToken.revoke_token(jti="test-jti-1", expires_at=expires)

        assert token.jti == "test-jti-1"
        assert token.expires_at == expires
        assert token.id is not None
        assert token.revoked_at is not None

    async def test_revoke_with_user_id_and_reason(self, init_test_db):
        """Optional fields stored correctly."""
        expires = datetime.now(timezone.utc) + timedelta(hours=2)
        token = await RevokedToken.revoke_token(
            jti="test-jti-2",
            expires_at=expires,
            user_id="user-123",
            reason="password_change",
        )

        assert token.user_id == "user-123"
        assert token.reason == "password_change"

    async def test_revoke_same_jti_twice_is_idempotent(self, init_test_db):
        """Revoking same jti twice: first succeeds, second is still findable as revoked."""
        expires = datetime.now(timezone.utc) + timedelta(hours=2)
        await RevokedToken.revoke_token(jti="dup-jti", expires_at=expires)

        # The jti should be revoked
        assert await RevokedToken.is_revoked("dup-jti") is True


@pytest.mark.asyncio
class TestIsRevoked:
    """Tests for revocation checks."""

    async def test_is_revoked_true_for_revoked(self, init_test_db):
        """is_revoked() returns True after revocation."""
        expires = datetime.now(timezone.utc) + timedelta(hours=2)
        await RevokedToken.revoke_token(jti="revoked-jti", expires_at=expires)

        assert await RevokedToken.is_revoked("revoked-jti") is True

    async def test_is_revoked_false_for_unknown(self, init_test_db):
        """is_revoked() returns False for unknown jti."""
        assert await RevokedToken.is_revoked("nonexistent-jti") is False


@pytest.mark.asyncio
class TestCleanupExpired:
    """Tests for cleanup of expired tokens."""

    async def test_cleanup_expired_removes_old(self, init_test_db):
        """Tokens with past expires_at removed."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        await RevokedToken.revoke_token(jti="expired-jti", expires_at=past)

        removed = await RevokedToken.cleanup_expired()
        assert removed == 1

    async def test_cleanup_expired_preserves_active(self, init_test_db):
        """Tokens with future expires_at kept."""
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        await RevokedToken.revoke_token(jti="active-jti", expires_at=future)

        removed = await RevokedToken.cleanup_expired()
        assert removed == 0

        # Token should still exist
        assert await RevokedToken.is_revoked("active-jti") is True
