"""Configuration settings for WineBox application."""

import logging
import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Marker value to detect if secret_key was not explicitly set
_SECRET_KEY_NOT_SET = "__NOT_SET__"


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_prefix="WINEBOX_",
        env_file=".env",
    )

    # Application
    app_name: str = "WineBox"
    debug: bool = False

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/winebox.db"

    # Image storage
    image_storage_path: Path = Path("data/images")
    max_upload_size_mb: int = 10  # Maximum file upload size in MB

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # OCR
    tesseract_cmd: str | None = None  # Use system default if None

    # Claude Vision (for wine label scanning)
    anthropic_api_key: str | None = None  # Set WINEBOX_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY
    use_claude_vision: bool = True  # Fall back to Tesseract if False or no API key

    # Authentication
    # SECURITY: Set WINEBOX_SECRET_KEY environment variable for production!
    # If not set, a random key will be generated (tokens invalidate on restart)
    secret_key: str = _SECRET_KEY_NOT_SET
    auth_enabled: bool = True  # Set to False to disable authentication

    # Security
    enforce_https: bool = False  # Set to True in production to enable HSTS header
    rate_limit_per_minute: int = 60  # Global rate limit per IP per minute
    auth_rate_limit_per_minute: int = 30  # Stricter rate limit for auth endpoints

    # Email settings
    email_backend: str = "console"  # "console" for dev/test, "ses" for production
    email_sender: str = "support@winebox.app"
    email_sender_name: str = "WineBox"
    frontend_url: str = "http://localhost:8000"

    # AWS SES settings (only needed when email_backend="ses")
    aws_region: str = "eu-west-1"  # Ireland region
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    # Registration settings
    email_verification_required: bool = True
    registration_enabled: bool = True  # Open registration

    @property
    def max_upload_size_bytes(self) -> int:
        """Get max upload size in bytes."""
        return self.max_upload_size_mb * 1024 * 1024


def _initialize_settings() -> Settings:
    """Initialize settings with security warnings."""
    s = Settings()

    # Handle secret key - generate if not set, but warn
    if s.secret_key == _SECRET_KEY_NOT_SET:
        s.secret_key = secrets.token_urlsafe(32)
        logger.warning(
            "SECURITY WARNING: No WINEBOX_SECRET_KEY environment variable set. "
            "A random secret key has been generated. JWT tokens will be invalidated "
            "when the server restarts. Set WINEBOX_SECRET_KEY for production use."
        )

    return s


settings = _initialize_settings()
