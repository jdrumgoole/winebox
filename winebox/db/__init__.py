"""MongoDB document base classes and utilities (lightweight)."""

from winebox.db.document import MongoDocument, QuerySet
from winebox.db.objectid import PyObjectId

__all__ = ["MongoDocument", "PyObjectId", "QuerySet"]
