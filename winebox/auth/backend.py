"""JWT authentication backend for fastapi-users."""

from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)

from winebox.config import settings

# Bearer token transport (Authorization: Bearer <token>)
bearer_transport = BearerTransport(tokenUrl="/api/auth/login")


def get_jwt_strategy() -> JWTStrategy:
    """Get the JWT strategy with current settings.

    Returns:
        JWTStrategy configured with secret key and lifetime.
    """
    # Import here to avoid circular dependency
    from winebox.services.auth import TOKEN_LIFETIME_SECONDS

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
