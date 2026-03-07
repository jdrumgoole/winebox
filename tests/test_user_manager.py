"""Tests for UserManager callbacks and secret derivation."""

import hashlib
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from winebox.auth.users import _derive_secret


class TestDeriveSecret:
    """Tests for _derive_secret helper."""

    def test_derive_secret_different_per_purpose(self):
        """Different secrets for different purposes."""
        base = "my-secret-key"
        secret1 = _derive_secret(base, "reset_password")
        secret2 = _derive_secret(base, "verification")

        assert secret1 != secret2
        assert len(secret1) == 64  # SHA-256 hex digest
        assert len(secret2) == 64

    def test_derive_secret_deterministic(self):
        """Same inputs produce same output."""
        secret1 = _derive_secret("key", "purpose")
        secret2 = _derive_secret("key", "purpose")
        assert secret1 == secret2

    def test_derive_secret_matches_sha256(self):
        """Output matches expected SHA-256 hash."""
        base = "test-key"
        purpose = "test"
        expected = hashlib.sha256(f"{base}:{purpose}".encode()).hexdigest()
        assert _derive_secret(base, purpose) == expected


@pytest.mark.asyncio
class TestUserManagerCallbacks:
    """Tests for UserManager email callbacks."""

    async def test_on_after_forgot_password_sends_email(self, init_test_db, mock_email_service):
        """Reset email sent with token."""
        from winebox.auth.users import UserManager
        from winebox.models.user import User

        user = User(
            email="forgot@example.com",
            hashed_password="hashed",
            is_active=True,
            is_verified=True,
            is_superuser=False,
        )
        await user.insert()

        manager = UserManager(MagicMock())
        await manager.on_after_forgot_password(user, token="reset-token-123")

        mock_email_service.send_password_reset_email.assert_called_once_with(
            to_email="forgot@example.com",
            token="reset-token-123",
        )

    async def test_on_after_request_verify_sends_email(self, init_test_db, mock_email_service):
        """Verification email sent."""
        from winebox.auth.users import UserManager
        from winebox.models.user import User

        user = User(
            email="verify@example.com",
            hashed_password="hashed",
            is_active=True,
            is_verified=False,
            is_superuser=False,
        )
        await user.insert()

        manager = UserManager(MagicMock())
        await manager.on_after_request_verify(user, token="verify-token-456")

        mock_email_service.send_verification_email.assert_called_once_with(
            to_email="verify@example.com",
            token="verify-token-456",
        )
