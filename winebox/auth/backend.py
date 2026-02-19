"""JWT authentication backend for fastapi-users."""

from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)

from winebox.config import settings

# Bearer token transport (Authorization: Bearer <token>)
bearer_transport = BearerTransport(tokenUrl="/api/auth/login")

# Token expiration in seconds (24 hours)
TOKEN_LIFETIME_SECONDS = 60 * 60 * 24


def get_jwt_strategy() -> JWTStrategy:
    """Get the JWT strategy with current settings.

    Returns:
        JWTStrategy configured with secret key and lifetime.
    """
    return JWTStrategy(
        secret=settings.secret_key,
        lifetime_seconds=TOKEN_LIFETIME_SECONDS,
    )


# Authentication backend combining transport and strategy
auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)
