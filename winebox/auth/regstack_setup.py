"""Construction and singleton management for the embedded regstack instance.

WineBox embeds the regstack library (https://pypi.org/project/regstack/)
to handle user registration, login, email verification, password reset,
account deletion, and JWT issue/validation. This module:

- Builds a `RegStackConfig` from WineBox `Settings`.
- Wires WineBox's PostHog hooks and email transports into regstack.
- Points regstack at WineBox-branded email templates.
- Holds the constructed `RegStack` as a process-wide singleton so all
  call sites (FastAPI routes, auth dependencies, CLI) share state.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import SecretStr
from regstack import RegStack, RegStackConfig
from regstack.config.schema import EmailConfig as RegStackEmailConfig

from winebox.config import settings
from winebox.integrations.regstack_email import (
    WineboxConsoleEmailService,
    WineboxSesEmailService,
)
from winebox.integrations.regstack_hooks import register_posthog_hooks

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "static" / "regstack_templates"


_regstack: RegStack | None = None


def _build_config() -> RegStackConfig:
    """Materialise a RegStackConfig from WineBox's Settings."""
    return RegStackConfig(
        app_name=settings.app_name,
        base_url=settings.frontend_url,
        database_url=SecretStr(settings.mongodb_url),
        mongodb_database=settings.mongodb_database,
        jwt_secret=SecretStr(settings.regstack_jwt_secret),
        jwt_ttl_seconds=120 * 60,
        require_verification=settings.email_verification_required,
        allow_registration=settings.registration_enabled,
        enable_password_reset=True,
        enable_account_deletion=True,
        enable_admin_router=False,
        enable_ui_router=False,
        enable_sms_2fa=False,
        api_prefix="/api/auth",
        email=RegStackEmailConfig(
            backend=settings.email_backend,
            from_address=settings.email_sender,
            from_name=settings.email_sender_name,
            ses_region=settings.aws_region,
        ),
    )


def build_regstack() -> RegStack:
    """Construct the singleton RegStack instance. Safe to call multiple times."""
    global _regstack
    if _regstack is not None:
        return _regstack

    rs = RegStack(config=_build_config())

    if settings.email_backend == "ses":
        rs.set_email_backend(
            WineboxSesEmailService(
                region=settings.aws_region,
                access_key_id=settings.aws_access_key_id,
                secret_access_key=settings.aws_secret_access_key,
            )
        )
    else:
        rs.set_email_backend(WineboxConsoleEmailService())

    if _TEMPLATE_DIR.is_dir():
        rs.add_template_dir(_TEMPLATE_DIR)

    register_posthog_hooks(rs)

    _regstack = rs
    logger.info("RegStack initialised (backend=%s)", settings.email_backend)
    return rs


def get_regstack() -> RegStack:
    """Return the singleton, raising if it has not been built yet."""
    if _regstack is None:
        raise RuntimeError(
            "RegStack not initialised. Call build_regstack() during app startup."
        )
    return _regstack


def reset_regstack() -> None:
    """Drop the singleton so the next build_regstack() rebuilds it.

    Used by test fixtures that swap in a fresh database / config.
    """
    global _regstack
    _regstack = None
