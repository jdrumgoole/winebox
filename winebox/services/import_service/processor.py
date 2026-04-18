"""Batch processing for wine imports.

Uses an asyncio pipeline for concurrent enrichment:
  Raw rows -> split into chunks -> [enrichment queue] -> N enrichment tasks
  -> [write queue] -> 1 writer task -> MongoDB (insert_many per batch)
  -> progress queue -> SSE generator

This gives pipeline parallelism: enrichment of chunk N+1 overlaps with
writing chunk N, and multiple enrichment tasks run concurrently.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

from pymongo.errors import BulkWriteError

from winebox.db import PyObjectId

from winebox.models.import_batch import ImportBatch, ImportStatus
from winebox.models.import_batch_row import RawUploadRow
from winebox.models.wine import Wine
from winebox.services.background_enrichment import enrich_unenriched_wines
from winebox.services.xwines_enrichment import enrich_batch_with_xwines

from .constants import ENRICHMENT_WORKERS
from .converters import is_non_wine_row, row_to_wine_data

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 75

# Only push progress to SSE when percentage advances by at least this much (reduces event count)
PROGRESS_PCT_STEP = 5

# Sentinel pushed to progress_queue when the writer is done
_PROGRESS_DONE = object()


def _maybe_emit_progress(
    progress_queue: asyncio.Queue[dict[str, Any] | object],
    progress_state: dict[str, Any],
    total: int,
    _phase: str,
) -> None:
    """Emit a progress event only when percentage has advanced by PROGRESS_PCT_STEP or we hit 100%."""
    if total <= 0:
        return
    processed = progress_state["processed"]
    pct = round(100 * processed / total)
    last_pct = progress_state.get("last_reported_pct", -1)
    if pct >= 100 or pct >= last_pct + PROGRESS_PCT_STEP or (last_pct < 0 and pct > last_pct):
        progress_state["last_reported_pct"] = pct
        progress_queue.put_nowait({
            "processed": processed,
            "total": total,
            "wines_created": progress_state["wines_created"],
            "rows_skipped": progress_state["rows_skipped"],
        })


# ---------------------------------------------------------------------------
# Chunk dataclass — carries a batch of rows through the pipeline
# ---------------------------------------------------------------------------

class _Chunk:
    """A batch of rows moving through the enrichment/write pipeline."""

    __slots__ = ("wine_datas", "chunk_start", "chunk_end", "rows_skipped", "skipped_rows", "errors", "batch_id")

    def __init__(
        self,
        wine_datas: list[tuple[dict[str, Any], int]],
        chunk_start: int,
        chunk_end: int,
        rows_skipped: int,
        skipped_rows: list[dict[str, Any]],
        errors: list[str],
        batch_id: PyObjectId | None = None,
    ) -> None:
        self.wine_datas = wine_datas
        self.chunk_start = chunk_start
        self.chunk_end = chunk_end
        self.rows_skipped = rows_skipped
        self.skipped_rows = skipped_rows
        self.errors = errors
        self.batch_id = batch_id


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def _convert_chunk_from_rows(
    rows: list[dict[str, Any]],
    column_mapping: dict[str, str] | None,
    owner_id: PyObjectId,
    chunk_start: int,
    chunk_end: int,
    skip_non_wine: bool,
    default_quantity: int,
    batch_id: PyObjectId | None = None,
    existing_wines: set[tuple[str, ...]] | None = None,
    skip_duplicates: bool = False,
    default_case_size: int | None = None,
) -> _Chunk:
    """Phase 1 helper: Convert raw row dicts to wine dicts (sync, fast)."""
    chunk_rows = rows
    wine_datas: list[tuple[dict[str, Any], int]] = []
    rows_skipped = 0
    skipped_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for offset, row in enumerate(chunk_rows):
        row_index = chunk_start + offset  # 0-based
        try:
            if skip_non_wine and is_non_wine_row(row, column_mapping):
                rows_skipped += 1
                skipped_rows.append({
                    "row": row_index + 1,
                    "reason": "Non-wine item detected",
                    "data": row,
                })
                continue

            wine_data = row_to_wine_data(
                row, column_mapping, owner_id, default_quantity,
                default_case_size=default_case_size,
                existing_wines=existing_wines,
            )
            if wine_data is None:
                rows_skipped += 1
                skipped_rows.append({
                    "row": row_index + 1,
                    "reason": "Missing required wine name",
                    "data": row,
                })
                continue

            # Handle duplicates: skip or flag depending on caller preference
            if wine_data.pop("_duplicate", False):
                if skip_duplicates:
                    rows_skipped += 1
                    skipped_rows.append({
                        "row": row_index + 1,
                        "reason": "Already in your cellar",
                        "data": row,
                    })
                    continue
                # else: import anyway (user chose to include duplicates)

            # Link wine to its import batch for later augmentation
            if batch_id is not None:
                wine_data["import_batch_id"] = batch_id

            wine_datas.append((wine_data, row_index + 1))
        except Exception as e:
            error_msg = f"Row {row_index + 1}: {str(e)}"
            errors.append(error_msg)
            logger.warning("Import error on row %d: %s", row_index + 1, e)

    return _Chunk(wine_datas, chunk_start, chunk_end, rows_skipped, skipped_rows, errors, batch_id)




async def _enrich_chunk(chunk: _Chunk) -> _Chunk:
    """Phase 2: Enrich all rows in a chunk with a single batch X-Wines query."""
    if not chunk.wine_datas:
        return chunk

    enrichment_inputs = []
    for wd, _ in chunk.wine_datas:
        enrichment_inputs.append({
            "name": wd.get("name"),
            "winery": wd.get("winery"),
            "grape_variety": wd.get("grape_variety"),
            "region": wd.get("region"),
            "country": wd.get("country"),
            "alcohol_percentage": wd.get("alcohol_percentage"),
        })
    try:
        await enrich_batch_with_xwines(enrichment_inputs)
        # Apply enrichment results back to wine_datas
        for (wd, _), enriched in zip(chunk.wine_datas, enrichment_inputs):
            enriched_fields = enriched.pop("enriched_fields", None)
            xwines_id = enriched.pop("xwines_id", None)
            for key in ("winery", "grape_variety", "region", "country", "alcohol_percentage"):
                if enriched.get(key):
                    wd[key] = enriched[key]
            wd["enriched_fields"] = enriched_fields
            wd["xwines_id"] = xwines_id
    except Exception as e:
        logger.warning(
            "Batch enrichment failed for chunk %d-%d: %s",
            chunk.chunk_start + 1, chunk.chunk_end, e,
        )

    return chunk


async def _write_chunk(chunk: _Chunk) -> tuple[int, list[str]]:
    """Phase 3: Batch insert Wine documents. Returns (wines_created, errors)."""
    if not chunk.wine_datas:
        return 0, []

    from bson import ObjectId as _OID
    # Extract case metadata before Wine construction (not valid Wine fields)
    case_meta: dict[Any, tuple[int, int]] = {}  # wine_id → (num_cases, case_size)
    for wd, _ in chunk.wine_datas:
        if "_id" not in wd and "id" not in wd:
            wd["id"] = _OID()
        num_cases = wd.pop("_num_cases", 0)
        case_size = wd.pop("_case_size", None)
        if num_cases and case_size:
            case_meta[wd["id"]] = (num_cases, case_size)

    wine_docs = [Wine(**wd) for wd, _ in chunk.wine_datas]
    errors: list[str] = []
    wines_created = 0

    try:
        await Wine.insert_many(wine_docs)
        wines_created = len(wine_docs)

        # Create cellar items (cases + loose bottles) and events
        from winebox.models.cellar import CellarItem, EmbeddedWine
        from winebox.models.cellar_event import CellarEvent, CellarEventType
        cellar_items: list[CellarItem] = []
        cellar_events: list[CellarEvent] = []
        now = datetime.now(timezone.utc)

        for wine_doc in wine_docs:
            qty = wine_doc.inventory.quantity if wine_doc.inventory else 1
            if qty <= 0:
                continue

            embedded_wine = EmbeddedWine(
                wine_id=wine_doc.id, name=wine_doc.name, winery=wine_doc.winery,
                vintage=wine_doc.vintage, grape_variety=wine_doc.grape_variety,
                country=wine_doc.country, region=wine_doc.region,
                wine_type=wine_doc.wine_type_id,
                estimated_price_low=wine_doc.estimated_price_low,
                estimated_price_high=wine_doc.estimated_price_high,
                price_tier=wine_doc.price_tier,
            )

            meta = case_meta.get(wine_doc.id)
            if meta:
                num_cases, case_size = meta
                loose_remainder = qty - (num_cases * case_size)

                for _ in range(num_cases):
                    item_id = _OID()
                    cellar_items.append(CellarItem(
                        id=item_id, cellar_id=wine_doc.owner_id,
                        item_type="case", wine=embedded_wine,
                        quantity=case_size, case_size=case_size,
                        purchase_date=getattr(wine_doc, 'purchase_date', None),
                        import_batch_id=chunk.batch_id,
                        created_at=now, updated_at=now,
                    ))
                    cellar_events.append(CellarEvent(
                        cellar_id=wine_doc.owner_id, cellar_item_id=item_id,
                        item_type="case", event_type=CellarEventType.ADDED,
                        quantity=case_size, import_batch_id=chunk.batch_id,
                        event_date=now, created_at=now,
                    ))

                if loose_remainder > 0:
                    item_id = _OID()
                    cellar_items.append(CellarItem(
                        id=item_id, cellar_id=wine_doc.owner_id,
                        item_type="bottle", wine=embedded_wine,
                        quantity=loose_remainder,
                        import_batch_id=chunk.batch_id,
                        created_at=now, updated_at=now,
                    ))
                    cellar_events.append(CellarEvent(
                        cellar_id=wine_doc.owner_id, cellar_item_id=item_id,
                        item_type="bottle", event_type=CellarEventType.ADDED,
                        quantity=loose_remainder, import_batch_id=chunk.batch_id,
                        event_date=now, created_at=now,
                    ))
            else:
                # Loose bottles — one cellar item per wine
                item_id = _OID()
                cellar_items.append(CellarItem(
                    id=item_id, cellar_id=wine_doc.owner_id,
                    item_type="bottle", wine=embedded_wine,
                    quantity=qty,
                    import_batch_id=chunk.batch_id,
                    created_at=now, updated_at=now,
                ))
                cellar_events.append(CellarEvent(
                    cellar_id=wine_doc.owner_id, cellar_item_id=item_id,
                    item_type="bottle", event_type=CellarEventType.ADDED,
                    quantity=qty, import_batch_id=chunk.batch_id,
                    event_date=now, created_at=now,
                ))

        if cellar_items:
            await CellarItem.insert_many(cellar_items)
            await CellarEvent.insert_many(cellar_events)
    except BulkWriteError as e:
        n_inserted = e.details.get("nInserted", 0)
        wines_created = n_inserted
        failed = len(wine_docs) - n_inserted
        error_msg = f"Batch insert partial failure: {failed} of {len(wine_docs)} failed"
        errors.append(error_msg)
        logger.warning(error_msg)
    except Exception as e:
        error_msg = (
            f"Batch insert failed for rows "
            f"{chunk.chunk_start + 1}-{chunk.chunk_end}: {str(e)}"
        )
        errors.append(error_msg)
        logger.warning(error_msg)

    return wines_created, errors


# ---------------------------------------------------------------------------
# Enrichment worker — consumes from enrichment_queue, pushes to write_queue
# ---------------------------------------------------------------------------

async def _enrichment_worker(
    enrichment_queue: asyncio.Queue[_Chunk | None],
    write_queue: asyncio.Queue[_Chunk | None],
    progress_queue: asyncio.Queue[dict[str, Any] | object],
    progress_state: dict[str, int],
    total: int,
    skip_enrichment: bool,
) -> None:
    """Enrichment worker: dequeue chunks, enrich, forward to write queue.

    Pushes a progress event after enrichment completes for each chunk,
    crediting half the chunk's rows to give smoother progress updates.
    """
    while True:
        chunk = await enrichment_queue.get()
        if chunk is None:
            # Poison pill — signal to stop
            enrichment_queue.task_done()
            break
        try:
            if not skip_enrichment:
                await _enrich_chunk(chunk)
        finally:
            # Credit half the chunk rows for the enrichment phase
            chunk_rows = chunk.chunk_end - chunk.chunk_start
            progress_state["processed"] += chunk_rows // 2
            _maybe_emit_progress(
                progress_queue, progress_state, total, "enrichment",
            )
            await write_queue.put(chunk)
            enrichment_queue.task_done()


# ---------------------------------------------------------------------------
# Writer worker — consumes from write_queue, inserts, pushes progress
# ---------------------------------------------------------------------------

async def _writer_worker(
    write_queue: asyncio.Queue[_Chunk | None],
    progress_queue: asyncio.Queue[dict[str, Any] | object],
    progress_state: dict[str, int],
    total: int,
    num_enrichment_workers: int,
) -> tuple[int, int, list[dict[str, Any]], list[str]]:
    """Writer: dequeue enriched chunks, insert_many, push progress updates.

    Credits the remaining half of each chunk's rows (enrichment credited the
    first half). Pushes _PROGRESS_DONE sentinel when all work is complete.
    Returns cumulative (wines_created, rows_skipped, skipped_rows, errors).
    """
    wines_created = 0
    rows_skipped = 0
    skipped_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    poison_pills_seen = 0

    while True:
        chunk = await write_queue.get()
        if chunk is None:
            poison_pills_seen += 1
            write_queue.task_done()
            if poison_pills_seen >= num_enrichment_workers:
                break
            continue

        # Accumulate skip/error counts from conversion phase
        rows_skipped += chunk.rows_skipped
        skipped_rows.extend(chunk.skipped_rows)
        errors.extend(chunk.errors)

        # Write
        created, write_errors = await _write_chunk(chunk)
        wines_created += created
        errors.extend(write_errors)

        # Credit the remaining half of this chunk's rows (enrichment took first half)
        chunk_rows = chunk.chunk_end - chunk.chunk_start
        remaining = chunk_rows - chunk_rows // 2  # handles odd sizes
        progress_state["processed"] += remaining
        progress_state["wines_created"] = wines_created
        progress_state["rows_skipped"] = rows_skipped

        _maybe_emit_progress(progress_queue, progress_state, total, "writer")

        write_queue.task_done()

    # Signal that all progress events have been pushed
    await progress_queue.put(_PROGRESS_DONE)

    return wines_created, rows_skipped, skipped_rows, errors


# ---------------------------------------------------------------------------
# Feeder — runs as a background task, feeds chunks and manages shutdown
# ---------------------------------------------------------------------------

async def _feeder(
    batch: ImportBatch,
    owner_id: PyObjectId,
    skip_non_wine: bool,
    default_quantity: int,
    chunk_size: int,
    total: int,
    enrichment_queue: asyncio.Queue[_Chunk | None],
    enrichment_tasks: list[asyncio.Task[None]],
    write_queue: asyncio.Queue[_Chunk | None],
    num_workers: int,
    existing_wines: set[tuple[str, ...]] | None = None,
    skip_duplicates: bool = False,
    default_case_size: int | None = None,
) -> None:
    """Feed chunks into the pipeline and manage orderly shutdown."""
    # Stream rows from raw_uploads collection by index
    collection = RawUploadRow.get_pymongo_collection()
    for chunk_start in range(0, total, chunk_size):
        chunk_end = min(chunk_start + chunk_size, total)
        cursor = collection.find(
            {
                "batch_id": batch.id,
                "index": {"$gte": chunk_start, "$lt": chunk_end},
            }
        ).sort("index", 1)
        docs = await cursor.to_list(length=chunk_end - chunk_start)
        rows = [doc.get("row", {}) for doc in docs]
        if not rows:
            continue
        chunk = await asyncio.to_thread(
            _convert_chunk_from_rows,
            rows,
            batch.column_mapping,
            owner_id,
            chunk_start,
            chunk_end,
            skip_non_wine,
            default_quantity,
            batch_id=batch.id,
            existing_wines=existing_wines,
            skip_duplicates=skip_duplicates,
            default_case_size=default_case_size,
        )
        await enrichment_queue.put(chunk)

    # Poison pills for enrichment workers
    for _ in range(num_workers):
        await enrichment_queue.put(None)

    # Wait for enrichment to complete
    await asyncio.gather(*enrichment_tasks)

    # Poison pills for writer
    for _ in range(num_workers):
        await write_queue.put(None)


# ---------------------------------------------------------------------------
# Main pipeline — replaces sequential _process_chunks
# ---------------------------------------------------------------------------

async def _prefetch_existing_wines(owner_id: PyObjectId) -> set[tuple[str, ...]]:
    """Fetch identity tuples for all wines owned by a user.

    Returns a set of (name, winery, vintage) tuples, lowercased and stripped,
    for O(1) duplicate lookups during import.
    """
    from .converters import _wine_identity_key

    wines_col = Wine.get_pymongo_collection()
    cursor = wines_col.find(
        {"owner_id": owner_id},
        {"name": 1, "winery": 1, "vintage": 1},
    )
    existing: set[tuple[str, ...]] = set()
    async for doc in cursor:
        existing.add(_wine_identity_key(doc))
    return existing


async def _process_chunks(
    batch: ImportBatch,
    owner_id: PyObjectId,
    skip_non_wine: bool = True,
    default_quantity: int = 1,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    skip_enrichment: bool = True,
    skip_duplicates: bool = False,
    default_case_size: int | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Process import rows using a pipelined async architecture.

    Pipeline:
      1. Split rows into chunk-sized batches, convert to wine dicts (sync)
      2. Feed chunks to enrichment_queue (background task)
      3. N enrichment tasks consume chunks, enrich via batch X-Wines query,
         push to write_queue
      4. 1 writer task consumes enriched chunks, does insert_many,
         pushes progress events to progress_queue
      5. This generator awaits progress_queue.get() and yields events
         to the SSE stream in real-time

    Yields dicts with keys: processed, total, wines_created, rows_skipped.
    The final yield includes done=True plus errors list and status.

    Args:
        batch: The ImportBatch document with rows and mapping.
        owner_id: Owner's ID for created wines.
        skip_non_wine: Whether to skip non-wine rows.
        default_quantity: Default bottle quantity.
        chunk_size: Number of rows per chunk.
        skip_duplicates: Whether to skip wines that already exist in cellar.
    """
    total = batch.row_count
    num_workers = ENRICHMENT_WORKERS

    # Pre-fetch existing wines for duplicate detection
    existing_wines = await _prefetch_existing_wines(owner_id) if skip_duplicates else None

    # Yield immediately so the client sees progress start without delay
    yield {
        "processed": 0,
        "total": total,
        "wines_created": 0,
        "rows_skipped": 0,
    }

    if total == 0:
        batch.wines_created = 0
        batch.rows_skipped = 0
        batch.errors = []
        batch.status = ImportStatus.COMPLETED
        await batch.save()
        yield {
            "done": True,
            "processed": 0,
            "total": 0,
            "wines_created": 0,
            "rows_skipped": 0,
            "errors": [],
            "status": "completed",
        }
        return

    # Queues
    enrichment_queue: asyncio.Queue[_Chunk | None] = asyncio.Queue(maxsize=num_workers * 2)
    write_queue: asyncio.Queue[_Chunk | None] = asyncio.Queue(maxsize=num_workers * 2)
    progress_queue: asyncio.Queue[dict[str, Any] | object] = asyncio.Queue()

    # Shared mutable progress state — safe because asyncio is single-threaded.
    # Enrichment workers credit half the chunk rows; writer credits the other half.
    progress_state: dict[str, Any] = {
        "processed": 0,
        "wines_created": 0,
        "rows_skipped": 0,
        "last_reported_pct": -1,
    }

    # Start enrichment workers
    enrichment_tasks = [
        asyncio.create_task(
            _enrichment_worker(
                enrichment_queue,
                write_queue,
                progress_queue,
                progress_state,
                total,
                skip_enrichment,
            )
        )
        for _ in range(num_workers)
    ]

    # Start writer (pushes progress events; pushes _PROGRESS_DONE when finished)
    writer_future: asyncio.Future[tuple[int, int, list[dict[str, Any]], list[str]]] = asyncio.ensure_future(
        _writer_worker(write_queue, progress_queue, progress_state, total, num_workers)
    )

    # Start feeder as a background task so we can drain progress_queue
    # concurrently instead of being blocked feeding chunks
    feeder_task = asyncio.create_task(
        _feeder(
            batch,
            owner_id,
            skip_non_wine,
            default_quantity,
            chunk_size,
            total,
            enrichment_queue,
            enrichment_tasks,
            write_queue,
            num_workers,
            existing_wines=existing_wines,
            skip_duplicates=skip_duplicates,
            default_case_size=default_case_size,
        )
    )

    # Yield progress events in real-time as the writer produces them.
    # The writer pushes _PROGRESS_DONE when all chunks are written.
    while True:
        event = await progress_queue.get()
        if event is _PROGRESS_DONE:
            break
        yield event

    # Collect final results from writer
    wines_created, rows_skipped, skipped_rows, errors = await writer_future
    await feeder_task

    # Compute unmapped headers from the column mapping
    if batch.column_mapping:
        batch.unmapped_headers = [
            header for header, field in batch.column_mapping.items()
            if field.startswith("custom:") or field == "skip"
        ]

    # Save final batch state
    batch.wines_created = wines_created
    batch.rows_skipped = rows_skipped
    batch.skipped_rows_detail = skipped_rows
    batch.errors = errors
    batch.status = ImportStatus.COMPLETED
    await batch.save()

    # Note: background enrichment is triggered by the router after the stream
    # completes, not here inside the generator (asyncio.create_task inside a
    # generator doesn't reliably persist after the response closes).

    # Final yield with done=True
    yield {
        "done": True,
        "processed": total,
        "total": total,
        "wines_created": wines_created,
        "rows_skipped": rows_skipped,
        "skipped_rows": skipped_rows,
        "errors": errors,
        "status": "completed",
        # True when the caller deferred enrichment with skip_enrichment=True
        # and at least one wine was created — tells the router to kick off
        # async enrichment after the SSE stream closes. The frontend reads
        # this flag to show a "Enriching wines…" banner.
        "trigger_post_import_enrichment": wines_created > 0 and skip_enrichment,
    }


