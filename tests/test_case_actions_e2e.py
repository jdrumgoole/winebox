"""End-to-end tests for case-level actions (sell, gift, breakage).

These tests verify that users can perform actions on entire cases
from the grouped cellar view.

Run with: uv run python -m pytest -m e2e tests/test_case_actions_e2e.py -v
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
    email, password = create_cli_worker_user(
        request,
        email_prefix="e2e_case_actions",
        password="testpass123",
    )
    yield email, password


@pytest.fixture(scope="function")
def authenticated_page(page: Page, worker_user: tuple[str, str]) -> Page:
    email, password = worker_user
    login_via_ui(page, email=email, password=password)
    return page


def _add_case_via_api(page: Page, name: str = "Case Action Wine") -> dict:
    """Add a case of wine via API."""
    result = page.evaluate(f"""async () => {{
        const token = localStorage.getItem('access_token');
        const resp = await fetch('/api/cases', {{
            method: 'POST',
            headers: {{
                'Authorization': 'Bearer ' + token,
                'Content-Type': 'application/json',
            }},
            body: JSON.stringify({{
                name: '{name}',
                winery: 'Test Winery',
                vintage: 2020,
                country: 'France',
                wine_type: 'Red',
                case_size: 6,
                num_cases: 1,
            }}),
        }});
        return await resp.json();
    }}""")
    return result


@pytest.mark.e2e
class TestCaseActionModal:
    """Test the case action modal opens and shows correct options."""

    def test_case_action_button_visible(self, authenticated_page: Page) -> None:
        """Case Action button appears on case rows in grouped cellar."""
        page = authenticated_page
        _add_case_via_api(page, "Visible Case Wine")

        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)

        # Should have a Case Actions button
        expect(page.locator(".case-action-btn").first).to_be_visible(timeout=5000)

    def test_case_action_modal_opens(self, authenticated_page: Page) -> None:
        """Clicking Case Actions opens the case action modal."""
        page = authenticated_page
        _add_case_via_api(page, "Modal Open Wine")

        page.click("a[data-page='cellar']")
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)

        page.locator(".case-action-btn").first.click()
        expect(page.locator("#case-action-modal.active")).to_be_visible(timeout=5000)

    def test_case_action_modal_shows_reasons(self, authenticated_page: Page) -> None:
        """Case action modal shows Sell, Gift, and Breakage options."""
        page = authenticated_page
        _add_case_via_api(page, "Reasons Wine")

        page.click("a[data-page='cellar']")
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)
        page.locator(".case-action-btn").first.click()
        page.wait_for_selector("#case-action-modal.active", state="visible", timeout=5000)

        expect(page.locator(".case-reason-card[data-reason='sold']")).to_be_visible()
        expect(page.locator(".case-reason-card[data-reason='gifted']")).to_be_visible()
        expect(page.locator(".case-reason-card[data-reason='breakage']")).to_be_visible()


@pytest.mark.e2e
class TestCaseActionExecution:
    """Test that case actions work end-to-end."""

    def test_sell_case(self, authenticated_page: Page) -> None:
        """Selling a case shows success toast and updates cellar."""
        page = authenticated_page
        _add_case_via_api(page, "Sell Case Wine")

        page.click("a[data-page='cellar']")
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)

        # Find the case action button for our wine
        card = page.locator(".wine-card", has_text="Sell Case Wine").first
        card.locator(".case-action-btn").click()
        page.wait_for_selector("#case-action-modal.active", state="visible", timeout=5000)

        # Select Sell
        page.locator(".case-reason-card[data-reason='sold']").click()

        # Fill sale price
        page.fill("#case-action-sale-price", "150")
        page.fill("#case-action-buyer", "Wine Shop")

        # Confirm
        page.click("#case-action-confirm-btn")

        # Should show success toast
        expect(page.locator(".toast")).to_be_visible(timeout=5000)
        toast_text = page.locator(".toast").text_content() or ""
        assert "sold" in toast_text.lower() or "bottle" in toast_text.lower()

    def test_gift_case(self, authenticated_page: Page) -> None:
        """Gifting a case shows success toast."""
        page = authenticated_page
        _add_case_via_api(page, "Gift Case Wine")

        page.click("a[data-page='cellar']")
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)

        card = page.locator(".wine-card", has_text="Gift Case Wine").first
        card.locator(".case-action-btn").click()
        page.wait_for_selector("#case-action-modal.active", state="visible", timeout=5000)

        page.locator(".case-reason-card[data-reason='gifted']").click()
        page.fill("#case-action-recipient", "Birthday Friend")
        page.click("#case-action-confirm-btn")

        expect(page.locator(".toast")).to_be_visible(timeout=5000)
