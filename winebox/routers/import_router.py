"""Import endpoints for spreadsheet wine collection import."""

import asyncio
import hashlib
import json
import logging
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from pydantic import ValidationError

from winebox.db import PyObjectId
from starlette.responses import StreamingResponse

from winebox.models.import_batch import ImportBatch, ImportStatus
from winebox.models.import_batch_row import RawUploadRow
from winebox.models.wine import Wine
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
    assess_mapping_confidence,
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


def _build_upload_response(
    batch: ImportBatch,
    headers: list[str],
    suggested_mapping: dict[str, str],
    mapping_source: str,
    confidence: dict[str, Any] | None = None,
    duplicate_batch: ImportBatch | None = None,
) -> ImportUploadResponse:
    """Build a standardized ImportUploadResponse with confidence and duplicate info."""
    response = ImportUploadResponse(
        batch_id=str(batch.id),
        filename=batch.filename,
        row_count=batch.row_count,
        headers=headers,
        preview_rows=batch.preview_rows,
        suggested_mapping=suggested_mapping,
        mapping_source=mapping_source,
    )

    if confidence:
        response.auto_import_eligible = confidence["confident"]
        response.matched_canonical_fields = confidence["matched_fields"]
        response.unmapped_headers = confidence["unmapped_headers"]

    if duplicate_batch:
        response.duplicate_of = str(duplicate_batch.id)
        response.duplicate_filename = duplicate_batch.filename
        response.duplicate_wines_created = duplicate_batch.wines_created
        response.duplicate_mapping = duplicate_batch.column_mapping
        response.duplicate_unmapped_headers = duplicate_batch.unmapped_headers

    return response


