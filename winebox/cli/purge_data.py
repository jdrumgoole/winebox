"""Data purge script for WineBox.

Commands:
    --user EMAIL      Remove a specific user account
    --wine            Purge all wine data (keeps user accounts)
    --all             Purge the entire database

Options:
    -y, --yes         Skip confirmation prompt
    -i, --images      Also delete uploaded images (default with --wine and --all)
    --no-images       Keep uploaded images
"""

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from winebox.config import settings
from winebox.models.user import User
from winebox.models.wine import Wine
from winebox.models.transaction import Transaction

# Track if database is initialized (for CLI use)
_db_initialized = False


async def init_db() -> None:
    """Initialize the database connection."""
    global _db_initialized
    if _db_initialized:
        return
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.mongodb_database]
    await init_beanie(database=db, document_models=[User, Wine, Transaction])
    _db_initialized = True


def get_images_path() -> Path:
    """Get the images directory path."""
    return Path("data/images")


async def count_wine_data(skip_db_init: bool = False) -> dict:
    """Count all wine-related data."""
    if not skip_db_init:
        await init_db()

    wine_count = await Wine.count()
    transaction_count = await Transaction.count()

    return {
        "wines": wine_count,
        "transactions": transaction_count,
    }


async def count_all_data(skip_db_init: bool = False) -> dict:
    """Count all data in the database."""
    if not skip_db_init:
        await init_db()

    wine_count = await Wine.count()
    transaction_count = await Transaction.count()
    user_count = await User.count()

    return {
        "wines": wine_count,
        "transactions": transaction_count,
        "users": user_count,
    }


async def remove_user(email: str, skip_db_init: bool = False) -> dict:
    """Remove a user account by email."""
    if not skip_db_init:
        await init_db()

    user = await User.find_one(User.email == email)
    if not user:
        return {"error": f"User '{email}' not found."}

    await user.delete()
    return {"deleted": True, "email": email}


async def purge_wine_data(skip_db_init: bool = False) -> dict:
    """Purge all wine data but keep user accounts."""
    if not skip_db_init:
        await init_db()

    # Delete all transactions
    trans_result = await Transaction.delete_all()
    trans_count = trans_result.deleted_count if trans_result else 0

    # Delete all wines
    wine_result = await Wine.delete_all()
    wine_count = wine_result.deleted_count if wine_result else 0

    return {
        "deleted_wines": wine_count,
        "deleted_transactions": trans_count,
    }


async def purge_all_data(skip_db_init: bool = False) -> dict:
    """Purge all data from the database."""
    if not skip_db_init:
        await init_db()

    # Delete all transactions
    trans_result = await Transaction.delete_all()
    trans_count = trans_result.deleted_count if trans_result else 0

    # Delete all wines
    wine_result = await Wine.delete_all()
    wine_count = wine_result.deleted_count if wine_result else 0

    # Delete all users
    user_result = await User.delete_all()
    user_count = user_result.deleted_count if user_result else 0

    return {
        "deleted_wines": wine_count,
        "deleted_transactions": trans_count,
        "deleted_users": user_count,
    }


def purge_images() -> int:
    """Delete all uploaded images. Returns count of deleted files."""
    images_path = get_images_path()
    if not images_path.exists():
        return 0

    count = len(list(images_path.glob("*")))
    if count > 0:
        shutil.rmtree(images_path)
        images_path.mkdir(parents=True)

    return count


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Purge data from WineBox",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Mutually exclusive purge options
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--user", "-u",
        metavar="EMAIL",
        help="Remove a specific user account"
    )
    group.add_argument(
        "--wine", "-w",
        action="store_true",
        help="Purge all wine data (keeps user accounts)"
    )
    group.add_argument(
        "--all", "-a",
        action="store_true",
        help="Purge all data from the database"
    )

    # Options
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt"
    )
    parser.add_argument(
        "-i", "--images",
        action="store_true",
        default=None,
        help="Also delete uploaded images"
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Keep uploaded images"
    )

    args = parser.parse_args()

    # Determine whether to delete images
    delete_images = args.images
    if args.no_images:
        delete_images = False
    elif delete_images is None:
        # Default: delete images for --wine and --all, not for --user
        delete_images = args.wine or args.all

    try:
        if args.user:
            # Remove specific user account
            if not args.yes:
                confirm = input(f"Are you sure you want to remove user '{args.user}'? [y/N]: ")
                if confirm.lower() not in ("y", "yes"):
                    print("Aborted.")
                    return 0

            result = asyncio.run(remove_user(args.user))
            if "error" in result:
                print(f"Error: {result['error']}")
                return 1

            print(f"User '{args.user}' has been removed.")

        elif args.wine:
            # Purge all wine data
            counts = asyncio.run(count_wine_data())
            images_path = get_images_path()
            image_count = len(list(images_path.glob("*"))) if images_path.exists() else 0

            total = counts["wines"] + counts["transactions"]
            if total == 0 and (not delete_images or image_count == 0):
                print("No wine data to purge.")
                return 0

            print("Wine data to be deleted:")
            print(f"  - Wines: {counts['wines']}")
            print(f"  - Transactions: {counts['transactions']}")
            if delete_images:
                print(f"  - Images: {image_count} files")
            print("\nUser accounts will NOT be affected.")

            if not args.yes:
                confirm = input("\nAre you sure you want to purge wine data? [y/N]: ")
                if confirm.lower() not in ("y", "yes"):
                    print("Aborted.")
                    return 0

            result = asyncio.run(purge_wine_data())
            print(f"\nDeleted {result['deleted_wines']} wines and {result['deleted_transactions']} transactions.")

            if delete_images and image_count > 0:
                purge_images()
                print(f"Deleted {image_count} images.")

            print("\nWine data purge complete. User accounts preserved.")

        elif args.all:
            # Purge entire database
            counts = asyncio.run(count_all_data())
            images_path = get_images_path()
            image_count = len(list(images_path.glob("*"))) if images_path.exists() else 0

            total = counts["wines"] + counts["transactions"] + counts["users"]
            if total == 0 and (not delete_images or image_count == 0):
                print("Nothing to purge. Database is empty.")
                return 0

            print("The following will be deleted:")
            print(f"  - Users: {counts['users']}")
            print(f"  - Wines: {counts['wines']}")
            print(f"  - Transactions: {counts['transactions']}")
            if delete_images:
                print(f"  - Images: {image_count} files")

            if not args.yes:
                confirm = input("\nAre you sure you want to purge everything? [y/N]: ")
                if confirm.lower() not in ("y", "yes"):
                    print("Aborted.")
                    return 0

            result = asyncio.run(purge_all_data())
            print(f"\nDeleted {result['deleted_users']} users, {result['deleted_wines']} wines, "
                  f"and {result['deleted_transactions']} transactions.")

            if delete_images and image_count > 0:
                purge_images()
                print(f"Deleted {image_count} images.")

            print("\nPurge complete.")

    except KeyboardInterrupt:
        print("\nAborted.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
