"""User administration script for WineBox.

Commands:
    add       Add a new user
    list      List all users
    disable   Disable a user account
    enable    Enable a user account
    remove    Remove a user account
    passwd    Change a user's password
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from getpass import getpass

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from winebox.config import settings
from winebox.models.user import User
from winebox.services.auth import get_password_hash

# Track if database is initialized (for CLI use)
_db_initialized = False


async def init_db() -> None:
    """Initialize the database connection."""
    global _db_initialized
    if _db_initialized:
        return
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.mongodb_database]
    await init_beanie(database=db, document_models=[User])
    _db_initialized = True


async def add_user(
    email: str,
    password: str,
    is_admin: bool = False,
    skip_db_init: bool = False,
) -> None:
    """Add a new user."""
    if not skip_db_init:
        await init_db()

    # Check if email already exists
    existing = await User.find_one(User.email == email)
    if existing:
        print(f"Error: Email '{email}' already in use.")
        sys.exit(1)

    # Create user
    now = datetime.now(timezone.utc)
    user = User(
        email=email,
        hashed_password=get_password_hash(password),
        is_superuser=is_admin,
        is_active=True,
        is_verified=True,  # CLI-created users are pre-verified
        created_at=now,
        updated_at=now,
    )
    await user.insert()

    role = "admin" if is_admin else "user"
    print(f"User '{email}' created successfully as {role}.")


async def list_users(skip_db_init: bool = False) -> None:
    """List all users."""
    if not skip_db_init:
        await init_db()

    users = await User.find_all().sort("+email").to_list()

    if not users:
        print("No users found.")
        return

    print(f"{'Email':<40} {'Admin':<6} {'Active':<6} {'Verified':<8} {'Last Login':<20}")
    print("-" * 90)

    for user in users:
        last_login = user.last_login.strftime("%Y-%m-%d %H:%M") if user.last_login else "Never"
        admin = "Yes" if user.is_superuser else "No"
        active = "Yes" if user.is_active else "No"
        verified = "Yes" if user.is_verified else "No"
        print(f"{user.email:<40} {admin:<6} {active:<6} {verified:<8} {last_login:<20}")


async def disable_user(email: str, skip_db_init: bool = False) -> None:
    """Disable a user account."""
    if not skip_db_init:
        await init_db()

    user = await User.find_one(User.email == email)
    if not user:
        print(f"Error: User '{email}' not found.")
        sys.exit(1)

    if not user.is_active:
        print(f"User '{email}' is already disabled.")
        return

    user.is_active = False
    user.updated_at = datetime.now(timezone.utc)
    await user.save()
    print(f"User '{email}' has been disabled.")


async def enable_user(email: str, skip_db_init: bool = False) -> None:
    """Enable a user account."""
    if not skip_db_init:
        await init_db()

    user = await User.find_one(User.email == email)
    if not user:
        print(f"Error: User '{email}' not found.")
        sys.exit(1)

    if user.is_active:
        print(f"User '{email}' is already active.")
        return

    user.is_active = True
    user.updated_at = datetime.now(timezone.utc)
    await user.save()
    print(f"User '{email}' has been enabled.")


async def remove_user(email: str, force: bool = False, skip_db_init: bool = False) -> None:
    """Remove a user account."""
    if not skip_db_init:
        await init_db()

    user = await User.find_one(User.email == email)
    if not user:
        print(f"Error: User '{email}' not found.")
        sys.exit(1)

    if not force:
        confirm = input(f"Are you sure you want to remove user '{email}'? [y/N]: ")
        if confirm.lower() != "y":
            print("Aborted.")
            return

    await user.delete()
    print(f"User '{email}' has been removed.")


async def change_password(email: str, password: str, skip_db_init: bool = False) -> None:
    """Change a user's password."""
    if not skip_db_init:
        await init_db()

    user = await User.find_one(User.email == email)
    if not user:
        print(f"Error: User '{email}' not found.")
        sys.exit(1)

    user.hashed_password = get_password_hash(password)
    user.updated_at = datetime.now(timezone.utc)
    await user.save()
    print(f"Password for user '{email}' has been updated.")


def get_password_interactive(confirm: bool = True) -> str:
    """Get password interactively from user."""
    password = getpass("Password: ")
    if not password:
        print("Error: Password cannot be empty.")
        sys.exit(1)

    if confirm:
        password2 = getpass("Confirm password: ")
        if password != password2:
            print("Error: Passwords do not match.")
            sys.exit(1)

    return password


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="User administration for WineBox",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Add user command
    add_parser = subparsers.add_parser("add", help="Add a new user")
    add_parser.add_argument("email", help="Email address for the new user")
    add_parser.add_argument("--admin", "-a", action="store_true", help="Make user an admin")
    add_parser.add_argument("--password", "-p", help="Password (will prompt if not provided)")

    # List users command
    subparsers.add_parser("list", help="List all users")

    # Disable user command
    disable_parser = subparsers.add_parser("disable", help="Disable a user account")
    disable_parser.add_argument("email", help="Email of user to disable")

    # Enable user command
    enable_parser = subparsers.add_parser("enable", help="Enable a user account")
    enable_parser.add_argument("email", help="Email of user to enable")

    # Remove user command
    remove_parser = subparsers.add_parser("remove", help="Remove a user account")
    remove_parser.add_argument("email", help="Email of user to remove")
    remove_parser.add_argument("--force", "-f", action="store_true", help="Skip confirmation")

    # Change password command
    passwd_parser = subparsers.add_parser("passwd", help="Change a user's password")
    passwd_parser.add_argument("email", help="Email of user to change password for")
    passwd_parser.add_argument("--password", "-p", help="New password (will prompt if not provided)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        if args.command == "add":
            password = args.password if args.password else get_password_interactive()
            asyncio.run(add_user(args.email, password, args.admin))

        elif args.command == "list":
            asyncio.run(list_users())

        elif args.command == "disable":
            asyncio.run(disable_user(args.email))

        elif args.command == "enable":
            asyncio.run(enable_user(args.email))

        elif args.command == "remove":
            asyncio.run(remove_user(args.email, args.force))

        elif args.command == "passwd":
            password = args.password if args.password else get_password_interactive()
            asyncio.run(change_password(args.email, password))

    except KeyboardInterrupt:
        print("\nAborted.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
