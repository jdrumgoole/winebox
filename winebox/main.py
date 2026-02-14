"""FastAPI application entry point for WineBox."""

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    # Startup
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
