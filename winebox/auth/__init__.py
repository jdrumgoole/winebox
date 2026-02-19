"""FastAPI-Users authentication module for WineBox."""

from winebox.auth.backend import auth_backend
from winebox.auth.db import get_user_db
from winebox.auth.schemas import UserCreate, UserRead, UserUpdate
from winebox.auth.users import UserManager, get_user_manager, fastapi_users

__all__ = [
    "auth_backend",
    "get_user_db",
    "UserManager",
    "get_user_manager",
    "fastapi_users",
    "UserCreate",
    "UserRead",
    "UserUpdate",
]
