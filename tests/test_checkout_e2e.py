"""E2E tests for the Remove Wine flow (formerly Checkout).

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_checkout_e2e.py -v --override-ini="addopts="
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
    email, password = create_cli_worker_user(request, email_prefix="e2e_checkout", password="testpass123")
    yield email, password


@pytest.fixture(scope="function")
def authenticated_page(page: Page, worker_user: tuple[str, str]) -> Page:
    email, password = worker_user
    login_via_ui(page, email=email, password=password)
    return page


@pytest.mark.e2e
class TestCheckoutUI:
    """E2E tests for remove wine UI elements."""

    def test_checkout_modal_exists(self, authenticated_page: Page) -> None:
        """Remove modal element exists in DOM."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=5000)
        expect(page.locator("#remove-modal")).to_be_attached()

    def test_checkout_form_exists(self, authenticated_page: Page) -> None:
        """Remove form exists inside modal."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=5000)
        expect(page.locator("#remove-form")).to_be_attached()

    def test_checkout_quantity_input_exists(self, authenticated_page: Page) -> None:
        """Remove quantity input exists in form."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=5000)
        expect(page.locator("#remove-quantity")).to_be_attached()

    def test_checkout_wine_id_hidden_field(self, authenticated_page: Page) -> None:
        """Remove modal has hidden wine ID field."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=5000)
        expect(page.locator("#remove-wine-id")).to_be_attached()

    def test_checkout_available_display(self, authenticated_page: Page) -> None:
        """Available quantity display element exists."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=5000)
        expect(page.locator("#remove-available")).to_be_attached()

    def test_reason_picker_exists(self, authenticated_page: Page) -> None:
        """Reason picker cards exist in remove modal."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=5000)
        expect(page.locator("#remove-reason-picker")).to_be_attached()
        # Four reason cards in the remove modal: DRINK, SELL, GIFT, OTHER
        cards = page.locator("#remove-reason-picker .reason-card")
        expect(cards).to_have_count(4)
