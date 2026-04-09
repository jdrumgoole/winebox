"""Background enrichment service for wines imported without X-Wines data.

Runs as a background asyncio task after CSV import completes. Finds wines
with no xwines_id, batches them through Atlas Search + Claude re-ranking,
and updates matched wines with reference data.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pymongo import UpdateOne

from winebox.db import PyObjectId
from winebox.models.wine import Wine
from winebox.services.xwines_enrichment import (
    _FIELD_MAP,
    _find_best_xwines_matches_batch,
    parse_xwines_grapes,
)

logger = logging.getLogger(__name__)

# Batch size for background enrichment
ENRICHMENT_BATCH_SIZE = 50

# In-memory progress store keyed by owner_id string.
# Each entry: {"phase": str, "enriched": int, "total": int}
_enrichment_progress: dict[str, dict[str, Any]] = {}


def get_enrichment_progress(owner_id: str) -> dict[str, Any] | None:
    """Get the current enrichment progress for an owner."""
    return _enrichment_progress.get(owner_id)


def clear_enrichment_progress(owner_id: str) -> None:
    """Clear enrichment progress for an owner."""
    _enrichment_progress.pop(owner_id, None)


async def enrich_unenriched_wines(
    owner_id: PyObjectId,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, int]:
    """Enrich wines that have no xwines_id set.

    Uses bulk_write to batch database updates instead of per-wine writes.
    Streams wines from the cursor in batches to avoid loading all into memory.
    """
    owner_str = str(owner_id)
    wines_col = Wine.get_pymongo_collection()

    # Set progress immediately so the SSE endpoint knows enrichment is starting
    _enrichment_progress[owner_str] = {
        "phase": "enriching",
        "enriched": 0,
        "total": 0,
    }

    # Count unenriched wines (lightweight query, no data transfer)
    total = await wines_col.count_documents(
        {"owner_id": owner_id, "xwines_id": None},
    )

    if total == 0:
        _enrichment_progress[owner_str] = {
            "phase": "done",
            "enriched": 0,
            "total": 0,
        }
        return {"total": 0, "enriched": 0, "failed": 0}

    _enrichment_progress[owner_str] = {
        "phase": "enriching",
        "enriched": 0,
        "total": total,
    }

    enriched_count = 0
    failed_count = 0

    # Stream wines in batches using skip/limit to avoid loading all into memory
    processed = 0
    while processed < total:
        batch_docs = await wines_col.find(
            {"owner_id": owner_id, "xwines_id": None},
        ).sort("_id", 1).limit(ENRICHMENT_BATCH_SIZE).to_list(length=ENRICHMENT_BATCH_SIZE)

        if not batch_docs:
            break

        names = [doc["name"] for doc in batch_docs]

        try:
            matches = await _find_best_xwines_matches_batch(names)
        except Exception as e:
            logger.warning("Batch enrichment lookup failed: %s", e)
            failed_count += len(batch_docs)
            processed += len(batch_docs)
            continue

        # Build bulk update operations for this batch
        bulk_ops = []
        now = datetime.now(timezone.utc)

        for doc in batch_docs:
            match = matches.get(doc["name"])
            if not match:
                continue

            enriched_fields: list[str] = []
            update_dict: dict[str, Any] = {}

            for parsed_key, xwines_attr, transform in _FIELD_MAP:
                existing_value = doc.get(parsed_key)
                if existing_value:
                    continue

                xwines_value = getattr(match, xwines_attr, None)
                if not xwines_value:
                    continue

                if transform == "grapes":
                    xwines_value = parse_xwines_grapes(str(xwines_value))
                elif transform == "lowercase":
                    xwines_value = str(xwines_value).lower()

                if xwines_value:
                    update_dict[parsed_key] = xwines_value
                    enriched_fields.append(parsed_key)

            if not doc.get("wine_type_id") and match.wine_type:
                wt = str(match.wine_type).lower()
                update_dict["wine_type_id"] = wt
                enriched_fields.append("wine_type_id")

            update_dict["xwines_id"] = match.xwines_id
            update_dict["enriched_fields"] = enriched_fields
            update_dict["updated_at"] = now

            bulk_ops.append(
                UpdateOne({"_id": doc["_id"]}, {"$set": update_dict})
            )

        # Execute all updates for this batch in one round-trip
        if bulk_ops:
            try:
                result = await wines_col.bulk_write(bulk_ops, ordered=False)
                enriched_count += result.modified_count
            except Exception as e:
                logger.warning("Bulk enrichment write failed: %s", e)
                failed_count += len(bulk_ops)

        processed += len(batch_docs)

        _enrichment_progress[owner_str] = {
            "phase": "enriching",
            "enriched": enriched_count,
            "total": total,
        }

        if progress_callback:
            progress_callback(enriched_count, total)

        await asyncio.sleep(0)

    _enrichment_progress[owner_str] = {
        "phase": "done",
        "enriched": enriched_count,
        "total": total,
    }

    logger.info(
        "Background enrichment complete for owner %s: %d/%d enriched, %d failed",
        owner_str, enriched_count, total, failed_count,
    )

    return {"total": total, "enriched": enriched_count, "failed": failed_count}
