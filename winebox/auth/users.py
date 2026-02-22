"""User manager for fastapi-users with email callbacks."""

import hashlib
import logging
from collections.abc import AsyncGenerator
from typing import Optional

from beanie import PydanticObjectId
from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers
from fastapi_users_db_beanie import BeanieUserDatabase, ObjectIDIDMixin

from winebox.auth.backend import auth_backend
from winebox.auth.db import get_user_db
from winebox.auth.schemas import UserCreate
from winebox.config import settings
from winebox.models.user import User
from winebox.services.analytics import posthog_service
from winebox.services.email import get_email_service

logger = logging.getLogger(__name__)


def _derive_secret(base_secret: str, purpose: str) -> str:
    """Derive a purpose-specific secret from the base secret.

    This ensures that different token types use different secrets,
    so compromising one type doesn't compromise others.

    Args:
        base_secret: The main application secret key.
        purpose: A string identifying the purpose (e.g., 'reset_password').

    Returns:
        A derived secret string.
    """
    combined = f"{base_secret}:{purpose}"
    return hashlib.sha256(combined.encode()).hexdigest()


class UserManager(ObjectIDIDMixin, BaseUserManager[User, PydanticObjectId]):
    """Custom user manager with email verification and password reset callbacks."""

    # Use derived secrets for different token types (security best practice)
    # This ensures JWT secret compromise doesn't affect reset/verification tokens
    reset_password_token_secret = _derive_secret(settings.secret_key, "reset_password")
    verification_token_secret = _derive_secret(settings.secret_key, "verification")

    async def on_after_register(
        self, user: User, request: Optional[Request] = None
    ) -> None:
        """Called after successful user registration.

        Sends verification email if email verification is required.
        """
        logger.info("User registered (id=%s, email=%s)", user.id, user.email)

        # Track registration event
        posthog_service.capture(
            distinct_id=str(user.id),
            event="user_registered",
            properties={"email_verification_required": settings.email_verification_required},
        )
        posthog_service.identify(
            distinct_id=str(user.id),
            properties={"email": user.email},
        )

        if settings.email_verification_required and not user.is_verified:
            await self.request_verify(user, request)

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        """Called after a password reset was requested.

        Sends password reset email.
        """
        logger.info("Password reset requested for user (id=%s)", user.id)

        email_service = get_email_service()
        success = await email_service.send_password_reset_email(
            to_email=user.email,
            token=token,
        )

        if success:
            logger.info("Password reset email sent for user (id=%s)", user.id)
        else:
            logger.error("Failed to send password reset email for user (id=%s)", user.id)

    async def on_after_reset_password(
        self, user: User, request: Optional[Request] = None
    ) -> None:
        """Called after password was reset successfully."""
        logger.info("User password reset successfully (id=%s)", user.id)

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        """Called after a verification email was requested.

        Sends verification email.
        """
        logger.info("Verification requested for user (id=%s)", user.id)

        email_service = get_email_service()
        success = await email_service.send_verification_email(
            to_email=user.email,
            token=token,
        )

        if success:
            logger.info("Verification email sent for user (id=%s)", user.id)
        else:
            logger.error("Failed to send verification email for user (id=%s)", user.id)

    async def on_after_verify(
        self, user: User, request: Optional[Request] = None
    ) -> None:
        """Called after a user was verified."""
        logger.info("User verified (id=%s)", user.id)

    async def on_after_login(
        self,
        user: User,
        request: Optional[Request] = None,
        response: Optional[object] = None,
    ) -> None:
        """Called after successful login."""
        logger.info("User logged in (id=%s)", user.id)

        # Track login event
        posthog_service.capture(
            distinct_id=str(user.id),
            event="user_login",
            properties={"method": "fastapi_users"},
        )


async def get_user_manager(
    user_db: BeanieUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    """Get the user manager instance.

    Args:
        user_db: Beanie user database adapter.

    Yields:
        UserManager instance.
    """
    yield UserManager(user_db)


# FastAPIUsers instance
fastapi_users = FastAPIUsers[User, PydanticObjectId](get_user_manager, [auth_backend])
