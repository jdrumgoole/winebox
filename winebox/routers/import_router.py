"""Import endpoints for spreadsheet wine collection import."""

import logging
from datetime import datetime, timezone

from beanie import PydanticObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import ValidationError

from winebox.models.import_batch import ImportBatch, ImportStatus
from winebox.schemas.import_schemas import (
    ColumnMappingRequest,
    ImportBatchSummary,
    ImportProcessRequest,
    ImportResultResponse,
    ImportUploadResponse,
)
from winebox.services.auth import RequireAuth
from winebox.services.import_service import (
    VALID_WINE_FIELDS,
    parse_csv,
    parse_xlsx,
    process_import_batch,
    suggest_column_mapping,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Allowed file extensions
ALLOWED_EXTENSIONS = {"csv", "xlsx"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _get_file_extension(filename: str | None) -> str:
    """Extract file extension from filename."""
    if not filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


@router.post("/upload", response_model=ImportUploadResponse)
async def upload_spreadsheet(
    current_user: RequireAuth,
    file: UploadFile = File(..., description="CSV or XLSX spreadsheet"),
) -> ImportUploadResponse:
    """Upload a spreadsheet for import.

    Parses the file, returns headers and preview rows with suggested column mapping.
    """
    # Validate file extension
    ext = _get_file_extension(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '.{ext}'. Allowed: CSV, XLSX",
        )

    # Read in chunks to avoid unbounded memory for oversized files
    chunks: list[bytes] = []
    total_size = 0
    while True:
        chunk = await file.read(64 * 1024)  # 64 KB chunks
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File exceeds maximum size of 10 MB",
            )
        chunks.append(chunk)
    content = b"".join(chunks)

    # Parse file
    try:
        if ext == "csv":
            headers, rows = parse_csv(content)
        else:
            headers, rows = parse_xlsx(content)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Spreadsheet has no data rows",
        )

    # Suggest column mapping
    suggested_mapping = suggest_column_mapping(headers)

    # Create batch document
    batch = ImportBatch(
        owner_id=current_user.id,
        filename=file.filename or "unknown",
        file_type=ext,
        headers=headers,
        rows=rows,
        row_count=len(rows),
        preview_rows=rows[:5],
        status=ImportStatus.UPLOADED,
    )
    await batch.insert()

    return ImportUploadResponse(
        batch_id=str(batch.id),
        filename=batch.filename,
        row_count=batch.row_count,
        headers=headers,
        preview_rows=batch.preview_rows,
        suggested_mapping=suggested_mapping,
    )


@router.post("/{batch_id}/mapping", response_model=ImportUploadResponse)
async def set_column_mapping(
    batch_id: str,
    current_user: RequireAuth,
    request: ColumnMappingRequest,
) -> ImportUploadResponse:
    """Set or update the column mapping for an import batch."""
    batch = await _get_user_batch(batch_id, current_user.id)

    # Validate mapping: at least 'name' must be mapped
    mapped_fields = set(request.mapping.values())
    if "name" not in mapped_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one column must be mapped to 'name' (wine name)",
        )

    # Validate that mapped fields are valid
    for header, field in request.mapping.items():
        if field == "skip":
            continue
        if field.startswith("custom:"):
            custom_name = field[7:]
            if not custom_name:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Custom field name cannot be empty for column '{header}'",
                )
            continue
        if field not in VALID_WINE_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid mapping target '{field}' for column '{header}'",
            )

    batch.column_mapping = request.mapping
    batch.status = ImportStatus.MAPPED
    await batch.save()

    return ImportUploadResponse(
        batch_id=str(batch.id),
        filename=batch.filename,
        row_count=batch.row_count,
        headers=batch.headers,
        preview_rows=batch.preview_rows,
        suggested_mapping=request.mapping,
    )


@router.post("/{batch_id}/process", response_model=ImportResultResponse)
async def process_batch(
    batch_id: str,
    current_user: RequireAuth,
    request: ImportProcessRequest | None = None,
) -> ImportResultResponse:
    """Process an import batch: create wine records from mapped rows."""
    batch = await _get_user_batch(batch_id, current_user.id)

    if batch.status not in (ImportStatus.MAPPED, ImportStatus.UPLOADED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch is in '{batch.status.value}' state, cannot process",
        )

    if not batch.column_mapping:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Column mapping must be set before processing",
        )

    opts = request or ImportProcessRequest()
    batch = await process_import_batch(
        batch=batch,
        owner_id=current_user.id,
        skip_non_wine=opts.skip_non_wine,
        default_quantity=opts.default_quantity,
    )

    return ImportResultResponse(
        batch_id=str(batch.id),
        wines_created=batch.wines_created,
        rows_skipped=batch.rows_skipped,
        errors=batch.errors,
        status=batch.status.value,
    )


@router.get("/batches", response_model=list[ImportBatchSummary])
async def list_batches(
    current_user: RequireAuth,
) -> list[ImportBatchSummary]:
    """List the current user's import batches."""
    batches = await ImportBatch.find(
        ImportBatch.owner_id == current_user.id,
    ).sort(-ImportBatch.imported_at).to_list()

    return [
        ImportBatchSummary(
            id=str(b.id),
            filename=b.filename,
            imported_at=b.imported_at,
            status=b.status.value,
            row_count=b.row_count,
            wines_created=b.wines_created,
            rows_skipped=b.rows_skipped,
        )
        for b in batches
    ]


@router.get("/batches/{batch_id}", response_model=ImportBatchSummary)
async def get_batch(
    batch_id: str,
    current_user: RequireAuth,
) -> ImportBatchSummary:
    """Get details of an import batch."""
    batch = await _get_user_batch(batch_id, current_user.id)
    return ImportBatchSummary(
        id=str(batch.id),
        filename=batch.filename,
        imported_at=batch.imported_at,
        status=batch.status.value,
        row_count=batch.row_count,
        wines_created=batch.wines_created,
        rows_skipped=batch.rows_skipped,
    )


@router.delete("/batches/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_batch(
    batch_id: str,
    current_user: RequireAuth,
) -> None:
    """Delete an import batch (does not delete wines created from it)."""
    batch = await _get_user_batch(batch_id, current_user.id)
    await batch.delete()


async def _get_user_batch(batch_id: str, owner_id: PydanticObjectId) -> ImportBatch:
    """Get an import batch by ID, verifying ownership.

    Args:
        batch_id: Batch ID string.
        owner_id: Expected owner ID.

    Returns:
        The ImportBatch document.

    Raises:
        HTTPException: If batch not found or not owned by user.
    """
    try:
        batch = await ImportBatch.find_one(
            ImportBatch.id == PydanticObjectId(batch_id),
            ImportBatch.owner_id == owner_id,
        )
    except (InvalidId, ValidationError):
        batch = None

    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Import batch '{batch_id}' not found",
        )

    return batch
