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


def _ensure_empty_cellar(page: Page) -> None:
    """Delete all wines so the cellar is empty."""
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
class TestExportFromCellar:
    """E2E tests for export functionality from cellar page."""

    def test_export_button_visible(self, authenticated_page: Page) -> None:
        """Export dropdown on cellar page."""
        _navigate_to_cellar(authenticated_page)
        expect(authenticated_page.locator("#cellar-export-btn")).to_be_visible()

    def test_export_dropdown_markup_exists(self, authenticated_page: Page) -> None:
        """Export dropdown markup is present in the DOM."""
        _navigate_to_cellar(authenticated_page)
        dropdown = authenticated_page.locator("#cellar-export-dropdown")
        expect(dropdown).to_be_attached()

    def test_export_csv_option_in_markup(self, authenticated_page: Page) -> None:
        """CSV export option exists in dropdown markup."""
        _navigate_to_cellar(authenticated_page)
        csv_option = authenticated_page.locator("#cellar-export-dropdown [data-format='csv']")
        expect(csv_option).to_be_attached()

    def test_export_xlsx_option_in_markup(self, authenticated_page: Page) -> None:
        """XLSX export option exists in dropdown markup."""
        _navigate_to_cellar(authenticated_page)
        xlsx_option = authenticated_page.locator("#cellar-export-dropdown [data-format='xlsx']")
        expect(xlsx_option).to_be_attached()

    def test_export_button_disabled_when_empty(self, authenticated_page: Page) -> None:
        """Export button is disabled when cellar is empty."""
        _ensure_empty_cellar(authenticated_page)
        _navigate_to_cellar(authenticated_page)
        # Wait for cellar to render the empty state
        authenticated_page.wait_for_timeout(1000)
        export_btn = authenticated_page.locator("#cellar-export-btn")
        expect(export_btn).to_be_attached()
        expect(export_btn).to_be_disabled()

    def test_export_yaml_option_in_markup(self, authenticated_page: Page) -> None:
        """YAML export option exists in dropdown markup."""
        _navigate_to_cellar(authenticated_page)
        yaml_option = authenticated_page.locator("#cellar-export-dropdown [data-format='yaml']")
        expect(yaml_option).to_be_attached()


@pytest.mark.e2e
class TestExportFromHistory:
    """E2E tests for export from history page."""

    def test_history_export_button_present(self, authenticated_page: Page) -> None:
        """Export button present on history page (disabled when empty)."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=5000)
        page.click("[data-cellar-tab='history']")
        page.wait_for_selector("#cellar-panel-history", state="visible", timeout=5000)
        export_btn = page.locator("#history-export-btn")
        expect(export_btn).to_be_attached()

    def test_history_export_dropdown_markup_exists(self, authenticated_page: Page) -> None:
        """History export dropdown markup exists in the DOM."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=5000)
        page.click("[data-cellar-tab='history']")
        page.wait_for_selector("#cellar-panel-history", state="visible", timeout=5000)
        dropdown = page.locator("#history-export-dropdown")
        expect(dropdown).to_be_attached()
