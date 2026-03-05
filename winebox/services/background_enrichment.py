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

from beanie import PydanticObjectId

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
    """Get the current enrichment progress for an owner.

    Args:
        owner_id: Owner ID string.

    Returns:
        Progress dict or None if no enrichment is running.
    """
    return _enrichment_progress.get(owner_id)


def clear_enrichment_progress(owner_id: str) -> None:
    """Clear enrichment progress for an owner.

    Args:
        owner_id: Owner ID string.
    """
    _enrichment_progress.pop(owner_id, None)


async def enrich_unenriched_wines(
    owner_id: PydanticObjectId,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, int]:
    """Enrich wines that have no xwines_id set.

    Queries for unenriched wines belonging to the owner, batches them,
    runs Atlas Search + Claude re-ranking, and updates matched documents.

    Args:
        owner_id: The owner whose wines to enrich.
        progress_callback: Optional callback(enriched_so_far, total) called
            after each batch completes.

    Returns:
        Dict with keys: total, enriched, failed.
    """
    owner_str = str(owner_id)

    # Find all unenriched wines for this owner
    unenriched = await Wine.find(
        Wine.owner_id == owner_id,
        Wine.xwines_id == None,  # noqa: E711
    ).to_list()

    total = len(unenriched)
    if total == 0:
        return {"total": 0, "enriched": 0, "failed": 0}

    # Update progress store
    _enrichment_progress[owner_str] = {
        "phase": "enriching",
        "enriched": 0,
        "total": total,
    }

    enriched_count = 0
    failed_count = 0

    # Process in batches
    for batch_start in range(0, total, ENRICHMENT_BATCH_SIZE):
        batch_end = min(batch_start + ENRICHMENT_BATCH_SIZE, total)
        batch = unenriched[batch_start:batch_end]

        names = [wine.name for wine in batch]

        try:
            matches = await _find_best_xwines_matches_batch(names)
        except Exception as e:
            logger.warning("Batch enrichment lookup failed: %s", e)
            failed_count += len(batch)
            continue

        for wine in batch:
            match = matches.get(wine.name)
            if not match:
                continue

            # Apply enrichment fields
            enriched_fields: list[str] = []
            update_dict: dict[str, Any] = {}

            for parsed_key, xwines_attr, transform in _FIELD_MAP:
                existing_value = getattr(wine, parsed_key, None)
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

            # Also fill wine_type_id from wine_type if empty
            if not wine.wine_type_id and match.wine_type:
                wt = str(match.wine_type).lower()
                update_dict["wine_type_id"] = wt
                enriched_fields.append("wine_type_id")

            update_dict["xwines_id"] = match.xwines_id
            update_dict["enriched_fields"] = enriched_fields
            update_dict["updated_at"] = datetime.now(timezone.utc)

            try:
                await wine.set(update_dict)
                enriched_count += 1
            except Exception as e:
                logger.warning("Failed to update wine %s: %s", wine.id, e)
                failed_count += 1

        # Update progress
        _enrichment_progress[owner_str] = {
            "phase": "enriching",
            "enriched": enriched_count,
            "total": total,
        }

        if progress_callback:
            progress_callback(enriched_count, total)

        # Yield control to event loop between batches
        await asyncio.sleep(0)

    # Mark as done
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
