"""Invoke tasks for WineBox application management."""

import re
import sys
import time
import urllib.request
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
    cmd = "uv run python -m pytest tests/ --ignore=tests/test_checkin_e2e.py --ignore=tests/test_registration_e2e.py"
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

    Note: Server should be started with registration enabled for registration tests:
        WINEBOX_AUTH_REGISTRATION_ENABLED=true invoke start-background
    """
    # Run all E2E tests (checkin and registration)
    cmd = f"uv run python -m pytest tests/test_checkin_e2e.py tests/test_registration_e2e.py -n {workers}"
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
def purge_user(ctx: Context, email: str, yes: bool = False) -> None:
    """Purge all data for a specific user.

    This deletes all wines, transactions, and inventory records for the
    specified user but keeps the user account.

    Args:
        ctx: Invoke context
        email: Email of user whose data to purge
        yes: Skip confirmation prompt (-y)
    """
    cmd = f"uv run winebox-purge --user {email}"
    if yes:
        cmd += " -y"
    ctx.run(cmd, pty=not yes)


# User Management Tasks
@task(name="add-user")
def add_user(
    ctx: Context,
    email: str,
    password: str,
    admin: bool = False,
) -> None:
    """Add a new user to the system.

    Args:
        ctx: Invoke context
        email: Email address for the new user
        password: Password for the new user
        admin: Make user an admin (default: False)
    """
    cmd = f"uv run winebox-admin add {email} --password {password}"
    if admin:
        cmd += " --admin"
    ctx.run(cmd)


@task(name="remove-user")
def remove_user(ctx: Context, email: str, force: bool = False) -> None:
    """Remove a user from the system.

    Args:
        ctx: Invoke context
        email: Email of user to remove
        force: Skip confirmation prompt
    """
    cmd = f"uv run winebox-admin remove {email}"
    if force:
        cmd += " --force"
    ctx.run(cmd, pty=True)


@task(name="list-users")
def list_users(ctx: Context) -> None:
    """List all users in the system."""
    ctx.run("uv run winebox-admin list")


@task(name="disable-user")
def disable_user(ctx: Context, email: str) -> None:
    """Disable a user account.

    Args:
        ctx: Invoke context
        email: Email of user to disable
    """
    ctx.run(f"uv run winebox-admin disable {email}")


@task(name="enable-user")
def enable_user(ctx: Context, email: str) -> None:
    """Enable a user account.

    Args:
        ctx: Invoke context
        email: Email of user to enable
    """
    ctx.run(f"uv run winebox-admin enable {email}")


@task(name="passwd")
def change_password(ctx: Context, email: str, password: str) -> None:
    """Change a user's password.

    Args:
        ctx: Invoke context
        email: Email of user to change password for
        password: New password
    """
    ctx.run(f"uv run winebox-admin passwd {email} --password {password}")


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


# =============================================================================
# Version & Release Helpers
# =============================================================================

def _get_current_version() -> str:
    """Read the current version from pyproject.toml."""
    content = Path("pyproject.toml").read_text()
    match = re.search(r'^version = "(.+)"', content, re.MULTILINE)
    if not match:
        print("Error: Could not find version in pyproject.toml")
        sys.exit(1)
    return match.group(1)


def _bump_version(current: str, major: bool = False, minor: bool = False) -> str:
    """Bump a semver version string.

    Args:
        current: Current version string (e.g. "0.5.8")
        major: Bump major version
        minor: Bump minor version

    Returns:
        New version string
    """
    parts = current.split(".")
    maj, min_, patch = int(parts[0]), int(parts[1]), int(parts[2])
    if major:
        return f"{maj + 1}.0.0"
    elif minor:
        return f"{maj}.{min_ + 1}.0"
    else:
        return f"{maj}.{min_}.{patch + 1}"


def _update_version_files(new_version: str) -> None:
    """Update version in pyproject.toml, __init__.py, and static files.

    Args:
        new_version: New version string to set
    """
    # pyproject.toml
    pyproject = Path("pyproject.toml")
    content = pyproject.read_text()
    content = re.sub(
        r'^version = ".*"',
        f'version = "{new_version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    pyproject.write_text(content)

    # __init__.py
    init = Path("winebox/__init__.py")
    content = init.read_text()
    content = re.sub(
        r'^__version__ = ".*"',
        f'__version__ = "{new_version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    init.write_text(content)

    # Static files — cache-busting params and version display
    index_html = Path("winebox/static/index.html")
    if index_html.exists():
        content = index_html.read_text()
        content = re.sub(r'\?v=[0-9.]+', f'?v={new_version}', content)
        index_html.write_text(content)

    landing_html = Path("winebox/static/landing.html")
    if landing_html.exists():
        content = landing_html.read_text()
        content = re.sub(r'>v[0-9.]+</span>', f'>v{new_version}</span>', content)
        landing_html.write_text(content)


def _wait_for_pypi(version: str, max_attempts: int = 30, interval: int = 10) -> bool:
    """Poll PyPI until the version is available.

    Args:
        version: Version string to check for
        max_attempts: Maximum number of polling attempts
        interval: Seconds between attempts

    Returns:
        True if version became available, False if timed out
    """
    url = f"https://pypi.org/pypi/winebox/{version}/json"
    for attempt in range(1, max_attempts + 1):
        try:
            resp = urllib.request.urlopen(url)
            if resp.status == 200:
                print(f"  v{version} is available on PyPI!")
                return True
        except Exception:
            pass
        print(f"  Attempt {attempt}/{max_attempts}: v{version} not yet on PyPI, waiting {interval}s...")
        time.sleep(interval)
    return False


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
    minor: bool = False,
    major: bool = False,
    no_secrets: bool = False,
    setup_dns: bool = False,
    skip_tests: bool = False,
    dry_run: bool = False,
) -> None:
    """Release and deploy WineBox: tests, version bump, PyPI publish, server deploy.

    Orchestrates the full release pipeline:
    1. Run tests (abort on failure)
    2. Bump version (patch by default, or --minor/--major)
    3. Commit, tag, and push to GitHub
    4. Create GitHub release (triggers PyPI publish via Actions)
    5. Wait for new version on PyPI
    6. Deploy to production server

    Args:
        ctx: Invoke context
        host: Droplet IP (optional, auto-discovered if not set)
        droplet_name: Droplet name for IP lookup (default: winebox-droplet)
        version: Explicit version to release (overrides auto-bump)
        minor: Bump minor version instead of patch
        major: Bump major version instead of patch
        no_secrets: Skip syncing secrets to production
        setup_dns: Configure DNS A records (first-time setup)
        skip_tests: Skip running the test suite
        dry_run: Preview what would happen without making changes
    """
    print("=" * 60)
    print("WineBox Release & Deploy Pipeline")
    print("=" * 60)

    # Pre-flight: Abort if there are uncommitted changes (excluding uv.lock)
    # This prevents deploying a version that doesn't include all code changes.
    dirty = ctx.run(
        "git diff --name-only HEAD -- . ':!uv.lock'",
        hide=True, warn=True,
    ).stdout.strip()
    untracked = ctx.run(
        "git ls-files --others --exclude-standard -- . ':!uv.lock' ':!.claude/'",
        hide=True, warn=True,
    ).stdout.strip()
    if dirty or untracked:
        print("\nERROR: Working tree has uncommitted changes:")
        for f in (dirty + "\n" + untracked).strip().splitlines():
            if f:
                print(f"  {f}")
        print("\nCommit or stash your changes before deploying.")
        print("The deploy pipeline only commits version bump files, so any")
        print("other changes would be missing from the PyPI package.")
        raise SystemExit(1)

    # Step 1: Run tests
    if not skip_tests:
        print("\n[1/7] Running test suite...")
        if dry_run:
            print("  DRY RUN - Would run: uv run python -m pytest tests/ --ignore=tests/test_checkin_e2e.py -v")
        else:
            ctx.run(
                "WINEBOX_USE_CLAUDE_VISION=false uv run python -m pytest tests/ --ignore=tests/test_checkin_e2e.py -v",
                pty=True,
            )
            print("  Tests passed!")
    else:
        print("\n[1/7] Skipping tests (--skip-tests)")

    # Step 2: Determine new version
    print("\n[2/7] Determining version...")
    current_version = _get_current_version()
    if version:
        new_version = version
        print(f"  Using explicit version: {current_version} -> {new_version}")
    else:
        new_version = _bump_version(current_version, major=major, minor=minor)
        bump_type = "major" if major else ("minor" if minor else "patch")
        print(f"  Auto-bump ({bump_type}): {current_version} -> {new_version}")

    # Step 3: Bump version in files
    print("\n[3/7] Updating version files...")
    if dry_run:
        print(f"  DRY RUN - Would update pyproject.toml and winebox/__init__.py to {new_version}")
    else:
        _update_version_files(new_version)
        print(f"  Updated pyproject.toml and winebox/__init__.py to {new_version}")

    # Step 4: Commit, tag, push
    print("\n[4/7] Committing, tagging, and pushing...")
    if dry_run:
        print(f"  DRY RUN - Would commit, tag v{new_version}, and push")
    else:
        ctx.run(
            f"git add pyproject.toml winebox/__init__.py winebox/static/index.html winebox/static/landing.html && "
            f'git commit -m "chore: Bump version to {new_version}"',
            pty=True,
        )
        ctx.run(f'git tag -a v{new_version} -m "Release v{new_version}"', pty=True)
        ctx.run("git push && git push --tags", pty=True)
        print(f"  Pushed tag v{new_version}")

    # Step 5: Create GitHub release
    print("\n[5/7] Creating GitHub release...")
    if dry_run:
        print(f"  DRY RUN - Would create GitHub release v{new_version}")
    else:
        ctx.run(
            f'gh release create v{new_version} --title "v{new_version}" --generate-notes',
            pty=True,
        )
        print(f"  GitHub release v{new_version} created")

    # Step 6: Wait for PyPI
    print("\n[6/7] Waiting for PyPI availability...")
    if dry_run:
        print(f"  DRY RUN - Would poll PyPI for winebox=={new_version}")
    else:
        if not _wait_for_pypi(new_version):
            print(f"  ERROR: Timed out waiting for v{new_version} on PyPI")
            print("  The GitHub release was created. PyPI publish may still be in progress.")
            print("  You can deploy manually later with: invoke deploy-only --version {new_version}")
            sys.exit(1)

    # Step 7: Deploy to server
    print("\n[7/7] Deploying to production server...")
    deploy_cmd = f"uv run python -m deploy.app --version {new_version}"
    if host:
        deploy_cmd += f" --host {host}"
    if droplet_name:
        deploy_cmd += f" --droplet-name {droplet_name}"
    if no_secrets:
        deploy_cmd += " --no-secrets"
    if setup_dns:
        deploy_cmd += " --setup-dns"
    if dry_run:
        deploy_cmd += " --dry-run"
    ctx.run(deploy_cmd, pty=True)

    print("\n" + "=" * 60)
    if dry_run:
        print("DRY RUN complete - no changes were made")
    else:
        print(f"Release v{new_version} deployed successfully!")
        print(f"  PyPI: https://pypi.org/project/winebox/{new_version}/")
        print(f"  App:  https://booze.winebox.app")
    print("=" * 60)


@task(name="deploy-only")
def deploy_only(
    ctx: Context,
    host: str = "",
    droplet_name: str = "",
    version: str = "",
    no_secrets: bool = False,
    setup_dns: bool = False,
    dry_run: bool = False,
) -> None:
    """Deploy to server only (no release). Use for re-deploying an existing version.

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


