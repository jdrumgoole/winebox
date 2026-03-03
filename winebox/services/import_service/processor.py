"""Batch processing for wine imports."""

import logging
from collections.abc import AsyncGenerator
from typing import Any

from beanie import PydanticObjectId

from winebox.models.import_batch import ImportBatch, ImportStatus
from winebox.models.wine import Wine
from winebox.services.xwines_enrichment import enrich_parsed_with_xwines

from .converters import is_non_wine_row, row_to_wine_data

logger = logging.getLogger(__name__)


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

    wines_created = 0
    rows_skipped = 0
    errors: list[str] = []

    for i, row in enumerate(batch.rows):
        try:
            # Skip non-wine rows
            if skip_non_wine and is_non_wine_row(row, batch.column_mapping):
                rows_skipped += 1
                continue

            wine_data = row_to_wine_data(row, batch.column_mapping, owner_id, default_quantity)
            if wine_data is None:
                rows_skipped += 1
                continue

            # Enrich with X-Wines data (best-effort, non-fatal)
            try:
                enrichment_input = {
                    "name": wine_data.get("name"),
                    "winery": wine_data.get("winery"),
                    "grape_variety": wine_data.get("grape_variety"),
                    "region": wine_data.get("region"),
                    "country": wine_data.get("country"),
                    "alcohol_percentage": wine_data.get("alcohol_percentage"),
                }
                enrichment_result = await enrich_parsed_with_xwines(enrichment_input)
                enriched_fields = enrichment_result.pop("enriched_fields", None)
                xwines_id = enrichment_result.pop("xwines_id", None)

                for key in ("winery", "grape_variety", "region", "country", "alcohol_percentage"):
                    if enrichment_result.get(key):
                        wine_data[key] = enrichment_result[key]

                wine_data["enriched_fields"] = enriched_fields
                wine_data["xwines_id"] = xwines_id
            except Exception as e:
                logger.warning("X-Wines enrichment failed for row %d: %s", i + 1, e)

            wine = Wine(**wine_data)
            await wine.insert()
            wines_created += 1

        except Exception as e:
            error_msg = f"Row {i + 1}: {str(e)}"
            errors.append(error_msg)
            logger.warning("Import error on row %d: %s", i + 1, e)

    batch.wines_created = wines_created
    batch.rows_skipped = rows_skipped
    batch.errors = errors
    batch.status = ImportStatus.COMPLETED
    await batch.save()

    return batch


async def process_import_batch_streaming(
    batch: ImportBatch,
    owner_id: PydanticObjectId,
    skip_non_wine: bool = True,
    default_quantity: int = 1,
) -> AsyncGenerator[dict[str, Any], None]:
    """Process an import batch, yielding progress after each row.

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

    total = len(batch.rows)
    wines_created = 0
    rows_skipped = 0
    errors: list[str] = []

    for i, row in enumerate(batch.rows):
        try:
            if skip_non_wine and is_non_wine_row(row, batch.column_mapping):
                rows_skipped += 1
                yield {
                    "processed": i + 1,
                    "total": total,
                    "wines_created": wines_created,
                    "rows_skipped": rows_skipped,
                }
                continue

            wine_data = row_to_wine_data(row, batch.column_mapping, owner_id, default_quantity)
            if wine_data is None:
                rows_skipped += 1
                yield {
                    "processed": i + 1,
                    "total": total,
                    "wines_created": wines_created,
                    "rows_skipped": rows_skipped,
                }
                continue

            # Enrich with X-Wines data (best-effort, non-fatal)
            try:
                enrichment_input = {
                    "name": wine_data.get("name"),
                    "winery": wine_data.get("winery"),
                    "grape_variety": wine_data.get("grape_variety"),
                    "region": wine_data.get("region"),
                    "country": wine_data.get("country"),
                    "alcohol_percentage": wine_data.get("alcohol_percentage"),
                }
                enrichment_result = await enrich_parsed_with_xwines(enrichment_input)
                enriched_fields = enrichment_result.pop("enriched_fields", None)
                xwines_id = enrichment_result.pop("xwines_id", None)

                for key in ("winery", "grape_variety", "region", "country", "alcohol_percentage"):
                    if enrichment_result.get(key):
                        wine_data[key] = enrichment_result[key]

                wine_data["enriched_fields"] = enriched_fields
                wine_data["xwines_id"] = xwines_id
            except Exception as e:
                logger.warning("X-Wines enrichment failed for row %d: %s", i + 1, e)

            wine = Wine(**wine_data)
            await wine.insert()
            wines_created += 1

        except Exception as e:
            error_msg = f"Row {i + 1}: {str(e)}"
            errors.append(error_msg)
            logger.warning("Import error on row %d: %s", i + 1, e)

        yield {
            "processed": i + 1,
            "total": total,
            "wines_created": wines_created,
            "rows_skipped": rows_skipped,
        }

    batch.wines_created = wines_created
    batch.rows_skipped = rows_skipped
    batch.errors = errors
    batch.status = ImportStatus.COMPLETED
    await batch.save()

    yield {
        "done": True,
        "processed": total,
        "total": total,
        "wines_created": wines_created,
        "rows_skipped": rows_skipped,
        "errors": errors,
        "status": "completed",
    }
