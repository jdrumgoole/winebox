"""E2E tests for the demo/sample data feature.

Tests the full flow: empty dashboard → load sample wines → verify data →
remove sample wines → verify empty again.

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_demo_e2e.py -v --override-ini="addopts="
"""

from typing import Generator

import pytest
from playwright.sync_api import Page, expect

from .playwright_utils import (
    BASE_URL,
    capture_artifacts,
    create_cli_worker_user,
    login_via_ui,
    preflight_check,
)


@pytest.fixture(scope="session", autouse=True)
def _e2e_preflight() -> None:
    preflight_check()


@pytest.fixture(scope="session")
def worker_user(request: pytest.FixtureRequest) -> Generator[tuple[str, str], None, None]:
    """Get test user for demo E2E tests."""
    email, password = create_cli_worker_user(request, email_prefix="e2e_demo", password="testpass123")
    yield email, password


@pytest.fixture(scope="function")
def authenticated_page(page: Page, worker_user: tuple[str, str]) -> Page:
    email, password = worker_user
    login_via_ui(page, email=email, password=password)
    return page


def _navigate_to_dashboard(page: Page) -> None:
    page.click("a[data-page='dashboard']")
    page.wait_for_selector("#page-dashboard", state="visible", timeout=5000)


def _cleanup_demo_data(page: Page) -> None:
    """Remove demo data via API if present, so tests start clean."""
    page.evaluate("""
        async () => {
            const token = localStorage.getItem('winebox_token');
            if (!token) return;
            try {
                await fetch('/api/demo/remove', {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + token }
                });
            } catch {}
        }
    """)
    page.wait_for_timeout(500)