@task(name="initialise-droplet")
def initialise_droplet(
    ctx: Context,
    host: str = "",
    domain: str = "booze.winebox.app",
    version: str = "",
    skip_xwines: bool = False,
    dry_run: bool = False,
) -> None:
    """Initialise a fresh droplet: setup, DNS, SSL, deploy, X-Wines.

    Combines deploy-setup, DNS config, cloud firewall, SSL certs,
    deploy, and deploy-xwines into a single command.

    Args:
        ctx: Invoke context
        host: Droplet IP (or set WINEBOX_DROPLET_IP in .env)
        domain: App domain (default: booze.winebox.app)
        version: Package version to install (default: latest)
        skip_xwines: Skip X-Wines dataset import
        dry_run: Preview changes without applying
    """
    cmd = "uv run python -m deploy.initialise"
    if host:
        cmd += f" --host {host}"
    if domain != "booze.winebox.app":
        cmd += f" --domain {domain}"
    if version:
        cmd += f" --version {version}"
    if skip_xwines:
        cmd += " --skip-xwines"
    if dry_run:
        cmd += " --dry-run"
    ctx.run(cmd, pty=True)


@task
def rebuild_droplet(
    ctx: Context,
    droplet_name: str = "winebox-droplet",
    image: str = "ubuntu-24-04-x64",
    confirm: bool = True,
) -> None:
    """Rebuild DO droplet for clean deploy testing.

    Uses Digital Ocean's rebuild action to reinstall the OS while keeping
    the same IP address (no DNS changes needed).

    Args:
        ctx: Invoke context
        droplet_name: Droplet name (default: winebox-droplet)
        image: OS image to rebuild with (default: ubuntu-24-04-x64)
        confirm: Skip confirmation prompt (default: True)
    """
    cmd = f"uv run python -m deploy.rebuild --droplet-name {droplet_name} --image {image}"
    if confirm:
        cmd += " --confirm"
    ctx.run(cmd, pty=True)


