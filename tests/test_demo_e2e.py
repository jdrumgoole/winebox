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


def _navigate_to_cellar(page: Page) -> None:
    page.click("a[data-page='cellar']")
    page.wait_for_selector("#page-cellar", state="visible", timeout=5000)


def _cleanup_demo_data(page: Page) -> None:
    """Remove all wines and demo data via API so tests start with a truly empty cellar."""
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
class TestDemoDataE2E:
    """E2E tests for loading and removing sample wine data."""

    def test_empty_dashboard_shows_welcome(self, authenticated_page: Page) -> None:
        """New user with empty cellar sees the demo welcome prompt."""
        page = authenticated_page
        _cleanup_demo_data(page)
        _navigate_to_cellar(page)

        try:
            # Wait for the demo welcome to appear
            page.wait_for_selector("#cellar-welcome-panel", state="visible", timeout=10000)
            expect(page.locator("#cellar-welcome-panel")).to_be_visible()
            expect(page.locator("#cellar-demo-install-btn")).to_be_visible()
            expect(page.locator("#cellar-demo-install-btn")).to_have_text("Load sample wines")
        except Exception:
            capture_artifacts(page, "demo_empty_welcome")
            raise

    def test_welcome_shows_entry_path_cards(self, authenticated_page: Page) -> None:
        """Welcome screen shows entry-path cards for Scan, Enter Details, Import."""
        page = authenticated_page
        _cleanup_demo_data(page)
        _navigate_to_cellar(page)

        try:
            page.wait_for_selector("#cellar-welcome-panel", state="visible", timeout=10000)
            cards = page.locator('#cellar-welcome-panel .entry-path-card')
            expect(cards).to_have_count(3)
            # First card navigates to add-to-cellar wizard
            cards.first.click()
            page.wait_for_selector("#page-add-to-cellar", state="visible", timeout=5000)
            expect(page.locator("#page-add-to-cellar")).to_be_visible()
        except Exception:
            capture_artifacts(page, "demo_entry_path_cards")
            raise

    def test_load_sample_wines(self, authenticated_page: Page) -> None:
        """Clicking 'Load sample wines' populates the cellar."""
        page = authenticated_page
        _cleanup_demo_data(page)
        _navigate_to_cellar(page)

        try:
            # Wait for welcome and click install
            page.wait_for_selector("#cellar-demo-install-btn", state="visible", timeout=10000)
            page.click("#cellar-demo-install-btn")

            # Wait for "Remove sample wines" button to appear (indicates install completed)
            page.wait_for_selector("#cellar-demo-remove-btn", state="visible", timeout=60000)
            expect(page.locator("#cellar-demo-remove-btn")).to_be_visible()
        except Exception:
            capture_artifacts(page, "demo_load_wines")
            raise

    def test_demo_shows_remove_button(self, authenticated_page: Page) -> None:
        """After loading demo data, welcome panel shows 'Remove sample wines'."""
        page = authenticated_page
        _cleanup_demo_data(page)
        _navigate_to_cellar(page)
        page.wait_for_selector("#cellar-demo-install-btn", state="visible", timeout=10000)
        page.click("#cellar-demo-install-btn")
        page.wait_for_selector("#cellar-demo-remove-btn", state="visible", timeout=60000)

        try:
            expect(page.locator("#cellar-demo-remove-btn")).to_have_text("Remove sample wines")
        except Exception:
            capture_artifacts(page, "demo_remove_button")
            raise

    def test_remove_sample_wines(self, authenticated_page: Page) -> None:
        """Clicking 'Remove sample wines' clears demo data and shows install button again."""
        page = authenticated_page
        _cleanup_demo_data(page)
        _navigate_to_cellar(page)
        page.wait_for_selector("#cellar-demo-install-btn", state="visible", timeout=10000)
        page.click("#cellar-demo-install-btn")
        page.wait_for_selector("#cellar-demo-remove-btn", state="visible", timeout=60000)

        try:
            page.click("#cellar-demo-remove-btn")
            # Wait for "Load sample wines" button to reappear
            page.wait_for_selector("#cellar-demo-install-btn", state="visible", timeout=15000)
            expect(page.locator("#cellar-demo-install-btn")).to_be_visible()
        except Exception:
            capture_artifacts(page, "demo_remove_wines")
            raise

    def test_cellar_has_demo_wines_after_install(self, authenticated_page: Page) -> None:
        """After loading demo data, the cellar page shows wines."""
        page = authenticated_page
        _cleanup_demo_data(page)
        _navigate_to_cellar(page)

        try:
            page.wait_for_selector("#cellar-demo-install-btn", state="visible", timeout=10000)
            page.click("#cellar-demo-install-btn")
            page.wait_for_selector("#cellar-demo-remove-btn", state="visible", timeout=60000)

            # Should have wine cards or rows
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
