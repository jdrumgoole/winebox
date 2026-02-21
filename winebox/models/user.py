"""User document model for authentication with fastapi-users integration."""

from datetime import datetime, timezone
from typing import Optional

from beanie import Document, Indexed
from pydantic import Field


def _utc_now() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class User(Document):
    """User document model for authentication.

    This model is compatible with fastapi-users BeanieUserDatabase.

    Fields:
    - id: ObjectId primary key (from Document)
    - email: unique email (required by fastapi-users)
    - hashed_password: password hash
    - is_active: account active status
    - is_verified: email verification status
    - is_superuser: admin/superuser status

    Custom fields added for WineBox:
    - full_name: optional full name
    - created_at, updated_at: timestamps
    - last_login: last login timestamp
    """

    # Required fields for fastapi-users
    email: Indexed(str, unique=True)
    hashed_password: str
    is_active: bool = True
    is_superuser: bool = False
    is_verified: bool = False

    # Custom fields for WineBox
    full_name: Optional[str] = None

    # Timestamps (timezone-aware UTC)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    last_login: Optional[datetime] = None

    class Settings:
        name = "users"
        use_state_management = True
        email_collation = None  # Use default case-insensitive collation

    # Alias is_superuser as is_admin for backward compatibility
    @property
    def is_admin(self) -> bool:
        """Alias for is_superuser for backward compatibility."""
        return self.is_superuser

    @is_admin.setter
    def is_admin(self, value: bool) -> None:
        """Set is_superuser via is_admin alias."""
        self.is_superuser = value

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, is_active={self.is_active})>"
