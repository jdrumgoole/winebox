"""User model for authentication with fastapi-users integration."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from winebox.database import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    """User model for authentication.

    Inherits from SQLAlchemyBaseUserTableUUID which provides:
    - id: UUID primary key
    - email: unique email (required by fastapi-users)
    - hashed_password: password hash
    - is_active: account active status
    - is_verified: email verification status
    - is_superuser: admin/superuser status

    Custom fields added for WineBox:
    - username: unique username for display
    - full_name: optional full name
    - anthropic_api_key: user's API key for Claude Vision
    - created_at, updated_at: timestamps
    - last_login: last login timestamp
    """

    __tablename__ = "users"

    # Custom fields for WineBox
    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    anthropic_api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

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
        return f"<User(id={self.id}, username={self.username}, email={self.email}, is_active={self.is_active})>"
