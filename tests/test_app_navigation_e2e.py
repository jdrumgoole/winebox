"""E2E smoke tests for core app navigation (cellar tabs, settings, met).

These tests focus on verifying that primary navigation targets are reachable
and that key UI elements render, rather than deep business logic. They reuse
the shared Playwright helpers for stability.

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_app_navigation_e2e.py -v
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
    """Fail fast if the E2E server is not reachable."""
    preflight_check()


@pytest.fixture(scope="session")
def base_url() -> str:
    """Return the base URL for the test server."""
    return BASE_URL


@pytest.fixture(scope="session")
def worker_user(request: pytest.FixtureRequest) -> Generator[tuple[str, str], None, None]:
    """Create a test user for this worker session."""
    email, password = create_cli_worker_user(
        request,
        email_prefix="e2e_nav",
        password="testpass123",
    )
    yield email, password


@pytest.fixture(scope="function")
def test_user(worker_user: tuple[str, str]) -> tuple[str, str]:
    """Return the worker's test user credentials."""
    return worker_user


@pytest.fixture(scope="function")
def authenticated_page(page: Page, test_user: tuple[str, str]) -> Page:
    """Log in via UI and return an authenticated page."""
    email, password = test_user
    login_via_ui(page, email=email, password=password)
    return page


@pytest.mark.e2e
class TestCoreNavigation:
    """Smoke tests for key navigation destinations."""

    def test_navigate_to_cellar(self, authenticated_page: Page) -> None:
        page = authenticated_page
        page.click("a[data-page='cellar']")
        expect(page.locator("#page-cellar")).to_be_visible()
        expect(page.locator("#cellar-tabs")).to_be_visible()
        # Dashboard tab active by default
        expect(page.locator("#cellar-panel-dashboard")).to_be_visible()

    def test_navigate_to_history_via_tab(self, authenticated_page: Page) -> None:
        page = authenticated_page
        page.click("a[data-page='cellar']")
        expect(page.locator("#page-cellar")).to_be_visible()
        page.click("[data-cellar-tab='history']")
        expect(page.locator("#cellar-panel-history")).to_be_visible()
        expect(page.locator("#history-list")).to_be_visible()

    def test_navigate_to_settings(self, authenticated_page: Page) -> None:
        page = authenticated_page
        # Settings is linked from the username display
        page.click("a[data-page='settings']")
        expect(page.locator("#page-settings")).to_be_visible()
        expect(page.locator("#password-form")).to_be_visible()

    def test_danger_zone_visible(self, authenticated_page: Page) -> None:
        page = authenticated_page
        page.click("a[data-page='settings']")
        expect(page.locator(".danger-zone")).to_be_visible()
        expect(page.locator("#delete-collection-btn")).to_be_visible()

    def test_navigate_to_met(self, authenticated_page: Page) -> None:
        """Test navigating to Wines I've Met page."""
        page = authenticated_page
        page.click("a[data-page='met']")
        expect(page.locator("#page-met")).to_be_visible()
        expect(page.locator("#met-record-wine-btn")).to_be_visible()

    def test_no_add_to_cellar_nav_link(self, authenticated_page: Page) -> None:
        """Test that 'Add to Cellar' nav link no longer exists — folded into My Cellar."""
        page = authenticated_page
        expect(page.locator("nav a[data-page='add-to-cellar']")).to_have_count(0)
        expect(page.locator("nav a[data-page='checkin']")).to_have_count(0)

    def test_no_search_or_history_nav_links(self, authenticated_page: Page) -> None:
        """Search and History are now sub-tabs under My Cellar, not top-level nav."""
        page = authenticated_page
        expect(page.locator("nav a[data-page='search']")).to_have_count(0)
        expect(page.locator("nav a[data-page='history']")).to_have_count(0)

    def test_cellar_entry_cards_navigate(self, authenticated_page: Page) -> None:
        """Test that import tab entry-path cards navigate to add-to-cellar wizard."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        expect(page.locator("#page-cellar")).to_be_visible()
        page.click("[data-cellar-tab='import']")
        page.wait_for_selector("#cellar-panel-import", state="visible", timeout=5000)
        page.click("#cellar-welcome-panel .entry-path-card[data-tab='scan']")
        expect(page.locator("#page-add-to-cellar")).to_be_visible()

    def test_record_wine_on_met_page(self, authenticated_page: Page) -> None:
        """Test that 'Record a Wine' button on Wines I've Met navigates to checkin form."""
        page = authenticated_page
        page.click("a[data-page='met']")
        expect(page.locator("#page-met")).to_be_visible()
        page.click("#met-record-wine-btn")
        expect(page.locator("#page-checkin")).to_be_visible()
        expect(page.locator("#front-label")).to_be_visible()
