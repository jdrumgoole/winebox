"""Enrichment endpoints for background X-Wines enrichment."""

import asyncio
import json
import logging

from fastapi import Request
from starlette.responses import StreamingResponse

from winebox.models.wine import Wine
from winebox.services.auth import RequireAuth
from winebox.services.background_enrichment import (
    clear_enrichment_progress,
    enrich_unenriched_wines,
    get_enrichment_progress,
)
from winebox.services.rate_limit import make_limiter

logger = logging.getLogger(__name__)

# Anthropic-bound and cost-bound; bursts of triggers are wasteful.
limiter = make_limiter()


async def enrichment_progress(current_user: RequireAuth) -> StreamingResponse:
    """SSE stream for background enrichment progress.

    Returns events with phase, enriched count, and total.
    Closes when enrichment is done or after timeout.
    """
    owner_str = str(current_user.id)

    async def event_generator():
        max_polls = 600  # 5 minutes at 0.5s intervals
        polls = 0

        # Wait briefly for the background enrichment task to initialise
        # (it may not have set progress yet if we connect immediately)
        for _ in range(6):  # Up to 3 seconds
            if get_enrichment_progress(owner_str) is not None:
                break
            await asyncio.sleep(0.5)

        while polls < max_polls:
            progress = get_enrichment_progress(owner_str)

            if progress is None:
                # No enrichment running — send idle and close
                yield f"data: {json.dumps({'phase': 'idle'})}\n\n"
                return

            yield f"data: {json.dumps(progress)}\n\n"

            if progress.get("phase") == "done":
                # Clean up and close
                clear_enrichment_progress(owner_str)
                return

            await asyncio.sleep(0.5)
            polls += 1

        # Timeout
        yield f"data: {json.dumps({'phase': 'timeout'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@limiter.limit("20/minute;100/hour")
async def enrich_wines(request: Request, current_user: RequireAuth) -> dict:
    """Trigger background enrichment for unenriched wines.

    Returns the count of unenriched wines and starts the background task.
    Use GET /enrichment-progress to monitor progress.
    """
    # Count unenriched wines
    unenriched_count = await Wine.find(
        {"owner_id": current_user.id, "xwines_id": None}
    ).count()

    if unenriched_count == 0:
        return {"message": "All wines are already enriched", "unenriched": 0}

    # Start background enrichment task
    asyncio.create_task(
        enrich_unenriched_wines(current_user.id),
    )

    return {
        "message": f"Background enrichment started for {unenriched_count} wines",
        "unenriched": unenriched_count,
    }
