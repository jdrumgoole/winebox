"""User manager for fastapi-users with email callbacks."""

import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Optional

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

from winebox.auth.backend import auth_backend
from winebox.auth.db import get_user_db
from winebox.config import settings
from winebox.models.user import User
from winebox.services.email import get_email_service

logger = logging.getLogger(__name__)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Custom user manager with email verification and password reset callbacks."""

    reset_password_token_secret = settings.secret_key
    verification_token_secret = settings.secret_key

    async def on_after_register(
        self, user: User, request: Optional[Request] = None
    ) -> None:
        """Called after successful user registration.

        Sends verification email if email verification is required.
        """
        logger.info("User %s (id=%s) has registered", user.email, user.id)

        if settings.email_verification_required and not user.is_verified:
            await self.request_verify(user, request)

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        """Called after a password reset was requested.

        Sends password reset email.
        """
        logger.info("User %s requested password reset", user.email)

        email_service = get_email_service()
        success = await email_service.send_password_reset_email(
            to_email=user.email,
            token=token,
        )

        if success:
            logger.info("Password reset email sent to %s", user.email)
        else:
            logger.error("Failed to send password reset email to %s", user.email)

    async def on_after_reset_password(
        self, user: User, request: Optional[Request] = None
    ) -> None:
        """Called after password was reset successfully."""
        logger.info("User %s successfully reset their password", user.email)

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        """Called after a verification email was requested.

        Sends verification email.
        """
        logger.info("Verification requested for user %s", user.email)

        email_service = get_email_service()
        success = await email_service.send_verification_email(
            to_email=user.email,
            token=token,
        )

        if success:
            logger.info("Verification email sent to %s", user.email)
        else:
            logger.error("Failed to send verification email to %s", user.email)

    async def on_after_verify(
        self, user: User, request: Optional[Request] = None
    ) -> None:
        """Called after a user was verified."""
        logger.info("User %s has been verified", user.email)

    async def on_after_login(
        self,
        user: User,
        request: Optional[Request] = None,
        response: Optional[object] = None,
    ) -> None:
        """Called after successful login."""
        logger.info("User %s logged in", user.email)


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    """Get the user manager instance.

    Args:
        user_db: SQLAlchemy user database adapter.

    Yields:
        UserManager instance.
    """
    yield UserManager(user_db)


# FastAPIUsers instance
fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])
