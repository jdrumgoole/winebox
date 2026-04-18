"""Post-import batch operations: rollback, remap, summary.

These previously lived inline in ``routers/import_router.py`` as handlers
that mixed HTTP concerns with multi-collection writes and aggregation.
Keeping them here lets the router stay thin and keeps the three-collection
rollback logic (wines + cellar_items + cellar_events) in one place.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from pymongo import UpdateOne

from winebox.db import PyObjectId
from winebox.models.cellar import CellarItem
from winebox.models.cellar_event import CellarEvent
from winebox.models.import_batch import ImportBatch, ImportStatus
from winebox.models.import_batch_row import RawUploadRow
from winebox.models.wine import Wine

from .constants import VALID_WINE_FIELDS

logger = logging.getLogger(__name__)


class BatchNotCompletedError(Exception):
    """Raised when an operation requires a completed batch and it isn't."""


class BatchNotRollbackableError(Exception):
    """Raised when a batch is in a state that can't be rolled back."""


class InvalidMappingError(Exception):
    """Raised when a remap request contains an invalid target field."""


@dataclass(frozen=True)
class RollbackResult:
    wines_deleted: int
    status: str


@dataclass(frozen=True)
class RemapResult:
    wines_updated: int
    fields_added: list[str]


async def rollback_batch(batch: ImportBatch) -> RollbackResult:
    """Delete all wines, cellar items, and cellar events for a batch.

    Marks the batch as ``ROLLED_BACK``. Accepts batches in the
    ``COMPLETED`` or ``PROCESSING`` state (partial imports can be undone).
    """
    if batch.status not in (ImportStatus.COMPLETED, ImportStatus.PROCESSING):
        raise BatchNotRollbackableError(
            "Only completed or in-progress imports can be undone"
        )

    wines_col = Wine.get_pymongo_collection()
    result = await wines_col.delete_many({
        "owner_id": batch.owner_id,
        "import_batch_id": batch.id,
    })

    await CellarItem.get_pymongo_collection().delete_many({
        "cellar_id": batch.owner_id,
        "import_batch_id": batch.id,
    })
    await CellarEvent.get_pymongo_collection().delete_many({
        "cellar_id": batch.owner_id,
        "import_batch_id": batch.id,
    })

    batch.status = ImportStatus.ROLLED_BACK
    await batch.save()

    logger.info(
        "Rolled back import batch %s: deleted %d wines for user %s",
        batch.id, result.deleted_count, batch.owner_id,
    )

    return RollbackResult(
        wines_deleted=result.deleted_count,
        status=ImportStatus.ROLLED_BACK.value,
    )


def _validate_remap_targets(mapping: dict[str, str]) -> None:
    """Raise :class:`InvalidMappingError` if any mapping target is invalid."""
    for header, field in mapping.items():
        if field == "skip":
            continue
        if field.startswith("custom:"):
            if not field[7:]:
                raise InvalidMappingError(
                    f"Custom field name cannot be empty for column '{header}'"
                )
            continue
        if field not in VALID_WINE_FIELDS:
            raise InvalidMappingError(
                f"Invalid mapping target '{field}' for column '{header}'"
            )


