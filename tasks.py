"""Invoke tasks for WineBox application management."""

import os
import re
import shlex
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from invoke import task
from invoke.context import Context

# PID file location (must match winebox_ctl.py)
PID_FILE = Path("data/winebox.pid")


@task(aliases=["server-start"])
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


@task(aliases=["server-stop"])
def stop(ctx: Context) -> None:
    """Stop the WineBox FastAPI server."""
    ctx.run("uv run winebox-server stop")


@task(aliases=["server-restart"])
def restart(ctx: Context, host: str = "0.0.0.0", port: int = 8000) -> None:
    """Restart the WineBox FastAPI server.

    Args:
        ctx: Invoke context
        host: Host to bind to (default: 0.0.0.0)
        port: Port to bind to (default: 8000)
    """
    ctx.run(f"uv run winebox-server restart --host {host} --port {port}")


@task(aliases=["server-status"])
def status(ctx: Context) -> None:
    """Check the status of the WineBox server."""
    ctx.run("uv run winebox-server status")


@task(aliases=["server-logs"])
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
        purge_wines(ctx, include_images=True, yes=True)


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


@task(name="test-quick")
def test_quick(ctx: Context, verbose: bool = False) -> None:
    """Run a small subset of fast unit tests (no DB, no server). Good for rapid feedback.

    Args:
        ctx: Invoke context
        verbose: Enable verbose output
    """
    cmd = (
        "uv run python -m pytest tests/test_ocr.py tests/test_config.py "
        "-m 'not e2e'"
    )
    if verbose:
        cmd += " -v"
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
        purge_wines(ctx, include_images=True, yes=True)


@task(name="test-e2e-fast")
def test_e2e_fast(ctx: Context, verbose: bool = False, workers: int = 4) -> None:
    """Run a fast subset of Playwright E2E tests.

    This is intended for local development and CI smoke runs. It exercises the
    most important happy-path flows without the very long-running big data
    imports.

    Expected server preconditions:
        uv run python -m invoke start-background
    """
    cmd = (
        "WINEBOX_USE_CLAUDE_VISION=false "
        "uv run python -m pytest -m e2e "
        "tests/test_registration_e2e.py "
        "tests/test_checkin_e2e.py "
        "tests/test_import_e2e.py "
        "tests/test_xwines_e2e.py "
        "tests/test_app_navigation_e2e.py "
        f"-n {workers} --dist loadfile"
    )
    if verbose:
        cmd += " -v"
    ctx.run(cmd, pty=True)


@task(name="test-e2e-full")
def test_e2e_full(ctx: Context, verbose: bool = False, workers: int = 4) -> None:
    """Run the full Playwright E2E suite, including slow tests.

    This includes large X-Wines CSV import validation and should typically be
    run on demand (e.g. before a release) rather than on every commit.

    Expected server preconditions:
        uv run python -m invoke start-background
    """
    cmd = (
        "WINEBOX_USE_CLAUDE_VISION=false "
        "uv run python -m pytest -m e2e "
        f"-n {workers} --dist loadfile"
    )
    if verbose:
        cmd += " -v"
    ctx.run(cmd, pty=True)


@task(name="test-e2e-db")
def test_e2e_db(
    ctx: Context,
    verbose: bool = False,
    workers: int = 1,
    port: int = 8001,
    database: str = "e2e",
    cleanup: bool = False,
    pattern: str = "",
) -> None:
    """Run E2E tests against production MongoDB but in a separate database.

    Starts a local server on a different port, configured to use the production
    MongoDB Atlas connection but with a separate database (default: 'e2e').
    This lets you test against real infrastructure without touching production data.

    The server uses the same WINEBOX_MONGODB_URL from your .env/secrets.env
    (i.e. the production Atlas cluster), but overrides the database name.

    Args:
        ctx: Invoke context
        verbose: Enable verbose output
        workers: Number of parallel workers (default: 1; increase with care on Atlas)
        port: Port for the e2e test server (default: 8001)
        database: Database name to use (default: 'e2e')
        cleanup: Drop the e2e database after tests (default: False, preserves data)
        pattern: Optional test file pattern (e.g. 'test_checkin_e2e.py')
    """
    import os
    import signal
    import subprocess

    e2e_port = port
    e2e_db = database
    server_url = f"http://localhost:{e2e_port}"
    pid_file = Path(f"data/winebox-e2e-{e2e_port}.pid")
    log_file = Path(f"data/winebox-e2e-{e2e_port}.log")
    Path("data").mkdir(parents=True, exist_ok=True)

    # Load X-Wines test data before starting server (to avoid index conflicts
    # between the import's text index and model indexes)
    _ensure_xwines_data(ctx, e2e_db)

    print(f"Starting e2e test server on port {e2e_port} with database '{e2e_db}'...")

    # Use a fixed secret key so the server and CLI (winebox-admin) share the
    # same JWT signing key.  Without this, the server generates a random key
    # on startup and tokens created by the CLI are rejected.
    e2e_secret = os.environ.get(
        "WINEBOX_E2E_SECRET_KEY",
        "e2e-test-secret-key-not-for-production-use-1234567890",
    )

    # Build env for the server subprocess — inherit current env + overrides
    server_env = os.environ.copy()
    server_env["WINEBOX_DATABASE"] = e2e_db
    server_env["WINEBOX_USE_CLAUDE_VISION"] = "false"
    server_env["WINEBOX_SECRET_KEY"] = e2e_secret

    # Start uvicorn directly (not via winebox-server, to avoid PID conflicts)
    uvicorn_cmd = [
        sys.executable, "-m", "uvicorn",
        "winebox.main:app",
        "--host", "0.0.0.0",
        "--port", str(e2e_port),
    ]

    with open(log_file, "w") as log:
        server_proc = subprocess.Popen(
            uvicorn_cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=server_env,
        )
    pid_file.write_text(str(server_proc.pid))
    print(f"  Server PID: {server_proc.pid}, logs: {log_file}")

    # Wait for server to be ready
    print(f"Waiting for server at {server_url}...")
    ready = False
    for _attempt in range(30):
        try:
            resp = urllib.request.urlopen(f"{server_url}/health", timeout=2)
            if resp.status == 200:
                ready = True
                break
        except Exception:
            pass
        # Check if process died
        if server_proc.poll() is not None:
            print(f"ERROR: Server process exited with code {server_proc.returncode}")
            print(f"  Check logs: {log_file}")
            pid_file.unlink(missing_ok=True)
            sys.exit(1)
        time.sleep(1)

    if not ready:
        print(f"ERROR: Server at {server_url} did not become ready within 30s")
        print(f"  Check logs: {log_file}")
        server_proc.terminate()
        pid_file.unlink(missing_ok=True)
        sys.exit(1)

    print(f"Server ready at {server_url} (database: {e2e_db})")

    # Build test command — must override addopts to remove the default
    # '-m "not e2e"' filter that excludes e2e tests from normal runs
    if pattern:
        test_files = f"tests/{pattern}"
    else:
        test_files = "-m e2e"

    test_cmd = (
        f"WINEBOX_TEST_URL={server_url} "
        f"WINEBOX_DATABASE={e2e_db} "
        f"WINEBOX_SECRET_KEY={e2e_secret} "
        f"WINEBOX_USE_CLAUDE_VISION=false "
        f'uv run python -m pytest {test_files} -n {workers} --override-ini="addopts="'
    )
    if verbose:
        test_cmd += " -v"

    # Run tests
    try:
        print(f"\nRunning e2e tests against {server_url}...")
        ctx.run(test_cmd, pty=True)
    finally:
        # Always stop the server
        print(f"\nStopping e2e test server (PID: {server_proc.pid})...")
        try:
            os.kill(server_proc.pid, signal.SIGTERM)
            server_proc.wait(timeout=10)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            os.kill(server_proc.pid, signal.SIGKILL)
        pid_file.unlink(missing_ok=True)

        # Drop the e2e database only if --cleanup is explicitly set
        if cleanup:
            _drop_e2e_database(ctx, e2e_db)
        else:
            print(f"Database '{e2e_db}' preserved (use --cleanup to drop it)")


