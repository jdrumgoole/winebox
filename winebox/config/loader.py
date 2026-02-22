"""Configuration loader for WineBox.

Loads configuration from TOML files and secrets from .env files.
Environment variables can override any configuration value.
"""

import logging
import os
from pathlib import Path
from typing import Any

from winebox.config.schema import SecretsConfig, WineboxConfig

logger = logging.getLogger(__name__)

# Try to import tomllib (Python 3.11+) or fall back to tomli
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[import-not-found]


def get_config_search_paths() -> list[Path]:
    """Get the list of paths to search for configuration files.

    Returns paths in priority order (first found wins):
    1. ./config.toml (project root - for development)
    2. ~/.config/winebox/config.toml (user config)
    3. /opt/winebox/config.toml (production install)
    4. /etc/winebox/config.toml (system config)
    """
    paths = []

    # Project root (current working directory)
    paths.append(Path.cwd() / "config.toml")

    # User config directory
    user_config = Path.home() / ".config" / "winebox" / "config.toml"
    paths.append(user_config)

    # Production install directory
    paths.append(Path("/opt/winebox/config.toml"))

    # System config (Linux FHS)
    system_config = Path("/etc/winebox/config.toml")
    paths.append(system_config)

    return paths


def get_secrets_search_paths() -> list[Path]:
    """Get the list of paths to search for secrets files.

    Returns paths in priority order (first found wins):
    1. ./secrets.env (project root - for development)
    2. ~/.config/winebox/secrets.env (user secrets)
    3. /opt/winebox/secrets.env (production install)
    4. /etc/winebox/secrets.env (system secrets)
    """
    paths = []

    # Project root
    paths.append(Path.cwd() / "secrets.env")

    # User config directory
    user_secrets = Path.home() / ".config" / "winebox" / "secrets.env"
    paths.append(user_secrets)

    # Production install directory
    paths.append(Path("/opt/winebox/secrets.env"))

    # System config (Linux FHS)
    system_secrets = Path("/etc/winebox/secrets.env")
    paths.append(system_secrets)

    return paths


def find_config_file() -> Path | None:
    """Find the first existing config file from search paths."""
    for path in get_config_search_paths():
        if path.exists() and path.is_file():
            logger.debug(f"Found config file: {path}")
            return path
    return None


def find_secrets_file() -> Path | None:
    """Find the first existing secrets file from search paths."""
    for path in get_secrets_search_paths():
        if path.exists() and path.is_file():
            logger.debug(f"Found secrets file: {path}")
            return path
    return None


