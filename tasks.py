"""Invoke tasks for WineBox application management."""

import sys
from pathlib import Path

from invoke import task
from invoke.context import Context

# PID file location (must match winebox_ctl.py)
PID_FILE = Path("data/winebox.pid")


@task
def start(ctx: Context, host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Start the WineBox FastAPI server.

    Args:
        ctx: Invoke context
        host: Host to bind to (default: 0.0.0.0)
        port: Port to bind to (default: 8000)
        reload: Enable auto-reload for development
    """
    cmd = f"uv run winebox-server start --host {host} --port {port} --foreground"
    if reload:
        cmd += " --reload"

    try:
        ctx.run(cmd, pty=True)
    except KeyboardInterrupt:
        print("\nServer stopped")
        sys.exit(0)


@task(name="start-background")
def start_background(ctx: Context, host: str = "0.0.0.0", port: int = 8000) -> None:
    """Start the WineBox FastAPI server in the background.

    Args:
        ctx: Invoke context
        host: Host to bind to (default: 0.0.0.0)
        port: Port to bind to (default: 8000)
    """
    ctx.run(f"uv run winebox-server start --host {host} --port {port}")


@task
def stop(ctx: Context) -> None:
    """Stop the WineBox FastAPI server."""
    ctx.run("uv run winebox-server stop")


@task
def restart(ctx: Context, host: str = "0.0.0.0", port: int = 8000) -> None:
    """Restart the WineBox FastAPI server.

    Args:
        ctx: Invoke context
        host: Host to bind to (default: 0.0.0.0)
        port: Port to bind to (default: 8000)
    """
    ctx.run(f"uv run winebox-server restart --host {host} --port {port}")


@task
def status(ctx: Context) -> None:
    """Check the status of the WineBox server."""
    ctx.run("uv run winebox-server status")


@task
def logs(ctx: Context, follow: bool = False, lines: int = 50) -> None:
    """View the WineBox server logs.

    Args:
        ctx: Invoke context
        follow: Follow log output (like tail -f)
        lines: Number of lines to show (default: 50)
    """
    log_file = Path("data/winebox.log")
    if not log_file.exists():
        print("No log file found. Server may not have been started in background mode.")
        return

    if follow:
        ctx.run(f"tail -f {log_file}", pty=True)
    else:
        ctx.run(f"tail -n {lines} {log_file}")


@task
def test(ctx: Context, verbose: bool = False, coverage: bool = False, no_purge: bool = False) -> None:
    """Run the full test suite (unit tests + E2E tests).

    Args:
        ctx: Invoke context
        verbose: Enable verbose output
        coverage: Run with coverage report
        no_purge: Skip purging test data after E2E tests (default: False)
    """
    # Run unit tests first (no parallel due to async issues)
    print("Running unit tests...")
    cmd = "uv run python -m pytest tests/ --ignore=tests/test_checkin_e2e.py"
    if verbose:
        cmd += " -v"
    if coverage:
        cmd += " --cov=winebox --cov-report=term-missing"
    ctx.run(cmd, pty=True)

    # Run E2E tests with parallel execution
    print("\nRunning E2E tests...")
    e2e_cmd = "uv run python -m pytest tests/test_checkin_e2e.py -n 4"
    if verbose:
        e2e_cmd += " -v"
    ctx.run(e2e_cmd, pty=True)

    # Purge test data after E2E tests
    if not no_purge:
        print("\nPurging test data...")
        purge_wines(ctx, include_images=True, force=True)


@task(name="test-unit")
def test_unit(ctx: Context, verbose: bool = False, coverage: bool = False) -> None:
    """Run unit tests only (faster, no server required).

    Args:
        ctx: Invoke context
        verbose: Enable verbose output
        coverage: Run with coverage report
    """
    cmd = "uv run python -m pytest tests/ --ignore=tests/test_checkin_e2e.py"
    if verbose:
        cmd += " -v"
    if coverage:
        cmd += " --cov=winebox --cov-report=term-missing"
    ctx.run(cmd, pty=True)


@task(name="test-e2e")
def test_e2e(ctx: Context, verbose: bool = False, workers: int = 4, no_purge: bool = False) -> None:
    """Run E2E tests only (requires running server).

    Args:
        ctx: Invoke context
        verbose: Enable verbose output
        workers: Number of parallel workers (default: 4)
        no_purge: Skip purging test data after tests (default: False)
    """
    cmd = f"uv run python -m pytest tests/test_checkin_e2e.py -n {workers}"
    if verbose:
        cmd += " -v"
    ctx.run(cmd, pty=True)

    # Purge test data after E2E tests
    if not no_purge:
        print("\nPurging test data...")
        purge_wines(ctx, include_images=True, force=True)


@task(name="init-db")
def init_db(ctx: Context) -> None:
    """Initialize the database."""
    print("Initializing database...")
    ctx.run("uv run python -c 'import asyncio; from winebox.database import init_db; asyncio.run(init_db())'")
    print("Database initialized successfully")


@task
def clean(ctx: Context, all: bool = False) -> None:
    """Clean up temporary files.

    Args:
        ctx: Invoke context
        all: Also remove database and uploaded images
    """
    import shutil

    # Clean Python cache
    for pattern in ["__pycache__", "*.pyc", "*.pyo", ".pytest_cache"]:
        ctx.run(f"find . -name '{pattern}' -exec rm -rf {{}} + 2>/dev/null || true", warn=True)

    # Clean build artifacts
    for path in ["build", "dist", "*.egg-info", ".eggs"]:
        ctx.run(f"rm -rf {path} 2>/dev/null || true", warn=True)

    if all:
        print("Removing database and images...")
        if Path("data/winebox.db").exists():
            Path("data/winebox.db").unlink()
        if Path("data/images").exists():
            shutil.rmtree("data/images")
            Path("data/images").mkdir(parents=True)

    print("Cleanup complete")


@task
def purge(ctx: Context, include_images: bool = False, force: bool = False) -> None:
    """Purge the database and optionally images. Stops the server if running.

    Args:
        ctx: Invoke context
        include_images: Also delete all uploaded wine label images
        force: Skip confirmation prompt
    """
    import shutil
    import time

    db_path = Path("data/winebox.db")
    images_path = Path("data/images")

    # Check what will be deleted
    items_to_delete = []
    if db_path.exists():
        items_to_delete.append(f"Database: {db_path}")
    if include_images and images_path.exists():
        image_count = len(list(images_path.glob("*")))
        if image_count > 0:
            items_to_delete.append(f"Images: {image_count} files in {images_path}")

    if not items_to_delete:
        print("Nothing to purge. Database and images directory are already empty.")
        return

    # Confirm unless --force is used
    if not force:
        print("The following will be deleted:")
        for item in items_to_delete:
            print(f"  - {item}")
        response = input("\nAre you sure you want to purge? [y/N]: ").strip().lower()
        if response not in ("y", "yes"):
            print("Purge cancelled.")
            return

    # Stop the server if running (SQLite requires exclusive access)
    print("Stopping server if running...")
    ctx.run("uv run winebox-server stop", warn=True)
    time.sleep(1)

    # Delete database
    if db_path.exists():
        try:
            db_path.unlink()
            print(f"Deleted database: {db_path}")
        except PermissionError:
            print(f"Error: Could not delete {db_path} - file may still be locked")
            return

    # Delete images if requested
    if include_images and images_path.exists():
        shutil.rmtree(images_path)
        images_path.mkdir(parents=True)
        print(f"Deleted all images and recreated: {images_path}")

    print("\nPurge complete.")
    print("\nNote: Run 'invoke start' to restart the server.")


@task(name="purge-wines")
def purge_wines(ctx: Context, include_images: bool = True, force: bool = False) -> None:
    """Purge all wine data from the database without affecting users.

    This deletes all wines, transactions, and inventory records but keeps
    user accounts intact.

    Args:
        ctx: Invoke context
        include_images: Also delete all uploaded wine label images (default: True)
        force: Skip confirmation prompt
    """
    import shutil

    db_path = Path("data/winebox.db")
    images_path = Path("data/images")

    if not db_path.exists():
        print("Database does not exist. Nothing to purge.")
        return

    # Count records to be deleted
    count_script = """
import asyncio
from sqlalchemy import text
from winebox.database import async_session_maker

async def count_records():
    async with async_session_maker() as session:
        wines = (await session.execute(text('SELECT COUNT(*) FROM wines'))).scalar()
        transactions = (await session.execute(text('SELECT COUNT(*) FROM transactions'))).scalar()
        inventory = (await session.execute(text('SELECT COUNT(*) FROM cellar_inventory'))).scalar()
        return wines, transactions, inventory

wines, transactions, inventory = asyncio.run(count_records())
print(f'{wines},{transactions},{inventory}')
"""
    result = ctx.run(f'uv run python -c "{count_script}"', hide=True, warn=True)

    if result.ok:
        counts = result.stdout.strip().split(',')
        wine_count, transaction_count, inventory_count = int(counts[0]), int(counts[1]), int(counts[2])
    else:
        wine_count, transaction_count, inventory_count = 0, 0, 0

    # Check images
    image_count = 0
    if include_images and images_path.exists():
        image_count = len(list(images_path.glob("*")))

    if wine_count == 0 and transaction_count == 0 and inventory_count == 0 and image_count == 0:
        print("No wine data to purge.")
        return

    # Show what will be deleted
    print("The following wine data will be deleted:")
    print(f"  - Wines: {wine_count} records")
    print(f"  - Transactions: {transaction_count} records")
    print(f"  - Inventory: {inventory_count} records")
    if include_images:
        print(f"  - Images: {image_count} files")
    print("\nUser accounts will NOT be affected.")

    # Confirm unless --force is used
    if not force:
        response = input("\nAre you sure you want to purge wine data? [y/N]: ").strip().lower()
        if response not in ("y", "yes"):
            print("Purge cancelled.")
            return

    # Delete wine data from database
    delete_script = """
import asyncio
from sqlalchemy import text
from winebox.database import async_session_maker

async def delete_wine_data():
    async with async_session_maker() as session:
        await session.execute(text('DELETE FROM transactions'))
        await session.execute(text('DELETE FROM cellar_inventory'))
        await session.execute(text('DELETE FROM wines'))
        await session.commit()
        print('Wine data deleted from database.')

asyncio.run(delete_wine_data())
"""
    ctx.run(f'uv run python -c "{delete_script}"')

    # Delete images if requested
    if include_images and images_path.exists() and image_count > 0:
        shutil.rmtree(images_path)
        images_path.mkdir(parents=True)
        print(f"Deleted {image_count} images and recreated: {images_path}")

    print("\nWine data purge complete. User accounts preserved.")


# User Management Tasks
@task(name="add-user")
def add_user(
    ctx: Context,
    username: str,
    password: str,
    email: str = "",
    admin: bool = False,
) -> None:
    """Add a new user to the system.

    Args:
        ctx: Invoke context
        username: Username for the new user
        password: Password for the new user
        email: Optional email address
        admin: Make user an admin (default: False)
    """
    cmd = f"uv run winebox-admin add {username} --password {password}"
    if email:
        cmd += f" --email {email}"
    if admin:
        cmd += " --admin"
    ctx.run(cmd)


@task(name="remove-user")
def remove_user(ctx: Context, username: str, force: bool = False) -> None:
    """Remove a user from the system.

    Args:
        ctx: Invoke context
        username: Username to remove
        force: Skip confirmation prompt
    """
    cmd = f"uv run winebox-admin remove {username}"
    if force:
        cmd += " --force"
    ctx.run(cmd, pty=True)


@task(name="list-users")
def list_users(ctx: Context) -> None:
    """List all users in the system."""
    ctx.run("uv run winebox-admin list")


@task(name="disable-user")
def disable_user(ctx: Context, username: str) -> None:
    """Disable a user account.

    Args:
        ctx: Invoke context
        username: Username to disable
    """
    ctx.run(f"uv run winebox-admin disable {username}")


@task(name="enable-user")
def enable_user(ctx: Context, username: str) -> None:
    """Enable a user account.

    Args:
        ctx: Invoke context
        username: Username to enable
    """
    ctx.run(f"uv run winebox-admin enable {username}")


@task(name="passwd")
def change_password(ctx: Context, username: str, password: str) -> None:
    """Change a user's password.

    Args:
        ctx: Invoke context
        username: Username to change password for
        password: New password
    """
    ctx.run(f"uv run winebox-admin passwd {username} --password {password}")


@task(name="docs-build")
def docs_build(ctx: Context) -> None:
    """Build the Sphinx documentation."""
    ctx.run("uv run sphinx-build -b html docs docs/_build/html", pty=True)
    print("Documentation built at docs/_build/html/index.html")


@task(name="docs-serve")
def docs_serve(ctx: Context, port: int = 8080) -> None:
    """Serve the documentation locally.

    Args:
        ctx: Invoke context
        port: Port to serve on (default: 8080)
    """
    docs_build(ctx)
    print(f"Serving documentation at http://localhost:{port}")
    ctx.run(f"uv run python -m http.server {port} --directory docs/_build/html", pty=True)
