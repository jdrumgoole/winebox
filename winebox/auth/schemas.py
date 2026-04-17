"""Custom Pydantic schemas for fastapi-users with MongoDB."""

from datetime import datetime

from fastapi_users import schemas
from pydantic import ConfigDict, field_validator

from winebox.db import PyObjectId

MIN_PASSWORD_LENGTH = 8


class UserRead(schemas.BaseUser[PyObjectId]):
    """Schema for reading user data.

    Includes all fastapi-users base fields plus WineBox custom fields.
    """

    full_name: str | None = None
    created_at: datetime
    last_login: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class UserCreate(schemas.BaseUserCreate):
    """Schema for creating a new user.

    Includes email, password from base.
    """

    full_name: str | None = None

    @field_validator("password")
    @classmethod
    def validate_password_length(cls, v: str) -> str:
        if len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
            )
        return v


class UserUpdate(schemas.BaseUserUpdate):
    """Schema for updating user data.

    All fields are optional for partial updates.
    """
