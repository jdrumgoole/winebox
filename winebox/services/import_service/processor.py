"""Batch processing for wine imports."""

import logging

from beanie import PydanticObjectId

from winebox.models.import_batch import ImportBatch, ImportStatus
from winebox.models.wine import Wine

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
