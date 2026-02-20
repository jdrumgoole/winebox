"""Global settings instance for WineBox.

This module provides a unified settings object that combines:
- Configuration from config.toml
- Secrets from secrets.env
- Environment variable overrides

The settings object provides a flat interface for backward compatibility
while internally using the structured configuration.
"""

import logging
import secrets as secrets_module
from pathlib import Path
from typing import TYPE_CHECKING

from winebox.config.loader import load_config, load_secrets
from winebox.config.schema import SecretsConfig, WineboxConfig

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class Settings:
    """Unified settings object combining config and secrets.

    This class provides a flat interface for accessing configuration values
    while internally using the structured WineboxConfig and SecretsConfig.

    Attributes are exposed as properties for backward compatibility with
    the old Settings class.
    """

    def __init__(
        self,
        config: WineboxConfig | None = None,
        secrets: SecretsConfig | None = None,
    ):
        """Initialize settings.

        Args:
            config: Optional WineboxConfig instance. If not provided, loads from file.
            secrets: Optional SecretsConfig instance. If not provided, loads from file.
        """
        self._config = config or load_config()
        self._secrets = secrets or load_secrets()

        # Handle secret key - generate if not set
        if not self._secrets.secret_key:
            self._secrets.secret_key = secrets_module.token_urlsafe(32)
            logger.warning(
                "SECURITY WARNING: No secret key configured. "
                "A random secret key has been generated. JWT tokens will be invalidated "
                "when the server restarts. Set WINEBOX_SECRET_KEY for production use."
            )

    # =========================================================================
    # Config accessors
    # =========================================================================

    @property
    def config(self) -> WineboxConfig:
        """Get the full configuration object."""
        return self._config

    @property
    def secrets(self) -> SecretsConfig:
        """Get the secrets configuration object."""
        return self._secrets

    # =========================================================================
    # Flat property interface (backward compatibility)
    # =========================================================================

    # Application
    @property
    def app_name(self) -> str:
        return self._config.app_name

    @property
    def debug(self) -> bool:
        return self._config.server.debug

    # Server
    @property
    def host(self) -> str:
        return self._config.server.host

    @property
    def port(self) -> int:
        return self._config.server.port

    @property
    def workers(self) -> int:
        return self._config.server.workers

    @property
    def enforce_https(self) -> bool:
        return self._config.server.enforce_https

    @property
    def rate_limit_per_minute(self) -> int:
        return self._config.server.rate_limit_per_minute

    @property
    def cors_origins(self) -> list[str]:
        return self._config.server.cors_origins

    # Database
    @property
    def mongodb_url(self) -> str:
        return self._config.database.mongodb_url

    @property
    def mongodb_database(self) -> str:
        return self._config.database.mongodb_database

    @property
    def min_pool_size(self) -> int:
        return self._config.database.min_pool_size

    @property
    def max_pool_size(self) -> int:
        return self._config.database.max_pool_size

    # Storage
    @property
    def data_dir(self) -> Path:
        return self._config.storage.data_dir

    @property
    def image_storage_path(self) -> Path:
        return self._config.storage.images_dir

    @property
    def max_upload_size_mb(self) -> int:
        return self._config.storage.max_upload_mb

    @property
    def max_upload_size_bytes(self) -> int:
        return self._config.storage.max_upload_bytes

    # OCR
    @property
    def use_claude_vision(self) -> bool:
        return self._config.ocr.use_claude_vision

    @property
    def tesseract_lang(self) -> str:
        return self._config.ocr.tesseract_lang

    @property
    def tesseract_cmd(self) -> str | None:
        return self._config.ocr.tesseract_cmd

    # Auth
    @property
    def auth_enabled(self) -> bool:
        return self._config.auth.enabled

    @property
    def registration_enabled(self) -> bool:
        return self._config.auth.registration_enabled

    @property
    def email_verification_required(self) -> bool:
        return self._config.auth.email_verification_required

    @property
    def auth_rate_limit_per_minute(self) -> int:
        return self._config.auth.auth_rate_limit_per_minute

    # Email
    @property
    def email_backend(self) -> str:
        return self._config.email.backend

    @property
    def email_sender(self) -> str:
        return self._config.email.from_address

    @property
    def email_sender_name(self) -> str:
        return self._config.email.from_name

    @property
    def frontend_url(self) -> str:
        return self._config.email.frontend_url

    @property
    def aws_region(self) -> str:
        return self._config.email.aws_region

    # Secrets
    @property
    def secret_key(self) -> str:
        # This should never be None due to __init__ handling
        return self._secrets.secret_key or ""

    @property
    def anthropic_api_key(self) -> str | None:
        return self._secrets.anthropic_api_key

    @property
    def aws_access_key_id(self) -> str | None:
        return self._secrets.aws_access_key_id

    @property
    def aws_secret_access_key(self) -> str | None:
        return self._secrets.aws_secret_access_key


# Global settings instance - lazily initialized
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the global settings instance.

    This function provides lazy initialization of the settings object.
    The settings are loaded once and cached for subsequent calls.

    Returns:
        The global Settings instance.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset the global settings instance.

    This is primarily useful for testing to reload configuration.
    """
    global _settings
    _settings = None


# Create a module-level settings property for backward compatibility
# This allows `from winebox.config import settings` to work
class _SettingsProxy:
    """Proxy object that lazily loads settings on first access."""

    def __getattr__(self, name: str):
        return getattr(get_settings(), name)

    def __repr__(self) -> str:
        return repr(get_settings())


settings = _SettingsProxy()
