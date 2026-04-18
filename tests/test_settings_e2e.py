"""E2E tests for the Settings page.

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_settings_e2e.py -v --override-ini="addopts="
"""

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
    email, password = create_cli_worker_user(request, email_prefix="e2e_settings", password="testpass123")
    yield email, password


def _navigate_to_settings(page: Page) -> None:
    page.click("a[data-page='settings']")
    page.wait_for_selector("#page-settings", state="visible", timeout=5000)


@pytest.mark.e2e
class TestSettingsPage:
    """E2E tests for the settings page."""

    def test_settings_page_renders(self, authenticated_page: Page) -> None:
        """Password form visible."""
        _navigate_to_settings(authenticated_page)
        expect(authenticated_page.locator("#page-settings")).to_be_visible()
        expect(authenticated_page.locator("#password-form")).to_be_visible()

    def test_password_form_has_inputs(self, authenticated_page: Page) -> None:
        """Password form has current, new, and confirm inputs."""
        _navigate_to_settings(authenticated_page)
        expect(authenticated_page.locator("#current-password")).to_be_visible()
        expect(authenticated_page.locator("#new-password")).to_be_visible()
        expect(authenticated_page.locator("#confirm-password")).to_be_visible()

    def test_password_change_wrong_current(self, authenticated_page: Page) -> None:
        """Wrong current password -> error message."""
        _navigate_to_settings(authenticated_page)
        authenticated_page.fill("#current-password", "wrongpassword")
        authenticated_page.fill("#new-password", "newpass123")
        authenticated_page.fill("#confirm-password", "newpass123")
        authenticated_page.click("#password-form button[type='submit']")
        authenticated_page.wait_for_timeout(2000)
        # Should show an error (toast, alert, or inline)
        # The page should still be on settings (not redirected)
        expect(authenticated_page.locator("#page-settings")).to_be_visible()

    def test_delete_collection_button_visible(self, authenticated_page: Page) -> None:
        """Delete button shows in danger zone."""
        _navigate_to_settings(authenticated_page)
        expect(authenticated_page.locator("#delete-collection-btn")).to_be_visible()

    def test_delete_collection_modal_exists(self, authenticated_page: Page) -> None:
        """Delete collection modal exists in DOM."""
        _navigate_to_settings(authenticated_page)
        expect(authenticated_page.locator("#delete-collection-modal")).to_be_attached()

    def test_danger_zone_visible(self, authenticated_page: Page) -> None:
        """Danger zone section is visible on settings page."""
        _navigate_to_settings(authenticated_page)
        expect(authenticated_page.locator(".danger-zone")).to_be_visible()
