"""Shared helpers for Playwright-based E2E tests.

These utilities centralize common logic like worker ID detection, CLI user
creation, environment configuration, and basic diagnostics to keep individual
test modules focused on scenarios and assertions.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Generator

import pytest
from playwright.sync_api import Page

# Base URL for the running WineBox server used by E2E tests.
# Can be overridden with WINEBOX_TEST_URL.
BASE_URL: str = os.environ.get("WINEBOX_TEST_URL", "http://localhost:8000")

# Project root directory (used for running CLI commands and artifacts).
PROJECT_DIR: Path = Path(__file__).parent.parent


def get_worker_id(request: pytest.FixtureRequest) -> str:
    """Return the pytest-xdist worker ID, or 'main' if not running in parallel."""
    if hasattr(request.config, "workerinput"):
        workerinput = request.config.workerinput
        if isinstance(workerinput, dict):
            return workerinput.get("workerid", "main")
    return "main"


def get_remote_test_credentials() -> tuple[str, str] | None:
    """Return (email, password) from env vars when testing against a remote server.

    When WINEBOX_TEST_URL is set (i.e. running E2E tests against OAT or
    production), we can't create users via the local CLI. Instead, use the
    pre-provisioned test user from WINEBOX_TEST_USER / WINEBOX_TEST_PASSWORD.

    Returns None if not running against a remote server or credentials are
    not configured.
    """
    test_url = os.environ.get("WINEBOX_TEST_URL", "")
    test_user = os.environ.get("WINEBOX_TEST_USER")
    test_pass = os.environ.get("WINEBOX_TEST_PASSWORD")
    if test_url and test_user and test_pass:
        return test_user, test_pass
    return None


def create_cli_worker_user(
    request: pytest.FixtureRequest,
    email_prefix: str,
    password: str = "testpass123",
    max_retries: int = 5,
    retry_delay: float = 2.0,
) -> tuple[str, str]:
    """Create (or reuse) a test user for the current worker.

    When WINEBOX_TEST_URL is set (remote testing), returns the pre-provisioned
    test credentials from environment variables instead of creating a local user.

    This function is intended to be called from a session-scoped fixture in an
    E2E test module, for example:

        @pytest.fixture(scope="session")
        def worker_user(request: pytest.FixtureRequest) -> Generator[tuple[str, str], None, None]:
            email, password = create_cli_worker_user(request, "e2e_worker")
            yield email, password

    The helper is resilient to the user already existing and will only emit a
    warning to stderr if creation fails entirely.
    """
    # For remote servers, use pre-provisioned test user
    remote_creds = get_remote_test_credentials()
    if remote_creds:
        print(f"Using remote test user: {remote_creds[0]}", file=sys.stderr)
        return remote_creds
    worker_id = get_worker_id(request)
    email = f"{email_prefix}_{worker_id}@test.example.com"

    result: subprocess.CompletedProcess[str] | None = None
    created = False

    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                ["uv", "run", "winebox-admin", "add", email, "--password", password],
                cwd=PROJECT_DIR,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.SubprocessError as exc:
            print(f"WARNING: subprocess error creating user {email}: {exc}", file=sys.stderr)
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            continue

        combined = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0 or "already exists" in combined or "already in use" in combined:
            created = True
            print(
                f"User {email}: {'reused' if 'already' in combined else 'created'} "
                f"(db={os.environ.get('WINEBOX_DATABASE', 'default')})",
                file=sys.stderr,
            )
            break

        if attempt < max_retries - 1:
            time.sleep(retry_delay)

    if not created:
        print(f"WARNING: Failed to create user {email}", file=sys.stderr)
        if result is not None:
            print(f"  returncode: {result.returncode}", file=sys.stderr)
            print(f"  stdout: {result.stdout}", file=sys.stderr)
            print(f"  stderr: {result.stderr}", file=sys.stderr)
        print(f"  WINEBOX_DATABASE={os.environ.get('WINEBOX_DATABASE', 'NOT SET')}", file=sys.stderr)

    # Delay to allow Atlas replica propagation before login attempts.
    time.sleep(2.0)
    return email, password


def preflight_check(timeout_seconds: int | None = None) -> None:
    """Fail fast if the E2E test server is not reachable.

    Raises via ``pytest.fail`` rather than ``pytest.skip`` so a misconfigured
    CI run doesn't silently no-op the whole E2E suite. Running the E2E
    marker intentionally requires a live server — use ``pytest -m "not e2e"``
    to skip these tests structurally.

    The default budget is generous because CI runners (GitHub Actions) have
    intermittent latency reaching the OAT droplet — short budgets produced
    flaky preflight failures while the server was actually responsive. Local
    dev answers in ~300ms so the upper bound doesn't slow down happy-path
    runs. Override via ``WINEBOX_E2E_PREFLIGHT_TIMEOUT`` if a specific runner
    needs longer or shorter.
    """
    if timeout_seconds is None:
        try:
            timeout_seconds = int(os.environ.get("WINEBOX_E2E_PREFLIGHT_TIMEOUT", "60"))
        except ValueError:
            timeout_seconds = 60

    start = time.time()
    urls = [f"{BASE_URL}/health", BASE_URL]
    per_request_timeout = 10.0

    last_error: Exception | None = None
    while time.time() - start < timeout_seconds:
        for url in urls:
            try:
                with urllib.request.urlopen(url, timeout=per_request_timeout):
                    return
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = exc
                continue
        time.sleep(1.0)

    msg = (
        f"E2E preflight failed: server at {BASE_URL!r} is not reachable "
        f"within {timeout_seconds}s. "
        "Start it with 'uv run python -m invoke start-background' or equivalent."
    )
    if last_error is not None:
        msg += f" Last error: {last_error!r}"
    pytest.fail(msg)


def login_via_ui(
    page: Page, email: str, password: str, *,
    timeout_ms: int = 15000, max_retries: int = 3, retry_delay_ms: int = 2000,
) -> None:
    """Log in through the UI and wait for main content to be visible.

    Retries on failure to handle transient issues (Atlas latency, race conditions
    with user creation, etc.).

    Raises an AssertionError with a helpful message if login fails after all retries.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            page.context.clear_cookies()
            page.goto(BASE_URL)
            page.evaluate("localStorage.clear()")
            page.reload()

            page.wait_for_selector("#login-form", state="visible", timeout=timeout_ms)
            page.fill("#login-email", email)
            page.fill("#login-password", password)
            page.click("#login-form button[type='submit']")

            page.wait_for_selector("#main-content", state="visible", timeout=timeout_ms)
            return  # Success
        except Exception as exc:
            last_error = exc
            error_elem = page.locator("#login-error")
            if error_elem.is_visible():
                error_text = error_elem.text_content() or ""
                if attempt < max_retries - 1:
                    print(
                        f"Login attempt {attempt + 1}/{max_retries} failed for "
                        f"'{email}': {error_text}. Retrying...",
                        file=__import__("sys").stderr,
                    )
                    page.wait_for_timeout(retry_delay_ms)
                    continue
                raise AssertionError(f"Login failed for user '{email}': {error_text}")
            if attempt < max_retries - 1:
                page.wait_for_timeout(retry_delay_ms)
                continue
            raise


