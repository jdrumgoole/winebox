"""Custom Pydantic schemas for fastapi-users with MongoDB."""

from datetime import datetime

from fastapi_users import schemas
from pydantic import ConfigDict

from winebox.db import PyObjectId


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


class UserUpdate(schemas.BaseUserUpdate):
    """Schema for updating user data.

    All fields are optional for partial updates.
    """