def load_toml_file(path: Path) -> dict[str, Any]:
    """Load a TOML file and return its contents as a dictionary."""
    with open(path, "rb") as f:
        return tomllib.load(f)


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple .env file into a dictionary.

    Supports:
    - KEY=value
    - KEY="quoted value"
    - # comments
    - Empty lines
    """
    env_vars: dict[str, str] = {}

    with open(path) as f:
        for line in f:
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Split on first =
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            # Remove surrounding quotes if present
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]

            env_vars[key] = value

    return env_vars


def apply_env_overrides(config_dict: dict[str, Any], prefix: str = "WINEBOX") -> None:
    """Apply environment variable overrides to configuration dictionary.

    Environment variables are mapped as follows:
    - WINEBOX_SERVER_HOST -> config_dict["server"]["host"]
    - WINEBOX_DATABASE_MONGODB_URL -> config_dict["database"]["mongodb_url"]
    - etc.

    Note: This modifies config_dict in place.
    """
    # Map of env var suffixes to config paths
    env_mappings = {
        # Server
        f"{prefix}_SERVER_HOST": ("server", "host"),
        f"{prefix}_SERVER_PORT": ("server", "port"),
        f"{prefix}_SERVER_WORKERS": ("server", "workers"),
        f"{prefix}_SERVER_DEBUG": ("server", "debug"),
        f"{prefix}_DEBUG": ("server", "debug"),  # Shorthand
        f"{prefix}_HOST": ("server", "host"),  # Shorthand
        f"{prefix}_PORT": ("server", "port"),  # Shorthand
        # Database
        f"{prefix}_DATABASE_MONGODB_URL": ("database", "mongodb_url"),
        f"{prefix}_DATABASE_MONGODB_DATABASE": ("database", "mongodb_database"),
        f"{prefix}_MONGODB_URL": ("database", "mongodb_url"),  # Shorthand
        f"{prefix}_MONGODB_DATABASE": ("database", "mongodb_database"),  # Shorthand
        # Storage
        f"{prefix}_STORAGE_DATA_DIR": ("storage", "data_dir"),
        f"{prefix}_STORAGE_LOG_DIR": ("storage", "log_dir"),
        f"{prefix}_STORAGE_MAX_UPLOAD_MB": ("storage", "max_upload_mb"),
        f"{prefix}_IMAGE_STORAGE_PATH": ("storage", "data_dir"),  # Legacy compat
        # OCR
        f"{prefix}_OCR_USE_CLAUDE_VISION": ("ocr", "use_claude_vision"),
        f"{prefix}_OCR_TESSERACT_LANG": ("ocr", "tesseract_lang"),
        f"{prefix}_USE_CLAUDE_VISION": ("ocr", "use_claude_vision"),  # Shorthand
        # Auth
        f"{prefix}_AUTH_ENABLED": ("auth", "enabled"),
        f"{prefix}_AUTH_REGISTRATION_ENABLED": ("auth", "registration_enabled"),
        f"{prefix}_AUTH_EMAIL_VERIFICATION_REQUIRED": (
            "auth",
            "email_verification_required",
        ),
        f"{prefix}_REGISTRATION_ENABLED": ("auth", "registration_enabled"),  # Shorthand
        # Email
        f"{prefix}_EMAIL_BACKEND": ("email", "backend"),
        f"{prefix}_EMAIL_FROM_ADDRESS": ("email", "from_address"),
        f"{prefix}_EMAIL_AWS_REGION": ("email", "aws_region"),
        f"{prefix}_FRONTEND_URL": ("email", "frontend_url"),
        # Analytics
        f"{prefix}_POSTHOG_ENABLED": ("analytics", "posthog_enabled"),
        f"{prefix}_POSTHOG_HOST": ("analytics", "posthog_host"),
        f"{prefix}_POSTHOG_DEBUG": ("analytics", "posthog_debug"),
    }

    for env_var, path in env_mappings.items():
        value = os.environ.get(env_var)
        if value is not None:
            section, key = path

            # Ensure section exists
            if section not in config_dict:
                config_dict[section] = {}

            # Convert value to appropriate type
            if key in ("port", "workers", "max_upload_mb", "auth_rate_limit_per_minute"):
                config_dict[section][key] = int(value)
            elif key in (
                "debug",
                "enforce_https",
                "enabled",
                "registration_enabled",
                "email_verification_required",
                "use_claude_vision",
                "posthog_enabled",
                "posthog_debug",
            ):
                config_dict[section][key] = value.lower() in ("true", "1", "yes")
            else:
                config_dict[section][key] = value


def load_secrets(secrets_file: Path | None = None) -> SecretsConfig:
    """Load secrets from environment variables and optional secrets.env file.

    Environment variables take precedence over file values.
    """
    secrets_dict: dict[str, str | None] = {}

    # Load from secrets file if found
    if secrets_file is None:
        secrets_file = find_secrets_file()

    if secrets_file and secrets_file.exists():
        logger.info(f"Loading secrets from: {secrets_file}")
        file_secrets = parse_env_file(secrets_file)

        # Map file keys to SecretsConfig fields
        key_mapping = {
            "WINEBOX_SECRET_KEY": "secret_key",
            "WINEBOX_ANTHROPIC_API_KEY": "anthropic_api_key",
            "AWS_ACCESS_KEY_ID": "aws_access_key_id",
            "AWS_SECRET_ACCESS_KEY": "aws_secret_access_key",
            "WINEBOX_POSTHOG_API_KEY": "posthog_api_key",
        }

        for file_key, config_key in key_mapping.items():
            if file_key in file_secrets:
                secrets_dict[config_key] = file_secrets[file_key]

    # Override with environment variables (takes precedence)
    env_mapping = {
        "WINEBOX_SECRET_KEY": "secret_key",
        "WINEBOX_ANTHROPIC_API_KEY": "anthropic_api_key",
        "ANTHROPIC_API_KEY": "anthropic_api_key",  # Also check common name
        "AWS_ACCESS_KEY_ID": "aws_access_key_id",
        "AWS_SECRET_ACCESS_KEY": "aws_secret_access_key",
        "WINEBOX_POSTHOG_API_KEY": "posthog_api_key",
    }

    for env_var, config_key in env_mapping.items():
        value = os.environ.get(env_var)
        if value:
            secrets_dict[config_key] = value

    return SecretsConfig(**secrets_dict)


def load_config(config_file: Path | None = None) -> WineboxConfig:
    """Load configuration from TOML file with environment variable overrides.

    Args:
        config_file: Optional path to config file. If not provided,
                     searches default locations.

    Returns:
        WineboxConfig instance with all settings loaded.
    """
    config_dict: dict[str, Any] = {}

    # Find and load config file
    if config_file is None:
        config_file = find_config_file()

    if config_file and config_file.exists():
        logger.info(f"Loading config from: {config_file}")
        config_dict = load_toml_file(config_file)
    else:
        logger.info("No config file found, using defaults with env overrides")

    # Apply environment variable overrides
    apply_env_overrides(config_dict)

    # Create config object
    return WineboxConfig(**config_dict)