# Production User Management Tasks
PROD_HOST = "104.248.46.96"
PROD_WINEBOX_ADMIN = "/opt/winebox/.venv/bin/winebox-admin"


def _ssh_cmd(cmd: str) -> str:
    """Build SSH command for production server."""
    return f'ssh -o StrictHostKeyChecking=accept-new root@{PROD_HOST} "{cmd}"'


@task(name="prod-list-users")
def prod_list_users(ctx: Context) -> None:
    """List all users on the production server."""
    ctx.run(_ssh_cmd(f"{PROD_WINEBOX_ADMIN} list"), pty=True)


@task(name="prod-add-user")
def prod_add_user(ctx: Context, email: str, password: str, admin: bool = False) -> None:
    """Add a user on the production server.

    Args:
        ctx: Invoke context
        email: Email for the new user
        password: Password for the new user
        admin: Make user an admin
    """
    cmd = f"{PROD_WINEBOX_ADMIN} add {email} --password {password}"
    if admin:
        cmd += " --admin"
    ctx.run(_ssh_cmd(cmd), pty=True)


@task(name="prod-remove-user")
def prod_remove_user(ctx: Context, email: str) -> None:
    """Remove a user from the production server.

    Args:
        ctx: Invoke context
        email: Email of user to remove
    """
    ctx.run(_ssh_cmd(f"{PROD_WINEBOX_ADMIN} remove {email} --force"), pty=True)