async def process_import_batch(
    batch: ImportBatch,
    owner_id: PyObjectId,
    skip_non_wine: bool = True,
    default_quantity: int = 1,
    skip_enrichment: bool = True,
    skip_duplicates: bool = False,
    default_case_size: int | None = None,
) -> ImportBatch:
    """Process an import batch: create Wine documents from mapped rows."""
    if not batch.column_mapping:
        batch.status = ImportStatus.FAILED
        batch.errors.append("No column mapping set")
        await batch.save()
        return batch

    batch.status = ImportStatus.PROCESSING
    await batch.save()

    async for _progress in _process_chunks(
        batch,
        owner_id,
        skip_non_wine,
        default_quantity,
        skip_enrichment=skip_enrichment,
        skip_duplicates=skip_duplicates,
        default_case_size=default_case_size,
    ):
        pass

    return batch


async def process_import_batch_streaming(
    batch: ImportBatch,
    owner_id: PyObjectId,
    skip_non_wine: bool = True,
    default_quantity: int = 1,
    skip_enrichment: bool = True,
    skip_duplicates: bool = False,
    default_case_size: int | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Process an import batch, yielding progress after each chunk.

    Yields dicts with keys: processed, total, wines_created, rows_skipped.
    The final yield includes done=True plus errors list.

    Args:
        batch: The ImportBatch document with rows and mapping.
        owner_id: Owner's ID for created wines.
        skip_non_wine: Whether to skip non-wine rows.
        default_quantity: Default bottle quantity.
        skip_duplicates: Whether to skip wines already in cellar.
    """
    if not batch.column_mapping:
        batch.status = ImportStatus.FAILED
        batch.errors.append("No column mapping set")
        await batch.save()
        yield {
            "done": True,
            "processed": 0,
            "total": 0,
            "wines_created": 0,
            "rows_skipped": 0,
            "errors": ["No column mapping set"],
            "status": "failed",
        }
        return

    batch.status = ImportStatus.PROCESSING
    await batch.save()

    async for progress in _process_chunks(
        batch,
        owner_id,
        skip_non_wine,
        default_quantity,
        skip_enrichment=skip_enrichment,
        skip_duplicates=skip_duplicates,
        default_case_size=default_case_size,
    ):
        yield progress
