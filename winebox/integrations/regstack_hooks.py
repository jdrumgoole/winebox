"""Bridge regstack auth lifecycle events to WineBox's PostHog analytics."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from winebox.services.analytics import posthog_service

if TYPE_CHECKING:
    from regstack import RegStack
    from regstack.models.user import BaseUser

logger = logging.getLogger(__name__)


def register_posthog_hooks(rs: "RegStack") -> None:
    """Subscribe PostHog handlers to regstack's auth events.

    regstack swallows exceptions inside hook handlers, so a PostHog
    outage cannot break the primary auth flow.
    """

    async def _on_registered(user: "BaseUser", **_: object) -> None:
        posthog_service.capture(
            distinct_id=str(user.id),
            event="user_registered",
        )
        posthog_service.identify(
            distinct_id=str(user.id),
            properties={"email": user.email},
        )

    async def _on_login(user: "BaseUser", **_: object) -> None:
        posthog_service.capture(
            distinct_id=str(user.id),
            event="user_login",
            properties={"method": "password"},
        )

    async def _on_logout(user: "BaseUser", **_: object) -> None:
        posthog_service.capture(
            distinct_id=str(user.id),
            event="user_logout",
        )

    async def _on_password_reset_completed(user: "BaseUser", **_: object) -> None:
        posthog_service.capture(
            distinct_id=str(user.id),
            event="password_reset_completed",
        )

    async def _on_password_changed(user: "BaseUser", **_: object) -> None:
        posthog_service.capture(
            distinct_id=str(user.id),
            event="password_changed",
        )

    rs.hooks.on("user_registered", _on_registered)
    rs.hooks.on("user_logged_in", _on_login)
    rs.hooks.on("user_logged_out", _on_logout)
    rs.hooks.on("password_reset_completed", _on_password_reset_completed)
    rs.hooks.on("password_changed", _on_password_changed)
    logger.info("Registered regstack PostHog hooks")
