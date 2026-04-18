"""E2E tests for the History page.

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_history_e2e.py -v --override-ini="addopts="
"""

from typing import Generator

import pytest
from playwright.sync_api import Page, expect

from .playwright_utils import (
    BASE_URL,
    authenticated_page,  # noqa: F401 — imported fixture
    create_cli_worker_user,
    e2e_preflight,  # noqa: F401 — imported autouse fixture
)


@pytest.fixture(scope="session")
def worker_user(request: pytest.FixtureRequest) -> Generator[tuple[str, str], None, None]:
    email, password = create_cli_worker_user(request, email_prefix="e2e_history", password="testpass123")
    yield email, password


def _navigate_to_history(page: Page) -> None:
    page.click("a[data-page='cellar']")
    page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
    page.wait_for_selector("[data-cellar-tab='history']", state="visible", timeout=10000)
    page.click("[data-cellar-tab='history']")
    page.wait_for_selector("#cellar-panel-history", state="visible", timeout=10000)


def _ensure_empty_cellar(page: Page) -> None:
    """Delete all wines so history is empty."""
    page.evaluate("""
        async () => {
            const token = localStorage.getItem('winebox_token');
            if (!token) return;
            try {
                await fetch('/api/wines/all', {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + token }
                });
            } catch {}
        }
    """)
    page.wait_for_timeout(500)


@pytest.mark.e2e
class TestHistoryPage:
    """E2E tests for the history/transactions page."""

    def test_history_page_renders(self, authenticated_page: Page) -> None:
        """History list visible."""
        _navigate_to_history(authenticated_page)
        expect(authenticated_page.locator("#cellar-panel-history")).to_be_visible()
        expect(authenticated_page.locator("#history-list")).to_be_visible()

    def test_history_has_filter(self, authenticated_page: Page) -> None:
        """Filter select is present for transaction types."""
        _navigate_to_history(authenticated_page)
        expect(authenticated_page.locator("#history-filter")).to_be_visible()

    def test_history_has_export(self, authenticated_page: Page) -> None:
        """Export button is present."""
        _navigate_to_history(authenticated_page)
        expect(authenticated_page.locator("#history-export-btn")).to_be_visible()

    def test_history_filter_options(self, authenticated_page: Page) -> None:
        """Filter has options for transaction types."""
        _navigate_to_history(authenticated_page)
        filter_select = authenticated_page.locator("#history-filter")
        # The filter should have at least one option
        options = filter_select.locator("option")
        assert options.count() > 0

    def test_history_export_button_present(self, authenticated_page: Page) -> None:
        """Export button is present and disabled when history is empty."""
        _ensure_empty_cellar(authenticated_page)
        _navigate_to_history(authenticated_page)
        # Wait for history to render the empty state
        authenticated_page.wait_for_timeout(1000)
        export_btn = authenticated_page.locator("#history-export-btn")
        expect(export_btn).to_be_attached()
        # Button is disabled when there are no transactions
        expect(export_btn).to_be_disabled()

    def test_history_page_empty_state(self, authenticated_page: Page) -> None:
        """History list is visible even when empty (shows empty state)."""
        _navigate_to_history(authenticated_page)
        # The list container should always be present
        expect(authenticated_page.locator("#history-list")).to_be_visible()
