"""End-to-end tests for wine detail modal with case/bottle breakdown.

These tests verify that the wine detail modal shows case and bottle
information when viewing a wine via the Search tab.

Run with: uv run python -m pytest -m e2e tests/test_wine_detail_e2e.py -v
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
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def worker_user(request: pytest.FixtureRequest) -> Generator[tuple[str, str], None, None]:
    email, password = create_cli_worker_user(
        request,
        email_prefix="e2e_wine_detail",
        password="testpass123",
    )
    yield email, password


@pytest.fixture(scope="function")
def authenticated_page(page: Page, worker_user: tuple[str, str]) -> Page:
    email, password = worker_user
    login_via_ui(page, email=email, password=password)
    return page


def _add_case_via_api(page: Page) -> str:
    """Add a case of wine via the API and return the wine_id."""
    result = page.evaluate("""async () => {
        const token = localStorage.getItem('winebox_token');
        const resp = await fetch('/api/cases', {
            method: 'POST',
            headers: {
                'Authorization': 'Bearer ' + token,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                name: 'Detail Test Margaux',
                winery: 'Chateau Margaux',
                vintage: 2015,
                country: 'France',
                region: 'Bordeaux',
                wine_type: 'Red',
                case_size: 6,
                num_cases: 1,
                provenance: 'Berry Bros',
                purchase_price: 240.0,
            }),
        });
        const data = await resp.json();
        return { wine_id: data.wine_id, case_id: data.cases[0].id };
    }""")
    return result["wine_id"]


def _add_loose_bottles_via_api(page: Page) -> str:
    """Add loose bottles via the API and return the wine_id."""
    result = page.evaluate("""async () => {
        const token = localStorage.getItem('winebox_token');
        const resp = await fetch('/api/bottles', {
            method: 'POST',
            headers: {
                'Authorization': 'Bearer ' + token,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                name: 'Detail Test Cloudy Bay',
                winery: 'Cloudy Bay',
                vintage: 2022,
                country: 'New Zealand',
                wine_type: 'White',
                quantity: 3,
            }),
        });
        return await resp.json();
    }""")
    return result["wine_id"]


def _open_wine_detail_via_search(page: Page, wine_name: str) -> None:
    """Navigate to Search tab, find a wine by name, and open its detail modal."""
    page.click("a[data-page='cellar']")
    page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
    page.wait_for_selector("[data-cellar-tab='search']", state="visible", timeout=10000)
    page.click("[data-cellar-tab='search']")
    page.wait_for_selector("#cellar-panel-search", state="visible", timeout=10000)
    page.wait_for_selector("#search-form button[type='submit']", state="visible", timeout=5000)
    page.fill("#search-q", wine_name)
    page.click("#search-form button[type='submit']")
    page.wait_for_selector(".wine-card", state="visible", timeout=10000)
    card = page.locator(".wine-card", has_text=wine_name).first
    card.click()
    page.wait_for_selector("#wine-modal.active", state="visible", timeout=10000)


@pytest.mark.e2e
class TestWineDetailBottleInfo:
    """Test that wine detail modal shows case and bottle information."""

    def test_detail_modal_shows_case_breakdown(self, authenticated_page: Page) -> None:
        """Wine detail modal shows case info for wines with cases."""
        page = authenticated_page
        _add_case_via_api(page)
        _open_wine_detail_via_search(page, "Detail Test Margaux")

        detail = page.locator("#wine-detail")
        expect(detail.locator(".wine-detail-bottles")).to_be_visible(timeout=5000)

        detail_text = detail.text_content() or ""
        assert "Case" in detail_text, f"Expected 'Case' in detail. Got: {detail_text[:500]}"
        assert "6" in detail_text, f"Expected bottle count '6' in detail"

    def test_detail_modal_shows_loose_bottles(self, authenticated_page: Page) -> None:
        """Wine detail modal shows loose bottle count."""
        page = authenticated_page
        _add_loose_bottles_via_api(page)
        _open_wine_detail_via_search(page, "Detail Test Cloudy Bay")

        detail = page.locator("#wine-detail")
        detail_text = detail.text_content() or ""
        assert "3" in detail_text, f"Expected '3' bottles in detail"
        assert "loose" in detail_text.lower() or "bottle" in detail_text.lower(), (
            f"Expected bottle info in detail. Got: {detail_text[:500]}"
        )

    def test_detail_modal_shows_provenance(self, authenticated_page: Page) -> None:
        """Wine detail modal shows provenance for cases."""
        page = authenticated_page
        _open_wine_detail_via_search(page, "Detail Test Margaux")

        detail_text = page.locator("#wine-detail").text_content() or ""
        assert "Berry Bros" in detail_text, (
            f"Expected provenance 'Berry Bros' in detail. Got: {detail_text[:500]}"
        )
