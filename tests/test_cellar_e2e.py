"""E2E tests for the Cellar page (tabbed layout, dashboard, modals).

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_cellar_e2e.py -v --override-ini="addopts="
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
    email, password = create_cli_worker_user(request, email_prefix="e2e_cellar", password="testpass123")
    yield email, password


def _navigate_to_cellar(page: Page) -> None:
    page.click("a[data-page='cellar']")
    page.wait_for_selector("#page-cellar", state="visible", timeout=5000)


@pytest.mark.e2e
class TestCellarPage:
    """E2E tests for the cellar page tab structure."""

    def test_cellar_has_tab_bar(self, authenticated_page: Page) -> None:
        """Tab bar with Dashboard/Search/Import/History is present."""
        _navigate_to_cellar(authenticated_page)
        expect(authenticated_page.locator("#cellar-tabs")).to_be_visible()
        tabs = authenticated_page.locator(".cellar-tab")
        assert tabs.count() == 4

    def test_cellar_dashboard_tab_active_by_default(self, authenticated_page: Page) -> None:
        """Dashboard tab is active by default."""
        _navigate_to_cellar(authenticated_page)
        dashboard_tab = authenticated_page.locator("[data-cellar-tab='dashboard']")
        expect(dashboard_tab).to_have_class(re.compile("active"))
        expect(authenticated_page.locator("#cellar-panel-dashboard")).to_be_visible()

    def test_cellar_stats_grid_visible(self, authenticated_page: Page) -> None:
        """Stats grid is visible on Dashboard tab."""
        _navigate_to_cellar(authenticated_page)
        expect(authenticated_page.locator("#cellar-stats-grid")).to_be_visible()

    def test_cellar_welcome_panel_on_import_tab(self, authenticated_page: Page) -> None:
        """Welcome panel with entry-path cards is on the Import tab."""
        _navigate_to_cellar(authenticated_page)
        authenticated_page.click("[data-cellar-tab='import']")
        authenticated_page.wait_for_selector("#cellar-panel-import", state="visible", timeout=5000)
        expect(authenticated_page.locator("#cellar-welcome-panel")).to_be_visible()


@pytest.mark.e2e
class TestWineDetailModal:
    """E2E tests for wine detail modal (requires wines in cellar)."""

    def test_wine_modal_container_exists(self, authenticated_page: Page) -> None:
        """Wine modal element exists in DOM (even if hidden)."""
        _navigate_to_cellar(authenticated_page)
        # The modal exists in the DOM but may be hidden
        modal = authenticated_page.locator("#wine-modal")
        expect(modal).to_be_attached()

    def test_checkout_modal_container_exists(self, authenticated_page: Page) -> None:
        """Remove modal element exists in DOM."""
        _navigate_to_cellar(authenticated_page)
        modal = authenticated_page.locator("#remove-modal")
        expect(modal).to_be_attached()

    def test_delete_wine_modal_container_exists(self, authenticated_page: Page) -> None:
        """Delete wine modal element exists in DOM."""
        _navigate_to_cellar(authenticated_page)
        modal = authenticated_page.locator("#delete-wine-modal")
        expect(modal).to_be_attached()
