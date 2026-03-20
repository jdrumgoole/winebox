"""MongoDB document base classes and utilities (Beanie-free)."""

from winebox.db.document import MongoDocument, QuerySet
from winebox.db.objectid import PyObjectId

__all__ = ["MongoDocument", "PyObjectId", "QuerySet"]
