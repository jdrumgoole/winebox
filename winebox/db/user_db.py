"""Motor-based user database adapter for fastapi-users.

Replaces fastapi_users_db_beanie.BeanieUserDatabase with a direct
motor implementation.
"""

from typing import Any, Optional

from bson import ObjectId
from fastapi_users.db import BaseUserDatabase

from winebox.db.objectid import PyObjectId


class MotorUserDatabase(BaseUserDatabase):
    """fastapi-users database adapter using motor directly.

    Implements the BaseUserDatabase protocol required by fastapi-users.
    """

    def __init__(self, user_model: type, collection_getter: Any) -> None:
        """Initialize the motor user database.

        Args:
            user_model: The User model class (MongoDocument subclass).
            collection_getter: Callable that returns the motor collection.
        """
        self.user_model = user_model
        self._get_collection = collection_getter

    @property
    def collection(self) -> Any:
        return self._get_collection()

    async def get(self, id: PyObjectId) -> Optional[Any]:
        """Get a user by ID."""
        if isinstance(id, str):
            id = ObjectId(id)
        doc = await self.collection.find_one({"_id": id})
        if doc is None:
            return None
        return self.user_model._from_doc(doc)

    async def get_by_email(self, email: str) -> Optional[Any]:
        """Get a user by email (case-insensitive)."""
        doc = await self.collection.find_one(
            {"email": {"$regex": f"^{email}$", "$options": "i"}}
        )
        if doc is None:
            return None
        return self.user_model._from_doc(doc)

    async def create(self, create_dict: dict) -> Any:
        """Create a new user."""
        user = self.user_model(**create_dict)
        await user.insert()
        return user

    async def update(self, user: Any, update_dict: dict) -> Any:
        """Update a user."""
        for key, value in update_dict.items():
            setattr(user, key, value)
        await user.save()
        return user

    async def delete(self, user: Any) -> None:
        """Delete a user."""
        await user.delete()
