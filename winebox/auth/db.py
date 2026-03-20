"""Database adapter for fastapi-users with motor/MongoDB."""

from collections.abc import AsyncGenerator

from winebox.db.user_db import MotorUserDatabase
from winebox.models.user import User


async def get_user_db() -> AsyncGenerator[MotorUserDatabase, None]:
    """Get the motor user database adapter.

    Yields:
        MotorUserDatabase instance for User document.
    """
    yield MotorUserDatabase(User, lambda: User._get_collection())
