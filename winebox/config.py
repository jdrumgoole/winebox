"""Configuration settings for WineBox application."""

import secrets
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


def generate_secret_key() -> str:
    """Generate a random secret key."""
    return secrets.token_urlsafe(32)


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

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # OCR
    tesseract_cmd: str | None = None  # Use system default if None

    # Claude Vision (for wine label scanning)
    anthropic_api_key: str | None = None  # Set WINEBOX_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY
    use_claude_vision: bool = True  # Fall back to Tesseract if False or no API key

    # Authentication
    secret_key: str = generate_secret_key()  # Override with WINEBOX_SECRET_KEY env var
    auth_enabled: bool = True  # Set to False to disable authentication


settings = Settings()