def _ensure_xwines_data(ctx: Context, db_name: str) -> None:
    """Load X-Wines test data into the e2e database if not already present."""
    print(f"Checking X-Wines data in '{db_name}'...")
    check_script = Path("data/_check_xwines.py")
    check_script.write_text(
        "import os\n"
        "from pymongo import MongoClient\n"
        "from winebox.config import settings\n"
        f"db_name = '{db_name}'\n"
        "client = MongoClient(settings.mongodb_url)\n"
        "db = client[db_name]\n"
        "# Drop any conflicting text indexes that would clash with startup indexes\n"
        "try:\n"
        "    for idx in db.xwines_wines.list_indexes():\n"
        "        if idx.get('textIndexVersion'):\n"
        "            db.xwines_wines.drop_index(idx['name'])\n"
        "except Exception:\n"
        "    pass\n"
        "count = db.xwines_wines.count_documents({})\n"
        "client.close()\n"
        "print(count)\n"
    )
    try:
        result = ctx.run(f"uv run python {check_script}", hide=True, warn=True)
        count = int(result.stdout.strip()) if result and result.stdout.strip().isdigit() else 0
    finally:
        check_script.unlink(missing_ok=True)

    if count > 0:
        print(f"  X-Wines data already loaded ({count} wines)")
        return

    print("  Loading X-Wines test dataset (100 wines)...")
    import_script = Path("data/_import_xwines.py")
    import_script.write_text(
        "import os\n"
        "os.environ.setdefault('WINEBOX_DATABASE', '" + db_name + "')\n"
        "# Patch the import script to use the correct database\n"
        "import deploy.import_xwines_mongo as importer\n"
        "# Override get_mongodb_url to ensure it reads our env\n"
        "original_import = importer.import_to_mongodb\n"
        "def patched_import(wines, ratings_agg, version, force=False, dry_run=False):\n"
        "    from pymongo import MongoClient\n"
        "    from winebox.config import settings\n"
        "    mongo_url = settings.mongodb_url\n"
        "    client = MongoClient(mongo_url)\n"
        "    db = client['" + db_name + "']\n"
        "    wines_col = db['xwines_wines']\n"
        "    metadata_col = db['xwines_metadata']\n"
        "    # Drop and re-create\n"
        "    wines_col.drop()\n"
        "    if wines:\n"
        "        wines_col.insert_many(wines)\n"
        "    metadata_col.delete_many({})\n"
        "    from datetime import datetime, timezone\n"
        "    metadata_col.insert_one({'key': 'version', 'value': version})\n"
        "    metadata_col.insert_one({'key': 'wine_count', 'value': len(wines)})\n"
        "    metadata_col.insert_one({'key': 'imported_at', 'value': datetime.now(timezone.utc).isoformat()})\n"
        "    # Do NOT create a text index — the app will create its own on startup\n"
        "    client.close()\n"
        "    print(f'  Loaded {len(wines)} wines into {db.name}')\n"
        "    return 0\n"
        "importer.import_to_mongodb = patched_import\n"
        "importer.main()\n"
    )
    try:
        ctx.run(
            f"uv run python {import_script} --version test --force",
            warn=True,
        )
    finally:
        import_script.unlink(missing_ok=True)


def _drop_e2e_database(ctx: Context, db_name: str) -> None:
    """Drop the e2e test database."""
    print(f"Dropping e2e database '{db_name}'...")
    # Use a script file to avoid shell quoting issues
    script = Path("data/_drop_e2e_db.py")
    script.write_text(
        "import asyncio\n"
        "from pymongo import AsyncMongoClient\n"
        "from winebox.config import settings\n"
        "async def drop():\n"
        f"    client = AsyncMongoClient(settings.mongodb_url)\n"
        f"    await client.drop_database('{db_name}')\n"
        "    client.close()\n"
        f"    print('  Dropped database: {db_name}')\n"
        "asyncio.run(drop())\n"
    )
    try:
        ctx.run(f"uv run python {script}", warn=True)
    finally:
        script.unlink(missing_ok=True)


@task(name="init-db", aliases=["db-init"])
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


@task(aliases=["db-purge"])
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


def _backup_url(base_url: str, database: str) -> str:
    """Embed the database name in a MongoDB connection URL.

    `WINEBOX_MONGODB_URL` is the cluster URL with no database path, but
    `scripts/mongodb_backup.py` requires the database name in the URL
    (e.g. ``mongodb+srv://.../winebox``). This strips any existing path,
    inserts the database before the query string, and preserves params
    like ``?retryWrites=true&w=majority``.
    """
    parts = urlsplit(base_url)
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment)
    )


def _backup_database(ctx: Context, *, database: str, profile: str) -> None:
    """Run the backup script for ``database`` against the configured cluster."""
    base_url = os.environ.get("WINEBOX_MONGODB_URL")
    if not base_url:
        print("Error: WINEBOX_MONGODB_URL is not set", file=sys.stderr)
        sys.exit(1)
    full_url = _backup_url(base_url, database)
    cmd = (
        f"uv run python scripts/mongodb_backup.py "
        f"--profile {shlex.quote(profile)} "
        f"backup {shlex.quote(full_url)}"
    )
    ctx.run(cmd, pty=True)


@task(aliases=["db-backup"])
def backup(ctx: Context, database: str, profile: str = "winebox_backup") -> None:
    """Back up a MongoDB database to S3.

    The database name is required so it is impossible to back up the
    wrong cluster by accident. Use ``prod-backup`` / ``oat-backup`` for
    the named environments rather than calling this directly.

    Args:
        ctx: Invoke context.
        database: Database name (e.g. ``winebox`` or ``winebox_oat``).
        profile: AWS profile for the S3 upload (default: ``winebox_backup``).
    """
    _backup_database(ctx, database=database, profile=profile)


@task(name="prod-backup")
def prod_backup(ctx: Context, profile: str = "winebox_backup") -> None:
    """Back up the production database (``winebox``) to S3.

    Run this before every production deploy. The MongoDB URL is read
    from ``WINEBOX_MONGODB_URL`` (in ``.env`` or the shell), and the
    ``winebox`` database name is appended to it.
    """
    _backup_database(ctx, database="winebox", profile=profile)


@task(name="oat-backup")
def oat_backup(ctx: Context, profile: str = "winebox_backup") -> None:
    """Back up the OAT database (``winebox_oat``) to S3."""
    _backup_database(ctx, database="winebox_oat", profile=profile)


@task(name="oat-clear-legacy-auth")
def oat_clear_legacy_auth(ctx: Context, confirm: bool = False) -> None:
    """Drop the pre-regstack ``revoked_tokens`` and ``login_attempts``
    collections from ``winebox_oat``. Required ONCE before the first
    regstack deploy — leaves the ``users`` collection untouched.
    """
    cmd = "uv run python scripts/clear_legacy_auth_collections.py --database winebox_oat"
    if confirm:
        cmd += " --confirm"
    ctx.run(cmd, pty=True)


@task(name="prod-clear-legacy-auth")
def prod_clear_legacy_auth(ctx: Context, confirm: bool = False) -> None:
    """Drop the pre-regstack ``revoked_tokens`` and ``login_attempts``
    collections from production ``winebox``. Required ONCE before the
    first regstack deploy. Requires ``WINEBOX_ALLOW_PROD_LEGACY_DROP=1``
    in the environment as a second safety gate.
    """
    cmd = "uv run python scripts/clear_legacy_auth_collections.py --database winebox"
    if confirm:
        cmd += " --confirm"
    ctx.run(cmd, pty=True)


