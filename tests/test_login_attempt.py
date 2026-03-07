"""Tests for LoginAttempt model - account lockout tracking."""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from winebox.models.login_attempt import LoginAttempt


@pytest.mark.asyncio
class TestRecordAttempt:
    """Tests for recording login attempts."""

    async def test_record_attempt_creates_document(self, init_test_db):
        """Document created with correct email, failed flag, timestamp."""
        attempt = await LoginAttempt.record_attempt("user@example.com", failed=True)

        assert attempt.email == "user@example.com"
        assert attempt.failed is True
        assert attempt.attempted_at is not None
        assert attempt.id is not None

    async def test_record_attempt_lowercases_email(self, init_test_db):
        """Mixed-case email stored as lowercase."""
        attempt = await LoginAttempt.record_attempt("User@EXAMPLE.Com")

        assert attempt.email == "user@example.com"

    async def test_record_attempt_stores_ip(self, init_test_db):
        """IP address is stored when provided."""
        attempt = await LoginAttempt.record_attempt(
            "user@example.com", ip_address="192.168.1.1"
        )

        assert attempt.ip_address == "192.168.1.1"


@pytest.mark.asyncio
class TestIsLockedOut:
    """Tests for account lockout detection."""

    async def test_is_locked_out_false_when_no_attempts(self, init_test_db):
        """Fresh email not locked out."""
        assert await LoginAttempt.is_locked_out("fresh@example.com") is False

    async def test_is_locked_out_false_below_threshold(self, init_test_db):
        """4 failures (below MAX_FAILED_ATTEMPTS=5) not locked."""
        for _ in range(4):
            await LoginAttempt.record_attempt("user@example.com", failed=True)

        assert await LoginAttempt.is_locked_out("user@example.com") is False

    async def test_is_locked_out_true_at_threshold(self, init_test_db):
        """5 failures triggers lockout."""
        for _ in range(5):
            await LoginAttempt.record_attempt("user@example.com", failed=True)

        assert await LoginAttempt.is_locked_out("user@example.com") is True

    async def test_is_locked_out_true_above_threshold(self, init_test_db):
        """7 failures still locked."""
        for _ in range(7):
            await LoginAttempt.record_attempt("user@example.com", failed=True)

        assert await LoginAttempt.is_locked_out("user@example.com") is True

    async def test_lockout_respects_window(self, init_test_db):
        """Old attempts outside LOCKOUT_WINDOW_MINUTES don't count."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=20)

        # Insert 5 old attempts directly
        for _ in range(5):
            attempt = LoginAttempt(
                email="user@example.com",
                failed=True,
                attempted_at=old_time,
            )
            await attempt.insert()

        # Old attempts should not cause lockout
        assert await LoginAttempt.is_locked_out("user@example.com") is False


@pytest.mark.asyncio
class TestGetLockoutRemainingSeconds:
    """Tests for lockout remaining time."""

    async def test_get_lockout_remaining_seconds(self, init_test_db):
        """Returns positive value when locked out."""
        for _ in range(5):
            await LoginAttempt.record_attempt("user@example.com", failed=True)

        remaining = await LoginAttempt.get_lockout_remaining_seconds("user@example.com")
        assert remaining > 0
        assert remaining <= LoginAttempt.LOCKOUT_DURATION_MINUTES * 60

    async def test_get_lockout_remaining_zero_when_not_locked(self, init_test_db):
        """Returns 0 when not locked out."""
        remaining = await LoginAttempt.get_lockout_remaining_seconds("fresh@example.com")
        assert remaining == 0


@pytest.mark.asyncio
class TestClearAttempts:
    """Tests for clearing login attempts."""

    async def test_clear_attempts_removes_all(self, init_test_db):
        """Clears attempts, returns count, unlocks account."""
        for _ in range(5):
            await LoginAttempt.record_attempt("user@example.com", failed=True)

        assert await LoginAttempt.is_locked_out("user@example.com") is True

        count = await LoginAttempt.clear_attempts("user@example.com")
        assert count == 5
        assert await LoginAttempt.is_locked_out("user@example.com") is False


@pytest.mark.asyncio
class TestCleanupOldAttempts:
    """Tests for cleanup of old attempts."""

    async def test_cleanup_old_attempts(self, init_test_db):
        """Removes old attempts, preserves recent ones."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)

        # Insert old attempt
        old = LoginAttempt(email="user@example.com", failed=True, attempted_at=old_time)
        await old.insert()

        # Insert recent attempt
        recent = LoginAttempt(email="user@example.com", failed=True, attempted_at=recent_time)
        await recent.insert()

        removed = await LoginAttempt.cleanup_old_attempts(older_than_hours=24)
        assert removed == 1

        # Recent attempt should still exist
        remaining = await LoginAttempt.find(
            LoginAttempt.email == "user@example.com"
        ).count()
        assert remaining == 1
