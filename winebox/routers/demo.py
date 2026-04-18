"""HTTP wrapper for the demo-data service.

Business logic (wine selection, install/remove, progress tracking) lives in
:mod:`winebox.services.demo_service`.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from winebox.services import demo_service
from winebox.services.auth import RequireAuth
from winebox.services.rate_limit import make_limiter

logger = logging.getLogger(__name__)

router = APIRouter()

limiter = make_limiter()


# --- Response models ---

class DemoStatusResponse(BaseModel):
    installed: bool
    wine_count: int
    bottle_count: int


class DemoInstallResponse(BaseModel):
    message: str
    total: int


class DemoRemoveResponse(BaseModel):
    wines_removed: int
    transactions_removed: int


# --- Endpoints ---

@router.get("/status", response_model=DemoStatusResponse)
async def demo_status(current_user: RequireAuth) -> DemoStatusResponse:
    """Check whether sample wines are installed for the current user."""
    status = await demo_service.get_demo_status(current_user.id)
    return DemoStatusResponse(
        installed=status.installed,
        wine_count=status.wine_count,
        bottle_count=status.bottle_count,
    )


@router.post("/install", response_model=DemoInstallResponse)
@limiter.limit("5/minute;10/hour")
async def install_demo(request: Request, current_user: RequireAuth) -> DemoInstallResponse:
    """Start loading sample wines into the current user's cellar.

    Returns immediately. Use GET /api/demo/install/progress to monitor.
    """
    try:
        total = await demo_service.start_install(current_user.id)
    except demo_service.DemoAlreadyInstalledError:
        raise HTTPException(
            status_code=409,
            detail="Sample wines are already loaded. Remove them first to reload.",
        )
    except demo_service.NoReferenceDataError:
        raise HTTPException(
            status_code=503,
            detail="No reference wine data available. The X-Wines dataset may not be loaded.",
        )

    return DemoInstallResponse(
        message=f"Loading {total} sample wines...",
        total=total,
    )


@router.get("/install/progress")
async def install_progress(current_user: RequireAuth) -> StreamingResponse:
    """SSE stream for demo install progress.

    Events contain: phase (loading/done/idle), created, total, and
    on completion: bottles, countries, wine_types.
    """
    async def event_generator():
        max_polls = 300  # 2.5 minutes at 0.5s intervals
        polls = 0

        while polls < max_polls:
            progress = demo_service.get_install_progress(current_user.id)

            if progress is None:
                yield f"data: {json.dumps({'phase': 'idle'})}\n\n"
                return

            yield f"data: {json.dumps(progress)}\n\n"

            if progress.get("phase") == "done":
                demo_service.pop_install_progress(current_user.id)
                return

            await asyncio.sleep(0.5)
            polls += 1

        yield f"data: {json.dumps({'phase': 'timeout'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/remove", response_model=DemoRemoveResponse)
async def remove_demo(current_user: RequireAuth) -> DemoRemoveResponse:
    """Remove all sample wines from the current user's cellar.

    Only removes wines tagged as demo data. Your own wines are not affected.
    """
    result = await demo_service.remove_demo_wines(current_user.id)
    return DemoRemoveResponse(
        wines_removed=result.wines_removed,
        transactions_removed=result.transactions_removed,
    )
