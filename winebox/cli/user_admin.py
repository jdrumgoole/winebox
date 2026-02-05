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
from getpass import getpass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from winebox.config import settings
from winebox.database import Base
from winebox.models.user import User
from winebox.services.auth import get_password_hash


async def get_db_session() -> AsyncSession:
    """Create a database session, ensuring tables exist."""
    engine = create_async_engine(settings.database_url, echo=False)

    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return async_session()


async def add_user(
    username: str,
    password: str,
    email: Optional[str] = None,
    is_admin: bool = False,
) -> None:
    """Add a new user."""
    async with await get_db_session() as db:
        # Check if user already exists
        result = await db.execute(select(User).where(User.username == username))
        if result.scalar_one_or_none():
            print(f"Error: User '{username}' already exists.")
            sys.exit(1)

        # Check if email already exists
        if email:
            result = await db.execute(select(User).where(User.email == email))
            if result.scalar_one_or_none():
                print(f"Error: Email '{email}' already in use.")
                sys.exit(1)

        # Create user
        user = User(
            username=username,
            email=email,
            hashed_password=get_password_hash(password),
            is_admin=is_admin,
            is_active=True,
        )
        db.add(user)
        await db.commit()

        role = "admin" if is_admin else "user"
        print(f"User '{username}' created successfully as {role}.")


async def list_users() -> None:
    """List all users."""
    async with await get_db_session() as db:
        result = await db.execute(select(User).order_by(User.username))
        users = result.scalars().all()

        if not users:
            print("No users found.")
            return

        print(f"{'Username':<20} {'Email':<30} {'Admin':<6} {'Active':<6} {'Last Login':<20}")
        print("-" * 90)

        for user in users:
            last_login = user.last_login.strftime("%Y-%m-%d %H:%M") if user.last_login else "Never"
            admin = "Yes" if user.is_admin else "No"
            active = "Yes" if user.is_active else "No"
            email = user.email or ""
            print(f"{user.username:<20} {email:<30} {admin:<6} {active:<6} {last_login:<20}")


async def disable_user(username: str) -> None:
    """Disable a user account."""
    async with await get_db_session() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if not user:
            print(f"Error: User '{username}' not found.")
            sys.exit(1)

        if not user.is_active:
            print(f"User '{username}' is already disabled.")
            return

        user.is_active = False
        await db.commit()
        print(f"User '{username}' has been disabled.")


async def enable_user(username: str) -> None:
    """Enable a user account."""
    async with await get_db_session() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if not user:
            print(f"Error: User '{username}' not found.")
            sys.exit(1)

        if user.is_active:
            print(f"User '{username}' is already active.")
            return

        user.is_active = True
        await db.commit()
        print(f"User '{username}' has been enabled.")


async def remove_user(username: str, force: bool = False) -> None:
    """Remove a user account."""
    async with await get_db_session() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if not user:
            print(f"Error: User '{username}' not found.")
            sys.exit(1)

        if not force:
            confirm = input(f"Are you sure you want to remove user '{username}'? [y/N]: ")
            if confirm.lower() != "y":
                print("Aborted.")
                return

        await db.delete(user)
        await db.commit()
        print(f"User '{username}' has been removed.")


async def change_password(username: str, password: str) -> None:
    """Change a user's password."""
    async with await get_db_session() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if not user:
            print(f"Error: User '{username}' not found.")
            sys.exit(1)

        user.hashed_password = get_password_hash(password)
        await db.commit()
        print(f"Password for user '{username}' has been updated.")


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
    add_parser.add_argument("username", help="Username for the new user")
    add_parser.add_argument("--email", "-e", help="Email address")
    add_parser.add_argument("--admin", "-a", action="store_true", help="Make user an admin")
    add_parser.add_argument("--password", "-p", help="Password (will prompt if not provided)")

    # List users command
    subparsers.add_parser("list", help="List all users")

    # Disable user command
    disable_parser = subparsers.add_parser("disable", help="Disable a user account")
    disable_parser.add_argument("username", help="Username to disable")

    # Enable user command
    enable_parser = subparsers.add_parser("enable", help="Enable a user account")
    enable_parser.add_argument("username", help="Username to enable")

    # Remove user command
    remove_parser = subparsers.add_parser("remove", help="Remove a user account")
    remove_parser.add_argument("username", help="Username to remove")
    remove_parser.add_argument("--force", "-f", action="store_true", help="Skip confirmation")

    # Change password command
    passwd_parser = subparsers.add_parser("passwd", help="Change a user's password")
    passwd_parser.add_argument("username", help="Username to change password for")
    passwd_parser.add_argument("--password", "-p", help="New password (will prompt if not provided)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        if args.command == "add":
            password = args.password if args.password else get_password_interactive()
            asyncio.run(add_user(args.username, password, args.email, args.admin))

        elif args.command == "list":
            asyncio.run(list_users())

        elif args.command == "disable":
            asyncio.run(disable_user(args.username))

        elif args.command == "enable":
            asyncio.run(enable_user(args.username))

        elif args.command == "remove":
            asyncio.run(remove_user(args.username, args.force))

        elif args.command == "passwd":
            password = args.password if args.password else get_password_interactive()
            asyncio.run(change_password(args.username, password))

    except KeyboardInterrupt:
        print("\nAborted.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
