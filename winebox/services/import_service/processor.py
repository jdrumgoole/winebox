"""Batch processing for wine imports."""

import logging
from collections.abc import AsyncGenerator
from typing import Any

from beanie import PydanticObjectId
from pymongo.errors import BulkWriteError

from winebox.models.import_batch import ImportBatch, ImportStatus
from winebox.models.wine import Wine
from winebox.services.xwines_enrichment import enrich_batch_with_xwines

from .converters import is_non_wine_row, row_to_wine_data

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 50


async def _process_chunks(
    batch: ImportBatch,
    owner_id: PydanticObjectId,
    skip_non_wine: bool = True,
    default_quantity: int = 1,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> AsyncGenerator[dict[str, Any], None]:
    """Process import rows in chunks, yielding progress after each chunk.

    Within each chunk:
    1. Convert all rows to wine dicts (fast, sync)
    2. Enrich all rows via single batch X-Wines lookup (one DB query per chunk)
    3. Insert all Wine docs in one insert_many call (single DB round-trip)
    4. Yield progress event

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
    wines_created = 0
    rows_skipped = 0
    errors: list[str] = []

    # Yield immediately so the client sees progress start without delay
    yield {
        "processed": 0,
        "total": total,
        "wines_created": 0,
        "rows_skipped": 0,
    }

    for chunk_start in range(0, total, chunk_size):
        chunk_end = min(chunk_start + chunk_size, total)
        chunk_rows = batch.rows[chunk_start:chunk_end]

        # Phase 1: Convert rows to wine dicts
        wine_datas: list[tuple[dict[str, Any], int]] = []  # (wine_data, 1-based row_index)
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

        # Phase 2: Enrich all rows in this chunk with a single batch query
        if wine_datas:
            enrichment_inputs = []
            for wd, _ in wine_datas:
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
                for (wd, _), enriched in zip(wine_datas, enrichment_inputs):
                    enriched_fields = enriched.pop("enriched_fields", None)
                    xwines_id = enriched.pop("xwines_id", None)
                    for key in ("winery", "grape_variety", "region", "country", "alcohol_percentage"):
                        if enriched.get(key):
                            wd[key] = enriched[key]
                    wd["enriched_fields"] = enriched_fields
                    wd["xwines_id"] = xwines_id
            except Exception as e:
                logger.warning("Batch enrichment failed for chunk %d-%d: %s", chunk_start + 1, chunk_end, e)

            # Mid-chunk progress: enrichment done, inserting next
            yield {
                "processed": chunk_start,  # Not yet at chunk_end (insert pending)
                "total": total,
                "wines_created": wines_created,
                "rows_skipped": rows_skipped,
                "phase": "inserting",
            }

        # Phase 3: Batch insert Wine documents
        if wine_datas:
            wine_docs = [Wine(**wd) for wd, _ in wine_datas]
            try:
                await Wine.insert_many(wine_docs)
                wines_created += len(wine_docs)
            except BulkWriteError as e:
                n_inserted = e.details.get("nInserted", 0)
                wines_created += n_inserted
                failed = len(wine_docs) - n_inserted
                error_msg = f"Batch insert partial failure: {failed} of {len(wine_docs)} failed"
                errors.append(error_msg)
                logger.warning(error_msg)
            except Exception as e:
                error_msg = f"Batch insert failed for rows {chunk_start + 1}-{chunk_end}: {str(e)}"
                errors.append(error_msg)
                logger.warning(error_msg)

        # Yield progress after each chunk
        yield {
            "processed": chunk_end,
            "total": total,
            "wines_created": wines_created,
            "rows_skipped": rows_skipped,
        }

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