@task(name="seed-reference", aliases=["db-seed"])
def seed_reference(ctx: Context, database: str | None = None, yes: bool = False) -> None:
    """Seed reference tables (wine types, grapes, regions, classifications).

    Thin wrapper around scripts/seed_reference_data.py so operators don't
    need to remember the full path.
    """
    cmd = "uv run python scripts/seed_reference_data.py"
    if database:
        cmd += f" --database {database}"
    if yes:
        cmd += " --yes"
    ctx.run(cmd, pty=True)


@task(name="purge-wines", aliases=["db-purge-wines"])
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


@task(name="purge-user", aliases=["db-purge-user"])
def purge_user(ctx: Context, email: str, yes: bool = False) -> None:
    """Purge all data for a specific user.

    This deletes all wines, transactions, and inventory records for the
    specified user but keeps the user account.

    Args:
        ctx: Invoke context
        email: Email of user whose data to purge
        yes: Skip confirmation prompt (-y)
    """
    cmd = f"uv run winebox-purge --user {shlex.quote(email)}"
    if yes:
        cmd += " -y"
    ctx.run(cmd, pty=not yes)


# User Management Tasks
@task(name="add-user", aliases=["user-add"])
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
    cmd = f"uv run winebox-admin add {shlex.quote(email)} --password {shlex.quote(password)}"
    if admin:
        cmd += " --admin"
    ctx.run(cmd)


@task(name="remove-user", aliases=["user-remove"])
def remove_user(ctx: Context, email: str, force: bool = False) -> None:
    """Remove a user from the system.

    Args:
        ctx: Invoke context
        email: Email of user to remove
        force: Skip confirmation prompt
    """
    cmd = f"uv run winebox-admin remove {shlex.quote(email)}"
    if force:
        cmd += " --force"
    ctx.run(cmd, pty=True)


@task(name="list-users", aliases=["user-list"])
def list_users(ctx: Context) -> None:
    """List all users in the system."""
    ctx.run("uv run winebox-admin list")


@task(name="disable-user", aliases=["user-disable"])
def disable_user(ctx: Context, email: str) -> None:
    """Disable a user account.

    Args:
        ctx: Invoke context
        email: Email of user to disable
    """
    ctx.run(f"uv run winebox-admin disable {shlex.quote(email)}")


@task(name="enable-user", aliases=["user-enable"])
def enable_user(ctx: Context, email: str) -> None:
    """Enable a user account.

    Args:
        ctx: Invoke context
        email: Email of user to enable
    """
    ctx.run(f"uv run winebox-admin enable {shlex.quote(email)}")


@task(name="passwd", aliases=["user-passwd"])
def change_password(ctx: Context, email: str, password: str) -> None:
    """Change a user's password.

    Args:
        ctx: Invoke context
        email: Email of user to change password for
        password: New password
    """
    ctx.run(
        f"uv run winebox-admin passwd {shlex.quote(email)} "
        f"--password {shlex.quote(password)}"
    )


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

    admin_html = Path("winebox/static/admin.html")
    if admin_html.exists():
        content = admin_html.read_text()
        content = re.sub(r'\?v=[0-9.]+', f'?v={new_version}', content)
        admin_html.write_text(content)

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


