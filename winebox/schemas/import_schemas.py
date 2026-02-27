"""Pydantic schemas for spreadsheet import functionality."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ImportUploadResponse(BaseModel):
    """Response after uploading a spreadsheet."""

    batch_id: str
    filename: str
    row_count: int
    headers: list[str]
    preview_rows: list[dict[str, Any]]
    suggested_mapping: dict[str, str]


class ColumnMappingRequest(BaseModel):
    """Request to set column mapping for an import batch."""

    mapping: dict[str, str] = Field(
        ...,
        description="Map of header name -> wine field / 'custom:FieldName' / 'skip'",
    )


class ImportProcessRequest(BaseModel):
    """Options for processing an import batch."""

    skip_non_wine: bool = Field(True, description="Skip rows that appear to be non-wine items")
    default_quantity: int = Field(1, ge=1, le=10000, description="Default bottle quantity per row")


class ImportResultResponse(BaseModel):
    """Response after processing an import batch."""

    batch_id: str
    wines_created: int
    rows_skipped: int
    errors: list[str]
    status: str


class ImportBatchSummary(BaseModel):
    """Summary of an import batch for listing."""

    id: str
    filename: str
    imported_at: datetime
    status: str
    row_count: int
    wines_created: int
    rows_skipped: int
