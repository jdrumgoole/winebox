"""Custom Pydantic schemas for fastapi-users with MongoDB/Beanie."""

from datetime import datetime

from beanie import PydanticObjectId
from fastapi_users import schemas
from pydantic import ConfigDict, Field


class UserRead(schemas.BaseUser[PydanticObjectId]):
    """Schema for reading user data.

    Includes all fastapi-users base fields plus WineBox custom fields.
    """

    username: str
    full_name: str | None = None
    has_api_key: bool = False
    created_at: datetime
    last_login: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class UserCreate(schemas.BaseUserCreate):
    """Schema for creating a new user.

    Includes email, password from base, plus username for WineBox.
    """

    username: str = Field(..., min_length=3, max_length=50)
    full_name: str | None = None


class UserUpdate(schemas.BaseUserUpdate):
    """Schema for updating user data.

    All fields are optional for partial updates.
    """

    username: str | None = Field(None, min_length=3, max_length=50)
    full_name: str | None = None
