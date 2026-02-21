"""End-to-end tests for X-Wines search tab using Playwright.

These tests require:
1. A running WineBox server: invoke start-background
2. X-Wines test data imported: uv run python deploy/import_xwines_mongo.py --version test --force

For parallel execution: pytest -n auto tests/test_xwines_e2e.py
"""

import json
import os
import uuid
from typing import Generator
from urllib.request import urlopen, Request

import pytest
from playwright.sync_api import Page, expect
from pymongo import MongoClient

# Server URL - can be overridden with WINEBOX_TEST_URL env var
BASE_URL = os.environ.get("WINEBOX_TEST_URL", "http://localhost:8000")

# MongoDB URL for verifying test users
TEST_MONGODB_URL = os.environ.get("TEST_MONGODB_URL", "mongodb://localhost:27017")


def get_worker_id(request: pytest.FixtureRequest) -> str:
    """Get the pytest-xdist worker ID, or 'main' if not running in parallel."""
    if hasattr(request.config, "workerinput"):
        return request.config.workerinput["workerid"]
    return "main"


@pytest.fixture(scope="session")
def base_url() -> str:
    """Return the base URL for the test server."""
    return BASE_URL


@pytest.fixture(scope="session")
def worker_user(request: pytest.FixtureRequest) -> Generator[tuple[str, str], None, None]:
    """Create a test user for this worker session via the registration API.

    Registers the user via HTTP, then marks them as verified in MongoDB
    so they can log in (email verification is required by default).

    Returns (email, password) tuple.
    """
    import sys

    worker_id = get_worker_id(request)
    unique = uuid.uuid4().hex[:6]
    email = f"e2e_xwines_{worker_id}_{unique}@test.example.com"
    password = "TestPass1234"

    # Register via the HTTP API
    try:
        payload = json.dumps({
            "email": email,
            "password": password,
        }).encode()
        req = Request(
            f"{BASE_URL}/api/auth/register",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        print(f"WARNING: Failed to register user {email}: {e}", file=sys.stderr)

    # Mark user as verified in MongoDB so login works
    try:
        client: MongoClient = MongoClient(TEST_MONGODB_URL)
        db = client["winebox"]
        result = db.users.update_one(
            {"email": email},
            {"$set": {"is_verified": True}},
        )
        if result.modified_count == 0:
            print(f"WARNING: Could not verify user {email}", file=sys.stderr)
        client.close()
    except Exception as e:
        print(f"WARNING: Failed to verify user {email}: {e}", file=sys.stderr)

    yield email, password


@pytest.fixture(scope="function")
def test_user(worker_user: tuple[str, str]) -> tuple[str, str]:
    """Return the worker's test user credentials."""
    return worker_user


@pytest.fixture(scope="session")
def auth_token(worker_user: tuple[str, str]) -> str:
    """Get an auth token via the API once per session.

    This avoids hitting the login rate limit (5/minute) by only
    authenticating once and reusing the token across all tests.
    """
    import urllib.parse

    email, password = worker_user
    form_data = urllib.parse.urlencode({
        "username": email,
        "password": password,
    }).encode()
    req = Request(
        f"{BASE_URL}/api/auth/token",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return data["access_token"]


@pytest.fixture(scope="function")
def authenticated_page(page: Page, auth_token: str) -> Page:
    """Set the auth token in localStorage and navigate to the app."""
    page.goto(BASE_URL)
    page.evaluate(f"localStorage.setItem('winebox_token', '{auth_token}')")
    page.reload()

    page.wait_for_selector("#main-content", state="visible", timeout=15000)
    return page


@pytest.mark.e2e
class TestXWinesNavigation:
    """Test X-Wines tab navigation and page structure."""

    def test_xwines_nav_link_visible(self, authenticated_page: Page) -> None:
        """Test that the X-Wines nav link is visible after login."""
        page = authenticated_page
        nav_link = page.locator("a[data-page='xwines']")
        expect(nav_link).to_be_visible()
        expect(nav_link).to_have_text("X-Wines")

    def test_navigate_to_xwines_tab(self, authenticated_page: Page) -> None:
        """Test navigating to the X-Wines tab."""
        page = authenticated_page
        page.click("a[data-page='xwines']")

        expect(page.locator("#page-xwines")).to_be_visible()
        expect(page.locator("#xwines-search-form")).to_be_visible()

    def test_xwines_page_has_search_form(self, authenticated_page: Page) -> None:
        """Test that the X-Wines page has all form elements."""
        page = authenticated_page
        page.click("a[data-page='xwines']")
        page.wait_for_selector("#page-xwines", state="visible")

        # Search input
        expect(page.locator("#xwines-q")).to_be_visible()

        # Dropdowns
        expect(page.locator("#xwines-type")).to_be_visible()
        expect(page.locator("#xwines-country")).to_be_visible()
        expect(page.locator("#xwines-limit")).to_be_visible()

        # Buttons
        expect(page.locator("#xwines-search-form button[type='submit']")).to_be_visible()
        expect(page.locator("#xwines-search-form button[type='reset']")).to_be_visible()

    def test_xwines_dropdowns_populated(self, authenticated_page: Page) -> None:
        """Test that wine type and country dropdowns are populated from the API."""
        page = authenticated_page
        page.click("a[data-page='xwines']")
        page.wait_for_selector("#page-xwines", state="visible")

        # Wait for filters to load (they're fetched asynchronously)
        page.wait_for_timeout(2000)

        # Wine type dropdown should have options beyond the default "All Types"
        type_options = page.locator("#xwines-type option").count()
        assert type_options > 1, f"Expected wine type options, got {type_options}"

        # Country dropdown should have options beyond the default "All Countries"
        country_options = page.locator("#xwines-country option").count()
        assert country_options > 1, f"Expected country options, got {country_options}"


@pytest.mark.e2e
class TestXWinesSearch:
    """Test X-Wines search functionality."""

    def test_search_returns_results(self, authenticated_page: Page) -> None:
        """Test that searching returns wine results."""
        page = authenticated_page
        page.click("a[data-page='xwines']")
        page.wait_for_selector("#page-xwines", state="visible")

        # Search for a common wine term
        page.fill("#xwines-q", "wine")
        page.click("#xwines-search-form button[type='submit']")

        # Wait for results to appear
        page.wait_for_selector(".xwines-card", state="visible", timeout=10000)

        # Should have at least one result card
        cards = page.locator(".xwines-card")
        assert cards.count() > 0, "Expected search results"

    def test_search_shows_result_count(self, authenticated_page: Page) -> None:
        """Test that search displays a result count header."""
        page = authenticated_page
        page.click("a[data-page='xwines']")
        page.wait_for_selector("#page-xwines", state="visible")

        page.fill("#xwines-q", "wine")
        page.click("#xwines-search-form button[type='submit']")

        # Wait for results
        page.wait_for_selector(".xwines-results-header", state="visible", timeout=10000)
        header = page.locator(".xwines-results-header")
        header_text = header.text_content() or ""
        assert "result" in header_text.lower(), f"Expected result count, got: {header_text}"

    def test_search_no_results(self, authenticated_page: Page) -> None:
        """Test search with a term that should match nothing."""
        page = authenticated_page
        page.click("a[data-page='xwines']")
        page.wait_for_selector("#page-xwines", state="visible")

        page.fill("#xwines-q", "xyznonexistentwine123")
        page.click("#xwines-search-form button[type='submit']")

        # Wait for the search to complete
        page.wait_for_timeout(2000)

        # Should show no result cards
        cards = page.locator(".xwines-card")
        assert cards.count() == 0, "Expected no results for nonsense query"

    def test_search_requires_minimum_query(self, authenticated_page: Page) -> None:
        """Test that search requires at least 2 characters."""
        page = authenticated_page
        page.click("a[data-page='xwines']")
        page.wait_for_selector("#page-xwines", state="visible")

        # Try to search with a single character
        page.fill("#xwines-q", "a")
        page.click("#xwines-search-form button[type='submit']")

        # Form validation should prevent submission (minlength=2)
        is_valid = page.evaluate(
            "document.getElementById('xwines-q').checkValidity()"
        )
        assert not is_valid, "Search input should be invalid with single character"

    def test_search_with_type_filter(self, authenticated_page: Page) -> None:
        """Test searching with a wine type filter."""
        page = authenticated_page
        page.click("a[data-page='xwines']")
        page.wait_for_selector("#page-xwines", state="visible")
        page.wait_for_timeout(2000)  # Wait for filters to load

        # Select "Red" type filter
        page.select_option("#xwines-type", label="Red")

        # Search
        page.fill("#xwines-q", "wine")
        page.click("#xwines-search-form button[type='submit']")

        # Wait for results
        page.wait_for_selector(".xwines-card", state="visible", timeout=10000)

        # All visible type tags should say "Red"
        type_tags = page.locator(".xwines-type-tag")
        for i in range(type_tags.count()):
            tag_text = type_tags.nth(i).text_content() or ""
            assert tag_text.strip() == "Red", f"Expected 'Red' type, got '{tag_text}'"

    def test_search_with_country_filter(self, authenticated_page: Page) -> None:
        """Test searching with a country filter."""
        page = authenticated_page
        page.click("a[data-page='xwines']")
        page.wait_for_selector("#page-xwines", state="visible")
        page.wait_for_timeout(2000)  # Wait for filters to load

        # Get the first real country option (not "All Countries")
        first_country = page.evaluate("""
            (() => {
                const opts = document.querySelectorAll('#xwines-country option');
                for (const opt of opts) {
                    if (opt.value) return opt.textContent;
                }
                return null;
            })()
        """)

        if not first_country:
            pytest.skip("No country options available in dropdown")

        # Select the first country
        page.select_option("#xwines-country", index=1)

        page.fill("#xwines-q", "wine")
        page.click("#xwines-search-form button[type='submit']")

        # Wait for results or timeout
        page.wait_for_timeout(3000)

        # Results should appear (or none if that country has no matching wines)
        # Just verify no error occurred - the request completed
        results_container = page.locator("#xwines-results")
        expect(results_container).to_be_visible()

    def test_search_limit_selector(self, authenticated_page: Page) -> None:
        """Test that the results limit selector works."""
        page = authenticated_page
        page.click("a[data-page='xwines']")
        page.wait_for_selector("#page-xwines", state="visible")

        # Set limit to 10
        page.select_option("#xwines-limit", "10")

        page.fill("#xwines-q", "wine")
        page.click("#xwines-search-form button[type='submit']")

        page.wait_for_selector(".xwines-card", state="visible", timeout=10000)

        cards = page.locator(".xwines-card")
        assert cards.count() <= 10, f"Expected at most 10 results, got {cards.count()}"

    def test_form_reset(self, authenticated_page: Page) -> None:
        """Test that the reset button clears the form."""
        page = authenticated_page
        page.click("a[data-page='xwines']")
        page.wait_for_selector("#page-xwines", state="visible")

        # Fill in some values
        page.fill("#xwines-q", "test query")
        page.wait_for_timeout(1000)  # Wait for filters
        page.select_option("#xwines-limit", "50")

        # Click reset
        page.click("#xwines-search-form button[type='reset']")
        page.wait_for_timeout(500)

        # Search input should be cleared
        q_value = page.evaluate("document.getElementById('xwines-q').value")
        assert q_value == "", f"Expected empty search input, got '{q_value}'"


@pytest.mark.e2e
class TestXWinesDetailModal:
    """Test X-Wines wine detail modal."""

    def _search_and_get_results(self, page: Page) -> None:
        """Helper: navigate to X-Wines, search, and wait for results."""
        page.click("a[data-page='xwines']")
        page.wait_for_selector("#page-xwines", state="visible")

        page.fill("#xwines-q", "wine")
        page.click("#xwines-search-form button[type='submit']")
        page.wait_for_selector(".xwines-card", state="visible", timeout=10000)

    def test_click_card_opens_detail_modal(self, authenticated_page: Page) -> None:
        """Test that clicking a wine card opens the detail modal."""
        page = authenticated_page
        self._search_and_get_results(page)

        # Click the first result card
        page.locator(".xwines-card").first.click()

        # Detail modal should appear
        page.wait_for_selector("#xwines-modal.active", state="visible", timeout=5000)
        expect(page.locator("#xwines-detail")).to_be_visible()

    def test_detail_modal_shows_wine_info(self, authenticated_page: Page) -> None:
        """Test that the detail modal displays wine information."""
        page = authenticated_page
        self._search_and_get_results(page)

        page.locator(".xwines-card").first.click()
        page.wait_for_selector("#xwines-modal.active", state="visible", timeout=5000)

        detail = page.locator("#xwines-detail")
        detail_text = detail.text_content() or ""

        # Should contain some wine details (name at minimum)
        assert len(detail_text.strip()) > 0, "Detail modal should have content"

        # Should have detail header with wine name
        expect(page.locator(".xwines-detail-header").first).to_be_visible()

    def test_close_detail_modal_with_x(self, authenticated_page: Page) -> None:
        """Test closing the detail modal with the X button."""
        page = authenticated_page
        self._search_and_get_results(page)

        # Open modal
        page.locator(".xwines-card").first.click()
        page.wait_for_selector("#xwines-modal.active", state="visible", timeout=5000)

        # Click close button
        page.locator("#xwines-modal .modal-close").click()

        # Modal should close
        expect(page.locator("#xwines-modal")).not_to_have_class("active")

    def test_close_detail_modal_with_backdrop(self, authenticated_page: Page) -> None:
        """Test closing the detail modal by clicking the backdrop."""
        page = authenticated_page
        self._search_and_get_results(page)

        # Open modal
        page.locator(".xwines-card").first.click()
        page.wait_for_selector("#xwines-modal.active", state="visible", timeout=5000)

        # Click the modal backdrop (the outer .modal element, not .modal-content)
        page.locator("#xwines-modal").click(position={"x": 10, "y": 10})

        # Modal should close
        page.wait_for_timeout(500)
        expect(page.locator("#xwines-modal")).not_to_have_class("active")

    def test_detail_modal_has_type_tag(self, authenticated_page: Page) -> None:
        """Test that the detail modal displays a wine type tag."""
        page = authenticated_page
        self._search_and_get_results(page)

        page.locator(".xwines-card").first.click()
        page.wait_for_selector("#xwines-modal.active", state="visible", timeout=5000)

        # Should show wine type tag in detail
        type_tag = page.locator("#xwines-detail .xwines-type-tag")
        expect(type_tag.first).to_be_visible()


@pytest.mark.e2e
class TestXWinesCardContent:
    """Test X-Wines result card content."""

    def test_card_shows_wine_name(self, authenticated_page: Page) -> None:
        """Test that result cards show the wine name."""
        page = authenticated_page
        page.click("a[data-page='xwines']")
        page.wait_for_selector("#page-xwines", state="visible")

        page.fill("#xwines-q", "wine")
        page.click("#xwines-search-form button[type='submit']")
        page.wait_for_selector(".xwines-card", state="visible", timeout=10000)

        # First card should have a title
        title = page.locator(".xwines-card-title").first
        expect(title).to_be_visible()
        title_text = title.text_content() or ""
        assert len(title_text.strip()) > 0, "Card should show wine name"

    def test_card_shows_type_tag(self, authenticated_page: Page) -> None:
        """Test that result cards show a wine type tag."""
        page = authenticated_page
        page.click("a[data-page='xwines']")
        page.wait_for_selector("#page-xwines", state="visible")

        page.fill("#xwines-q", "wine")
        page.click("#xwines-search-form button[type='submit']")
        page.wait_for_selector(".xwines-card", state="visible", timeout=10000)

        type_tag = page.locator(".xwines-type-tag").first
        expect(type_tag).to_be_visible()
        tag_text = type_tag.text_content() or ""
        assert len(tag_text.strip()) > 0, "Card should show wine type"


@pytest.mark.e2e
class TestXWinesDoesNotBreakExisting:
    """Verify the X-Wines tab doesn't break existing functionality."""

    def test_search_tab_still_works(self, authenticated_page: Page) -> None:
        """Test that the existing Search tab still works after adding X-Wines."""
        page = authenticated_page

        # Navigate to Search tab
        page.click("a[data-page='search']")
        expect(page.locator("#page-search")).to_be_visible()

        # Then navigate to X-Wines
        page.click("a[data-page='xwines']")
        expect(page.locator("#page-xwines")).to_be_visible()

        # And back to Search
        page.click("a[data-page='search']")
        expect(page.locator("#page-search")).to_be_visible()

    def test_cellar_tab_still_works(self, authenticated_page: Page) -> None:
        """Test that the Cellar tab still works."""
        page = authenticated_page

        # Navigate to X-Wines first
        page.click("a[data-page='xwines']")
        expect(page.locator("#page-xwines")).to_be_visible()

        # Navigate to Cellar
        page.click("a[data-page='cellar']")
        expect(page.locator("#page-cellar")).to_be_visible()
