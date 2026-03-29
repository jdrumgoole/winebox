"""Pydantic schemas for spreadsheet import functionality."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ImportUploadResponse(BaseModel):
    """Response after uploading a spreadsheet."""

    batch_id: str
    filename: str
    row_count: int
    headers: list[str]
    preview_rows: list[dict[str, Any]]
    suggested_mapping: dict[str, str]
    mapping_source: str = "static"

    # Auto-import confidence assessment
    auto_import_eligible: bool = False
    matched_canonical_fields: list[str] = Field(default_factory=list)
    unmapped_headers: list[str] = Field(default_factory=list)

    # Duplicate detection
    duplicate_of: Optional[str] = None
    duplicate_filename: Optional[str] = None
    duplicate_wines_created: Optional[int] = None
    duplicate_mapping: Optional[dict[str, str]] = None
    duplicate_unmapped_headers: list[str] = Field(default_factory=list)


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
    skip_enrichment: bool = Field(
        True,
        description="Skip X-Wines enrichment during import (background enrichment runs afterwards)",
    )
    skip_duplicates: bool = Field(
        True,
        description="Skip wines that already exist in your cellar (matched by name, winery, vintage)",
    )


class ImportResultResponse(BaseModel):
    """Response after processing an import batch."""

    batch_id: str
    wines_created: int
    rows_skipped: int
    errors: list[str]
    status: str


class ParsedUploadRequest(BaseModel):
    """Request for uploading client-parsed CSV data (headers + preview only)."""

    filename: str = Field(..., max_length=255)
    headers: list[str] = Field(..., min_length=1, max_length=200)
    preview_rows: list[dict[str, Any]] = Field(..., max_length=5)
    row_count: int = Field(..., ge=1, le=10000)
    use_ai_mapping: bool = Field(
        True,
        description="Whether to use AI for column mapping (can be disabled for faster uploads)",
    )
    file_checksum: Optional[str] = Field(
        None,
        description="SHA-256 hex digest of the uploaded file (for duplicate detection)",
    )


class RowChunkRequest(BaseModel):
    """Request to append a chunk of parsed rows to an import batch."""

    rows: list[dict[str, Any]] = Field(..., min_length=1, max_length=500)


class ImportBatchSummary(BaseModel):
    """Summary of an import batch for listing."""

    id: str
    filename: str
    imported_at: datetime
    status: str
    row_count: int
    wines_created: int
    rows_skipped: int
    file_checksum: Optional[str] = None
    unmapped_headers: list[str] = Field(default_factory=list)
