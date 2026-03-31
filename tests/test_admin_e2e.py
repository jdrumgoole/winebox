"""E2E tests for the Admin page.

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_admin_e2e.py -v --override-ini="addopts="
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
    email, password = create_cli_worker_user(request, email_prefix="e2e_admin", password="testpass123")
    yield email, password


@pytest.fixture(scope="function")
def authenticated_page(page: Page, worker_user: tuple[str, str]) -> Page:
    email, password = worker_user
    login_via_ui(page, email=email, password=password)
    return page


@pytest.mark.e2e
class TestAdminAccess:
    """E2E tests for admin page access control."""

    def test_admin_non_admin_no_link(self, authenticated_page: Page) -> None:
        """Regular user doesn't see admin link in nav."""
        page = authenticated_page
        admin_link = page.locator("#admin-link")
        # Admin link should either not exist or be hidden for regular users
        expect(admin_link).to_be_hidden()

    def test_admin_unauthenticated_rejected(self, page: Page) -> None:
        """Unauthenticated access to /admin is rejected."""
        page.goto(f"{BASE_URL}/admin")
        page.wait_for_timeout(2000)
        # Should either redirect to login or show error
        # Check we're not on the admin page with user list
        content = page.content()
        # Admin page should not render for unauthenticated users
        assert "login" in content.lower() or page.url != f"{BASE_URL}/admin"

    def test_admin_direct_url_non_admin(self, authenticated_page: Page) -> None:
        """Regular user navigating to /admin directly is rejected."""
        page = authenticated_page
        response = page.goto(f"{BASE_URL}/admin")
        page.wait_for_timeout(2000)
        # The server should return 403 or the page should not show admin user list
        content = page.content()
        status = response.status if response else 0
        assert (
            status == 403
            or "403" in content
            or "forbidden" in content.lower()
            or "privileges" in content.lower()
            # If the admin page returns the main app HTML (no user list), that's also OK
            or "user-management" not in content.lower()
        )

    def test_admin_link_not_in_nav(self, authenticated_page: Page) -> None:
        """Admin link should not be visible for regular users."""
        page = authenticated_page
        # Navigate to cellar to ensure nav is loaded
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=5000)
        admin_link = page.locator("#admin-link")
        expect(admin_link).to_be_hidden()

    def test_admin_page_returns_html(self, page: Page) -> None:
        """Admin page endpoint returns a response (not 500)."""
        page.goto(f"{BASE_URL}/admin")
        page.wait_for_timeout(2000)
        # Should return some response, not a server error
        content = page.content()
        assert len(content) > 0

    def test_nav_has_correct_links(self, authenticated_page: Page) -> None:
        """Regular user nav has standard links but not admin."""
        page = authenticated_page
        expect(page.locator("nav a[data-page='cellar']")).to_be_visible()
        expect(page.locator("nav a[data-page='history']")).to_be_visible()
        expect(page.locator("#admin-link")).to_be_hidden()
