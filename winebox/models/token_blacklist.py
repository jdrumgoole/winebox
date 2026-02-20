"""Token blacklist model for JWT token revocation."""

from datetime import datetime

from beanie import Document, Indexed
from pydantic import Field


class RevokedToken(Document):
    """Stores revoked JWT tokens until they expire.

    Tokens are stored with their expiration time to allow automatic cleanup.
    """

    # JWT ID (jti claim) - unique identifier for the token
    jti: Indexed(str, unique=True)

    # When the token was revoked
    revoked_at: datetime = Field(default_factory=datetime.utcnow)

    # When the token expires (for automatic cleanup)
    expires_at: Indexed(datetime)

    # User ID who owns the token (for audit purposes)
    user_id: str | None = None

    # Reason for revocation
    reason: str = "logout"

    class Settings:
        name = "revoked_tokens"
        indexes = [
            "jti",
            "expires_at",
        ]

    @classmethod
    async def is_revoked(cls, jti: str) -> bool:
        """Check if a token is revoked.

        Args:
            jti: The JWT ID to check.

        Returns:
            True if the token is revoked, False otherwise.
        """
        token = await cls.find_one(cls.jti == jti)
        return token is not None

    @classmethod
    async def revoke_token(
        cls,
        jti: str,
        expires_at: datetime,
        user_id: str | None = None,
        reason: str = "logout",
    ) -> "RevokedToken":
        """Revoke a token by adding it to the blacklist.

        Args:
            jti: The JWT ID to revoke.
            expires_at: When the token expires.
            user_id: Optional user ID who owns the token.
            reason: Reason for revocation.

        Returns:
            The created RevokedToken document.
        """
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
        """Remove expired tokens from the blacklist.

        Returns:
            Number of tokens removed.
        """
        result = await cls.find(cls.expires_at < datetime.utcnow()).delete()
        return result.deleted_count if result else 0