async def apply_column_remap(
    batch: ImportBatch,
    owner_id: PyObjectId,
    mapping: dict[str, str],
) -> RemapResult:
    """Apply a new column mapping to wines already created by ``batch``.

    Loads each raw row, looks up the corresponding Wine by name, and fills
    in any previously-empty field for which the caller has supplied a new
    mapping. Wines with no matching raw row (or an empty value for the
    remapped column) are left untouched.
    """
    if batch.status != ImportStatus.COMPLETED:
        raise BatchNotCompletedError("Batch must be completed before remapping")

    _validate_remap_targets(mapping)

    wines = await Wine.find(
        {"import_batch_id": batch.id, "owner_id": owner_id}
    ).to_list()
    if not wines:
        return RemapResult(wines_updated=0, fields_added=[])

    raw_collection = RawUploadRow.get_pymongo_collection()
    cursor = raw_collection.find({"batch_id": batch.id}).sort("index", 1)
    raw_rows_by_index: dict[int, dict] = {}
    async for doc in cursor:
        raw_rows_by_index[doc["index"]] = doc.get("row", {})

    # Multiple wines can share a name within one batch; match wines to raw
    # rows in insertion order by popping from a per-name queue.
    wine_by_name: dict[str, list[Wine]] = defaultdict(list)
    for wine in wines:
        wine_by_name[wine.name].append(wine)

    name_header = None
    if batch.column_mapping:
        for h, f in batch.column_mapping.items():
            if f == "name":
                name_header = h
                break

    bulk_ops: list[UpdateOne] = []
    wines_updated = 0
    fields_added: set[str] = set()

    for idx in sorted(raw_rows_by_index.keys()):
        raw_row = raw_rows_by_index[idx]
        if not name_header:
            continue

        row_name = str(raw_row.get(name_header, "")).strip()
        if not row_name or not wine_by_name.get(row_name):
            continue

        wine = wine_by_name[row_name].pop(0)
        updates: dict[str, Any] = {}

        for header, field in mapping.items():
            if field == "skip":
                continue
            value = str(raw_row.get(header, "")).strip()
            if not value:
                continue

            if field.startswith("custom:"):
                custom_name = field[7:]
                updates[f"custom_fields.{custom_name}"] = value
                fields_added.add(custom_name)
            elif field in VALID_WINE_FIELDS:
                current_val = getattr(wine, field, None)
                if current_val is None or current_val == "" or current_val == 0:
                    updates[field] = value
                    fields_added.add(field)

        if updates:
            bulk_ops.append(UpdateOne({"_id": wine.id}, {"$set": updates}))
            wines_updated += 1

    if bulk_ops:
        wines_col = Wine.get_pymongo_collection()
        await wines_col.bulk_write(bulk_ops, ordered=False)

    # Strip remapped headers from the batch's unmapped list and merge the
    # new mapping into the original.
    remapped_headers = [h for h, f in mapping.items() if f != "skip"]
    batch.unmapped_headers = [
        h for h in batch.unmapped_headers if h not in remapped_headers
    ]
    if batch.column_mapping:
        batch.column_mapping.update(mapping)
    await batch.save()

    return RemapResult(
        wines_updated=wines_updated,
        fields_added=sorted(fields_added),
    )


async def summarize_batch_wines(
    batch: ImportBatch,
    owner_id: PyObjectId,
) -> dict[str, Any]:
    """Return the wines created by a batch along with display summary stats.

    Shape matches what ``GET /api/import/{batch_id}/wines`` returns — owner
    IDs are stripped from wine documents since the caller already owns them.
    """
    wines = await Wine.find(
        {"import_batch_id": batch.id, "owner_id": owner_id}
    ).to_list()

    wine_types: dict[str, int] = {}
    countries: dict[str, int] = {}
    grapes: dict[str, int] = {}
    vintages: dict[str, int] = {}

    for wine in wines:
        if wine.wine_type:
            wine_types[wine.wine_type] = wine_types.get(wine.wine_type, 0) + 1
        if wine.country:
            countries[wine.country] = countries.get(wine.country, 0) + 1
        if wine.grape_variety:
            grapes[wine.grape_variety] = grapes.get(wine.grape_variety, 0) + 1
        if wine.vintage:
            vintages[str(wine.vintage)] = vintages.get(str(wine.vintage), 0) + 1

    wine_list: list[dict[str, Any]] = []
    for wine in wines:
        wine_dict = wine.model_dump(mode="json")
        wine_dict["id"] = str(wine.id)
        wine_dict.pop("owner_id", None)
        wine_list.append(wine_dict)

    total_bottles = sum(
        (w.inventory.quantity if w.inventory else 0) for w in wines
    )

    total_cases = 0
    if batch.id:
        total_cases = await CellarItem.get_pymongo_collection().count_documents({
            "cellar_id": owner_id,
            "item_type": "case",
            "import_batch_id": batch.id,
        })

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
