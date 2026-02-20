"""FastAPI application entry point for WineBox."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from winebox import __version__
from winebox.config import settings
from winebox.database import close_db, init_db

logger = logging.getLogger(__name__)


# Rate limiter configuration
limiter = Limiter(key_func=get_remote_address)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content Security Policy - allow self and inline styles for the UI
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self'; "
            "frame-ancestors 'none';"
        )

        # HTTPS enforcement header (browsers will upgrade to HTTPS)
        if settings.enforce_https:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response


def _is_production() -> bool:
    """Check if we're running in production mode.

    Returns:
        True if running in production (not debug mode and not testing).
    """
    return not settings.debug and not os.getenv("PYTEST_CURRENT_TEST")


def _validate_security_configuration() -> None:
    """Validate security configuration at startup.

    Raises:
        RuntimeError: If critical security issues are detected in production.
    """
    issues = []
    warnings = []

    # Check for weak/missing secret key
    secret_key = settings.secret_key
    if not secret_key or len(secret_key) < 32:
        issues.append(
            "SECRET_KEY is missing or too short (minimum 32 characters). "
            "Set WINEBOX_SECRET_KEY environment variable."
        )

    # Check for insecure defaults in production
    if _is_production():
        # Debug mode should be off in production
        if settings.debug:
            issues.append(
                "Debug mode is enabled in production. "
                "Set debug=false in config.toml or WINEBOX_DEBUG=false."
            )

        # Localhost MongoDB is suspicious in production
        mongodb_url = settings.mongodb_url
        if "localhost" in mongodb_url or "127.0.0.1" in mongodb_url:
            warnings.append(
                "MongoDB URL points to localhost in production. "
                "This may indicate an insecure configuration."
            )

        # HTTPS should be enforced in production
        if not settings.enforce_https:
            warnings.append(
                "HTTPS enforcement is disabled. "
                "Consider enabling enforce_https=true for production."
            )

    # Log warnings
    for warning in warnings:
        logger.warning("SECURITY WARNING: %s", warning)

    # Fail on critical issues in production
    if issues and _is_production():
        for issue in issues:
            logger.error("SECURITY ERROR: %s", issue)
        raise RuntimeError(
            "Application startup blocked due to security configuration issues. "
            "See logs for details."
        )
    elif issues:
        # Log as warnings in development
        for issue in issues:
            logger.warning("SECURITY WARNING (development mode): %s", issue)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    # Startup
    # Validate security configuration before proceeding
    _validate_security_configuration()

    # Ensure data directories exist
    settings.image_storage_path.mkdir(parents=True, exist_ok=True)
    Path("data").mkdir(parents=True, exist_ok=True)

    # Initialize database
    await init_db()

    yield

    # Shutdown
    await close_db()


app = FastAPI(
    title=settings.app_name,
    description="Wine Cellar Management Application with OCR label scanning",
    version=__version__,
    lifespan=lifespan,
)

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)


# Root redirect to web interface - defined first to ensure it's matched
@app.get("/", tags=["Root"])
async def root() -> RedirectResponse:
    """Root endpoint - redirects to web interface."""
    return RedirectResponse(url="/static/index.html")


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check() -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse(
        content={
            "status": "healthy",
            "version": __version__,
            "app_name": settings.app_name,
        }
    )


# Import and include routers
from winebox.routers import auth, cellar, reference, search, transactions, wines, xwines

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(wines.router, prefix="/api/wines", tags=["Wines"])
app.include_router(cellar.router, prefix="/api/cellar", tags=["Cellar"])
app.include_router(transactions.router, prefix="/api/transactions", tags=["Transactions"])
app.include_router(search.router, prefix="/api/search", tags=["Search"])
app.include_router(reference.router, prefix="/api/reference", tags=["Reference Data"])
app.include_router(xwines.router, prefix="/api/xwines", tags=["X-Wines Dataset"])

# Serve static files - mounted after routes to avoid conflicts
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Serve images
images_path = settings.image_storage_path
if images_path.exists():
    app.mount("/api/images", StaticFiles(directory=str(images_path)), name="images")
