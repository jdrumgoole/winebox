"""WineBox Admin Panel - Standalone FastAPI application.

Defaults to the OAT database (winebox_oat) to prevent accidental
production access during local development. The production database
can only be used when running on the production server (booze.winebox.app),
enforced by winebox.config.settings._check_database_safety().
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

# Default to OAT database BEFORE importing winebox (which loads settings).
# The only way to reach the production database is:
# 1. Explicitly set WINEBOX_DATABASE=winebox, AND
# 2. Be running on booze.winebox.app (FQDN check in winebox.config.settings)
if "WINEBOX_DATABASE" not in os.environ:
    os.environ["WINEBOX_DATABASE"] = "winebox_oat"

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from winebox.config import settings
from winebox.database import close_db, init_db
from winebox.main import SecurityHeadersMiddleware

from winebox.admin import __version__
from winebox.admin.routers import admin, auth

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle: database connection."""
    await init_db()
    logger.info("WineBox Admin %s started", __version__)
    yield
    await close_db()
    logger.info("WineBox Admin shutting down")


limiter = Limiter(key_func=get_remote_address)

# Disable interactive API docs outside debug mode. The admin panel sits
# behind an IP allowlist, but exposing the full OpenAPI schema to anyone
# inside the allowlist (or anyone who bypasses it) is unnecessary.
_docs_enabled = settings.debug

app = FastAPI(
    title="WineBox Admin",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security headers
app.add_middleware(SecurityHeadersMiddleware)

# Routers
app.include_router(admin.router, prefix="/api")
app.include_router(auth.router, prefix="/api/auth")

# Static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_model=None)
async def serve_admin_panel() -> FileResponse:
    """Serve the admin panel HTML page."""
    return FileResponse(STATIC_DIR / "admin.html", media_type="text/html")


@app.get("/health")
async def health_check(request: Request) -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": __version__,
        "app_name": "WineBox Admin",
    }
