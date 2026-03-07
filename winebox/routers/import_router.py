"""Import endpoints for spreadsheet wine collection import."""

import asyncio
import json
import logging

from beanie import PydanticObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from pydantic import ValidationError
from starlette.responses import StreamingResponse

from winebox.models.import_batch import ImportBatch, ImportStatus
from winebox.models.import_batch_row import RawUploadRow
from winebox.schemas.import_schemas import (
    ColumnMappingRequest,
    ImportBatchSummary,
    ImportProcessRequest,
    ImportResultResponse,
    ImportUploadResponse,
    ParsedUploadRequest,
    RowChunkRequest,
)
from winebox.services.auth import RequireAuth
from winebox.services.import_service import (
    UPLOAD_CHUNK_SIZE,
    VALID_WINE_FIELDS,
    chunked,
    parse_csv,
    parse_xlsx,
    process_import_batch,
    process_import_batch_streaming,
    suggest_column_mapping,
    suggest_column_mapping_ai,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Allowed file extensions
ALLOWED_EXTENSIONS = {"csv", "xlsx"}


def _get_file_extension(filename: str | None) -> str:
    """Extract file extension from filename."""
    if not filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


@router.post("/upload", response_model=ImportUploadResponse)
async def upload_spreadsheet(
    current_user: RequireAuth,
    file: UploadFile = File(..., description="CSV or XLSX spreadsheet"),
    use_ai_mapping: bool = Query(
        True,
        description="Whether to use AI for column mapping (can be disabled for faster uploads)",
    ),
) -> ImportUploadResponse:
    """Upload a spreadsheet for import.

    Parses the file, returns headers and preview rows with suggested column mapping.
    Row insertion and AI column mapping run concurrently via asyncio.gather.
    """
    # Validate file extension
    ext = _get_file_extension(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '.{ext}'. Allowed: CSV, XLSX",
        )

    # Parse directly from Starlette's underlying file object — no copy
    try:
        if ext == "csv":
            headers, row_gen = parse_csv(file.file)
        else:
            headers, row_gen = parse_xlsx(file.file)

        # Consume first 5 rows for preview (needed by both insert and AI mapping)
        preview_rows: list[dict] = []
        for row in row_gen:
            preview_rows.append(row)
            if len(preview_rows) >= 5:
                break

        if not preview_rows:
            raise ValueError("Spreadsheet has no data rows")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Create batch document (row_count updated after insertion)
    batch = ImportBatch(
        owner_id=current_user.id,
        filename=file.filename or "unknown",
        file_type=ext,
        headers=headers,
        rows=[],  # rows stored in RawUploadRow collection
        row_count=0,
        preview_rows=preview_rows,
        status=ImportStatus.UPLOADED,
    )
    await batch.insert()

    # Run row insertion and AI mapping concurrently — the AI call (~1.7s) overlaps
    # with DB inserts (~30ms), so the upload returns as soon as AI finishes.
    async def insert_rows() -> int:
        """Insert preview + remaining rows into raw_uploads collection."""
        row_index = 0
        preview_docs = [
            RawUploadRow(batch_id=batch.id, index=i, row=row)
            for i, row in enumerate(preview_rows)
        ]
        if preview_docs:
            await RawUploadRow.insert_many(preview_docs)
        row_index = len(preview_rows)

        for chunk in chunked(row_gen, UPLOAD_CHUNK_SIZE):
            docs = [
                RawUploadRow(batch_id=batch.id, index=row_index + i, row=row)
                for i, row in enumerate(chunk)
            ]
            await RawUploadRow.insert_many(docs)
            row_index += len(chunk)

        return row_index

    async def get_ai_mapping() -> dict[str, str] | None:
        """Get AI-suggested column mapping if enabled."""
        if use_ai_mapping:
            return await suggest_column_mapping_ai(headers, preview_rows[:5])
        return None

    row_count, ai_mapping = await asyncio.gather(insert_rows(), get_ai_mapping())

    # Update batch with final row count
    batch.row_count = row_count
    await batch.save()

    # Determine mapping source
    if ai_mapping is not None:
        suggested_mapping = ai_mapping
        mapping_source = "ai"
        logger.info("Using AI-suggested column mapping for %s", file.filename)
    else:
        suggested_mapping = suggest_column_mapping(headers)
        mapping_source = "static"
        logger.info("Using static alias column mapping for %s", file.filename)

    return ImportUploadResponse(
        batch_id=str(batch.id),
        filename=batch.filename,
        row_count=batch.row_count,
        headers=headers,
        preview_rows=batch.preview_rows,
        suggested_mapping=suggested_mapping,
        mapping_source=mapping_source,
    )


@router.post("/upload-parsed", response_model=ImportUploadResponse)
async def upload_parsed(
    current_user: RequireAuth,
    request: ParsedUploadRequest,
) -> ImportUploadResponse:
    """Upload client-parsed CSV data (headers + preview + row count).

    The client parses the CSV using PapaParse and sends only metadata here.
    Actual rows are uploaded via POST /{batch_id}/rows in chunks.
    """
    # Suggest column mapping — optionally use AI first, fall back to static aliases
    ai_mapping = None
    if request.use_ai_mapping:
        ai_mapping = await suggest_column_mapping_ai(request.headers, request.preview_rows[:5])
    if ai_mapping is not None:
        suggested_mapping = ai_mapping
        mapping_source = "ai"
        logger.info("Using AI-suggested column mapping for %s", request.filename)
    else:
        suggested_mapping = suggest_column_mapping(request.headers)
        mapping_source = "static"
        logger.info("Using static alias column mapping for %s", request.filename)

    # Create batch document with empty rows (rows arrive via /rows endpoint)
    batch = ImportBatch(
        owner_id=current_user.id,
        filename=request.filename,
        file_type="csv",
        headers=request.headers,
        rows=[],
        row_count=request.row_count,
        preview_rows=request.preview_rows[:5],
        status=ImportStatus.UPLOADED,
    )
    await batch.insert()

    return ImportUploadResponse(
        batch_id=str(batch.id),
        filename=batch.filename,
        row_count=batch.row_count,
        headers=request.headers,
        preview_rows=batch.preview_rows,
        suggested_mapping=suggested_mapping,
        mapping_source=mapping_source,
    )


@router.post("/{batch_id}/rows")
async def append_rows(
    batch_id: str,
    current_user: RequireAuth,
    request: RowChunkRequest,
    clear: bool = Query(False, description="Replace existing rows instead of appending"),
) -> dict:
    """Append a chunk of parsed rows to an import batch.

    Used by the client-side CSV parser to upload rows in 500-row chunks.
    Pass ?clear=true on the first chunk to replace any existing rows (safe retry).
    """
    batch = await _get_user_batch(batch_id, current_user.id)

    if batch.status not in (ImportStatus.UPLOADED, ImportStatus.MAPPED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot add rows to batch in '{batch.status.value}' state",
        )

    if clear:
        # Replace rows (first chunk or retry)
        await RawUploadRow.get_pymongo_collection().delete_many(
            {"batch_id": batch.id}
        )
        start_index = 0
    else:
        # Append rows (subsequent chunks) - find current max index
        last = await RawUploadRow.find(
            RawUploadRow.batch_id == batch.id
        ).sort("-index").first_or_none()
        start_index = (last.index + 1) if last is not None else 0

    docs = [
        RawUploadRow(batch_id=batch.id, index=start_index + i, row=row)
        for i, row in enumerate(request.rows)
    ]
    if docs:
        await RawUploadRow.insert_many(docs)

    return {"status": "ok", "rows_added": len(request.rows)}


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
        skip_enrichment=opts.skip_enrichment,
    )

    return ImportResultResponse(
        batch_id=str(batch.id),
        wines_created=batch.wines_created,
        rows_skipped=batch.rows_skipped,
        errors=batch.errors,
        status=batch.status.value,
    )


@router.post("/{batch_id}/process-stream")
async def process_batch_stream(
    batch_id: str,
    current_user: RequireAuth,
    request: ImportProcessRequest | None = None,
) -> StreamingResponse:
    """Process an import batch with SSE progress streaming."""
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

    async def event_generator():
        async for progress in process_import_batch_streaming(
            batch=batch,
            owner_id=current_user.id,
            skip_non_wine=opts.skip_non_wine,
            default_quantity=opts.default_quantity,
            skip_enrichment=opts.skip_enrichment,
        ):
            yield f"data: {json.dumps(progress)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
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
