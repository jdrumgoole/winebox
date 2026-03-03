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

# Project root directory (used for running CLI commands).
PROJECT_DIR: Path = Path(__file__).parent.parent


def get_worker_id(request: pytest.FixtureRequest) -> str:
    """Return the pytest-xdist worker ID, or 'main' if not running in parallel."""
    if hasattr(request.config, "workerinput"):
        return request.config.workerinput.get("workerid", "main")
    return "main"


def create_cli_worker_user(
    request: pytest.FixtureRequest,
    email_prefix: str,
    password: str = "testpass123",
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> tuple[str, str]:
    """Create (or reuse) a CLI-managed test user for the current worker.

    This function is intended to be called from a session-scoped fixture in an
    E2E test module, for example:

        @pytest.fixture(scope=\"session\")
        def worker_user(request: pytest.FixtureRequest) -> Generator[tuple[str, str], None, None]:
            email, password = create_cli_worker_user(request, \"e2e_worker\")
            yield email, password

    The helper is resilient to the user already existing and will only emit a
    warning to stderr if creation fails entirely.
    """
    worker_id = get_worker_id(request)
    email = f\"{email_prefix}_{worker_id}@test.example.com\"

    result: subprocess.CompletedProcess[str] | None = None
    created = False

    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                [\"uv\", \"run\", \"winebox-admin\", \"add\", email, \"--password\", password],
                cwd=PROJECT_DIR,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.SubprocessError as exc:  # timeout or similar
            print(f\"WARNING: subprocess error creating user {email}: {exc}\", file=sys.stderr)
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            continue

        combined = (result.stdout or \"\") + (result.stderr or \"\")
        if result.returncode == 0 or \"already exists\" in combined or \"already in use\" in combined:
            created = True
            break

        if attempt < max_retries - 1:
            time.sleep(retry_delay)

    if not created:
        print(f\"WARNING: Failed to create user {email}\", file=sys.stderr)
        if result is not None:
            print(f\"  stdout: {result.stdout}\", file=sys.stderr)
            print(f\"  stderr: {result.stderr}\", file=sys.stderr)

    # Small delay to reduce chances of race conditions with database writes.
    time.sleep(0.5)
    return email, password


def preflight_check(timeout_seconds: int = 10) -> None:
    """Fail fast if the E2E test server is not reachable.

    This performs a simple HTTP GET against the /health endpoint if available,
    otherwise the root URL. Any failure raises pytest.skip with a clear message
    so users immediately see that the server must be running.
    """
    start = time.time()
    urls = [f\"{BASE_URL}/health\", BASE_URL]

    last_error: Exception | None = None
    while time.time() - start < timeout_seconds:
        for url in urls:
            try:
                with urllib.request.urlopen(url, timeout=3):
                    return
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = exc
                continue
        time.sleep(0.5)

    msg = f\"E2E preflight failed: server at {BASE_URL!r} is not reachable. \" \\\n          \"Start it with 'uv run python -m invoke start-background' or equivalent.\"\n    if last_error is not None:
        msg += f\" Last error: {last_error!r}\"\n    pytest.skip(msg)


def login_via_ui(page: Page, email: str, password: str, *, timeout_ms: int = 15000) -> None:
    \"\"\"Log in through the UI and wait for main content to be visible.
\n    Raises an AssertionError with a helpful message if login fails.\n    \"\"\"\n    page.context.clear_cookies()\n    page.goto(BASE_URL)\n    page.evaluate(\"localStorage.clear()\")\n    page.reload()\n\n    page.wait_for_selector(\"#login-form\", state=\"visible\", timeout=timeout_ms)\n    page.fill(\"#login-email\", email)\n    page.fill(\"#login-password\", password)\n    page.click(\"#login-form button[type='submit']\")\n\n    try:\n        page.wait_for_selector(\"#main-content\", state=\"visible\", timeout=timeout_ms)\n    except Exception:\n        error_elem = page.locator(\"#login-error\")\n        if error_elem.is_visible():\n            error_text = error_elem.text_content() or \"\"\n            raise AssertionError(f\"Login failed for user '{email}': {error_text}\")\n        raise\n+\n+\n+def capture_artifacts(page: Page, name: str) -> None:\n+    \"\"\"Capture best-effort diagnostics (screenshot + HTML) for a failing test.\n+\n+    This is intended to be called from except blocks in tests when a failure is\n+    detected. Errors while capturing artifacts are swallowed so they do not\n+    mask the original test failure.\n+    \"\"\"\n+    artifacts_root = PROJECT_DIR / \"artifacts\" / \"playwright\"\n+    try:\n+        artifacts_root.mkdir(parents=True, exist_ok=True)\n+        safe_name = name.replace(\"/\", \"_\").replace(\" \", \"_\")\n+        screenshot_path = artifacts_root / f\"{safe_name}.png\"\n+        html_path = artifacts_root / f\"{safe_name}.html\"\n+\n+        page.screenshot(path=str(screenshot_path), full_page=True)\n+        html = page.content()\n+        html_path.write_text(html, encoding=\"utf-8\")\n+    except Exception as exc:  # pragma: no cover - best-effort diagnostics\n+        print(f\"WARNING: Failed to capture Playwright artifacts for {name}: {exc}\", file=sys.stderr)\n+\n*** End Patch
}"/>
