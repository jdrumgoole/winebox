"""FastAPI application entry point for WineBox."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from winebox import __version__
from winebox.config import settings
from winebox.database import close_db, init_db


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
from winebox.routers import auth, cellar, search, transactions, wines

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(wines.router, prefix="/api/wines", tags=["Wines"])
app.include_router(cellar.router, prefix="/api/cellar", tags=["Cellar"])
app.include_router(transactions.router, prefix="/api/transactions", tags=["Transactions"])
app.include_router(search.router, prefix="/api/search", tags=["Search"])

# Serve static files - mounted after routes to avoid conflicts
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Serve images
images_path = settings.image_storage_path
if images_path.exists():
    app.mount("/api/images", StaticFiles(directory=str(images_path)), name="images")
