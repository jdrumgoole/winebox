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
def purge(ctx: Context, include_images: bool = True, yes: bool = False) -> None:
    """Purge the entire database. Stops the server if running.

    Args:
        ctx: Invoke context
        include_images: Also delete all uploaded wine label images (default: True)
        yes: Skip confirmation prompt (-y)
    """
    cmd = "uv run winebox-purge --all"
    if yes:
        cmd += " -y"
    if not include_images:
        cmd += " --no-images"
    ctx.run(cmd, pty=not yes)


@task(name="purge-wines")
def purge_wines(ctx: Context, include_images: bool = True, yes: bool = False) -> None:
    """Purge all wine data from the database without affecting users.

    This deletes all wines, transactions, and inventory records but keeps
    user accounts intact.

    Args:
        ctx: Invoke context
        include_images: Also delete all uploaded wine label images (default: True)
        yes: Skip confirmation prompt (-y)
    """
    cmd = "uv run winebox-purge --wine"
    if yes:
        cmd += " -y"
    if not include_images:
        cmd += " --no-images"
    ctx.run(cmd, pty=not yes)


@task(name="purge-user")
def purge_user(ctx: Context, username: str, yes: bool = False) -> None:
    """Purge all data for a specific user.

    This deletes all wines, transactions, and inventory records for the
    specified user but keeps the user account.

    Args:
        ctx: Invoke context
        username: Username whose data to purge
        yes: Skip confirmation prompt (-y)
    """
    cmd = f"uv run winebox-purge --user {username}"
    if yes:
        cmd += " -y"
    ctx.run(cmd, pty=not yes)


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


# Deployment Tasks
@task(name="deploy-setup")
def deploy_setup(ctx: Context, host: str = "", domain: str = "booze.winebox.app") -> None:
    """Run initial setup on a Digital Ocean droplet.

    This installs MongoDB, nginx, uv, and configures the server.
    Run this once on a fresh Ubuntu droplet.

    Args:
        ctx: Invoke context
        host: Droplet IP (or set WINEBOX_DROPLET_IP in .env)
        domain: Domain name for the app (default: booze.winebox.app)
    """
    cmd = f"uv run python -m deploy.setup --domain {domain}"
    if host:
        cmd += f" --host {host}"
    ctx.run(cmd, pty=True)


@task
def deploy(
    ctx: Context,
    host: str = "",
    droplet_name: str = "",
    version: str = "",
    no_secrets: bool = False,
    setup_dns: bool = False,
    dry_run: bool = False,
) -> None:
    """Deploy WineBox to the Digital Ocean droplet.

    Installs/upgrades winebox from PyPI, syncs secrets, and restarts the service.
    Droplet IP is auto-discovered from the API using WINEBOX_DO_TOKEN.

    Args:
        ctx: Invoke context
        host: Droplet IP (optional, auto-discovered if not set)
        droplet_name: Droplet name for IP lookup (default: winebox-droplet)
        version: Package version to install (default: latest)
        no_secrets: Skip syncing secrets to production
        setup_dns: Configure DNS A records (first-time setup)
        dry_run: Preview changes without applying
    """
    cmd = "uv run python -m deploy.app"
    if host:
        cmd += f" --host {host}"
    if droplet_name:
        cmd += f" --droplet-name {droplet_name}"
    if version:
        cmd += f" --version {version}"
    if no_secrets:
        cmd += " --no-secrets"
    if setup_dns:
        cmd += " --setup-dns"
    if dry_run:
        cmd += " --dry-run"
    ctx.run(cmd, pty=True)


@task(name="deploy-xwines")
def deploy_xwines(
    ctx: Context,
    host: str = "",
    droplet_name: str = "",
    test: bool = False,
    dry_run: bool = False,
) -> None:
    """Deploy X-Wines dataset to the production server.

    Downloads and imports the X-Wines dataset (100K+ wines with community
    ratings) to the production MongoDB database.

    This is a one-time operation that only needs to be run once after initial
    server setup, or when updating to a newer version of the dataset.

    Args:
        ctx: Invoke context
        host: Droplet IP (optional, auto-discovered if not set)
        droplet_name: Droplet name for IP lookup (default: winebox-droplet)
        test: Use test dataset (100 wines) instead of full dataset
        dry_run: Preview changes without applying
    """
    cmd = "uv run python -m deploy.xwines"
    if host:
        cmd += f" --host {host}"
    if droplet_name:
        cmd += f" --droplet-name {droplet_name}"
    if test:
        cmd += " --test"
    if dry_run:
        cmd += " --dry-run"
    ctx.run(cmd, pty=True)


@task
def rebuild_droplet(
    ctx: Context,
    droplet_name: str = "winebox-droplet",
    image: str = "ubuntu-24-04-x64",
    confirm: bool = False,
) -> None:
    """Rebuild DO droplet for clean deploy testing.

    Uses Digital Ocean's rebuild action to reinstall the OS while keeping
    the same IP address (no DNS changes needed).

    Args:
        ctx: Invoke context
        droplet_name: Droplet name (default: winebox-droplet)
        image: OS image to rebuild with (default: ubuntu-24-04-x64)
        confirm: Skip confirmation prompt
    """
    cmd = f"uv run python -m deploy.rebuild --droplet-name {droplet_name} --image {image}"
    if confirm:
        cmd += " --confirm"
    ctx.run(cmd, pty=True)
