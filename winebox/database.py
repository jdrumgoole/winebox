"""MongoDB database setup and Beanie ODM initialization."""

from typing import TYPE_CHECKING

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from winebox.config import settings

if TYPE_CHECKING:
    from beanie import Document

# Global database client and database references
client: AsyncIOMotorClient | None = None
database: AsyncIOMotorDatabase | None = None


def get_document_models() -> list[type["Document"]]:
    """Get all Beanie document models for initialization.

    Returns:
        List of Document model classes.
    """
    from winebox.models import (
        Classification,
        GrapeVariety,
        LoginAttempt,
        Region,
        RevokedToken,
        Transaction,
        User,
        Wine,
        WineType,
        XWinesMetadata,
        XWinesWine,
    )

    return [
        User,
        Wine,
        Transaction,
        WineType,
        GrapeVariety,
        Region,
        Classification,
        XWinesWine,
        XWinesMetadata,
        RevokedToken,
        LoginAttempt,
    ]


async def init_db(
    mongodb_url: str | None = None,
    mongodb_database: str | None = None,
    motor_client: AsyncIOMotorClient | None = None,
) -> None:
    """Initialize the MongoDB database connection and Beanie ODM.

    Args:
        mongodb_url: Optional MongoDB connection URL. Defaults to settings.
        mongodb_database: Optional database name. Defaults to settings.
        motor_client: Optional pre-configured motor client (for testing).
    """
    global client, database

    if motor_client is not None:
        # Use provided client (e.g., for testing with mongomock)
        client = motor_client
    else:
        # Create new client from settings with connection pool configuration
        url = mongodb_url or settings.mongodb_url
        client = AsyncIOMotorClient(
            url,
            minPoolSize=settings.min_pool_size,
            maxPoolSize=settings.max_pool_size,
        )

    db_name = mongodb_database or settings.mongodb_database
    database = client[db_name]

    # Initialize Beanie with all document models
    await init_beanie(
        database=database,
        document_models=get_document_models(),
    )


async def close_db() -> None:
    """Close the MongoDB database connection."""
    global client, database

    if client is not None:
        client.close()
        client = None
        database = None


def get_database() -> AsyncIOMotorDatabase:
    """Get the current database instance.

    Returns:
        The active MongoDB database.

    Raises:
        RuntimeError: If database is not initialized.
    """
    if database is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return database
