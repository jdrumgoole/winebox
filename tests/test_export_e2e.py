"""E2E tests for the Export functionality.

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_export_e2e.py -v --override-ini="addopts="
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
    email, password = create_cli_worker_user(request, email_prefix="e2e_export", password="testpass123")
    yield email, password


@pytest.fixture(scope="function")
def authenticated_page(page: Page, worker_user: tuple[str, str]) -> Page:
    email, password = worker_user
    login_via_ui(page, email=email, password=password)
    return page


def _navigate_to_cellar(page: Page) -> None:
    page.click("a[data-page='cellar']")
    page.wait_for_selector("#page-cellar", state="visible", timeout=5000)


@pytest.mark.e2e
class TestExportFromCellar:
    """E2E tests for export functionality from cellar page."""

    def test_export_button_visible(self, authenticated_page: Page) -> None:
        """Export dropdown on cellar page."""
        _navigate_to_cellar(authenticated_page)
        expect(authenticated_page.locator("#cellar-export-btn")).to_be_visible()

    def test_export_dropdown_opens(self, authenticated_page: Page) -> None:
        """Export dropdown menu opens on click."""
        _navigate_to_cellar(authenticated_page)
        authenticated_page.click("#cellar-export-btn")
        # Scope to cellar export dropdown specifically
        dropdown = authenticated_page.locator("#cellar-export-dropdown .export-dropdown-menu")
        expect(dropdown).to_be_visible(timeout=5000)

    def test_export_csv_option_exists(self, authenticated_page: Page) -> None:
        """CSV export option exists in dropdown."""
        _navigate_to_cellar(authenticated_page)
        authenticated_page.click("#cellar-export-btn")
        authenticated_page.wait_for_selector("#cellar-export-dropdown .export-dropdown-menu", state="visible", timeout=5000)
        csv_option = authenticated_page.locator("#cellar-export-dropdown [data-format='csv']")
        expect(csv_option).to_be_visible()

    def test_export_xlsx_option_exists(self, authenticated_page: Page) -> None:
        """XLSX export option exists in dropdown."""
        _navigate_to_cellar(authenticated_page)
        authenticated_page.click("#cellar-export-btn")
        authenticated_page.wait_for_selector("#cellar-export-dropdown .export-dropdown-menu", state="visible", timeout=5000)
        xlsx_option = authenticated_page.locator("#cellar-export-dropdown [data-format='xlsx']")
        expect(xlsx_option).to_be_visible()

    def test_export_csv_triggers_download(self, authenticated_page: Page) -> None:
        """CSV download triggers when clicked."""
        _navigate_to_cellar(authenticated_page)
        authenticated_page.click("#cellar-export-btn")
        authenticated_page.wait_for_timeout(500)

        with authenticated_page.expect_download(timeout=10000) as download_info:
            authenticated_page.click("[data-format='csv']")
        download = download_info.value
        assert download.suggested_filename.endswith(".csv")

    def test_export_xlsx_triggers_download(self, authenticated_page: Page) -> None:
        """XLSX download triggers when clicked."""
        _navigate_to_cellar(authenticated_page)
        authenticated_page.click("#cellar-export-btn")
        authenticated_page.wait_for_timeout(500)

        with authenticated_page.expect_download(timeout=10000) as download_info:
            authenticated_page.click("[data-format='xlsx']")
        download = download_info.value
        assert download.suggested_filename.endswith(".xlsx")


@pytest.mark.e2e
class TestExportFromHistory:
    """E2E tests for export from history page."""

    def test_history_export_button_visible(self, authenticated_page: Page) -> None:
        """Export button visible on history page."""
        page = authenticated_page
        page.click("a[data-page='history']")
        page.wait_for_selector("#page-history", state="visible", timeout=5000)
        expect(page.locator("#history-export-btn")).to_be_visible()

    def test_history_export_dropdown_opens(self, authenticated_page: Page) -> None:
        """History export dropdown opens on click."""
        page = authenticated_page
        page.click("a[data-page='history']")
        page.wait_for_selector("#page-history", state="visible", timeout=5000)
        page.click("#history-export-btn")
        page.wait_for_timeout(500)
        expect(page.locator("#history-export-dropdown .export-dropdown-menu")).to_be_visible()
