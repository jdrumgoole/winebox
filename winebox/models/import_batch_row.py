from datetime import datetime, timezone
from typing import Any

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field


class RawUploadRow(Document):
    """Stores individual import rows as a permanent audit trail.

    Raw upload data lives in the `raw_uploads` collection, timestamped so the
    same file can be uploaded multiple times. These documents are preserved
    even when the parent ImportBatch is deleted.
    """

    batch_id: Indexed(PydanticObjectId)
    index: Indexed(int)
    row: dict[str, Any] = Field(default_factory=dict)
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "raw_uploads"
        indexes = [
            [("batch_id", 1), ("index", 1)],
        ]
