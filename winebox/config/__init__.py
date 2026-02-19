"""WineBox configuration module.

This module provides TOML-based configuration with environment variable overrides.

Configuration is loaded from the following locations (in order of priority):
1. Environment variables (highest priority)
2. ./config.toml (project root - for development)
3. ~/.config/winebox/config.toml (user config)
4. /etc/winebox/config.toml (system config)

Secrets are loaded from secrets.env files in the same directories.
"""

from winebox.config.schema import (
    AuthConfig,
    DatabaseConfig,
    EmailConfig,
    OCRConfig,
    SecretsConfig,
    ServerConfig,
    StorageConfig,
    WineboxConfig,
)
from winebox.config.settings import get_settings, settings

__all__ = [
    "AuthConfig",
    "DatabaseConfig",
    "EmailConfig",
    "OCRConfig",
    "SecretsConfig",
    "ServerConfig",
    "StorageConfig",
    "WineboxConfig",
    "get_settings",
    "settings",
]
