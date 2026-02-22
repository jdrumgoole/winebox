#!/usr/bin/env python3
"""Migration script to add owner_id to existing Wine and Transaction documents.

This script:
1. Finds the first superuser (admin) in the database
2. Updates all Wine documents to set owner_id to the admin's user ID
3. Updates all Transaction documents to set owner_id to the admin's user ID
4. Creates indexes on owner_id fields

Usage:
    uv run python scripts/migrate_wine_ownership.py
    uv run python scripts/migrate_wine_ownership.py --dry-run
"""

import argparse
import asyncio
import logging
import sys
from typing import Any

from beanie import PydanticObjectId, init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from winebox.config import settings
from winebox.models import Transaction, User, Wine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def get_admin_user() -> User | None:
    """Find the first superuser (admin) in the database."""
    return await User.find_one(User.is_superuser == True)


async def migrate_wines(admin_id: PydanticObjectId, dry_run: bool = False) -> int:
    """Migrate all Wine documents to have owner_id set to admin's ID.

    Args:
        admin_id: The admin user's ID to set as owner.
        dry_run: If True, don't actually update documents.

    Returns:
        Number of documents updated.
    """
    # Use PyMongo directly to avoid Beanie model validation
    collection = Wine.get_pymongo_collection()

    # Count wines without owner_id
    count = await collection.count_documents({"owner_id": {"$exists": False}})

    if count == 0:
        logger.info("No wines found without owner_id")
        return 0

    logger.info(f"Found {count} wines without owner_id")

    if dry_run:
        logger.info("[DRY RUN] Would update %d wines with owner_id=%s", count, admin_id)
        return count

    # Update all wines
    result = await collection.update_many(
        {"owner_id": {"$exists": False}},
        {"$set": {"owner_id": admin_id}},
    )

    logger.info(f"Updated {result.modified_count} wines with owner_id={admin_id}")
    return result.modified_count


async def migrate_transactions(admin_id: PydanticObjectId, dry_run: bool = False) -> int:
    """Migrate all Transaction documents to have owner_id set to admin's ID.

    Args:
        admin_id: The admin user's ID to set as owner.
        dry_run: If True, don't actually update documents.

    Returns:
        Number of documents updated.
    """
    # Use PyMongo directly to avoid Beanie model validation
    collection = Transaction.get_pymongo_collection()

    # Count transactions without owner_id
    count = await collection.count_documents({"owner_id": {"$exists": False}})

    if count == 0:
        logger.info("No transactions found without owner_id")
        return 0

    logger.info(f"Found {count} transactions without owner_id")

    if dry_run:
        logger.info("[DRY RUN] Would update %d transactions with owner_id=%s", count, admin_id)
        return count

    # Update all transactions
    result = await collection.update_many(
        {"owner_id": {"$exists": False}},
        {"$set": {"owner_id": admin_id}},
    )

    logger.info(f"Updated {result.modified_count} transactions with owner_id={admin_id}")
    return result.modified_count


async def create_indexes(dry_run: bool = False) -> None:
    """Create indexes on owner_id fields.

    Note: Beanie should handle this automatically on init, but this ensures
    the indexes exist after migration.
    """
    if dry_run:
        logger.info("[DRY RUN] Would create indexes on owner_id fields")
        return

    # The indexes are defined in the model Settings, so Beanie should create them
    # However, we can explicitly ensure they exist
    wine_collection = Wine.get_pymongo_collection()
    transaction_collection = Transaction.get_pymongo_collection()

    # Create indexes if they don't exist
    await wine_collection.create_index("owner_id")
    await transaction_collection.create_index("owner_id")

    logger.info("Created indexes on owner_id fields")


async def verify_migration() -> dict[str, Any]:
    """Verify the migration was successful.

    Returns:
        Dictionary with verification results.
    """
    results = {}

    # Use PyMongo directly to avoid Beanie model validation issues
    wine_collection = Wine.get_pymongo_collection()
    transaction_collection = Transaction.get_pymongo_collection()

    # Check wines
    total_wines = await wine_collection.count_documents({})
    wines_with_owner = await wine_collection.count_documents({"owner_id": {"$exists": True}})
    wines_without_owner = total_wines - wines_with_owner

    results["wines"] = {
        "total": total_wines,
        "with_owner": wines_with_owner,
        "without_owner": wines_without_owner,
    }

    # Check transactions
    total_transactions = await transaction_collection.count_documents({})
    transactions_with_owner = await transaction_collection.count_documents({"owner_id": {"$exists": True}})
    transactions_without_owner = total_transactions - transactions_with_owner

    results["transactions"] = {
        "total": total_transactions,
        "with_owner": transactions_with_owner,
        "without_owner": transactions_without_owner,
    }

    return results


async def run_migration(dry_run: bool = False) -> int:
    """Run the full migration.

    Args:
        dry_run: If True, don't actually modify the database.

    Returns:
        0 on success, 1 on failure.
    """
    # Initialize database connection
    logger.info("Connecting to MongoDB at %s", settings.mongodb_url)
    client = AsyncIOMotorClient(settings.mongodb_url)

    # Initialize Beanie
    await init_beanie(
        database=client[settings.mongodb_database],
        document_models=[User, Wine, Transaction],
    )

    logger.info("Connected to database: %s", settings.mongodb_database)

    # Find admin user
    admin = await get_admin_user()
    if not admin:
        logger.error("No admin user found. Please create an admin user first.")
        logger.error("You can create an admin user by registering and then updating is_superuser=True")
        return 1

    logger.info(f"Using admin user: {admin.email} (ID: {admin.id})")

    if dry_run:
        logger.info("=== DRY RUN MODE - No changes will be made ===")

    # Check current state
    verification_before = await verify_migration()
    logger.info("Before migration:")
    logger.info(f"  Wines: {verification_before['wines']['total']} total, "
                f"{verification_before['wines']['without_owner']} without owner_id")
    logger.info(f"  Transactions: {verification_before['transactions']['total']} total, "
                f"{verification_before['transactions']['without_owner']} without owner_id")

    if (verification_before['wines']['without_owner'] == 0 and
        verification_before['transactions']['without_owner'] == 0):
        logger.info("All documents already have owner_id. Nothing to migrate.")
        return 0

    # Run migrations
    wines_updated = await migrate_wines(admin.id, dry_run=dry_run)
    transactions_updated = await migrate_transactions(admin.id, dry_run=dry_run)

    # Create indexes
    await create_indexes(dry_run=dry_run)

    # Verify migration
    if not dry_run:
        verification_after = await verify_migration()
        logger.info("After migration:")
        logger.info(f"  Wines: {verification_after['wines']['total']} total, "
                    f"{verification_after['wines']['without_owner']} without owner_id")
        logger.info(f"  Transactions: {verification_after['transactions']['total']} total, "
                    f"{verification_after['transactions']['without_owner']} without owner_id")

        if (verification_after['wines']['without_owner'] > 0 or
            verification_after['transactions']['without_owner'] > 0):
            logger.error("Migration incomplete! Some documents still don't have owner_id.")
            return 1

    logger.info("Migration completed successfully!")
    logger.info(f"  Wines updated: {wines_updated}")
    logger.info(f"  Transactions updated: {transactions_updated}")

    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate Wine and Transaction documents to add owner_id field",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This migration assigns all existing wines and transactions to the first
admin user found in the database. This is typically run once after adding
the owner_id field to support multi-user data isolation.

Examples:
    uv run python scripts/migrate_wine_ownership.py --dry-run
    uv run python scripts/migrate_wine_ownership.py
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    args = parser.parse_args()

    return asyncio.run(run_migration(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
