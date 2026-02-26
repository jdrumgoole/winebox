"""FastAPI application entry point for WineBox."""

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from winebox import __version__
from winebox.config import settings
from winebox.database import close_db, init_db
from winebox.services.analytics import posthog_service

logger = logging.getLogger(__name__)

# Background cleanup task handle
_cleanup_task: asyncio.Task | None = None


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

        # Additional security headers
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )

        # Content Security Policy
        # Note: 'unsafe-inline' is kept for style-src only (for basic inline styles
        # like style="display: none;"). Script-src does not need unsafe-inline as
        # all JavaScript is loaded from external files.
        # PostHog domains are allowed for analytics when enabled.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://eu.posthog.com https://eu-assets.i.posthog.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: blob: https://eu.posthog.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self' https://eu.posthog.com https://eu.i.posthog.com; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "object-src 'none';"
        )

        # HTTPS enforcement header (browsers will upgrade to HTTPS)
        if settings.enforce_https:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        return response


def _is_production() -> bool:
    """Check if we're running in production mode.

    Returns:
        True if running in production (not debug mode and not testing).
    """
    return not settings.debug and not os.getenv("PYTEST_CURRENT_TEST")


async def _run_security_cleanup() -> None:
    """Background task to cleanup expired tokens and old login attempts.

    Runs every hour to remove:
    - Expired tokens from the blacklist
    - Old login attempts (> 24 hours)
    """
    from winebox.models.login_attempt import LoginAttempt
    from winebox.models.token_blacklist import RevokedToken

    while True:
        try:
            # Wait 1 hour between cleanups
            await asyncio.sleep(3600)

            # Cleanup expired revoked tokens
            tokens_cleaned = await RevokedToken.cleanup_expired()
            if tokens_cleaned > 0:
                logger.info("Token blacklist cleanup: removed %d expired tokens", tokens_cleaned)

            # Cleanup old login attempts
            attempts_cleaned = await LoginAttempt.cleanup_old_attempts(older_than_hours=24)
            if attempts_cleaned > 0:
                logger.info("Login attempts cleanup: removed %d old attempts", attempts_cleaned)

        except asyncio.CancelledError:
            logger.debug("Security cleanup task cancelled")
            break
        except Exception as e:
            logger.error("Security cleanup task error: %s", str(e))
            # Continue running despite errors


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
    global _cleanup_task

    # Startup
    # Validate security configuration before proceeding
    _validate_security_configuration()

    # Ensure data directories exist
    settings.image_storage_path.mkdir(parents=True, exist_ok=True)
    Path("data").mkdir(parents=True, exist_ok=True)

    # Initialize database
    await init_db()

    # Start background cleanup task
    _cleanup_task = asyncio.create_task(_run_security_cleanup())
    logger.info("Started security cleanup background task")

    yield

    # Shutdown
    # Cancel cleanup task
    if _cleanup_task:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("Stopped security cleanup background task")

    # Shutdown PostHog analytics (flush pending events)
    posthog_service.shutdown()

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

# Add CORS middleware with explicit configuration
# Only allow origins from the whitelist; empty list means same-origin only
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Request-ID"],
        max_age=600,  # Cache preflight for 10 minutes
    )

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)


# Root serves web interface directly - no redirect to keep URL clean
@app.get("/", tags=["Root"])
async def root() -> FileResponse:
    """Root endpoint - serves the main web interface."""
    static_path = Path(__file__).parent / "static" / "index.html"
    return FileResponse(static_path, media_type="text/html")


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


# PostHog analytics configuration endpoint
@app.get("/api/config/analytics", tags=["Configuration"])
async def get_analytics_config() -> JSONResponse:
    """Get analytics configuration for frontend.

    Returns PostHog settings (enabled, host, API key) for client-side analytics.
    Only returns the public API key which is safe to expose.
    """
    return JSONResponse(
        content={
            "enabled": settings.posthog_enabled,
            "host": settings.posthog_host,
            "api_key": settings.posthog_api_key or "",
        }
    )


# Import and include routers
from winebox.routers import admin, auth, cellar, export, reference, search, transactions, wines, xwines

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(wines.router, prefix="/api/wines", tags=["Wines"])
app.include_router(cellar.router, prefix="/api/cellar", tags=["Cellar"])
app.include_router(transactions.router, prefix="/api/transactions", tags=["Transactions"])
app.include_router(search.router, prefix="/api/search", tags=["Search"])
app.include_router(reference.router, prefix="/api/reference", tags=["Reference Data"])
app.include_router(xwines.router, prefix="/api/xwines", tags=["X-Wines Dataset"])
app.include_router(export.router, prefix="/api/export", tags=["Export"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])

# Serve static files - mounted after routes to avoid conflicts
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Serve images
images_path = settings.image_storage_path
if images_path.exists():
    app.mount("/api/images", StaticFiles(directory=str(images_path)), name="images")