# ---------------------------------------------------------------------------
# Shared E2E fixtures
#
# These were previously duplicated verbatim in every ``test_*_e2e.py`` file.
# Each E2E test module now imports them:
#
#     from .playwright_utils import authenticated_page, e2e_preflight
#
# Each module is still responsible for providing its own session-scoped
# ``worker_user`` fixture with a module-specific ``email_prefix`` so each
# suite gets an isolated user under xdist ``--dist loadfile``.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def e2e_preflight() -> None:
    """Verify the E2E server is reachable before any tests in the module run."""
    preflight_check()


@pytest.fixture(scope="function")
def authenticated_page(page: Page, worker_user: tuple[str, str]) -> Page:
    """A Playwright page already logged in as the module's ``worker_user``."""
    email, password = worker_user
    login_via_ui(page, email=email, password=password)
    return page


def capture_artifacts(page: Page, name: str) -> None:
    """Capture best-effort diagnostics (screenshot + HTML) for a failing test.

    This is intended to be called from except blocks in tests when a failure is
    detected. Errors while capturing artifacts are swallowed so they do not
    mask the original test failure.
    """
    artifacts_root = PROJECT_DIR / "artifacts" / "playwright"
    try:
        artifacts_root.mkdir(parents=True, exist_ok=True)
        safe_name = name.replace("/", "_").replace(" ", "_")
        screenshot_path = artifacts_root / f"{safe_name}.png"
        html_path = artifacts_root / f"{safe_name}.html"

        page.screenshot(path=str(screenshot_path), full_page=True)
        html = page.content()
        html_path.write_text(html, encoding="utf-8")
    except Exception as exc:  # pragma: no cover - best-effort diagnostics
        print(f"WARNING: Failed to capture Playwright artifacts for {name}: {exc}", file=sys.stderr)

