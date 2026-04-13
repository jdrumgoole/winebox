"""MongoDB document base class using async pymongo directly.

Provides a convenient API for MongoDB operations without the automatic
index management that caused production issues. All index management is
explicit via the setup_indexes script.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar, Optional, Self

from bson import ObjectId
from pydantic import BaseModel, Field, model_validator
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.results import DeleteResult

from winebox.db.objectid import PyObjectId

logger = logging.getLogger(__name__)


class QuerySet:
    """Async query builder for MongoDB find operations.

    Provides a chainable API similar to an ODM query builder:
        Model.find({"field": "value"}).sort([("f", -1)]).skip(10).limit(5).to_list()
    """

    def __init__(
        self,
        collection: AsyncCollection,
        filter_dict: dict,
        model_cls: type[MongoDocument],
    ) -> None:
        self._collection = collection
        self._filter = filter_dict
        self._sort_spec: list[tuple[str, int]] | None = None
        self._skip_val: int = 0
        self._limit_val: int = 0
        self._model_cls = model_cls

    def sort(self, spec: list[tuple[str, int]] | str) -> QuerySet:
        """Set sort order.

        Args:
            spec: Sort specification — either a list of (field, direction) tuples
                  or a single field name string (ascending).
        """
        if isinstance(spec, str):
            self._sort_spec = [(spec, 1)]
        else:
            self._sort_spec = spec
        return self

    def skip(self, n: int) -> QuerySet:
        """Skip n results."""
        self._skip_val = n
        return self

    def limit(self, n: int) -> QuerySet:
        """Limit to n results."""
        self._limit_val = n
        return self

    def _build_cursor(self) -> Any:
        cursor = self._collection.find(self._filter)
        if self._sort_spec:
            cursor = cursor.sort(self._sort_spec)
        if self._skip_val:
            cursor = cursor.skip(self._skip_val)
        if self._limit_val:
            cursor = cursor.limit(self._limit_val)
        return cursor

    async def to_list(self, length: int | None = None) -> list[MongoDocument]:
        """Execute query and return list of model instances."""
        cursor = self._build_cursor()
        docs = await cursor.to_list(length=length)
        return [self._model_cls._from_doc(doc) for doc in docs]

    async def first_or_none(self) -> MongoDocument | None:
        """Return the first matching document or None."""
        self._limit_val = 1
        results = await self.to_list(length=1)
        return results[0] if results else None

    async def count(self) -> int:
        """Count matching documents."""
        return await self._collection.count_documents(self._filter)

    async def delete(self) -> DeleteResult:
        """Delete all matching documents."""
        return await self._collection.delete_many(self._filter)


class MongoDocument(BaseModel):
    """Base class for MongoDB documents using motor directly.

    Provides an ODM-like API without automatic index management.
    Subclasses must define a Settings inner class with a `name` attribute
    specifying the MongoDB collection name.

    Usage:
        class Wine(MongoDocument):
            name: str
            vintage: int

            class Settings:
                name = "wines"

        # Find
        wines = await Wine.find({"vintage": 2020}).sort([("name", 1)]).to_list()
        wine = await Wine.find_one({"name": "Chateau Margaux"})

        # Insert
        wine = Wine(name="Chateau Margaux", vintage=2020)
        await wine.insert()

        # Update
        await wine.set({"vintage": 2021})
        await wine.save()

        # Delete
        await wine.delete()
    """

    id: Optional[PyObjectId] = Field(None, alias="_id")

    # Subclasses define this
    class Settings:
        name: ClassVar[str] = ""

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
    }

    @model_validator(mode="before")
    @classmethod
    def _handle_id_field(cls, data: Any) -> Any:
        """Accept both 'id' and '_id' from input data."""
        if isinstance(data, dict):
            if "_id" in data and "id" not in data:
                pass  # alias handles it
            elif "id" in data and "_id" not in data:
                data["_id"] = data.pop("id")
        return data

    # ---- Collection access ----

    @classmethod
    def _get_collection(cls) -> AsyncCollection:
        from winebox.database import get_database

        return get_database()[cls.Settings.name]

    @classmethod
    def get_pymongo_collection(cls) -> AsyncCollection:
        """Get the raw motor collection for advanced operations."""
        return cls._get_collection()

    # ---- Serialization ----

    @classmethod
    def _from_doc(cls, doc: dict) -> Self:
        """Create a model instance from a MongoDB document."""
        return cls.model_validate(doc)

    def _to_doc(self) -> dict:
        """Convert model instance to a MongoDB document dict."""
        data = self.model_dump(by_alias=True)
        # Remove _id if None (let MongoDB generate it)
        if data.get("_id") is None:
            data.pop("_id", None)
        return data

    # ---- Query methods ----

    @classmethod
    def find(cls, filter_dict: dict | None = None) -> QuerySet:
        """Find documents matching a filter.

        Args:
            filter_dict: MongoDB query filter dict. If None, matches all.

        Returns:
            QuerySet for chaining .sort(), .skip(), .limit(), .to_list(), etc.
        """
        return QuerySet(cls._get_collection(), filter_dict or {}, cls)

    @classmethod
    def find_all(cls) -> QuerySet:
        """Find all documents in the collection."""
        return cls.find({})

    @classmethod
    async def find_one(
        cls,
        filter_dict: dict | None = None,
        sort: list[tuple[str, int]] | None = None,
    ) -> Self | None:
        """Find a single document.

        Args:
            filter_dict: MongoDB query filter dict.
            sort: Optional sort spec to control which document is returned.

        Returns:
            Model instance or None.
        """
        kwargs: dict[str, Any] = {}
        if sort:
            kwargs["sort"] = sort
        doc = await cls._get_collection().find_one(filter_dict or {}, **kwargs)
        return cls._from_doc(doc) if doc else None

    @classmethod
    async def get(cls, doc_id: PyObjectId | str) -> Self | None:
        """Get a document by its _id.

        Args:
            doc_id: Document ID (ObjectId or string).

        Returns:
            Model instance or None.
        """
        if isinstance(doc_id, str):
            doc_id = ObjectId(doc_id)
        return await cls.find_one({"_id": doc_id})

    @classmethod
    async def count(cls, filter_dict: dict | None = None) -> int:
        """Count documents matching a filter.

        Args:
            filter_dict: MongoDB query filter. If None, counts all.
        """
        return await cls._get_collection().count_documents(filter_dict or {})

    @classmethod
    async def aggregate(cls, pipeline: list[dict], length: int | None = None) -> list[dict]:
        """Run an aggregation pipeline and return results as a list.

        Args:
            pipeline: MongoDB aggregation pipeline.
            length: Maximum number of documents to return. None for unlimited.

        Returns:
            List of result documents (raw dicts, not model instances).
        """
        cursor = await cls._get_collection().aggregate(pipeline)
        return await cursor.to_list(length=length)

    # ---- Write methods ----

    async def insert(self) -> Self:
        """Insert this document into MongoDB.

        Sets self.id to the generated ObjectId.
        """
        doc = self._to_doc()
        result = await self._get_collection().insert_one(doc)
        self.id = result.inserted_id
        return self

    @classmethod
    async def insert_many(cls, documents: list[MongoDocument]) -> Any:
        """Insert multiple documents.

        Args:
            documents: List of model instances to insert.

        Returns:
            pymongo InsertManyResult.
        """
        docs = [d._to_doc() for d in documents]
        return await cls._get_collection().insert_many(docs)

    async def save(self) -> Self:
        """Save (upsert) this document.

        If the document has an id, replaces the existing document.
        Otherwise, inserts a new one.
        """
        if self.id is None:
            return await self.insert()
        doc = self._to_doc()
        await self._get_collection().replace_one(
            {"_id": self.id}, doc, upsert=True
        )
        return self

    async def set(self, fields: dict) -> None:
        """Update specific fields on this document using $set.

        Args:
            fields: Dict of field names to new values.
        """
        if self.id is None:
            raise ValueError("Cannot set fields on unsaved document")
        await self._get_collection().update_one(
            {"_id": self.id}, {"$set": fields}
        )
        # Update local instance
        for key, value in fields.items():
            if hasattr(self, key):
                setattr(self, key, value)

    async def delete(self) -> None:
        """Delete this document from MongoDB."""
        if self.id is None:
            raise ValueError("Cannot delete unsaved document")
        await self._get_collection().delete_one({"_id": self.id})

    @classmethod
    async def delete_all(cls) -> DeleteResult:
        """Delete all documents in the collection."""
        return await cls._get_collection().delete_many({})
