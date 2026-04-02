"""End-to-end tests for wine detail modal with case/bottle breakdown.

These tests verify that the wine detail modal shows case and bottle
information when viewing a wine that has bottles tracked.

Run with: uv run python -m pytest -m e2e tests/test_wine_detail_e2e.py -v
"""

import re
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
    """Fail fast if the E2E server is not reachable."""
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
        const token = localStorage.getItem('access_token');
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
        const token = localStorage.getItem('access_token');
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


@pytest.mark.e2e
class TestWineDetailBottleInfo:
    """Test that wine detail modal shows case and bottle information."""

    def test_detail_modal_shows_case_breakdown(self, authenticated_page: Page) -> None:
        """Wine detail modal shows case info for wines with cases."""
        page = authenticated_page
        _add_case_via_api(page)

        # Navigate to cellar and wait for wines to load
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)

        # Click on the wine card with our test wine
        card = page.locator(".wine-card", has_text="Detail Test Margaux").first
        card.click()

        # Wait for detail modal
        page.wait_for_selector("#wine-modal.active", state="visible", timeout=10000)

        # Should show case breakdown section
        detail = page.locator("#wine-detail")
        expect(detail.locator(".wine-detail-bottles")).to_be_visible(timeout=5000)

        # Should show case info with remaining count
        detail_text = detail.text_content() or ""
        assert "Case" in detail_text, f"Expected 'Case' in detail. Got: {detail_text[:500]}"
        assert "6" in detail_text, f"Expected bottle count '6' in detail"

    def test_detail_modal_shows_loose_bottles(self, authenticated_page: Page) -> None:
        """Wine detail modal shows loose bottle count."""
        page = authenticated_page
        _add_loose_bottles_via_api(page)

        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)

        card = page.locator(".wine-card", has_text="Detail Test Cloudy Bay").first
        card.click()

        page.wait_for_selector("#wine-modal.active", state="visible", timeout=10000)

        detail = page.locator("#wine-detail")
        detail_text = detail.text_content() or ""
        assert "3" in detail_text, f"Expected '3' bottles in detail"
        assert "loose" in detail_text.lower() or "bottle" in detail_text.lower(), (
            f"Expected bottle info in detail. Got: {detail_text[:500]}"
        )

    def test_detail_modal_shows_provenance(self, authenticated_page: Page) -> None:
        """Wine detail modal shows provenance for cases."""
        page = authenticated_page
        # Use wine already created by earlier test
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)

        card = page.locator(".wine-card", has_text="Detail Test Margaux").first
        card.click()

        page.wait_for_selector("#wine-modal.active", state="visible", timeout=10000)

        detail_text = page.locator("#wine-detail").text_content() or ""
        assert "Berry Bros" in detail_text, (
            f"Expected provenance 'Berry Bros' in detail. Got: {detail_text[:500]}"
        )


@pytest.mark.e2e
class TestWineDetailCellarFilter:
    """Test that the cellar filter works with the grouped view."""

    def test_cellar_filter_dropdown_visible(self, authenticated_page: Page) -> None:
        """Filter dropdown is visible on the cellar page."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=5000)
        expect(page.locator("#cellar-filter")).to_be_visible()

    def test_out_of_stock_filter_shows_legacy_view(self, authenticated_page: Page) -> None:
        """Selecting out-of-stock falls back to legacy view (no grouped cards)."""
        page = authenticated_page
        _add_case_via_api(page)

        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)

        # Switch to out-of-stock
        page.select_option("#cellar-filter", "out-of-stock")
        page.wait_for_timeout(2000)

        # Should not show grouped case rows (those are all in-stock)
        case_rows = page.locator(".case-row")
        assert case_rows.count() == 0


@pytest.mark.e2e
class TestWineDetailViewToggle:
    """Test that view toggle works with grouped cellar data."""

    def test_table_view_toggle(self, authenticated_page: Page) -> None:
        """Clicking table view shows a table layout."""
        page = authenticated_page
        _add_case_via_api(page)

        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)

        # Switch to table view
        page.click("#cellar-view-table")

        # Should show a table
        expect(page.locator(".cellar-table")).to_be_visible(timeout=5000)
        expect(page.locator(".cellar-table th", has_text="Wine")).to_be_visible()

    def test_card_view_toggle_back(self, authenticated_page: Page) -> None:
        """Switching back to card view shows cards again."""
        page = authenticated_page

        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)

        # Switch to table then back to cards
        page.click("#cellar-view-table")
        page.wait_for_selector(".cellar-table", state="visible", timeout=5000)
        page.click("#cellar-view-cards")

        # Should show cards again
        expect(page.locator(".wine-card").first).to_be_visible(timeout=5000)
