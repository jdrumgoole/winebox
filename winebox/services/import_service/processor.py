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
from typing import Any

from beanie import PydanticObjectId
from pymongo.errors import BulkWriteError

from winebox.models.import_batch import ImportBatch, ImportStatus
from winebox.models.wine import Wine
from winebox.services.xwines_enrichment import enrich_batch_with_xwines

from .constants import ENRICHMENT_WORKERS
from .converters import is_non_wine_row, row_to_wine_data

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 25

# Sentinel pushed to progress_queue when the writer is done
_PROGRESS_DONE = object()


# ---------------------------------------------------------------------------
# Chunk dataclass — carries a batch of rows through the pipeline
# ---------------------------------------------------------------------------

class _Chunk:
    """A batch of rows moving through the enrichment/write pipeline."""

    __slots__ = ("wine_datas", "chunk_start", "chunk_end", "rows_skipped", "errors")

    def __init__(
        self,
        wine_datas: list[tuple[dict[str, Any], int]],
        chunk_start: int,
        chunk_end: int,
        rows_skipped: int,
        errors: list[str],
    ) -> None:
        self.wine_datas = wine_datas
        self.chunk_start = chunk_start
        self.chunk_end = chunk_end
        self.rows_skipped = rows_skipped
        self.errors = errors


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def _convert_chunk(
    batch: ImportBatch,
    owner_id: PydanticObjectId,
    chunk_start: int,
    chunk_end: int,
    skip_non_wine: bool,
    default_quantity: int,
) -> _Chunk:
    """Phase 1: Convert raw rows to wine dicts (sync, fast)."""
    chunk_rows = batch.rows[chunk_start:chunk_end]
    wine_datas: list[tuple[dict[str, Any], int]] = []
    rows_skipped = 0
    errors: list[str] = []

    for offset, row in enumerate(chunk_rows):
        row_index = chunk_start + offset  # 0-based
        try:
            if skip_non_wine and is_non_wine_row(row, batch.column_mapping):
                rows_skipped += 1
                continue

            wine_data = row_to_wine_data(row, batch.column_mapping, owner_id, default_quantity)
            if wine_data is None:
                rows_skipped += 1
                continue

            wine_datas.append((wine_data, row_index + 1))
        except Exception as e:
            error_msg = f"Row {row_index + 1}: {str(e)}"
            errors.append(error_msg)
            logger.warning("Import error on row %d: %s", row_index + 1, e)

    return _Chunk(wine_datas, chunk_start, chunk_end, rows_skipped, errors)


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

    wine_docs = [Wine(**wd) for wd, _ in chunk.wine_datas]
    errors: list[str] = []
    wines_created = 0

    try:
        await Wine.insert_many(wine_docs)
        wines_created = len(wine_docs)
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
            await _enrich_chunk(chunk)
        finally:
            # Credit half the chunk rows for the enrichment phase
            chunk_rows = chunk.chunk_end - chunk.chunk_start
            progress_state["processed"] += chunk_rows // 2
            await progress_queue.put({
                "processed": progress_state["processed"],
                "total": total,
                "wines_created": progress_state["wines_created"],
                "rows_skipped": progress_state["rows_skipped"],
            })
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
) -> tuple[int, int, list[str]]:
    """Writer: dequeue enriched chunks, insert_many, push progress updates.

    Credits the remaining half of each chunk's rows (enrichment credited the
    first half). Pushes _PROGRESS_DONE sentinel when all work is complete.
    Returns cumulative (wines_created, rows_skipped, errors).
    """
    wines_created = 0
    rows_skipped = 0
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

        # Push progress
        await progress_queue.put({
            "processed": progress_state["processed"],
            "total": total,
            "wines_created": wines_created,
            "rows_skipped": rows_skipped,
        })

        write_queue.task_done()

    # Signal that all progress events have been pushed
    await progress_queue.put(_PROGRESS_DONE)

    return wines_created, rows_skipped, errors


# ---------------------------------------------------------------------------
# Feeder — runs as a background task, feeds chunks and manages shutdown
# ---------------------------------------------------------------------------

