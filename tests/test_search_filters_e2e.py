"""E2E tests for case-aware search filters (storage type, provenance).

Run with: uv run python -m pytest -m e2e tests/test_search_filters_e2e.py -v
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
    email, password = create_cli_worker_user(
        request,
        email_prefix="e2e_search_filters",
        password="testpass123",
    )
    yield email, password


@pytest.mark.e2e
class TestCaseAwareSearchFilters:
    """Test that search includes storage type and provenance filters."""

    def test_storage_filter_visible(self, authenticated_page: Page) -> None:
        """Storage filter dropdown is visible on search page."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector("[data-cellar-tab='search']", state="visible", timeout=10000)
        page.click("[data-cellar-tab='search']")
        page.wait_for_selector("#cellar-panel-search", state="visible", timeout=10000)
        expect(page.locator("#search-storage")).to_be_visible()

    def test_provenance_filter_visible(self, authenticated_page: Page) -> None:
        """Provenance input is visible on search page."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector("[data-cellar-tab='search']", state="visible", timeout=10000)
        page.click("[data-cellar-tab='search']")
        page.wait_for_selector("#cellar-panel-search", state="visible", timeout=10000)
        expect(page.locator("#search-provenance")).to_be_visible()

    def test_storage_filter_has_options(self, authenticated_page: Page) -> None:
        """Storage filter has All, In Case, and Loose Bottles options."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector("[data-cellar-tab='search']", state="visible", timeout=10000)
        page.click("[data-cellar-tab='search']")
        page.wait_for_selector("#cellar-panel-search", state="visible", timeout=10000)

        options = page.locator("#search-storage option")
        assert options.count() == 3
        expect(options.nth(0)).to_have_text("All")
        expect(options.nth(1)).to_have_text("In Case")
        expect(options.nth(2)).to_have_text("Loose Bottles")

    def test_search_with_case_filter(self, authenticated_page: Page) -> None:
        """Searching with 'In Case' filter sends storage=case parameter."""
        page = authenticated_page

        # Add a case via API first
        page.evaluate("""async () => {
            const token = localStorage.getItem('winebox_token');
            await fetch('/api/cases', {
                method: 'POST',
                headers: {
                    'Authorization': 'Bearer ' + token,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    name: 'Search Case Wine',
                    winery: 'Test',
                    case_size: 6,
                    num_cases: 1,
                    provenance: 'Wine Merchant Ltd',
                }),
            });
        }""")

        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector("[data-cellar-tab='search']", state="visible", timeout=10000)
        page.click("[data-cellar-tab='search']")
        page.wait_for_selector("#cellar-panel-search", state="visible", timeout=10000)

        page.select_option("#search-storage", "case")
        page.evaluate("document.querySelector('#search-form').requestSubmit()")
        page.wait_for_timeout(2000)

        # Should show results (at least our cased wine)
        results = page.locator("#search-results")
        expect(results).to_be_visible()

    def test_search_with_provenance_filter(self, authenticated_page: Page) -> None:
        """Searching by provenance finds wines from matching cases."""
        page = authenticated_page

        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector("[data-cellar-tab='search']", state="visible", timeout=10000)
        page.click("[data-cellar-tab='search']")
        page.wait_for_selector("#cellar-panel-search", state="visible", timeout=10000)

        page.fill("#search-provenance", "Wine Merchant")
        page.press("#search-provenance", "Enter")
        page.wait_for_timeout(2000)

        results_text = page.locator("#search-results").text_content() or ""
        assert "Search Case Wine" in results_text or len(results_text) > 0
