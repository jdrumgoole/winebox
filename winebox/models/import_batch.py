"""ImportBatch document model for tracking spreadsheet imports."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field


class ImportStatus(str, Enum):
    """Status of an import batch."""

    UPLOADED = "uploaded"
    MAPPED = "mapped"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ImportBatch(Document):
    """Tracks a spreadsheet import batch through the upload/map/process workflow."""

    owner_id: Indexed(PydanticObjectId)
    filename: str
    file_type: str  # "csv" or "xlsx"
    imported_at: datetime = Field(default_factory=datetime.utcnow)
    status: ImportStatus = ImportStatus.UPLOADED

    # Column mapping: header name -> wine field / "custom:FieldName" / "skip"
    column_mapping: Optional[dict[str, str]] = None

    # Raw data from spreadsheet
    headers: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    preview_rows: list[dict[str, Any]] = Field(default_factory=list)

    # Processing results
    wines_created: int = 0
    rows_skipped: int = 0
    errors: list[str] = Field(default_factory=list)

    class Settings:
        name = "import_batches"
