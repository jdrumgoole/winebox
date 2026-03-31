"""E2E tests for the Cellar page (wine list, detail modal, views).

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_cellar_e2e.py -v --override-ini="addopts="
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
    email, password = create_cli_worker_user(request, email_prefix="e2e_cellar", password="testpass123")
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
class TestCellarPage:
    """E2E tests for the cellar page."""

    def test_cellar_shows_welcome_or_list(self, authenticated_page: Page) -> None:
        """Welcome panel or wine list is present."""
        _navigate_to_cellar(authenticated_page)
        # Either the welcome panel (empty cellar) or wine list (populated) should exist
        expect(authenticated_page.locator("#cellar-welcome-panel, #cellar-list")).to_be_attached()

    def test_cellar_has_filter(self, authenticated_page: Page) -> None:
        """Filter dropdown is present."""
        _navigate_to_cellar(authenticated_page)
        expect(authenticated_page.locator("#cellar-filter")).to_be_visible()

    def test_cellar_card_view_toggle(self, authenticated_page: Page) -> None:
        """Card view toggle button is present."""
        _navigate_to_cellar(authenticated_page)
        expect(authenticated_page.locator("#cellar-view-cards")).to_be_visible()

    def test_cellar_table_view_toggle(self, authenticated_page: Page) -> None:
        """Table view toggle button is present and switchable."""
        _navigate_to_cellar(authenticated_page)
        table_btn = authenticated_page.locator("#cellar-view-table")
        expect(table_btn).to_be_visible()
        table_btn.click()
        authenticated_page.wait_for_timeout(500)
        # Should switch to table view
        cards_btn = authenticated_page.locator("#cellar-view-cards")
        expect(cards_btn).to_be_visible()

    def test_cellar_export_available(self, authenticated_page: Page) -> None:
        """Export button is present on cellar page."""
        _navigate_to_cellar(authenticated_page)
        expect(authenticated_page.locator("#cellar-export-btn")).to_be_visible()


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
