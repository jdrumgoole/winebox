"""Data purge script for WineBox.

Commands:
    --user EMAIL      Purge all data for a specific user (by email)
    --wine            Purge all wine data for all users (keeps user accounts)
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
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from winebox.config import settings
from winebox.database import Base
from winebox.models.user import User


def get_db_path() -> Path:
    """Extract database path from settings."""
    # Parse sqlite:///path or sqlite+aiosqlite:///path
    url = settings.database_url
    if ":///" in url:
        path = url.split("///")[1]
        return Path(path)
    return Path("data/winebox.db")


def get_images_path() -> Path:
    """Get the images directory path."""
    return Path("data/images")


async def get_db_session() -> AsyncSession:
    """Create a database session."""
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return async_session()


async def count_user_data(email: str) -> dict:
    """Count data records for a specific user."""
    async with await get_db_session() as db:
        # Check if user exists
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            return {"error": f"User '{email}' not found."}

        # Count wines
        wines_result = await db.execute(
            text("SELECT COUNT(*) FROM wines WHERE user_id = :user_id"),
            {"user_id": user.id}
        )
        wine_count = wines_result.scalar() or 0

        # Count transactions
        trans_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM transactions t
                JOIN wines w ON t.wine_id = w.id
                WHERE w.user_id = :user_id
            """),
            {"user_id": user.id}
        )
        transaction_count = trans_result.scalar() or 0

        # Count inventory
        inv_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM cellar_inventory ci
                JOIN wines w ON ci.wine_id = w.id
                WHERE w.user_id = :user_id
            """),
            {"user_id": user.id}
        )
        inventory_count = inv_result.scalar() or 0

        return {
            "user_id": user.id,
            "email": email,
            "wines": wine_count,
            "transactions": transaction_count,
            "inventory": inventory_count,
        }


async def count_wine_data() -> dict:
    """Count all wine-related data."""
    async with await get_db_session() as db:
        wines = (await db.execute(text("SELECT COUNT(*) FROM wines"))).scalar() or 0
        transactions = (await db.execute(text("SELECT COUNT(*) FROM transactions"))).scalar() or 0
        inventory = (await db.execute(text("SELECT COUNT(*) FROM cellar_inventory"))).scalar() or 0

        # Count reference data
        wine_grapes = 0
        wine_scores = 0
        try:
            wine_grapes = (await db.execute(text("SELECT COUNT(*) FROM wine_grapes"))).scalar() or 0
            wine_scores = (await db.execute(text("SELECT COUNT(*) FROM wine_scores"))).scalar() or 0
        except Exception:
            pass  # Tables may not exist in older schema

        return {
            "wines": wines,
            "transactions": transactions,
            "inventory": inventory,
            "wine_grapes": wine_grapes,
            "wine_scores": wine_scores,
        }


async def purge_user_data(email: str) -> dict:
    """Purge all data for a specific user."""
    async with await get_db_session() as db:
        # Get user
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            return {"error": f"User '{email}' not found."}

        user_id = user.id

        # Delete in order due to foreign keys
        # 1. Delete wine_scores for user's wines
        try:
            await db.execute(
                text("""
                    DELETE FROM wine_scores WHERE wine_id IN (
                        SELECT id FROM wines WHERE user_id = :user_id
                    )
                """),
                {"user_id": user_id}
            )
        except Exception:
            pass

        # 2. Delete wine_grapes for user's wines
        try:
            await db.execute(
                text("""
                    DELETE FROM wine_grapes WHERE wine_id IN (
                        SELECT id FROM wines WHERE user_id = :user_id
                    )
                """),
                {"user_id": user_id}
            )
        except Exception:
            pass

        # 3. Delete transactions
        await db.execute(
            text("""
                DELETE FROM transactions WHERE wine_id IN (
                    SELECT id FROM wines WHERE user_id = :user_id
                )
            """),
            {"user_id": user_id}
        )

        # 4. Delete inventory
        await db.execute(
            text("""
                DELETE FROM cellar_inventory WHERE wine_id IN (
                    SELECT id FROM wines WHERE user_id = :user_id
                )
            """),
            {"user_id": user_id}
        )

        # 5. Delete wines
        result = await db.execute(
            text("DELETE FROM wines WHERE user_id = :user_id"),
            {"user_id": user_id}
        )

        await db.commit()
        return {"deleted_wines": result.rowcount}


async def purge_wine_data() -> dict:
    """Purge all wine data but keep user accounts."""
    async with await get_db_session() as db:
        # Delete in order due to foreign keys
        try:
            await db.execute(text("DELETE FROM wine_scores"))
        except Exception:
            pass

        try:
            await db.execute(text("DELETE FROM wine_grapes"))
        except Exception:
            pass

        await db.execute(text("DELETE FROM transactions"))
        await db.execute(text("DELETE FROM cellar_inventory"))
        result = await db.execute(text("DELETE FROM wines"))

        await db.commit()
        return {"deleted_wines": result.rowcount}


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


def purge_database() -> bool:
    """Delete the database file. Returns True if deleted."""
    db_path = get_db_path()
    if db_path.exists():
        db_path.unlink()
        return True
    return False


def stop_server() -> None:
    """Stop the WineBox server if running."""
    import subprocess

    try:
        result = subprocess.run(
            ["uv", "run", "winebox-server", "stop"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if "stopped" in result.stdout.lower() or "stopped" in result.stderr.lower():
            print("Server stopped.")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


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
        help="Purge all data for a specific user (by email)"
    )
    group.add_argument(
        "--wine", "-w",
        action="store_true",
        help="Purge all wine data for all users (keeps user accounts)"
    )
    group.add_argument(
        "--all", "-a",
        action="store_true",
        help="Purge the entire database"
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
            # Purge specific user's data
            counts = asyncio.run(count_user_data(args.user))

            if "error" in counts:
                print(f"Error: {counts['error']}")
                return 1

            if counts["wines"] == 0:
                print(f"No wine data found for user '{args.user}'.")
                return 0

            print(f"Data to be deleted for user '{args.user}':")
            print(f"  - Wines: {counts['wines']}")
            print(f"  - Transactions: {counts['transactions']}")
            print(f"  - Inventory: {counts['inventory']}")

            if not args.yes:
                confirm = input("\nAre you sure you want to purge this data? [y/N]: ")
                if confirm.lower() not in ("y", "yes"):
                    print("Aborted.")
                    return 0

            result = asyncio.run(purge_user_data(args.user))
            if "error" in result:
                print(f"Error: {result['error']}")
                return 1

            print(f"\nPurged data for user '{args.user}'.")

        elif args.wine:
            # Purge all wine data
            counts = asyncio.run(count_wine_data())
            images_path = get_images_path()
            image_count = len(list(images_path.glob("*"))) if images_path.exists() else 0

            total = counts["wines"] + counts["transactions"] + counts["inventory"]
            if total == 0 and (not delete_images or image_count == 0):
                print("No wine data to purge.")
                return 0

            print("Wine data to be deleted:")
            print(f"  - Wines: {counts['wines']}")
            print(f"  - Transactions: {counts['transactions']}")
            print(f"  - Inventory: {counts['inventory']}")
            if counts.get("wine_grapes"):
                print(f"  - Wine grape blends: {counts['wine_grapes']}")
            if counts.get("wine_scores"):
                print(f"  - Wine scores: {counts['wine_scores']}")
            if delete_images:
                print(f"  - Images: {image_count} files")
            print("\nUser accounts will NOT be affected.")

            if not args.yes:
                confirm = input("\nAre you sure you want to purge wine data? [y/N]: ")
                if confirm.lower() not in ("y", "yes"):
                    print("Aborted.")
                    return 0

            asyncio.run(purge_wine_data())
            print("Wine data deleted from database.")

            if delete_images and image_count > 0:
                purge_images()
                print(f"Deleted {image_count} images.")

            print("\nWine data purge complete. User accounts preserved.")

        elif args.all:
            # Purge entire database
            db_path = get_db_path()
            images_path = get_images_path()
            image_count = len(list(images_path.glob("*"))) if images_path.exists() else 0

            if not db_path.exists() and (not delete_images or image_count == 0):
                print("Nothing to purge. Database does not exist.")
                return 0

            print("The following will be deleted:")
            if db_path.exists():
                print(f"  - Database: {db_path}")
            if delete_images:
                print(f"  - Images: {image_count} files")

            if not args.yes:
                confirm = input("\nAre you sure you want to purge everything? [y/N]: ")
                if confirm.lower() not in ("y", "yes"):
                    print("Aborted.")
                    return 0

            # Stop server before deleting database
            print("Stopping server if running...")
            stop_server()

            import time
            time.sleep(1)

            if db_path.exists():
                if purge_database():
                    print(f"Deleted database: {db_path}")
                else:
                    print(f"Error: Could not delete {db_path}")
                    return 1

            if delete_images and image_count > 0:
                purge_images()
                print(f"Deleted {image_count} images.")

            print("\nPurge complete.")
            print("Note: Run 'winebox-server start' to restart the server.")

    except KeyboardInterrupt:
        print("\nAborted.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