@pytest.mark.e2e
class TestDemoDataE2E:
    """E2E tests for loading and removing sample wine data."""

    def test_empty_dashboard_shows_welcome(self, authenticated_page: Page) -> None:
        """New user with empty cellar sees the demo welcome prompt."""
        page = authenticated_page
        _cleanup_demo_data(page)
        _navigate_to_dashboard(page)

        try:
            # Wait for the demo welcome to appear
            page.wait_for_selector("#demo-welcome", state="visible", timeout=10000)
            expect(page.locator("#demo-welcome")).to_be_visible()
            expect(page.locator("#demo-install-btn")).to_be_visible()
            expect(page.locator("#demo-install-btn")).to_have_text("Load sample wines")
        except Exception:
            capture_artifacts(page, "demo_empty_welcome")
            raise

    def test_load_sample_wines(self, authenticated_page: Page) -> None:
        """Clicking 'Load sample wines' populates the cellar."""
        page = authenticated_page
        _cleanup_demo_data(page)
        _navigate_to_dashboard(page)

        try:
            # Wait for welcome and click install
            page.wait_for_selector("#demo-install-btn", state="visible", timeout=10000)
            page.click("#demo-install-btn")

            # Wait for the banner to appear (indicates install completed and dashboard reloaded)
            page.wait_for_selector("#demo-banner", state="visible", timeout=30000)
            expect(page.locator("#demo-banner")).to_be_visible()
            expect(page.locator("#demo-banner")).to_contain_text("sample wines")

            # Verify dashboard stats updated — total bottles should be > 0
            stat = page.locator("#stat-total-bottles")
            expect(stat).to_be_visible()
            bottles_text = stat.text_content()
            assert bottles_text is not None
            assert int(bottles_text) > 0, f"Expected bottles > 0, got '{bottles_text}'"
        except Exception:
            capture_artifacts(page, "demo_load_wines")
            raise

    def test_demo_banner_shows_remove_button(self, authenticated_page: Page) -> None:
        """After loading demo data, a banner with 'Remove' button appears."""
        page = authenticated_page
        # Ensure demo data is loaded
        _cleanup_demo_data(page)
        _navigate_to_dashboard(page)
        page.wait_for_selector("#demo-install-btn", state="visible", timeout=10000)
        page.click("#demo-install-btn")
        page.wait_for_selector("#demo-banner", state="visible", timeout=30000)

        try:
            expect(page.locator("#demo-remove-btn")).to_be_visible()
            expect(page.locator("#demo-remove-btn")).to_have_text("Remove sample wines")
        except Exception:
            capture_artifacts(page, "demo_banner_remove")
            raise

    def test_remove_sample_wines(self, authenticated_page: Page) -> None:
        """Clicking 'Remove sample wines' clears demo data and shows welcome again."""
        page = authenticated_page
        # Load demo data first
        _cleanup_demo_data(page)
        _navigate_to_dashboard(page)
        page.wait_for_selector("#demo-install-btn", state="visible", timeout=10000)
        page.click("#demo-install-btn")
        page.wait_for_selector("#demo-banner", state="visible", timeout=30000)

        try:
            # Click remove
            page.click("#demo-remove-btn")

            # Wait for welcome prompt to reappear (demo data removed, cellar empty)
            page.wait_for_selector("#demo-welcome", state="visible", timeout=15000)
            expect(page.locator("#demo-welcome")).to_be_visible()

            # Banner should be gone
            expect(page.locator("#demo-banner")).not_to_be_attached()

            # Stats should be back to 0
            stat = page.locator("#stat-total-bottles")
            expect(stat).to_be_visible()
            bottles_text = stat.text_content()
            assert bottles_text == "0", f"Expected 0 bottles after removal, got '{bottles_text}'"
        except Exception:
            capture_artifacts(page, "demo_remove_wines")
            raise

    def test_cellar_page_has_demo_wines_after_install(self, authenticated_page: Page) -> None:
        """After loading demo data, the cellar page shows wines."""
        page = authenticated_page
        _cleanup_demo_data(page)
        _navigate_to_dashboard(page)

        try:
            # Install demo data
            page.wait_for_selector("#demo-install-btn", state="visible", timeout=10000)
            page.click("#demo-install-btn")
            page.wait_for_selector("#demo-banner", state="visible", timeout=30000)

            # Navigate to cellar
            page.click("a[data-page='cellar']")
            page.wait_for_selector("#page-cellar", state="visible", timeout=5000)

            # Should have wine cards
            page.wait_for_selector(".wine-card, .wine-row, tr[data-wine-id]", timeout=10000)
            wine_elements = page.locator(".wine-card, .wine-row, tr[data-wine-id]")
            count = wine_elements.count()
            assert count > 0, f"Expected wines in cellar, got {count}"
        except Exception:
            capture_artifacts(page, "demo_cellar_wines")
            raise
        finally:
            _cleanup_demo_data(page)

    def test_demo_api_status(self, authenticated_page: Page) -> None:
        """The /api/demo/status endpoint reports correct state."""
        page = authenticated_page
        _cleanup_demo_data(page)

        try:
            # Check status — should be not installed
            status = page.evaluate("""
                async () => {
                    const token = localStorage.getItem('winebox_token');
                    const resp = await fetch('/api/demo/status', {
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    return await resp.json();
                }
            """)
            assert status["installed"] is False
            assert status["wine_count"] == 0

            # Install via API (async — returns immediately with total)
            install_result = page.evaluate("""
                async () => {
                    const token = localStorage.getItem('winebox_token');
                    const resp = await fetch('/api/demo/install', {
                        method: 'POST',
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    return await resp.json();
                }
            """)
            assert install_result["total"] > 0

            # Wait for background install to finish by polling status
            page.evaluate("""
                async () => {
                    const token = localStorage.getItem('winebox_token');
                    for (let i = 0; i < 60; i++) {
                        await new Promise(r => setTimeout(r, 1000));
                        const resp = await fetch('/api/demo/status', {
                            headers: { 'Authorization': 'Bearer ' + token }
                        });
                        const status = await resp.json();
                        if (status.installed && status.wine_count > 0) return status;
                    }
                    throw new Error('Install timed out');
                }
            """)

            # Check status — should be installed
            status2 = page.evaluate("""
                async () => {
                    const token = localStorage.getItem('winebox_token');
                    const resp = await fetch('/api/demo/status', {
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    return await resp.json();
                }
            """)
            assert status2["installed"] is True
            assert status2["wine_count"] > 0

            # Remove via API
            remove_result = page.evaluate("""
                async () => {
                    const token = localStorage.getItem('winebox_token');
                    const resp = await fetch('/api/demo/remove', {
                        method: 'DELETE',
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    return await resp.json();
                }
            """)
            assert remove_result["wines_removed"] > 0
        except Exception:
            capture_artifacts(page, "demo_api_status")
            raise
