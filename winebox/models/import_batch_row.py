from datetime import datetime, timezone
from typing import Any

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field


class ImportBatchRow(Document):
    """Stores individual import rows for an ImportBatch.

    This keeps large spreadsheets out of the ImportBatch document itself and
    allows streaming/chunked processing by batch_id + index.
    """

    batch_id: Indexed(PydanticObjectId)
    index: Indexed(int)
    row: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "import_batch_rows"
        indexes = [
            [("batch_id", 1), ("index", 1)],
        ]

