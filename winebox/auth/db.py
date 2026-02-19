"""Database adapter for fastapi-users."""

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from fastapi import Depends
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from winebox.database import get_db

if TYPE_CHECKING:
    from winebox.models.user import User


async def get_user_db(
    session: AsyncSession = Depends(get_db),
) -> AsyncGenerator["SQLAlchemyUserDatabase[User, str]", None]:
    """Get the SQLAlchemy user database adapter.

    Args:
        session: Database session from dependency injection.

    Yields:
        SQLAlchemyUserDatabase instance.
    """
    from winebox.models.user import User

    yield SQLAlchemyUserDatabase(session, User)
