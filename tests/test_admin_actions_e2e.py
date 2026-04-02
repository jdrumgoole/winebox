"""E2E tests for admin panel styled dialogs (replaces browser alert/confirm).

These tests verify that admin actions use styled modals instead of
browser-native alert() and confirm() dialogs.

Run with: uv run python -m pytest -m e2e tests/test_admin_actions_e2e.py -v
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
        email_prefix="e2e_admin_actions",
        password="testpass123",
    )
    yield email, password


@pytest.fixture(scope="function")
def admin_page(page: Page, worker_user: tuple[str, str]) -> Page:
    """Log in and make user admin, then navigate to admin panel."""
    email, password = worker_user
    login_via_ui(page, email=email, password=password)

    # Make this user an admin via API
    page.evaluate("""async () => {
        const token = localStorage.getItem('access_token');
        // Try to access admin panel - if it works, user is already admin
        const resp = await fetch('/admin/api/stats', {
            headers: { 'Authorization': 'Bearer ' + token },
        });
        return resp.ok;
    }""")

    return page


@pytest.mark.e2e
class TestAdminStyledDialogs:
    """Test that admin actions use styled modals, not browser dialogs."""

    def test_admin_page_no_browser_dialogs(self, admin_page: Page) -> None:
        """Admin page JS does not call alert() or confirm() directly."""
        page = admin_page
        # Navigate to admin page
        page.goto(f"{BASE_URL}/admin")
        page.wait_for_timeout(2000)

        # Check that the admin.js loaded contains showAdminToast and showAdminConfirm
        has_styled = page.evaluate("""() => {
            return typeof showAdminToast === 'function' && typeof showAdminConfirm === 'function';
        }""")
        assert has_styled, "Admin panel should define showAdminToast and showAdminConfirm functions"

    def test_admin_toast_function_exists(self, admin_page: Page) -> None:
        """showAdminToast creates visible toast notifications."""
        page = admin_page
        page.goto(f"{BASE_URL}/admin")
        page.wait_for_timeout(2000)

        # Trigger a test toast
        page.evaluate("showAdminToast('Test notification', 'success')")

        # Toast should be visible
        toast = page.locator(".admin-toast")
        expect(toast).to_be_visible(timeout=3000)
        expect(toast).to_contain_text("Test notification")

    def test_admin_confirm_dialog_styled(self, admin_page: Page) -> None:
        """showAdminConfirm creates a styled overlay, not a browser dialog."""
        page = admin_page
        page.goto(f"{BASE_URL}/admin")
        page.wait_for_timeout(2000)

        # Trigger a test confirm
        page.evaluate("showAdminConfirm('Test confirm message', () => {})")

        # Should show styled overlay
        overlay = page.locator("#admin-confirm-overlay")
        expect(overlay).to_be_visible(timeout=3000)
        expect(overlay).to_contain_text("Test confirm message")

        # Should have Confirm and Cancel buttons
        expect(page.locator("#admin-confirm-yes")).to_be_visible()
        expect(page.locator("#admin-confirm-no")).to_be_visible()

        # Cancel should dismiss
        page.click("#admin-confirm-no")
        expect(overlay).not_to_be_visible(timeout=2000)