async def _find_duplicate_batch(
    owner_id: PyObjectId,
    file_checksum: str | None,
) -> ImportBatch | None:
    """Find an existing completed batch with the same file checksum for this user."""
    if not file_checksum:
        return None
    return await ImportBatch.find_one({
        "owner_id": owner_id,
        "file_checksum": file_checksum,
        "status": ImportStatus.COMPLETED.value,
    })


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
    AI mapping runs concurrently with row consumption (in a thread). Rows are
    embedded in the batch document for immediate availability; a background task
    copies them to raw_uploads for the permanent audit trail.
    """
    # Validate file extension
    ext = _get_file_extension(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '.{ext}'. Allowed: CSV, XLSX",
        )

    # Read file into memory so the generator survives after the request body closes
    file_bytes = await file.read()

    # Compute file checksum for duplicate detection
    file_checksum = hashlib.sha256(file_bytes).hexdigest()

    try:
        if ext == "csv":
            headers, row_gen = parse_csv(file_bytes)
        else:
            headers, row_gen = parse_xlsx(file_bytes)

        # Consume first 5 rows for preview
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

    # Fire off AI mapping and duplicate check concurrently
    ai_task: asyncio.Task[dict[str, str] | None] | None = None
    if use_ai_mapping:
        ai_task = asyncio.create_task(
            suggest_column_mapping_ai(headers, preview_rows[:5])
        )
    dup_task = asyncio.create_task(
        _find_duplicate_batch(current_user.id, file_checksum)
    )

    # Consume remaining rows in a thread — unblocks the event loop so the
    # AI HTTP call can progress concurrently with openpyxl/CSV parsing
    remaining_rows: list[dict] = await asyncio.to_thread(list, row_gen)
    all_rows = preview_rows + remaining_rows

    # Create batch with rows embedded (single document write, no chunked inserts).
    # The processor reads directly from batch.rows — no wait for raw_uploads.
    batch = ImportBatch(
        owner_id=current_user.id,
        filename=file.filename or "unknown",
        file_type=ext,
        headers=headers,
        rows=all_rows,
        row_count=len(all_rows),
        preview_rows=preview_rows,
        file_checksum=file_checksum,
        status=ImportStatus.UPLOADED,
    )
    await batch.insert()

    # Copy rows to raw_uploads for permanent audit trail (background, non-blocking)
    asyncio.create_task(_insert_raw_upload_rows(batch.id, all_rows))

    # Collect AI result (likely already finished during row consumption + batch insert)
    ai_mapping = None
    if ai_task is not None:
        ai_mapping = await ai_task

    # Determine mapping source
    if ai_mapping is not None:
        suggested_mapping = ai_mapping
        mapping_source = "ai"
        logger.info("Using AI-suggested column mapping for %s", file.filename)
    else:
        suggested_mapping = suggest_column_mapping(headers)
        mapping_source = "static"
        logger.info("Using static alias column mapping for %s", file.filename)

    # Assess confidence for auto-import
    confidence = assess_mapping_confidence(suggested_mapping)

    # Check for duplicate
    duplicate_batch = await dup_task

    return _build_upload_response(
        batch=batch,
        headers=headers,
        suggested_mapping=suggested_mapping,
        mapping_source=mapping_source,
        confidence=confidence,
        duplicate_batch=duplicate_batch,
    )


async def _insert_raw_upload_rows(
    batch_id: PyObjectId, rows: list[dict],
) -> None:
    """Insert rows into raw_uploads collection for audit trail (background task)."""
    try:
        for i in range(0, len(rows), UPLOAD_CHUNK_SIZE):
            chunk = rows[i : i + UPLOAD_CHUNK_SIZE]
            docs = [
                RawUploadRow(batch_id=batch_id, index=i + j, row=row)
                for j, row in enumerate(chunk)
            ]
            await RawUploadRow.insert_many(docs)
    except Exception:
        logger.exception(
            "Failed to insert raw upload rows for batch %s", batch_id
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
    # Also check for duplicates concurrently
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

    # Check for duplicate file
    duplicate_batch = await _find_duplicate_batch(current_user.id, request.file_checksum)

    # Create batch document with empty rows (rows arrive via /rows endpoint)
    batch = ImportBatch(
        owner_id=current_user.id,
        filename=request.filename,
        file_type="csv",
        headers=request.headers,
        rows=[],
        row_count=request.row_count,
        preview_rows=request.preview_rows[:5],
        file_checksum=request.file_checksum,
        status=ImportStatus.UPLOADED,
    )
    await batch.insert()

    # Assess confidence for auto-import
    confidence = assess_mapping_confidence(suggested_mapping)

    return _build_upload_response(
        batch=batch,
        headers=request.headers,
        suggested_mapping=suggested_mapping,
        mapping_source=mapping_source,
        confidence=confidence,
        duplicate_batch=duplicate_batch,
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
            {"batch_id": batch.id}
        ).sort([("index", -1)]).first_or_none()
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
        skip_duplicates=opts.skip_duplicates,
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
            skip_duplicates=opts.skip_duplicates,
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
        {"owner_id": current_user.id}
    ).sort([("imported_at", -1)]).to_list()

    return [
        ImportBatchSummary(
            id=str(b.id),
            filename=b.filename,
            imported_at=b.imported_at,
            status=b.status.value,
            row_count=b.row_count,
            wines_created=b.wines_created,
            rows_skipped=b.rows_skipped,
            file_checksum=b.file_checksum,
            unmapped_headers=b.unmapped_headers,
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
        file_checksum=batch.file_checksum,
        unmapped_headers=batch.unmapped_headers,
    )


@router.delete("/batches/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_batch(
    batch_id: str,
    current_user: RequireAuth,
) -> None:
    """Delete an import batch (does not delete wines created from it)."""
    batch = await _get_user_batch(batch_id, current_user.id)
    await batch.delete()


@router.delete("/batches/{batch_id}/wines")
async def undo_import(
    batch_id: str,
    current_user: RequireAuth,
) -> dict:
    """Undo an import by deleting all wines created from a batch.

    Allowed for COMPLETED or PROCESSING batches (partial imports).
    Deletes all wines where import_batch_id matches and sets batch
    status to ROLLED_BACK.
    """
    batch = await _get_user_batch(batch_id, current_user.id)

    if batch.status not in (ImportStatus.COMPLETED, ImportStatus.PROCESSING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only completed or in-progress imports can be undone",
        )

    # Delete all wines created by this batch for this user
    wines_col = Wine.get_pymongo_collection()
    result = await wines_col.delete_many({
        "owner_id": batch.owner_id,
        "import_batch_id": batch.id,
    })

    # Mark batch as rolled back
    batch.status = ImportStatus.ROLLED_BACK
    await batch.save()

    logger.info(
        "Undid import batch %s: deleted %d wines for user %s",
        batch_id, result.deleted_count, current_user.id,
    )

    return {
        "wines_deleted": result.deleted_count,
        "batch_id": batch_id,
        "status": ImportStatus.ROLLED_BACK.value,
    }


@router.get("/{batch_id}/unmapped-columns")
async def get_unmapped_columns(
    batch_id: str,
    current_user: RequireAuth,
) -> dict:
    """Return unmapped headers and preview data from raw_uploads for a completed batch."""
    batch = await _get_user_batch(batch_id, current_user.id)

    if batch.status != ImportStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch must be completed before viewing unmapped columns",
        )

    unmapped = batch.unmapped_headers
    if not unmapped:
        return {"unmapped_headers": [], "preview_data": []}

    # Fetch first 5 raw rows for preview
    collection = RawUploadRow.get_pymongo_collection()
    cursor = collection.find(
        {"batch_id": batch.id}
    ).sort("index", 1).limit(5)
    docs = await cursor.to_list(length=5)

    preview_data = []
    for doc in docs:
        row = doc.get("row", {})
        preview_data.append({h: row.get(h, "") for h in unmapped})

    return {
        "unmapped_headers": unmapped,
        "preview_data": preview_data,
    }


@router.post("/{batch_id}/remap")
async def remap_unmapped_columns(
    batch_id: str,
    current_user: RequireAuth,
    request: ColumnMappingRequest,
) -> dict:
    """Remap previously-unmapped columns: load raw rows, find wines by batch, update them."""
    batch = await _get_user_batch(batch_id, current_user.id)

    if batch.status != ImportStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch must be completed before remapping",
        )

    # Validate new mapping targets
    for header, field in request.mapping.items():
        if field == "skip":
            continue
        if field.startswith("custom:"):
            if not field[7:]:
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

    # Find all wines from this batch
    wines = await Wine.find(
        {"import_batch_id": batch.id, "owner_id": current_user.id}
    ).to_list()

    if not wines:
        return {"wines_updated": 0, "fields_added": []}

    # Build a lookup from raw_uploads: index -> row data
    collection = RawUploadRow.get_pymongo_collection()
    cursor = collection.find({"batch_id": batch.id}).sort("index", 1)
    raw_rows_by_index: dict[int, dict] = {}
    async for doc in cursor:
        raw_rows_by_index[doc["index"]] = doc.get("row", {})

    # We need to match wines to raw rows. Since wines were created in order,
    # we'll iterate raw rows and match by wine name as a best effort.
    # Build index: (name, row_index) -> raw row
    wines_updated = 0
    fields_added = set()

    # Create a mapping from wine name to wine objects for matching
    # Since multiple wines could have the same name, we use a list
    from collections import defaultdict
    wine_by_name: dict[str, list[Wine]] = defaultdict(list)
    for wine in wines:
        wine_by_name[wine.name].append(wine)

    # Process raw rows in order
    name_header = None
    if batch.column_mapping:
        for h, f in batch.column_mapping.items():
            if f == "name":
                name_header = h
                break

    for idx in sorted(raw_rows_by_index.keys()):
        raw_row = raw_rows_by_index[idx]
        if not name_header:
            continue

        row_name = str(raw_row.get(name_header, "")).strip()
        if not row_name or row_name not in wine_by_name or not wine_by_name[row_name]:
            continue

        wine = wine_by_name[row_name].pop(0)
        updates: dict[str, Any] = {}

        for header, field in request.mapping.items():
            if field == "skip":
                continue
            value = str(raw_row.get(header, "")).strip()
            if not value:
                continue

            if field.startswith("custom:"):
                custom_name = field[7:]
                if wine.custom_fields is None:
                    wine.custom_fields = {}
                wine.custom_fields[custom_name] = value
                updates[f"custom_fields.{custom_name}"] = value
                fields_added.add(custom_name)
            elif field in VALID_WINE_FIELDS:
                # Only set if the wine doesn't already have this field populated
                current_val = getattr(wine, field, None)
                if current_val is None or current_val == "" or current_val == 0:
                    setattr(wine, field, value)
                    updates[field] = value
                    fields_added.add(field)

        if updates:
            await wine.save()
            wines_updated += 1

    # Update batch to remove remapped headers from unmapped_headers
    remapped_headers = [h for h, f in request.mapping.items() if f != "skip"]
    batch.unmapped_headers = [h for h in batch.unmapped_headers if h not in remapped_headers]

    # Merge the new mapping into the batch's column_mapping
    if batch.column_mapping:
        batch.column_mapping.update(request.mapping)
    await batch.save()

    return {
        "wines_updated": wines_updated,
        "fields_added": sorted(fields_added),
    }


@router.get("/{batch_id}/wines")
async def get_batch_wines(
    batch_id: str,
    current_user: RequireAuth,
) -> dict:
    """Return wines created by this import batch with summary stats."""
    batch = await _get_user_batch(batch_id, current_user.id)

    wines = await Wine.find(
        {"import_batch_id": batch.id, "owner_id": current_user.id}
    ).to_list()

    # Build summary stats
    wine_types: dict[str, int] = {}
    countries: dict[str, int] = {}
    grapes: dict[str, int] = {}
    vintages: dict[str, int] = {}

    for wine in wines:
        if wine.wine_type_id:
            wine_types[wine.wine_type_id] = wine_types.get(wine.wine_type_id, 0) + 1
        if wine.country:
            countries[wine.country] = countries.get(wine.country, 0) + 1
        if wine.grape_variety:
            grapes[wine.grape_variety] = grapes.get(wine.grape_variety, 0) + 1
        if wine.vintage:
            vintages[str(wine.vintage)] = vintages.get(str(wine.vintage), 0) + 1

    # Serialize wines (match cellar format)
    wine_list = []
    for wine in wines:
        wine_dict = wine.model_dump(mode="json")
        wine_dict["id"] = str(wine.id)
        wine_list.append(wine_dict)

    total_bottles = sum(
        (w.inventory.quantity if w.inventory else 0) for w in wines
    )

    # Count cases created for this batch's wines
    from winebox.models.case import Case
    wine_ids = [w.id for w in wines]
    total_cases = 0
    if wine_ids:
        total_cases = await Case.get_pymongo_collection().count_documents(
            {"owner_id": current_user.id, "wine_id": {"$in": wine_ids}}
        )

    return {
        "batch_id": str(batch.id),
        "filename": batch.filename,
        "wines": wine_list,
        "summary": {
            "wines_created": len(wines),
            "total_bottles": total_bottles,
            "total_cases": total_cases,
            "by_wine_type": wine_types,
            "by_country": countries,
            "by_grape_variety": grapes,
            "by_vintage": vintages,
        },
        "unmapped_headers": batch.unmapped_headers,
    }


async def _get_user_batch(batch_id: str, owner_id: PyObjectId) -> ImportBatch:
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
            {"_id": ObjectId(batch_id), "owner_id": owner_id}
        )
    except (InvalidId, ValidationError):
        batch = None

    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Import batch '{batch_id}' not found",
        )

    return batch
