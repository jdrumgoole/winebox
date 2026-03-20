"""Login attempt tracking model for account lockout."""

from datetime import datetime, timedelta, timezone
from typing import ClassVar

from pydantic import Field

from winebox.db import MongoDocument


class LoginAttempt(MongoDocument):
    """Tracks failed login attempts for account lockout.

    After MAX_FAILED_ATTEMPTS failures within LOCKOUT_WINDOW_MINUTES,
    the account is locked for LOCKOUT_DURATION_MINUTES.
    """

    # Email being attempted (case-insensitive lookup via index)
    email: str

    # Timestamp of the attempt
    attempted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # IP address for logging (not used for lockout decisions)
    ip_address: str | None = None

    # Whether this was a failed attempt
    failed: bool = True

    class Settings:
        name = "login_attempts"

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
        """Record a login attempt."""
        attempt = cls(
            email=email.lower(),
            failed=failed,
            ip_address=ip_address,
        )
        await attempt.insert()
        return attempt

    @classmethod
    async def is_locked_out(cls, email: str) -> bool:
        """Check if an email is locked out due to too many failed attempts."""
        window_start = datetime.now(timezone.utc) - timedelta(
            minutes=cls.LOCKOUT_WINDOW_MINUTES
        )

        failed_count = await cls.find(
            {
                "email": email.lower(),
                "failed": True,
                "attempted_at": {"$gte": window_start},
            }
        ).count()

        return failed_count >= cls.MAX_FAILED_ATTEMPTS

    @classmethod
    async def get_lockout_remaining_seconds(cls, email: str) -> int:
        """Get remaining lockout time in seconds."""
        window_start = datetime.now(timezone.utc) - timedelta(
            minutes=cls.LOCKOUT_WINDOW_MINUTES
        )

        latest_attempt = await cls.find_one(
            {
                "email": email.lower(),
                "failed": True,
                "attempted_at": {"$gte": window_start},
            },
            sort=[("attempted_at", -1)],
        )

        if not latest_attempt:
            return 0

        failed_count = await cls.find(
            {
                "email": email.lower(),
                "failed": True,
                "attempted_at": {"$gte": window_start},
            }
        ).count()

        if failed_count < cls.MAX_FAILED_ATTEMPTS:
            return 0

        # Ensure timezone-aware comparison
        attempted_at = latest_attempt.attempted_at
        if attempted_at.tzinfo is None:
            attempted_at = attempted_at.replace(tzinfo=timezone.utc)
        lockout_end = attempted_at + timedelta(
            minutes=cls.LOCKOUT_DURATION_MINUTES
        )
        remaining = (lockout_end - datetime.now(timezone.utc)).total_seconds()

        return max(0, int(remaining))

    @classmethod
    async def clear_attempts(cls, email: str) -> int:
        """Clear all login attempts for an email (after successful login)."""
        result = await cls.find({"email": email.lower()}).delete()
        return result.deleted_count if result else 0

    @classmethod
    async def cleanup_old_attempts(cls, older_than_hours: int = 24) -> int:
        """Remove old login attempts for cleanup."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        result = await cls.find({"attempted_at": {"$lt": cutoff}}).delete()
        return result.deleted_count if result else 0
