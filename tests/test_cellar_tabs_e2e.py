"""E2E tests for My Cellar sub-tab navigation.

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_cellar_tabs_e2e.py -v --override-ini="addopts="
"""

import re
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
    email, password = create_cli_worker_user(request, email_prefix="e2e_tabs", password="testpass123")
    yield email, password


@pytest.mark.e2e
class TestCellarTabs:
    """E2E tests for sub-tab switching within My Cellar."""

    def test_cellar_loads_with_dashboard_tab_active(self, authenticated_page: Page) -> None:
        """Dashboard tab is active by default when navigating to cellar."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=5000)

        dashboard_tab = page.locator("[data-cellar-tab='dashboard']")
        expect(dashboard_tab).to_have_class(re.compile("active"))
        expect(page.locator("#cellar-panel-dashboard")).to_be_visible()
        expect(page.locator("#cellar-panel-search")).not_to_be_visible()
        expect(page.locator("#cellar-panel-import")).not_to_be_visible()
        expect(page.locator("#cellar-panel-history")).not_to_be_visible()

    def test_switch_to_search_tab(self, authenticated_page: Page) -> None:
        """Clicking Search tab shows search form."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=5000)

        page.click("[data-cellar-tab='search']")
        page.wait_for_selector("#cellar-panel-search", state="visible", timeout=5000)
        expect(page.locator("#search-form")).to_be_visible()
        expect(page.locator("#cellar-panel-dashboard")).not_to_be_visible()

    def test_switch_to_import_tab(self, authenticated_page: Page) -> None:
        """Clicking Import tab shows entry-path cards."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=5000)

        page.click("[data-cellar-tab='import']")
        page.wait_for_selector("#cellar-panel-import", state="visible", timeout=5000)
        expect(page.locator("#cellar-welcome-panel")).to_be_visible()
        expect(page.locator("#cellar-panel-dashboard")).not_to_be_visible()

    def test_switch_to_history_tab(self, authenticated_page: Page) -> None:
        """Clicking History tab shows history list."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=5000)

        page.click("[data-cellar-tab='history']")
        page.wait_for_selector("#cellar-panel-history", state="visible", timeout=5000)
        expect(page.locator("#history-list")).to_be_visible()
        expect(page.locator("#cellar-panel-dashboard")).not_to_be_visible()

    def test_deep_link_cellar_search(self, authenticated_page: Page) -> None:
        """Navigating to #cellar/search opens the Search tab."""
        page = authenticated_page
        page.goto(f"{BASE_URL}#cellar/search")
        page.wait_for_selector("#cellar-panel-search", state="visible", timeout=10000)
        expect(page.locator("#search-form")).to_be_visible()
        search_tab = page.locator("[data-cellar-tab='search']")
        expect(search_tab).to_have_class(re.compile("active"))

    def test_deep_link_cellar_history(self, authenticated_page: Page) -> None:
        """Navigating to #cellar/history opens the History tab."""
        page = authenticated_page
        page.goto(f"{BASE_URL}#cellar/history")
        page.wait_for_selector("#cellar-panel-history", state="visible", timeout=10000)
        expect(page.locator("#history-list")).to_be_visible()
        history_tab = page.locator("[data-cellar-tab='history']")
        expect(history_tab).to_have_class(re.compile("active"))

    def test_backward_compat_hash_search(self, authenticated_page: Page) -> None:
        """Old #search bookmark redirects to cellar Search tab."""
        page = authenticated_page
        page.goto(f"{BASE_URL}#search")
        page.wait_for_selector("#cellar-panel-search", state="visible", timeout=10000)
        expect(page.locator("#search-form")).to_be_visible()

    def test_backward_compat_hash_history(self, authenticated_page: Page) -> None:
        """Old #history bookmark redirects to cellar History tab."""
        page = authenticated_page
        page.goto(f"{BASE_URL}#history")
        page.wait_for_selector("#cellar-panel-history", state="visible", timeout=10000)
        expect(page.locator("#history-list")).to_be_visible()
