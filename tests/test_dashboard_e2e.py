"""E2E tests for the Dashboard page.

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_dashboard_e2e.py -v --override-ini="addopts="
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
    email, password = create_cli_worker_user(request, email_prefix="e2e_dashboard", password="testpass123")
    yield email, password


@pytest.fixture(scope="function")
def authenticated_page(page: Page, worker_user: tuple[str, str]) -> Page:
    email, password = worker_user
    login_via_ui(page, email=email, password=password)
    return page


def _navigate_to_dashboard(page: Page) -> None:
    page.click("a[data-page='dashboard']")
    page.wait_for_selector("#page-dashboard", state="visible", timeout=5000)


@pytest.mark.e2e
class TestDashboardPage:
    """E2E tests for the dashboard page."""

    def test_dashboard_renders(self, authenticated_page: Page) -> None:
        """#dashboard page visible."""
        _navigate_to_dashboard(authenticated_page)
        expect(authenticated_page.locator("#page-dashboard")).to_be_visible()

    def test_dashboard_shows_stats_grid(self, authenticated_page: Page) -> None:
        """Statistics grid container renders."""
        _navigate_to_dashboard(authenticated_page)
        expect(authenticated_page.locator("#stats-grid")).to_be_visible()

    def test_dashboard_shows_total_bottles(self, authenticated_page: Page) -> None:
        """Total bottles stat displayed."""
        _navigate_to_dashboard(authenticated_page)
        expect(authenticated_page.locator("#stat-total-bottles")).to_be_visible()

    def test_dashboard_shows_unique_wines(self, authenticated_page: Page) -> None:
        """Unique wines stat displayed."""
        _navigate_to_dashboard(authenticated_page)
        expect(authenticated_page.locator("#stat-unique-wines")).to_be_visible()

    def test_dashboard_shows_charts(self, authenticated_page: Page) -> None:
        """Chart containers render (by-country, by-grape, by-vintage)."""
        _navigate_to_dashboard(authenticated_page)
        expect(authenticated_page.locator("#by-country")).to_be_visible()
        expect(authenticated_page.locator("#by-grape")).to_be_visible()
        expect(authenticated_page.locator("#by-vintage")).to_be_visible()

    def test_dashboard_shows_recent_activity(self, authenticated_page: Page) -> None:
        """Recent activity section present."""
        _navigate_to_dashboard(authenticated_page)
        expect(authenticated_page.locator("#recent-activity")).to_be_visible()
