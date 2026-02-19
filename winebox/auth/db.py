"""Database adapter for fastapi-users with Beanie/MongoDB."""

from collections.abc import AsyncGenerator

from fastapi_users_db_beanie import BeanieUserDatabase

from winebox.models.user import User


async def get_user_db() -> AsyncGenerator[BeanieUserDatabase, None]:
    """Get the Beanie user database adapter.

    Yields:
        BeanieUserDatabase instance for User document.
    """
    yield BeanieUserDatabase(User)
