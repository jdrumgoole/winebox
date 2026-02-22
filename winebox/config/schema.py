"""Pydantic models for WineBox configuration.

These models define the structure of config.toml and secrets.env files.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    """Server configuration."""

    host: str = "127.0.0.1"
    port: int = 8000
    workers: int = 2
    debug: bool = False
    enforce_https: bool = False
    rate_limit_per_minute: int = 60
    # CORS configuration - empty list means same-origin only
    cors_origins: list[str] = []


class DatabaseConfig(BaseModel):
    """MongoDB database configuration."""

    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_database: str = "winebox"
    # Connection pool settings
    min_pool_size: int = 10
    max_pool_size: int = 100


class StorageConfig(BaseModel):
    """File storage configuration."""

    data_dir: Path = Field(default_factory=lambda: Path("data"))
    log_dir: Path = Field(default_factory=lambda: Path("data/logs"))
    max_upload_mb: int = 10

    @property
    def images_dir(self) -> Path:
        """Get the images directory path."""
        return self.data_dir / "images"

    @property
    def max_upload_bytes(self) -> int:
        """Get max upload size in bytes."""
        return self.max_upload_mb * 1024 * 1024


class OCRConfig(BaseModel):
    """OCR (Optical Character Recognition) configuration."""

    use_claude_vision: bool = True
    tesseract_lang: str = "eng"
    tesseract_cmd: str | None = None


class AuthConfig(BaseModel):
    """Authentication configuration."""

    enabled: bool = True
    registration_enabled: bool = True
    email_verification_required: bool = True
    auth_rate_limit_per_minute: int = 30


class EmailConfig(BaseModel):
    """Email configuration."""

    backend: Literal["console", "ses"] = "console"
    from_address: str = "support@winebox.app"
    from_name: str = "WineBox"
    frontend_url: str = "http://localhost:8000"
    aws_region: str = "eu-west-1"


class AnalyticsConfig(BaseModel):
    """Analytics configuration."""

    posthog_enabled: bool = False
    posthog_host: str = "https://eu.posthog.com"
    posthog_debug: bool = False


class WineboxConfig(BaseModel):
    """Main WineBox configuration loaded from config.toml."""

    app_name: str = "WineBox"
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    ocr: OCRConfig = Field(default_factory=OCRConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)


class SecretsConfig(BaseModel):
    """Secrets loaded from secrets.env file.

    These are sensitive values that should not be stored in config.toml.
    """

    secret_key: str | None = None
    anthropic_api_key: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    posthog_api_key: str | None = None
