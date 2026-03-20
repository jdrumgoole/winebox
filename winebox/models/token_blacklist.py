"""Token blacklist model for JWT token revocation."""

from datetime import datetime, timezone

from pydantic import Field

from winebox.db import MongoDocument


def _utc_now() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class RevokedToken(MongoDocument):
    """Stores revoked JWT tokens until they expire.

    Tokens are stored with their expiration time to allow automatic cleanup.
    """

    # JWT ID (jti claim) - unique identifier for the token
    jti: str

    # When the token was revoked
    revoked_at: datetime = Field(default_factory=_utc_now)

    # When the token expires (for automatic cleanup)
    expires_at: datetime

    # User ID who owns the token (for audit purposes)
    user_id: str | None = None

    # Reason for revocation
    reason: str = "logout"

    class Settings:
        name = "revoked_tokens"

    @classmethod
    async def is_revoked(cls, jti: str) -> bool:
        """Check if a token is revoked."""
        token = await cls.find_one({"jti": jti})
        return token is not None

    @classmethod
    async def revoke_token(
        cls,
        jti: str,
        expires_at: datetime,
        user_id: str | None = None,
        reason: str = "logout",
    ) -> "RevokedToken":
        """Revoke a token by adding it to the blacklist."""
        token = cls(
            jti=jti,
            expires_at=expires_at,
            user_id=user_id,
            reason=reason,
        )
        await token.insert()
        return token

    @classmethod
    async def cleanup_expired(cls) -> int:
        """Remove expired tokens from the blacklist."""
        result = await cls.find({"expires_at": {"$lt": _utc_now()}}).delete()
        return result.deleted_count if result else 0