@task(name="prod-disable-user")
def prod_disable_user(ctx: Context, email: str) -> None:
    """Disable a user on the production server.

    Args:
        ctx: Invoke context
        email: Email of user to disable
    """
    ctx.run(_ssh_cmd(f"{PROD_WINEBOX_ADMIN} disable {email}"), pty=True)


@task(name="prod-enable-user")
def prod_enable_user(ctx: Context, email: str) -> None:
    """Enable a user on the production server.

    Args:
        ctx: Invoke context
        email: Email of user to enable
    """
    ctx.run(_ssh_cmd(f"{PROD_WINEBOX_ADMIN} enable {email}"), pty=True)


@task(name="generate-test-data")
def generate_test_data(
    ctx: Context,
    rows: int = 5000,
    output: str = "tests/data/xwines-test-data.csv",
    seed: int = 42,
) -> None:
    """Generate a test CSV from the production X-Wines dataset.

    Connects to the production MongoDB, samples real wines from the X-Wines
    collection (100K+ wines), and expands their vintages into rows matching
    the Berry Bros & Rudd (bc-test-data.csv) column format.

    Args:
        ctx: Invoke context
        rows: Number of data rows to generate (default: 5000)
        output: Output CSV path (default: tests/data/xwines-test-data.csv)
        seed: Random seed for reproducibility (default: 42)
    """
    ctx.run(
        f"uv run python scripts/generate_test_csv.py -n {rows} -o {output} --seed {seed}",
        pty=True,
    )
