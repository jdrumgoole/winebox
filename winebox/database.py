"""MongoDB database setup using native async pymongo."""

import logging

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from winebox.config import settings

logger = logging.getLogger(__name__)

# Global database client and database references
client: AsyncMongoClient | None = None
database: AsyncDatabase | None = None


async def init_db(
    mongodb_url: str | None = None,
    mongodb_database: str | None = None,
    mongo_client: AsyncMongoClient | None = None,
    skip_indexes: bool = False,
) -> None:
    """Initialize the MongoDB database connection.

    Args:
        mongodb_url: Optional MongoDB connection URL. Defaults to settings.
        mongodb_database: Optional database name. Defaults to settings.
        mongo_client: Optional pre-configured client (for testing).
        skip_indexes: If True, skip index creation (for throwaway test databases).
    """
    global client, database

    if mongo_client is not None:
        # Use provided client (e.g., for testing)
        client = mongo_client
    else:
        # Create new client from settings with connection pool configuration
        url = mongodb_url or settings.mongodb_url
        client = AsyncMongoClient(
            url,
            minPoolSize=settings.min_pool_size,
            maxPoolSize=settings.max_pool_size,
        )

    db_name = mongodb_database or settings.mongodb_database
    database = client[db_name]

    # Create indexes (idempotent)
    if not skip_indexes:
        from winebox.db.indexes import ensure_indexes

        await ensure_indexes(database)

    logger.info("Database initialized: %s", db_name)


async def close_db() -> None:
    """Close the MongoDB database connection."""
    global client, database

    if client is not None:
        await client.close()
        client = None
        database = None


def get_database() -> AsyncDatabase:
    """Get the current database instance.

    Returns:
        The active MongoDB database.

    Raises:
        RuntimeError: If database is not initialized.
    """
    if database is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return database