async def _feeder(
    batch: ImportBatch,
    owner_id: PydanticObjectId,
    skip_non_wine: bool,
    default_quantity: int,
    chunk_size: int,
    total: int,
    enrichment_queue: asyncio.Queue[_Chunk | None],
    enrichment_tasks: list[asyncio.Task[None]],
    write_queue: asyncio.Queue[_Chunk | None],
    num_workers: int,
) -> None:
    """Feed chunks into the pipeline and manage orderly shutdown."""
    # Convert and enqueue all chunks
    for chunk_start in range(0, total, chunk_size):
        chunk_end = min(chunk_start + chunk_size, total)
        chunk = _convert_chunk(
            batch, owner_id, chunk_start, chunk_end, skip_non_wine, default_quantity,
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

async def _process_chunks(
    batch: ImportBatch,
    owner_id: PydanticObjectId,
    skip_non_wine: bool = True,
    default_quantity: int = 1,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
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
    """
    total = len(batch.rows)
    num_workers = ENRICHMENT_WORKERS

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
    progress_state: dict[str, int] = {
        "processed": 0,
        "wines_created": 0,
        "rows_skipped": 0,
    }

    # Start enrichment workers
    enrichment_tasks = [
        asyncio.create_task(
            _enrichment_worker(
                enrichment_queue, write_queue, progress_queue, progress_state, total,
            )
        )
        for _ in range(num_workers)
    ]

    # Start writer (pushes progress events; pushes _PROGRESS_DONE when finished)
    writer_future: asyncio.Future[tuple[int, int, list[str]]] = asyncio.ensure_future(
        _writer_worker(write_queue, progress_queue, progress_state, total, num_workers)
    )

    # Start feeder as a background task so we can drain progress_queue
    # concurrently instead of being blocked feeding chunks
    feeder_task = asyncio.create_task(
        _feeder(
            batch, owner_id, skip_non_wine, default_quantity, chunk_size,
            total, enrichment_queue, enrichment_tasks, write_queue, num_workers,
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
    wines_created, rows_skipped, errors = await writer_future
    await feeder_task

    # Save final batch state
    batch.wines_created = wines_created
    batch.rows_skipped = rows_skipped
    batch.errors = errors
    batch.status = ImportStatus.COMPLETED
    await batch.save()

    # Final yield with done=True
    yield {
        "done": True,
        "processed": total,
        "total": total,
        "wines_created": wines_created,
        "rows_skipped": rows_skipped,
        "errors": errors,
        "status": "completed",
    }


async def process_import_batch(
    batch: ImportBatch,
    owner_id: PydanticObjectId,
    skip_non_wine: bool = True,
    default_quantity: int = 1,
) -> ImportBatch:
    """Process an import batch: create Wine documents from mapped rows.

    Args:
        batch: The ImportBatch document with rows and mapping.
        owner_id: Owner's ID for created wines.
        skip_non_wine: Whether to skip non-wine rows.
        default_quantity: Default bottle quantity.

    Returns:
        Updated ImportBatch with processing results.
    """
    if not batch.column_mapping:
        batch.status = ImportStatus.FAILED
        batch.errors.append("No column mapping set")
        await batch.save()
        return batch

    batch.status = ImportStatus.PROCESSING
    await batch.save()

    async for _progress in _process_chunks(batch, owner_id, skip_non_wine, default_quantity):
        pass  # Consume all progress; batch is saved inside _process_chunks

    return batch


async def process_import_batch_streaming(
    batch: ImportBatch,
    owner_id: PydanticObjectId,
    skip_non_wine: bool = True,
    default_quantity: int = 1,
) -> AsyncGenerator[dict[str, Any], None]:
    """Process an import batch, yielding progress after each chunk.

    Yields dicts with keys: processed, total, wines_created, rows_skipped.
    The final yield includes done=True plus errors list.

    Args:
        batch: The ImportBatch document with rows and mapping.
        owner_id: Owner's ID for created wines.
        skip_non_wine: Whether to skip non-wine rows.
        default_quantity: Default bottle quantity.
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

    async for progress in _process_chunks(batch, owner_id, skip_non_wine, default_quantity):
        yield progress
