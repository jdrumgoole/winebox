"""Login attempt tracking model for account lockout."""

from datetime import datetime, timedelta, timezone
from typing import ClassVar

from beanie import Document, Indexed
from pydantic import Field


class LoginAttempt(Document):
    """Tracks failed login attempts for account lockout.

    After MAX_FAILED_ATTEMPTS failures within LOCKOUT_WINDOW_MINUTES,
    the account is locked for LOCKOUT_DURATION_MINUTES.
    """

    # Email being attempted (case-insensitive lookup via index)
    email: Indexed(str)

    # Timestamp of the attempt
    attempted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # IP address for logging (not used for lockout decisions)
    ip_address: str | None = None

    # Whether this was a failed attempt
    failed: bool = True

    class Settings:
        name = "login_attempts"
        indexes = [
            "email",
            "attempted_at",
        ]

    # Lockout configuration (ClassVar to avoid Pydantic treating as fields)
    MAX_FAILED_ATTEMPTS: ClassVar[int] = 5
    LOCKOUT_WINDOW_MINUTES: ClassVar[int] = 15
    LOCKOUT_DURATION_MINUTES: ClassVar[int] = 15

    @classmethod
    async def record_attempt(
        cls,
        email: str,
        failed: bool = True,
        ip_address: str | None = None,
    ) -> "LoginAttempt":
        """Record a login attempt.

        Args:
            email: Email address attempted.
            failed: Whether the attempt failed.
            ip_address: Client IP address.

        Returns:
            The created LoginAttempt document.
        """
        attempt = cls(
            email=email.lower(),
            failed=failed,
            ip_address=ip_address,
        )
        await attempt.insert()
        return attempt

    @classmethod
    async def is_locked_out(cls, email: str) -> bool:
        """Check if an email is locked out due to too many failed attempts.

        Args:
            email: Email address to check.

        Returns:
            True if the email is locked out, False otherwise.
        """
        window_start = datetime.now(timezone.utc) - timedelta(
            minutes=cls.LOCKOUT_WINDOW_MINUTES
        )

        # Count failed attempts in the lockout window
        failed_count = await cls.find(
            cls.email == email.lower(),
            cls.failed == True,  # noqa: E712
            cls.attempted_at >= window_start,
        ).count()

        return failed_count >= cls.MAX_FAILED_ATTEMPTS

    @classmethod
    async def get_lockout_remaining_seconds(cls, email: str) -> int:
        """Get remaining lockout time in seconds.

        Args:
            email: Email address to check.

        Returns:
            Remaining lockout time in seconds, or 0 if not locked out.
        """
        window_start = datetime.now(timezone.utc) - timedelta(
            minutes=cls.LOCKOUT_WINDOW_MINUTES
        )

        # Get the most recent failed attempt
        latest_attempt = await cls.find_one(
            cls.email == email.lower(),
            cls.failed == True,  # noqa: E712
            cls.attempted_at >= window_start,
            sort=[("attempted_at", -1)],
        )

        if not latest_attempt:
            return 0

        # Count failed attempts
        failed_count = await cls.find(
            cls.email == email.lower(),
            cls.failed == True,  # noqa: E712
            cls.attempted_at >= window_start,
        ).count()

        if failed_count < cls.MAX_FAILED_ATTEMPTS:
            return 0

        # Calculate when lockout expires (from the Nth failed attempt)
        lockout_end = latest_attempt.attempted_at + timedelta(
            minutes=cls.LOCKOUT_DURATION_MINUTES
        )
        remaining = (lockout_end - datetime.now(timezone.utc)).total_seconds()

        return max(0, int(remaining))

    @classmethod
    async def clear_attempts(cls, email: str) -> int:
        """Clear all login attempts for an email (after successful login).

        Args:
            email: Email address to clear.

        Returns:
            Number of attempts cleared.
        """
        result = await cls.find(cls.email == email.lower()).delete()
        return result.deleted_count if result else 0

    @classmethod
    async def cleanup_old_attempts(cls, older_than_hours: int = 24) -> int:
        """Remove old login attempts for cleanup.

        Args:
            older_than_hours: Remove attempts older than this many hours.

        Returns:
            Number of attempts removed.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        result = await cls.find(cls.attempted_at < cutoff).delete()
        return result.deleted_count if result else 0
