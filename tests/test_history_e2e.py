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
    create_cli_worker_user,
    login_via_ui,
    preflight_check,
)


@pytest.fixture(scope="session", autouse=True)
def _e2e_preflight() -> None:
    preflight_check()


@pytest.fixture(scope="session")
def worker_user(request: pytest.FixtureRequest) -> Generator[tuple[str, str], None, None]:
    email, password = create_cli_worker_user(request, email_prefix="e2e_history", password="testpass123")
    yield email, password


@pytest.fixture(scope="function")
def authenticated_page(page: Page, worker_user: tuple[str, str]) -> Page:
    email, password = worker_user
    login_via_ui(page, email=email, password=password)
    return page


def _navigate_to_history(page: Page) -> None:
    page.click("a[data-page='history']")
    page.wait_for_selector("#page-history", state="visible", timeout=5000)


@pytest.mark.e2e
class TestHistoryPage:
    """E2E tests for the history/transactions page."""

    def test_history_page_renders(self, authenticated_page: Page) -> None:
        """History list visible."""
        _navigate_to_history(authenticated_page)
        expect(authenticated_page.locator("#page-history")).to_be_visible()
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

    def test_history_export_dropdown(self, authenticated_page: Page) -> None:
        """Export dropdown opens."""
        _navigate_to_history(authenticated_page)
        authenticated_page.click("#history-export-btn")
        authenticated_page.wait_for_timeout(500)
        expect(authenticated_page.locator("#history-export-dropdown .export-dropdown-menu")).to_be_visible()

    def test_history_page_empty_state(self, authenticated_page: Page) -> None:
        """History list is visible even when empty (shows empty state)."""
        _navigate_to_history(authenticated_page)
        # The list container should always be present
        expect(authenticated_page.locator("#history-list")).to_be_visible()
