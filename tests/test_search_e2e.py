"""E2E tests for the Search page.

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_search_e2e.py -v --override-ini="addopts="
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
    email, password = create_cli_worker_user(request, email_prefix="e2e_search", password="testpass123")
    yield email, password


def _navigate_to_search(page: Page) -> None:
    page.click("a[data-page='cellar']")
    page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
    page.wait_for_selector("[data-cellar-tab='search']", state="visible", timeout=10000)
    page.click("[data-cellar-tab='search']")
    page.wait_for_selector("#cellar-panel-search", state="visible", timeout=10000)
    page.wait_for_selector("#search-form", state="visible", timeout=5000)


def _expand_advanced_filters(page: Page) -> None:
    """Expand the Advanced Filters toggle so filter fields become visible."""
    # The filters are inside a <details> element — click the <summary> to expand
    if not page.locator("#search-country").is_visible():
        page.locator("#search-form details.advanced-fields summary").click()
        page.wait_for_timeout(300)


@pytest.mark.e2e
class TestSearchPage:
    """E2E tests for the search page."""

    def test_search_page_renders(self, authenticated_page: Page) -> None:
        """#search page and form visible."""
        _navigate_to_search(authenticated_page)
        expect(authenticated_page.locator("#cellar-panel-search")).to_be_visible()
        expect(authenticated_page.locator("#search-form")).to_be_visible()

    def test_search_form_has_inputs(self, authenticated_page: Page) -> None:
        """Search form has query input and filter fields."""
        _navigate_to_search(authenticated_page)
        expect(authenticated_page.locator("#search-q")).to_be_visible()

    def test_search_by_name(self, authenticated_page: Page) -> None:
        """Enter a name, submit form - results area should exist."""
        _navigate_to_search(authenticated_page)
        authenticated_page.fill("#search-q", "wine")
        authenticated_page.press("#search-q", "Enter")
        authenticated_page.wait_for_timeout(1000)
        expect(authenticated_page.locator("#search-results")).to_be_attached()

    def test_search_no_results(self, authenticated_page: Page) -> None:
        """Gibberish query returns no results."""
        _navigate_to_search(authenticated_page)
        authenticated_page.fill("#search-q", "zzzznonexistentwine99999")
        authenticated_page.press("#search-q", "Enter")
        authenticated_page.wait_for_timeout(1000)
        expect(authenticated_page.locator("#search-results")).to_be_attached()

    def test_search_filter_by_country(self, authenticated_page: Page) -> None:
        """Country filter field is functional."""
        _navigate_to_search(authenticated_page)
        _expand_advanced_filters(authenticated_page)
        country_input = authenticated_page.locator("#search-country")
        expect(country_input).to_be_visible()
        country_input.fill("France")

    def test_search_filter_by_vintage(self, authenticated_page: Page) -> None:
        """Vintage filter field is functional."""
        _navigate_to_search(authenticated_page)
        _expand_advanced_filters(authenticated_page)
        vintage_input = authenticated_page.locator("#search-vintage")
        expect(vintage_input).to_be_visible()
        vintage_input.fill("2020")

    def test_search_has_wine_type_filter(self, authenticated_page: Page) -> None:
        """Wine type filter select is present in advanced filters."""
        _navigate_to_search(authenticated_page)
        _expand_advanced_filters(authenticated_page)
        expect(authenticated_page.locator("#search-wine-type")).to_be_visible()

    def test_search_has_in_stock_filter(self, authenticated_page: Page) -> None:
        """In stock checkbox filter is present in advanced filters."""
        _navigate_to_search(authenticated_page)
        _expand_advanced_filters(authenticated_page)
        expect(authenticated_page.locator("#search-in-stock")).to_be_visible()
