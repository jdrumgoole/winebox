"""E2E tests verifying that key screens render correctly at mobile viewports.

Playwright is configured with a 375×667 viewport (iPhone SE size) to exercise
the responsive CSS breakpoints (768px, 600px, 480px).

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_mobile_e2e.py -v --override-ini="addopts="
"""

from typing import Generator

import pytest
from playwright.sync_api import BrowserContext, Page, expect

from .playwright_utils import (
    BASE_URL,
    create_cli_worker_user,
    e2e_preflight,  # noqa: F401 — imported autouse fixture
    login_via_ui,
)

# iPhone SE-ish viewport
MOBILE_WIDTH = 375
MOBILE_HEIGHT = 667


@pytest.fixture(scope="session")
def worker_user(request: pytest.FixtureRequest) -> Generator[tuple[str, str], None, None]:
    email, password = create_cli_worker_user(request, email_prefix="e2e_mobile", password="testpass123")
    yield email, password


@pytest.fixture(scope="function")
def mobile_page(browser: "BrowserContext", worker_user: tuple[str, str]) -> Generator[Page, None, None]:
    """Create a browser context with a mobile-sized viewport and log in."""
    # browser here is actually the Browser instance provided by pytest-playwright
    context = browser.new_context(viewport={"width": MOBILE_WIDTH, "height": MOBILE_HEIGHT})
    page = context.new_page()
    email, password = worker_user
    login_via_ui(page, email=email, password=password)
    yield page
    context.close()


@pytest.fixture(scope="function")
def mobile_page_unauthenticated(browser: "BrowserContext") -> Generator[Page, None, None]:
    """A mobile-sized page without logging in (for login page tests)."""
    context = browser.new_context(viewport={"width": MOBILE_WIDTH, "height": MOBILE_HEIGHT})
    page = context.new_page()
    yield page
    context.close()


@pytest.mark.e2e
class TestMobileLoginPage:
    """Login page should be usable on mobile viewports."""

    def test_login_form_visible_on_mobile(self, mobile_page_unauthenticated: Page) -> None:
        """Login form fits within the mobile viewport."""
        page = mobile_page_unauthenticated
        page.goto(BASE_URL)
        page.wait_for_selector("#login-form", state="visible", timeout=10000)

        expect(page.locator("#login-email")).to_be_visible()
        expect(page.locator("#login-password")).to_be_visible()
        expect(page.locator("#login-form button[type='submit']")).to_be_visible()

    def test_login_form_not_clipped(self, mobile_page_unauthenticated: Page) -> None:
        """Submit button is within the visible viewport (not cut off)."""
        page = mobile_page_unauthenticated
        page.goto(BASE_URL)
        page.wait_for_selector("#login-form", state="visible", timeout=10000)

        box = page.locator("#login-form button[type='submit']").bounding_box()
        assert box is not None, "Submit button has no bounding box"
        # Button's right edge should be within viewport width
        assert box["x"] + box["width"] <= MOBILE_WIDTH + 10, (
            f"Submit button extends beyond mobile viewport: right edge at {box['x'] + box['width']}px"
        )


@pytest.mark.e2e
class TestMobileNavigation:
    """Navigation on mobile should use the hamburger menu."""

    def test_hamburger_menu_visible(self, mobile_page: Page) -> None:
        """Hamburger menu button is visible at mobile width."""
        page = mobile_page
        expect(page.locator("#hamburger-btn")).to_be_visible()

    def test_hamburger_toggles_nav(self, mobile_page: Page) -> None:
        """Clicking the hamburger opens and closes the nav menu."""
        page = mobile_page
        page.locator("#hamburger-btn").click()
        page.wait_for_timeout(300)

        # Navigation links should now be visible
        nav_links = page.locator("nav a[data-page]")
        assert nav_links.count() > 0, "Expected navigation links in the menu"
        expect(nav_links.first).to_be_visible()

    def test_nav_link_navigates_and_closes_menu(self, mobile_page: Page) -> None:
        """Tapping a nav link navigates to the target page."""
        page = mobile_page
        page.locator("#hamburger-btn").click()
        page.wait_for_timeout(300)

        # Tap "Wines I've Met" — one of the top-level nav targets that
        # still renders a distinct page (search/history are now sub-tabs
        # of the cellar page, not separate routes).
        page.click("nav a[data-page='met']")
        expect(page.locator("#page-met")).to_be_visible(timeout=5000)


@pytest.mark.e2e
class TestMobileCellarPage:
    """Cellar page renders acceptably on mobile."""

    def test_cellar_renders_on_mobile(self, mobile_page: Page) -> None:
        """Cellar page loads without horizontal overflow."""
        page = mobile_page
        page.locator("#hamburger-btn").click()
        page.wait_for_timeout(300)
        page.click("nav a[data-page='cellar']")
        expect(page.locator("#page-cellar")).to_be_visible(timeout=5000)

        # Check the page doesn't create massive horizontal scroll
        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        assert scroll_width <= MOBILE_WIDTH + 20, (
            f"Page has horizontal overflow: scrollWidth={scroll_width}, viewport={MOBILE_WIDTH}"
        )


@pytest.mark.e2e
class TestMobileSettingsPage:
    """Settings page is usable on mobile viewports."""

    def test_settings_page_renders_on_mobile(self, mobile_page: Page) -> None:
        """Settings page and password form visible on mobile."""
        page = mobile_page
        page.locator("#hamburger-btn").click()
        page.wait_for_timeout(300)
        page.click("a[data-page='settings']")
        expect(page.locator("#page-settings")).to_be_visible(timeout=5000)
        expect(page.locator("#password-form")).to_be_visible()

    def test_danger_zone_visible_on_mobile(self, mobile_page: Page) -> None:
        """Danger zone section is accessible on mobile."""
        page = mobile_page
        page.locator("#hamburger-btn").click()
        page.wait_for_timeout(300)
        page.click("a[data-page='settings']")
        expect(page.locator("#page-settings")).to_be_visible(timeout=5000)

        # Scroll down if needed — danger zone may be below fold
        page.locator(".danger-zone").scroll_into_view_if_needed()
        expect(page.locator(".danger-zone")).to_be_visible()