def _release_to_pypi(
    ctx: Context,
    version: str = "",
    minor: bool = False,
    major: bool = False,
    skip_tests: bool = False,
    dry_run: bool = False,
) -> str:
    """Run the release pipeline: tests, version bump, PyPI publish.

    Shared by deploy (production) and deploy-oat --release.
    Returns the new version string.
    """
    # Pre-flight: Auto-commit any uncommitted changes so they are included
    # in the PyPI package. Excludes uv.lock (committed with version bump)
    # and .claude/ (not tracked).
    dirty = ctx.run(
        "git diff --name-only HEAD -- . ':!uv.lock'",
        hide=True, warn=True,
    ).stdout.strip()
    untracked = ctx.run(
        "git ls-files --others --exclude-standard -- . ':!uv.lock' ':!.claude/'",
        hide=True, warn=True,
    ).stdout.strip()
    if dirty or untracked:
        changed_files = [f for f in (dirty + "\n" + untracked).strip().splitlines() if f]
        print("\n  Uncommitted changes detected:")
        for f in changed_files:
            print(f"    {f}")
        if dry_run:
            print("  DRY RUN - Would commit these files before deploying")
        else:
            # Stage all changed/untracked files (excluding .claude/)
            for f in changed_files:
                ctx.run(f"git add {f}", hide=True)
            ctx.run(
                'git commit -m "chore: Pre-deploy commit of pending changes"',
                pty=True,
            )
            print("  Committed pending changes.")

    # Step 1: Run tests
    # test_production_login.py and test_production_admin_smoke.py hit live
    # production and are *post*-deploy smoke checks (see line ~1050) — they
    # must not gate the pre-deploy run, especially for OAT releases where
    # production is irrelevant.
    pretest_cmd = (
        "WINEBOX_USE_CLAUDE_VISION=false uv run python -m pytest tests/ "
        "--ignore=tests/test_checkin_e2e.py "
        "--ignore=tests/test_production_login.py "
        "--ignore=tests/test_production_admin_smoke.py -v"
    )
    if not skip_tests:
        print("\n[1/6] Running test suite...")
        if dry_run:
            print(f"  DRY RUN - Would run: {pretest_cmd}")
        else:
            ctx.run(pretest_cmd, pty=True)
            print("  Tests passed!")
    else:
        print("\n[1/6] Skipping tests (--skip-tests)")

    # Step 2: Determine new version
    print("\n[2/6] Determining version...")
    current_version = _get_current_version()
    if version:
        new_version = version
        print(f"  Using explicit version: {current_version} -> {new_version}")
    else:
        new_version = _bump_version(current_version, major=major, minor=minor)
        bump_type = "major" if major else ("minor" if minor else "patch")
        print(f"  Auto-bump ({bump_type}): {current_version} -> {new_version}")

    # Step 3: Bump version in files
    print("\n[3/6] Updating version files...")
    if dry_run:
        print(f"  DRY RUN - Would update pyproject.toml and winebox/__init__.py to {new_version}")
    else:
        _update_version_files(new_version)
        print(f"  Updated pyproject.toml and winebox/__init__.py to {new_version}")

    # Step 4: Commit, tag, push
    print("\n[4/6] Committing, tagging, and pushing...")
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
    print("\n[5/6] Creating GitHub release...")
    if dry_run:
        print(f"  DRY RUN - Would create GitHub release v{new_version}")
    else:
        ctx.run(
            f'gh release create v{new_version} --title "v{new_version}" --generate-notes',
            pty=True,
        )
        print(f"  GitHub release v{new_version} created")

    # Step 6: Wait for PyPI
    print("\n[6/6] Waiting for PyPI availability...")
    if dry_run:
        print(f"  DRY RUN - Would poll PyPI for winebox=={new_version}")
    else:
        if not _wait_for_pypi(new_version):
            print(f"  ERROR: Timed out waiting for v{new_version} on PyPI")
            print("  The GitHub release was created. PyPI publish may still be in progress.")
            print(f"  You can deploy manually later with: invoke deploy-only --version {new_version}")
            sys.exit(1)

    return new_version


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
        droplet_name: Droplet name for IP lookup (default: winebox-production)
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

    new_version = _release_to_pypi(
        ctx,
        version=version,
        minor=minor,
        major=major,
        skip_tests=skip_tests,
        dry_run=dry_run,
    )

    # Resolve production host once so we can bracket deploy.app with admin
    # service upload (before) and admin service start (after).
    prod_host = host or _resolve_prod_host()

    # Pre-deploy: upload the admin systemd unit so the new nginx config
    # (rendered inside deploy.app) has a valid backend on 127.0.0.1:8001.
    # daemon-reload only — the service is started AFTER deploy.app finishes,
    # at which point the new winebox wheel (with winebox.admin) is installed.
    if not dry_run:
        from deploy.common import run_ssh, upload_file
        admin_unit = Path(PROD_ADMIN_SERVICE_FILE)
        if admin_unit.exists():
            upload_file(prod_host, "root", admin_unit, "/tmp/winebox-admin.service")
            run_ssh(prod_host, "root", [
                "mv /tmp/winebox-admin.service /etc/systemd/system/winebox-admin.service",
                "systemctl daemon-reload",
            ])

    # Deploy to server
    print("\n[7/7] Deploying to production server...")
    deploy_cmd = f"uv run python -m deploy.app --version {new_version} --host {prod_host}"
    if droplet_name:
        deploy_cmd += f" --droplet-name {droplet_name}"
    if no_secrets:
        deploy_cmd += " --no-secrets"
    if setup_dns:
        deploy_cmd += " --setup-dns"
    if dry_run:
        deploy_cmd += " --dry-run"
    ctx.run(deploy_cmd, pty=True)

    # Post-deploy: start (or restart) the admin service against the new code.
    # Cold start observed at ~5s on OAT; production has more cores so it's
    # usually faster, but the same 30s polling window applies.
    if not dry_run:
        from deploy.common import run_ssh
        print(f"\nStarting admin panel ({PROD_ADMIN_DOMAIN})...")
        run_ssh(prod_host, "root", [
            "systemctl enable winebox-admin",
            "systemctl restart winebox-admin",
            "systemctl is-active winebox-admin",
            "for i in $(seq 1 30); do "
            "  curl -sf http://localhost:8001/health >/dev/null && exit 0; "
            "  sleep 1; "
            "done; "
            "echo '--- admin failed health check after 30s, recent logs: ---'; "
            "journalctl -u winebox-admin -n 30 --no-pager; "
            "exit 1",
        ])

    print("\n" + "=" * 60)
    if dry_run:
        print("DRY RUN complete - no changes were made")
    else:
        print(f"Release v{new_version} deployed successfully!")
        print(f"  PyPI:        https://pypi.org/project/winebox/{new_version}/")
        print(f"  App:         https://booze.winebox.app")
        print(f"  Admin:       https://{PROD_ADMIN_DOMAIN}  (IP-restricted)")
        print()
        print(f"Smoke-test:")
        print(f"  uv run python -m pytest tests/test_production_login.py tests/test_production_admin_smoke.py -v")
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
        droplet_name: Droplet name for IP lookup (default: winebox-production)
        version: Package version to install (default: latest)
        no_secrets: Skip syncing secrets to production
        setup_dns: Configure DNS A records (first-time setup)
        dry_run: Preview changes without applying
    """
    prod_host = host or _resolve_prod_host()

    # Pre-deploy: keep the admin systemd unit fresh so any local edits to
    # deploy/winebox-admin.service propagate without needing a full release.
    if not dry_run:
        from deploy.common import run_ssh, upload_file
        admin_unit = Path(PROD_ADMIN_SERVICE_FILE)
        if admin_unit.exists():
            upload_file(prod_host, "root", admin_unit, "/tmp/winebox-admin.service")
            run_ssh(prod_host, "root", [
                "mv /tmp/winebox-admin.service /etc/systemd/system/winebox-admin.service",
                "systemctl daemon-reload",
            ])

    cmd = f"uv run python -m deploy.app --host {prod_host}"
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

    # Post-deploy: restart the admin service against the new code.
    if not dry_run:
        from deploy.common import run_ssh
        print(f"\nRestarting admin panel ({PROD_ADMIN_DOMAIN})...")
        run_ssh(prod_host, "root", [
            "systemctl enable winebox-admin",
            "systemctl restart winebox-admin",
            "systemctl is-active winebox-admin",
            "for i in $(seq 1 30); do "
            "  curl -sf http://localhost:8001/health >/dev/null && exit 0; "
            "  sleep 1; "
            "done; "
            "echo '--- admin failed health check after 30s, recent logs: ---'; "
            "journalctl -u winebox-admin -n 30 --no-pager; "
            "exit 1",
        ])


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
        droplet_name: Droplet name for IP lookup (default: winebox-production)
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


@task(name="enrich-xwines-drinkability")
def enrich_xwines_drinkability_task(
    ctx: Context,
    limit: int = 0,
    model: str = "claude-sonnet-4-5",
) -> None:
    """Enrich XWinesWine docs with Claude-estimated drinkability windows.

    Streams reference wines that have no `drinkability` set, batches them
    through Claude, and writes the result back. Idempotent — re-runs only
    process docs still missing the field.

    Args:
        ctx: Invoke context
        limit: Cap total docs considered (0 = no cap; useful for smoke runs)
        model: Claude model to use (default: claude-sonnet-4-5)
    """
    limit_arg = f"--limit {limit}" if limit > 0 else ""
    model_arg = f"--model {model}" if model else ""
    ctx.run(
        f"uv run python -m winebox.cli.enrich_drinkability {limit_arg} {model_arg}".strip(),
        pty=True,
    )


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
    droplet_name: str = "winebox-production",
    image: str = "ubuntu-24-04-x64",
    confirm: bool = True,
) -> None:
    """Rebuild DO droplet for clean deploy testing.

    Uses Digital Ocean's rebuild action to reinstall the OS while keeping
    the same IP address (no DNS changes needed).

    Args:
        ctx: Invoke context
        droplet_name: Droplet name (default: winebox-production)
        image: OS image to rebuild with (default: ubuntu-24-04-x64)
        confirm: Skip confirmation prompt (default: True)
    """
    cmd = f"uv run python -m deploy.rebuild --droplet-name {droplet_name} --image {image}"
    if confirm:
        cmd += " --confirm"
    ctx.run(cmd, pty=True)


# Production User Management Tasks
#
# The production droplet IP is resolved dynamically via the DigitalOcean API
# (matching how `invoke deploy` and the oat-* tasks work) rather than being
# pinned to a literal so a droplet rebuild/re-IP doesn't silently break these
# tasks. Fall back to WINEBOX_DROPLET_IP env override for offline use.
PROD_DROPLET_NAME = "winebox-production"
PROD_DOMAIN = "booze.winebox.app"
PROD_ADMIN_DOMAIN = "admin.winebox.app"
PROD_ADMIN_SERVICE_FILE = "deploy/winebox-admin.service"
PROD_WINEBOX_ADMIN = "/opt/winebox/.venv/bin/winebox-admin"


def _resolve_prod_host() -> str:
    """Return the current production droplet IP."""
    override = os.environ.get("WINEBOX_DROPLET_IP")
    if override:
        return override
    try:
        from dotenv import load_dotenv

        from deploy.common import get_droplet_ip

        load_dotenv(".env")
        token = os.environ.get("WINEBOX_DO_TOKEN")
        if not token:
            print(
                "Error: WINEBOX_DO_TOKEN not set. Put it in .env or export it, "
                "or pass WINEBOX_DROPLET_IP to bypass DO API lookup.",
                file=sys.stderr,
            )
            sys.exit(1)
        ip = get_droplet_ip(token, PROD_DROPLET_NAME)
    except Exception as exc:  # pragma: no cover - operational failure path
        print(f"Error resolving production droplet IP: {exc}", file=sys.stderr)
        sys.exit(1)
    if not ip:
        print(f"Error: could not find droplet '{PROD_DROPLET_NAME}'", file=sys.stderr)
        sys.exit(1)
    return ip


def _ssh_cmd(cmd: str) -> str:
    """Build SSH command for production server.

    Quotes `cmd` for the LOCAL shell (the shell ctx.run uses to launch ssh)
    so $, backticks, and double-quotes inside it are not interpreted before
    SSH transmits them. Callers must additionally shlex.quote() any
    user-supplied values they substitute into `cmd` so they are safe for
    the REMOTE shell as well.
    """
    host = _resolve_prod_host()
    return f"ssh -o StrictHostKeyChecking=accept-new root@{host} {shlex.quote(cmd)}"


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
    cmd = (
        f"{PROD_WINEBOX_ADMIN} add {shlex.quote(email)} "
        f"--password {shlex.quote(password)}"
    )
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
    ctx.run(
        _ssh_cmd(f"{PROD_WINEBOX_ADMIN} remove {shlex.quote(email)} --force"),
        pty=True,
    )


@task(name="prod-disable-user")
def prod_disable_user(ctx: Context, email: str) -> None:
    """Disable a user on the production server.

    Args:
        ctx: Invoke context
        email: Email of user to disable
    """
    ctx.run(_ssh_cmd(f"{PROD_WINEBOX_ADMIN} disable {shlex.quote(email)}"), pty=True)


@task(name="prod-enable-user")
def prod_enable_user(ctx: Context, email: str) -> None:
    """Enable a user on the production server.

    Args:
        ctx: Invoke context
        email: Email of user to enable
    """
    ctx.run(_ssh_cmd(f"{PROD_WINEBOX_ADMIN} enable {shlex.quote(email)}"), pty=True)


@task(name="prod-admin-dns")
def prod_admin_dns(ctx: Context, dry_run: bool = False) -> None:
    """Create or update the `admin.winebox.app` A record at DigitalOcean.

    One-time setup. Idempotent — safe to rerun. Adds an A record named
    `admin` inside the existing `winebox.app` zone, pointing at the
    production droplet IP. Run this BEFORE `prod-admin-ssl` (certbot needs
    DNS to resolve before it can complete the HTTP-01 challenge).

    Args:
        ctx: Invoke context
        dry_run: Preview without applying
    """
    prod_host = _resolve_prod_host() if not dry_run else "<droplet-ip>"

    parent_zone = "winebox.app"
    record_name = "admin"
    fqdn = f"{record_name}.{parent_zone}"

    print(f"Configuring DNS: {fqdn} -> {prod_host}")
    if dry_run:
        print("  DRY RUN - no changes")
        return

    from dotenv import load_dotenv
    load_dotenv(".env")
    token = os.environ.get("WINEBOX_DO_TOKEN")
    if not token:
        print("Error: WINEBOX_DO_TOKEN not set in .env or environment")
        sys.exit(1)

    from deploy.common import DigitalOceanAPI

    client = DigitalOceanAPI(token)
    existing = client.list_dns_records(parent_zone)
    match = next(
        (r for r in existing if r["type"] == "A" and r["name"] == record_name),
        None,
    )

    record = {"type": "A", "name": record_name, "data": prod_host, "ttl": 300}
    if match is None:
        client.create_dns_record(parent_zone, record)
        print(f"  Created A {fqdn} -> {prod_host}")
    elif match["data"] == prod_host:
        print(f"  Already set: A {fqdn} -> {prod_host}")
    else:
        client.update_dns_record(parent_zone, match["id"], record)
        print(f"  Updated A {fqdn}: {match['data']} -> {prod_host}")

    print(f"\nVerify propagation: dig +short {fqdn}")
    print("Then run: invoke prod-admin-ssl")


@task(name="prod-admin-ssl")
def prod_admin_ssl(ctx: Context) -> None:
    """Issue a Let's Encrypt cert for `admin.winebox.app`.

    One-time setup. Must be run AFTER `prod-admin-dns` and after DNS has
    propagated (test with `dig +short admin.winebox.app`).

    Briefly stops nginx so certbot's standalone HTTP-01 challenge can bind
    port 80 — the same approach as `oat-admin-ssl`. This means
    `booze.winebox.app` is unavailable for the few seconds certbot takes to
    issue the cert; do it during a quiet window.

    After this, run `invoke deploy` to publish the nginx config that
    references the new certs and start the admin systemd unit. nginx won't
    reload cleanly until both the cert files and the updated config are in
    place.
    """
    prod_host = _resolve_prod_host()
    print(f"Setting up SSL for {PROD_ADMIN_DOMAIN} on {prod_host}...")

    from deploy.common import run_ssh

    run_ssh(prod_host, "root", "systemctl stop nginx", check=False)
    try:
        run_ssh(
            prod_host, "root",
            f"certbot certonly --standalone --non-interactive --agree-tos "
            f"--email support@winebox.app -d {PROD_ADMIN_DOMAIN}",
        )
    finally:
        # Always bring nginx back up, even if certbot failed — otherwise
        # booze.winebox.app stays down until the operator notices.
        run_ssh(prod_host, "root", "systemctl start nginx")

    print(f"SSL configured for {PROD_ADMIN_DOMAIN}")
    print("\nNext: run `invoke deploy` (or `invoke deploy-only --version X`)")
    print("to publish the nginx config that references the new certs.")


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


# =============================================================================
# OAT (Pre-release Testing) Environment
# =============================================================================

OAT_DROPLET_NAME = "winebox-oat"
OAT_DOMAIN = "oat.winebox.app"
OAT_ADMIN_DOMAIN = "oatadmin.winebox.app"
OAT_DATABASE = "winebox_oat"
OAT_NGINX_CONF = "nginx-winebox-oat.conf"
OAT_ADMIN_SERVICE_FILE = "deploy/winebox-admin-oat.service"
OAT_WINEBOX_ADMIN = "/opt/winebox/.venv/bin/winebox-admin"


def _resolve_oat_host(ctx: Context, host: str | None = None) -> str:
    """Resolve the OAT droplet IP."""
    if host:
        return host
    # Use DO API to find the droplet
    result = ctx.run(
        f'uv run python -c "'
        f"from deploy.common import get_droplet_ip; "
        f"import os; "
        f"from dotenv import load_dotenv; load_dotenv('.env'); "
        f"ip = get_droplet_ip(os.environ['WINEBOX_DO_TOKEN'], '{OAT_DROPLET_NAME}'); "
        f"print(ip or '')"
        f'"',
        hide=True,
    )
    ip = result.stdout.strip()
    if not ip:
        print(f"Error: Could not find droplet '{OAT_DROPLET_NAME}'")
        sys.exit(1)
    return ip


@task(name="oat-setup")
def oat_setup(ctx: Context, host: str = "", dry_run: bool = False) -> None:
    """Set up the OAT (pre-release testing) droplet.

    Runs initial server setup on the winebox-oat droplet with:
    - oat.winebox.app domain
    - winebox_oat database
    - OAT-specific nginx config (no landing page)

    Args:
        ctx: Invoke context
        host: Override droplet IP
        dry_run: Preview changes
    """
    oat_host = _resolve_oat_host(ctx, host or None)
    print(f"Setting up OAT environment on {oat_host}...")
    print(f"Domain: {OAT_DOMAIN}")
    print(f"Database: {OAT_DATABASE}")

    if dry_run:
        print("DRY RUN - Would run setup with OAT configuration")
        return

    cmd = (
        f"uv run python -m deploy.setup "
        f"--host {oat_host} "
        f"--domain {OAT_DOMAIN} "
        f"--mongodb-database {OAT_DATABASE} "
        f"--nginx-conf {OAT_NGINX_CONF}"
    )
    ctx.run(cmd, pty=True)


@task(name="oat-ssl")
def oat_ssl(ctx: Context, host: str = "") -> None:
    """Set up SSL certificates for oat.winebox.app.

    Must be run after oat-setup and after DNS has propagated.

    Args:
        ctx: Invoke context
        host: Override droplet IP
    """
    oat_host = _resolve_oat_host(ctx, host or None)
    print(f"Setting up SSL for {OAT_DOMAIN} on {oat_host}...")

    from deploy.common import run_ssh

    # Stop nginx to free port 80
    run_ssh(oat_host, "root", "systemctl stop nginx", check=False)

    # Request certificate
    run_ssh(
        oat_host, "root",
        f"certbot certonly --standalone --non-interactive --agree-tos "
        f"--email support@winebox.app -d {OAT_DOMAIN}",
    )

    # Start nginx
    run_ssh(oat_host, "root", "systemctl start nginx")
    print(f"SSL configured for {OAT_DOMAIN}")


@task(name="oat-admin-dns")
def oat_admin_dns(ctx: Context, host: str = "", dry_run: bool = False) -> None:
    """Create or update the `oatadmin.winebox.app` A record at DigitalOcean.

    One-time setup. Idempotent — safe to rerun. Adds an A record named
    `oatadmin` inside the existing `winebox.app` zone, pointing at the OAT
    droplet IP. Run this BEFORE `oat-admin-ssl` (certbot needs DNS to
    resolve before it can complete the HTTP-01 challenge).

    Args:
        ctx: Invoke context
        host: Override droplet IP (default: discovered via DO API)
        dry_run: Preview without applying
    """
    oat_host = _resolve_oat_host(ctx, host or None) if host or not dry_run else "<droplet-ip>"

    parent_zone = "winebox.app"
    record_name = "oatadmin"
    fqdn = f"{record_name}.{parent_zone}"

    print(f"Configuring DNS: {fqdn} -> {oat_host}")
    if dry_run:
        print("  DRY RUN - no changes")
        return

    from dotenv import load_dotenv
    load_dotenv(".env")
    token = os.environ.get("WINEBOX_DO_TOKEN")
    if not token:
        print("Error: WINEBOX_DO_TOKEN not set in .env or environment")
        sys.exit(1)

    from deploy.common import DigitalOceanAPI

    client = DigitalOceanAPI(token)
    existing = client.list_dns_records(parent_zone)
    match = next(
        (r for r in existing if r["type"] == "A" and r["name"] == record_name),
        None,
    )

    record = {"type": "A", "name": record_name, "data": oat_host, "ttl": 300}
    if match is None:
        client.create_dns_record(parent_zone, record)
        print(f"  Created A {fqdn} -> {oat_host}")
    elif match["data"] == oat_host:
        print(f"  Already set: A {fqdn} -> {oat_host}")
    else:
        client.update_dns_record(parent_zone, match["id"], record)
        print(f"  Updated A {fqdn}: {match['data']} -> {oat_host}")

    print(f"\nVerify propagation: dig +short {fqdn}")
    print("Then run: invoke oat-admin-ssl")


@task(name="oat-admin-ssl")
def oat_admin_ssl(ctx: Context, host: str = "") -> None:
    """Issue a Let's Encrypt cert for `oatadmin.winebox.app`.

    One-time setup. Must be run AFTER `oat-admin-dns` and after DNS has
    propagated (test with `dig +short oatadmin.winebox.app`).

    Briefly stops nginx so certbot's standalone HTTP-01 challenge can bind
    port 80 — the same approach as `oat-ssl`. This means `oat.winebox.app`
    is unavailable for the few seconds certbot takes to issue the cert; do
    it during a quiet window.

    After this, run `invoke deploy-oat` to publish the nginx config that
    references the new certs. nginx won't reload cleanly until both the
    cert files and the updated config are in place.

    Args:
        ctx: Invoke context
        host: Override droplet IP
    """
    oat_host = _resolve_oat_host(ctx, host or None)
    print(f"Setting up SSL for {OAT_ADMIN_DOMAIN} on {oat_host}...")

    from deploy.common import run_ssh

    # Stop nginx to free port 80 for certbot --standalone
    run_ssh(oat_host, "root", "systemctl stop nginx", check=False)

    try:
        run_ssh(
            oat_host, "root",
            f"certbot certonly --standalone --non-interactive --agree-tos "
            f"--email support@winebox.app -d {OAT_ADMIN_DOMAIN}",
        )
    finally:
        # Always bring nginx back up, even if certbot failed — otherwise
        # oat.winebox.app stays down until the operator notices.
        run_ssh(oat_host, "root", "systemctl start nginx")

    print(f"SSL configured for {OAT_ADMIN_DOMAIN}")
    print("\nNext: run `invoke deploy-oat` to publish the nginx config that")
    print("references the new certs and start the admin service.")


@task(name="deploy-oat")
def deploy_oat(
    ctx: Context,
    host: str = "",
    version: str = "",
    no_secrets: bool = False,
    dry_run: bool = False,
    release: bool = False,
    minor: bool = False,
    major: bool = False,
    skip_tests: bool = False,
) -> None:
    """Deploy WineBox to the OAT (pre-release testing) server.

    Uses the same deployment pipeline as production but targets the OAT
    droplet with its own domain and database.

    With --release: runs the full release pipeline (tests, version bump,
    PyPI publish) before deploying to OAT. Without --release, deploys
    the specified or latest version already on PyPI.

    Args:
        ctx: Invoke context
        host: Override droplet IP
        version: Package version to install (default: latest)
        no_secrets: Skip syncing secrets
        dry_run: Preview changes
        release: Run version bump + PyPI publish before deploying
        minor: Bump minor version (requires --release)
        major: Bump major version (requires --release)
        skip_tests: Skip test suite (requires --release)
    """
    if release:
        print("=" * 60)
        print("WineBox OAT Release & Deploy Pipeline")
        print("=" * 60)
        version = _release_to_pypi(
            ctx,
            version=version,
            minor=minor,
            major=major,
            skip_tests=skip_tests,
            dry_run=dry_run,
        )

    oat_host = _resolve_oat_host(ctx, host or None)
    print(f"\nDeploying to OAT: {oat_host} ({OAT_DOMAIN})")

    cmd = (
        f"uv run python -m deploy.app "
        f"--host {oat_host} "
        f"--domain {OAT_DOMAIN} "
    )
    if version:
        cmd += f"--version {version} "
    if no_secrets:
        cmd += "--no-secrets "
    if dry_run:
        cmd += "--dry-run "

    # Upload OAT-specific service files BEFORE deploy.app runs (so the units
    # have the correct WINEBOX_DATABASE=winebox_oat when they restart). We
    # only daemon-reload here; the admin service is started after the main
    # deploy finishes so it runs against the new code, not stale.
    if not dry_run:
        from deploy.common import run_ssh, upload_file
        service_file = Path("deploy/winebox-oat.service")
        if service_file.exists():
            upload_file(oat_host, "root", service_file, "/tmp/winebox.service")
            run_ssh(oat_host, "root", [
                "mv /tmp/winebox.service /etc/systemd/system/winebox.service",
            ])
        admin_service_file = Path(OAT_ADMIN_SERVICE_FILE)
        if admin_service_file.exists():
            upload_file(
                oat_host, "root",
                admin_service_file,
                "/tmp/winebox-admin.service",
            )
            run_ssh(oat_host, "root", [
                "mv /tmp/winebox-admin.service /etc/systemd/system/winebox-admin.service",
            ])
        run_ssh(oat_host, "root", ["systemctl daemon-reload"])

    # Override nginx config for OAT
    ctx.run(cmd, pty=True, env={"WINEBOX_NGINX_CONF": OAT_NGINX_CONF})

    # Start/restart the admin service AFTER the main deploy finishes — by
    # then the new winebox wheel (which contains winebox.admin.main:app) is
    # installed in /opt/winebox/.venv. `systemctl enable` is idempotent on
    # subsequent deploys; restart picks up the new code each time. Failures
    # propagate (check=True) so a bad unit or crashed app fails the deploy
    # rather than silently shipping a dead admin panel.
    if not dry_run:
        from deploy.common import run_ssh
        print(f"\nStarting admin panel ({OAT_ADMIN_DOMAIN})...")
        # Cold start observed at ~5s (winebox imports + Mongo init); poll
        # /health up to ~30s before failing. systemctl is-active happens
        # first so a unit that exits immediately still fails fast instead
        # of waiting the full window.
        run_ssh(oat_host, "root", [
            "systemctl enable winebox-admin",
            "systemctl restart winebox-admin",
            "systemctl is-active winebox-admin",
            "for i in $(seq 1 30); do "
            "  curl -sf http://localhost:8001/health >/dev/null && exit 0; "
            "  sleep 1; "
            "done; "
            "echo '--- admin failed health check after 30s, recent logs: ---'; "
            "journalctl -u winebox-admin -n 30 --no-pager; "
            "exit 1",
        ])

    # Ensure test user exists on OAT (idempotent — ignores if already exists)
    if not dry_run:
        from dotenv import load_dotenv
        load_dotenv(".env")
        test_user = os.environ.get("WINEBOX_TEST_USER")
        test_pass = os.environ.get("WINEBOX_TEST_PASSWORD")
        if test_user and test_pass:
            print(f"\n[6/6] Ensuring test user exists...")
            add_user_cmd = _oat_ssh_cmd(
                oat_host,
                f"cd /opt/winebox && set -a && . secrets.env && set +a && "
                f"{OAT_WINEBOX_ADMIN} add {shlex.quote(test_user)} "
                f"--password {shlex.quote(test_pass)}"
            )
            result = ctx.run(add_user_cmd, warn=True, hide=True)
            combined = (result.stdout or "") + (result.stderr or "")
            if "already" in combined.lower():
                print(f"  Test user {test_user}: already exists")
            elif result.ok:
                print(f"  Test user {test_user}: created")
            else:
                print(f"  Warning: could not create test user: {combined.strip()}")

    print(f"\nOAT deployment complete!")
    print(f"  App URL:    https://{OAT_DOMAIN}")
    print(f"  Admin URL:  https://{OAT_ADMIN_DOMAIN}  (IP-restricted)")
    print(f"  Database:   {OAT_DATABASE}")
    print(f"\nSmoke test the admin panel:")
    print(f"  uv run python -m pytest tests/test_oat_admin_smoke.py -v")


@task(name="oat-deploy-xwines")
def oat_deploy_xwines(ctx: Context, host: str = "", test: bool = True, dry_run: bool = False) -> None:
    """Deploy X-Wines dataset to the OAT server.

    Args:
        ctx: Invoke context
        host: Override droplet IP
        test: Use test dataset (default: True for OAT)
        dry_run: Preview changes
    """
    oat_host = _resolve_oat_host(ctx, host or None)
    cmd = f"uv run python -m deploy.xwines --host {oat_host} --database {OAT_DATABASE}"
    if test:
        cmd += " --test"
    if dry_run:
        cmd += " --dry-run"
    ctx.run(cmd, pty=True)


def _oat_ssh_cmd(host: str, cmd: str) -> str:
    """Build SSH command for OAT server.

    Quotes `cmd` for the LOCAL shell so $, backticks, and double-quotes
    inside it are not interpreted before SSH transmits them. Callers must
    additionally shlex.quote() any user-supplied values they substitute
    into `cmd` so they are safe for the REMOTE shell as well.
    """
    return f"ssh -o StrictHostKeyChecking=accept-new root@{host} {shlex.quote(cmd)}"


@task(name="oat-status")
def oat_status(ctx: Context, host: str = "") -> None:
    """Check the status of the OAT server.

    Args:
        ctx: Invoke context
        host: Override droplet IP
    """
    oat_host = _resolve_oat_host(ctx, host or None)
    print(f"OAT server: {oat_host} ({OAT_DOMAIN})")
    print("\n--- winebox (main app) ---")
    ctx.run(_oat_ssh_cmd(oat_host, "systemctl status winebox --no-pager"), pty=True, warn=True)
    ctx.run(_oat_ssh_cmd(oat_host, "curl -sf http://localhost:8000/health || echo 'Health check failed'"), pty=True, warn=True)
    print(f"\n--- winebox-admin ({OAT_ADMIN_DOMAIN}) ---")
    ctx.run(_oat_ssh_cmd(oat_host, "systemctl status winebox-admin --no-pager"), pty=True, warn=True)
    ctx.run(_oat_ssh_cmd(oat_host, "curl -sf http://localhost:8001/health || echo 'Admin health check failed'"), pty=True, warn=True)


@task(name="oat-logs")
def oat_logs(ctx: Context, host: str = "", lines: int = 50, follow: bool = False) -> None:
    """View OAT server logs.

    Args:
        ctx: Invoke context
        host: Override droplet IP
        lines: Number of lines to show
        follow: Follow log output
    """
    oat_host = _resolve_oat_host(ctx, host or None)
    follow_flag = "-f" if follow else ""
    ctx.run(
        f'ssh -o StrictHostKeyChecking=accept-new root@{oat_host} '
        f'"journalctl -u winebox -n {lines} --no-pager {follow_flag}"',
        pty=True,
    )


@task(name="oat-install-runner")
def oat_install_runner(ctx: Context, host: str = "", token: str = "", repo: str = "jdrumgoole/winebox") -> None:
    """Install a GitHub Actions self-hosted runner on the OAT droplet.

    Get --token from GitHub: Repo -> Settings -> Actions -> Runners ->
    New self-hosted runner (Linux/x64). The token expires in ~1 hour.

    Args:
        ctx: Invoke context
        host: Override droplet IP
        token: Runner registration token from GitHub
        repo: GitHub owner/repo
    """
    if not token:
        print("Error: --token is required. Get one from GitHub:")
        print("  Repo -> Settings -> Actions -> Runners -> New self-hosted runner")
        sys.exit(1)

    oat_host = _resolve_oat_host(ctx, host or None)
    ctx.run(
        f"uv run python -m deploy.install_oat_runner "
        f"--host {oat_host} --token {token} --repo {repo}",
        pty=True,
    )


@task(name="test-e2e-oat")
def test_e2e_oat(
    ctx: Context,
    verbose: bool = False,
    workers: int = 2,
    pattern: str = "",
    host: str = "",
) -> None:
    """Run E2E tests against the OAT server.

    Runs Playwright e2e tests against the live OAT server at oat.winebox.app.
    Uses the winebox_oat database via the server's own config.

    Args:
        ctx: Invoke context
        verbose: Enable verbose output
        workers: Number of parallel workers (default: 2)
        pattern: Optional test file pattern (e.g. 'test_checkin_e2e.py')
        host: Override droplet IP for user creation
    """
    oat_url = f"https://{OAT_DOMAIN}"
    oat_host = _resolve_oat_host(ctx, host or None)

    print(f"Running E2E tests against OAT: {oat_url}")

    # Build test command — order files by speed for better xdist distribution
    if pattern:
        test_files = f"tests/{pattern}"
    else:
        test_files = (
            # Fast (UI-only)
            "tests/test_app_navigation_e2e.py "
            "tests/test_cellar_e2e.py "
            "tests/test_cellar_tabs_e2e.py "
            "tests/test_case_actions_e2e.py "
            "tests/test_checkout_e2e.py "
            "tests/test_export_e2e.py "
            "tests/test_history_e2e.py "
            "tests/test_search_e2e.py "
            "tests/test_search_filters_e2e.py "
            "tests/test_settings_e2e.py "
            "tests/test_registration_e2e.py "
            "tests/test_undo_import_e2e.py "
            "tests/test_wine_detail_e2e.py "
            # Medium
            "tests/test_checkin_e2e.py "
            "tests/test_demo_e2e.py "
            "tests/test_xwines_e2e.py "
            "tests/test_import_e2e.py "
            # Slow (large CSV imports)
            "tests/test_import_xwines_e2e.py"
        )

    # Load .env to get WINEBOX_MONGODB_URL for user creation via winebox-admin
    from dotenv import dotenv_values
    env_values = dotenv_values(Path(".env"))
    mongodb_url = env_values.get("WINEBOX_MONGODB_URL", "")
    secret_key = env_values.get("WINEBOX_SECRET_KEY", "oat-e2e-test-secret-key-1234567890")

    # Set environment via os.environ to avoid shell quoting issues with pty
    import os
    os.environ["WINEBOX_TEST_URL"] = oat_url
    os.environ["WINEBOX_MONGODB_URL"] = mongodb_url
    os.environ["WINEBOX_DATABASE"] = OAT_DATABASE
    os.environ["WINEBOX_SECRET_KEY"] = secret_key
    os.environ["WINEBOX_USE_CLAUDE_VISION"] = "false"
    os.environ["WINEBOX_TEST_USER"] = ""
    os.environ["WINEBOX_TEST_PASSWORD"] = ""

    # Use separate pytest-e2e.ini to avoid pyproject.toml's addopts which has
    # `-m 'not e2e'` — xdist workers re-read the config and would exclude all E2E tests.
    test_cmd = (
        f"uv run python -m pytest -c pytest-e2e.ini {test_files} -n {workers}"
    )
    if verbose:
        test_cmd += " -v"

    ctx.run(test_cmd, pty=True)


# ---------------------------------------------------------------------------
# Environment validation & secrets management
# ---------------------------------------------------------------------------

# Secrets required for local development
_LOCAL_DEV_SECRETS = [
    "WINEBOX_MONGODB_URL",
    "WINEBOX_SECRET_KEY",
    "WINEBOX_REGSTACK_JWT_SECRET",
    "WINEBOX_ANTHROPIC_API_KEY",
]

# Secrets required for deployment
_DEPLOY_SECRETS = [
    "WINEBOX_MONGODB_URL",
    "WINEBOX_SECRET_KEY",
    "WINEBOX_REGSTACK_JWT_SECRET",
    "WINEBOX_ANTHROPIC_API_KEY",
    "WINEBOX_DO_TOKEN",
    "WINEBOX_POSTHOG_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
]

# All secrets that should be in GitHub Secrets
_GITHUB_SECRETS = [
    "WINEBOX_MONGODB_URL",
    "WINEBOX_SECRET_KEY",
    "WINEBOX_REGSTACK_JWT_SECRET",
    "WINEBOX_ANTHROPIC_API_KEY",
    "WINEBOX_POSTHOG_API_KEY",
    "WINEBOX_POSTHOG_ENABLED",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "WINEBOX_DO_TOKEN",
    "BRAVE_API_KEY",
    "WINEBOX_PROD_TEST_USER",
    "WINEBOX_PROD_TEST_PASSWORD",
    "WINEBOX_TEST_USER",
    "WINEBOX_TEST_PASSWORD",
]


@task(name="check-env")
def check_env(ctx: Context, deploy: bool = False) -> None:
    """Verify the development environment is ready.

    Checks that required tools, secrets, and services are available.

    Args:
        deploy: Also check deployment secrets (default: False)
    """
    from dotenv import dotenv_values

    errors: list[str] = []
    warnings: list[str] = []

    # 1. Check tools
    print("Checking tools...")
    for tool, check_cmd in [
        ("uv", "uv --version"),
        ("git", "git --version"),
        ("gh", "gh --version"),
    ]:
        result = ctx.run(check_cmd, hide=True, warn=True)
        if result and result.ok:
            version = result.stdout.strip().split("\n")[0]
            print(f"  {tool}: {version}")
        else:
            warnings.append(f"{tool} not found")
            print(f"  {tool}: NOT FOUND")

    # 2. Check Python
    print("\nChecking Python...")
    result = ctx.run("uv run python --version", hide=True, warn=True)
    if result and result.ok:
        print(f"  {result.stdout.strip()}")
    else:
        errors.append("Python not available via uv")

    # 3. Check .env and secrets
    print("\nChecking secrets (.env)...")
    env_file = Path(".env")
    if not env_file.exists():
        errors.append(".env file not found — copy from another dev machine or create manually")
        print("  .env: NOT FOUND")
    else:
        env_values = dotenv_values(".env")
        required = _DEPLOY_SECRETS if deploy else _LOCAL_DEV_SECRETS
        for key in required:
            if env_values.get(key):
                masked = env_values[key][:4] + "..."
                print(f"  {key}: {masked}")
            else:
                errors.append(f"Missing secret: {key}")
                print(f"  {key}: MISSING")

    # 4. Check MongoDB
    print("\nChecking MongoDB...")
    mongo_check = ctx.run(
        "uv run python -c \""
        "from dotenv import load_dotenv; load_dotenv(); "
        "import os; from pymongo import MongoClient; "
        "c = MongoClient(os.environ.get('WINEBOX_MONGODB_URL', ''), serverSelectionTimeoutMS=5000); "
        "info = c.server_info(); "
        "print(f'Connected: MongoDB {info.get(chr(118)+chr(101)+chr(114)+chr(115)+chr(105)+chr(111)+chr(110), chr(63))}')"
        "\"",
        hide=True,
        warn=True,
    )
    if mongo_check and mongo_check.ok:
        print(f"  {mongo_check.stdout.strip()}")
    else:
        errors.append("Cannot connect to MongoDB — check WINEBOX_MONGODB_URL")
        print("  MongoDB: CONNECTION FAILED")

    # 5. Check GitHub auth
    print("\nChecking GitHub...")
    gh_check = ctx.run("gh auth status", hide=True, warn=True)
    if gh_check and gh_check.ok:
        print("  GitHub CLI: authenticated")
    else:
        warnings.append("gh not authenticated — run 'gh auth login'")
        print("  GitHub CLI: NOT AUTHENTICATED")

    # Summary
    print("\n" + "=" * 50)
    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")
    if not errors and not warnings:
        print("Environment is ready.")
    elif not errors:
        print("Environment is ready (with warnings).")
    else:
        print("Environment has issues — fix errors above.")
        sys.exit(1)


@task(name="push-secrets")
def push_secrets(ctx: Context) -> None:
    """Push local .env secrets to GitHub Secrets for CI and other machines.

    Reads secrets from .env and uploads them to GitHub Secrets.
    """
    from dotenv import dotenv_values

    env_file = Path(".env")
    if not env_file.exists():
        print("Error: .env file not found")
        sys.exit(1)

    env_values = dotenv_values(".env")
    pushed = 0
    skipped = 0

    for key in _GITHUB_SECRETS:
        value = env_values.get(key)
        if not value:
            print(f"  {key}: skipped (not in .env)")
            skipped += 1
            continue

        result = ctx.run(
            f'printf "%s" "$GH_SECRET_VALUE" | gh secret set {key} --repo jdrumgoole/winebox',
            hide=True,
            warn=True,
            env={"GH_SECRET_VALUE": value},
        )
        if result and result.ok:
            print(f"  {key}: pushed")
            pushed += 1
        else:
            print(f"  {key}: FAILED")

    print(f"\nPushed {pushed} secrets, skipped {skipped}.")
