"""End-to-end tests for X-Wines CSV import validation using Playwright.

Imports tests/data/xwines-test-data.csv (5000 rows of real wine data) and
validates that what the UI displays matches the actual CSV content.

These tests require a running WineBox server. Start the server with:
    uv run python -m invoke start-background

Run with:
    WINEBOX_USE_CLAUDE_VISION=false uv run python -m pytest -m e2e tests/test_import_xwines_e2e.py -v
"""

import csv
import os
import subprocess
import time
from pathlib import Path
from typing import Generator

import pytest
from playwright.sync_api import Page, expect

from .playwright_utils import (
    BASE_URL,
    create_cli_worker_user,
    login_via_ui,
    preflight_check,
)

# --- CSV column names from xwines-test-data.csv ---
XWINES_HEADERS = [
    "Parent ID",
    "Product Code(s)",
    "Country",
    "Region",
    "Vintage",
    "Description",
    "Colour",
    "Maturity",
    "Bottle Format",
    "Bottle Volume",
    "Quantity in Bottles",
    "Eligible for Sale on BBX",
    "Purchase Price per Case",
    "Case Size",
    "Livex Market Price",
    "Wine Searcher Lowest List Price",
    "BBX Last Transaction Price",
    "BBX Lowest Price",
    "BBX Highest Bid",
    "Selling Case Quantity on BBX",
    "Selling Price on BBX",
    "Pending Sale Case Quantity on BBX",
    "Account Payer",
    "Beneficial Owner",
    "Current Status",
    "Provenance",
    "Bottle Condition",
    "Packaging Condition",
    "Wine Condition",
    "Own Goods?",
]

# Columns that HEADER_ALIASES auto-maps
# Note: "Quantity in Bottles" normalizes to "quantity in bottles" which is NOT
# in HEADER_ALIASES (only "quantity", "qty", "bottles", "count" are), so it
# maps to "skip".
AUTO_MAPPED = {
    "Country": "country",
    "Region": "region",
    "Vintage": "vintage",
    "Description": "notes",
    "Colour": "wine_type_id",
}

# Columns expected to default to custom fields (not auto-mapped)
EXPECTED_CUSTOM = [
    "Parent ID",
    "Product Code(s)",
    "Maturity",
    "Bottle Format",
    "Bottle Volume",
    "Quantity in Bottles",
    "Eligible for Sale on BBX",
    "Purchase Price per Case",
    "Case Size",
    "Livex Market Price",
    "Wine Searcher Lowest List Price",
    "BBX Last Transaction Price",
    "BBX Lowest Price",
    "BBX Highest Bid",
    "Selling Case Quantity on BBX",
    "Selling Price on BBX",
    "Pending Sale Case Quantity on BBX",
    "Account Payer",
    "Beneficial Owner",
    "Current Status",
    "Provenance",
    "Bottle Condition",
    "Packaging Condition",
    "Wine Condition",
    "Own Goods?",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_worker_id(request: pytest.FixtureRequest) -> str:
    """Get the pytest-xdist worker ID, or 'main' if not running in parallel."""
    if hasattr(request.config, "workerinput"):
        return request.config.workerinput["workerid"]
    return "main"


def _load_csv_data(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Load headers and all rows from a CSV file."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        rows = list(reader)
    return headers, rows


def _navigate_to_import(page: Page) -> None:
    """Navigate to the import wizard via My Cellar → Import tab → Import from File card."""
    page.click("a[data-page='cellar']")
    page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
    page.click("[data-cellar-tab='import']")
    page.wait_for_selector("#cellar-panel-import", state="visible", timeout=10000)
    page.click("#cellar-welcome-panel .entry-path-card[data-tab='import']")
    page.wait_for_selector("#import-step-upload", state="visible", timeout=10000)


def _upload_file(page: Page, csv_path: Path, timeout_ms: int = 60000) -> None:
    """Upload a CSV file and wait for the mapping step (long timeout for large files)."""
    # Disable AI mapping to avoid slow API calls during E2E tests
    page.evaluate("document.getElementById('import-use-ai-mapping').checked = false")
    # Force the mapping step so auto-import doesn't skip it
    page.evaluate("document.getElementById('import-force-mapping').checked = true")
    page.set_input_files("#import-file-input", str(csv_path))
    # After upload, wait for any post-upload step (map, duplicate, or dashboard)
    page.evaluate("""(timeout) => new Promise((resolve, reject) => {
        const start = Date.now();
        const check = () => {
            const map = document.getElementById('import-step-map');
            const dup = document.getElementById('import-step-duplicate');
            const dash = document.getElementById('import-step-dashboard');
            if (map && map.style.display !== 'none') return resolve('map');
            if (dup && dup.style.display !== 'none') return resolve('duplicate');
            if (dash && dash.style.display !== 'none') return resolve('dashboard');
            if (Date.now() - start > timeout) return reject(new Error('No import step appeared'));
            requestAnimationFrame(check);
        };
        check();
    })""", timeout_ms)
    # If duplicate detected, click "Import again anyway" to proceed to mapping
    dup_btn = page.locator("#import-duplicate-reimport-btn")
    if dup_btn.is_visible():
        dup_btn.click()
    page.wait_for_selector("#import-step-map", state="visible", timeout=timeout_ms)


def _upload_and_remap(page: Page, csv_path: Path) -> None:
    """Upload file and remap Description from 'notes' to 'name'."""
    _upload_file(page, csv_path)
    # Remap Description → name (required for the import to have wine names)
    desc_select = page.locator('.import-mapping-select[data-header="Description"]')
    desc_select.select_option("name")
    expect(desc_select).to_have_value("name")


def _confirm_and_wait_for_import(page: Page, timeout_ms: int = 180000) -> None:
    """Click Confirm Mapping and wait for the import to complete.

    After confirming, the flow goes: progress → dashboard (or results as fallback).
    Uses a long timeout (180s default) for large CSV imports.
    """
    page.click("#import-confirm-mapping-btn")
    page.evaluate("""(timeout) => new Promise((resolve, reject) => {
        const start = Date.now();
        const check = () => {
            const dash = document.getElementById('import-step-dashboard');
            const results = document.getElementById('import-step-results');
            if (dash && dash.style.display !== 'none') return resolve('dashboard');
            if (results && results.style.display !== 'none') return resolve('results');
            if (Date.now() - start > timeout) return reject(new Error('Import did not complete'));
            requestAnimationFrame(check);
        };
        check();
    })""", timeout_ms)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _e2e_preflight() -> None:
    """Fail fast if the E2E server is not reachable."""
    preflight_check()


@pytest.fixture(scope="session")
def base_url() -> str:
    """Return the base URL for the test server."""
    return BASE_URL


@pytest.fixture(scope="session")
def xwines_csv_path() -> Path:
    """Return the path to the X-Wines test CSV."""
    path = Path(__file__).parent / "data" / "xwines-test-data.csv"
    assert path.exists(), f"X-Wines test CSV not found at {path}"
    return path


@pytest.fixture(scope="session")
def xwines_csv_data(xwines_csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Load X-Wines CSV data once per session."""
    return _load_csv_data(xwines_csv_path)


@pytest.fixture(scope="session")
def worker_user(
    request: pytest.FixtureRequest,
) -> Generator[tuple[str, str], None, None]:
    """Create a test user for this worker session."""
    email, password = create_cli_worker_user(
        request,
        email_prefix="e2e_xwines",
        password="testpass123",
    )
    yield email, password


@pytest.fixture(scope="function")
def test_user(worker_user: tuple[str, str]) -> tuple[str, str]:
    """Return the worker's test user credentials."""
    return worker_user


@pytest.fixture(scope="function")
def authenticated_page(page: Page, test_user: tuple[str, str]) -> Page:
    """Log in and return an authenticated page."""
    email, password = test_user
    login_via_ui(page, email=email, password=password)
    return page


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestXWinesImport:
    """Tests for importing the X-Wines 5000-row CSV and validating UI output."""

    def test_upload_shows_correct_headers(
        self,
        authenticated_page: Page,
        xwines_csv_path: Path,
        xwines_csv_data: tuple[list[str], list[dict[str, str]]],
    ) -> None:
        """Verify all 30 column headers appear in the mapping table."""
        page = authenticated_page
        headers, _ = xwines_csv_data

        _navigate_to_import(page)
        _upload_file(page, xwines_csv_path)

        # Verify file info shows 5000 rows
        file_info = page.locator("#import-file-info")
        expect(file_info).to_contain_text("5000")

        # Verify all 30 headers appear in the mapping table
        mapping_table = page.locator(".import-mapping-table")
        for header in headers:
            expect(mapping_table).to_contain_text(header)

    def test_upload_shows_correct_preview(
        self,
        authenticated_page: Page,
        xwines_csv_path: Path,
        xwines_csv_data: tuple[list[str], list[dict[str, str]]],
    ) -> None:
        """Verify the preview table contains values from the first rows of the CSV."""
        page = authenticated_page
        _, rows = xwines_csv_data

        _navigate_to_import(page)
        _upload_file(page, xwines_csv_path)

        preview = page.locator(".import-preview-table")
        expect(preview).to_be_visible()

        # Spot-check Description, Country, and Vintage from rows 0-2
        for i in range(3):
            row = rows[i]
            # Check country (short, unambiguous value)
            expect(preview).to_contain_text(row["Country"])
            # Check vintage
            expect(preview).to_contain_text(row["Vintage"])

    def test_auto_mapping_suggestions(
        self,
        authenticated_page: Page,
        xwines_csv_path: Path,
    ) -> None:
        """Verify auto-mapped dropdowns have the correct values."""
        page = authenticated_page

        _navigate_to_import(page)
        _upload_file(page, xwines_csv_path)

        # Check auto-mapped columns
        for header, expected_value in AUTO_MAPPED.items():
            select = page.locator(f'.import-mapping-select[data-header="{header}"]')
            expect(select).to_have_value(expected_value)

        # Check a sample of unmapped columns default to custom option in dropdown
        # Unmatched fields are added as custom:Name options and pre-selected
        for header in EXPECTED_CUSTOM[:5]:
            select = page.locator(f'.import-mapping-select[data-header="{header}"]')
            expect(select).to_have_value(f"custom:{header}")

    def test_full_import_and_cellar_validation(
        self,
        authenticated_page: Page,
        xwines_csv_path: Path,
        xwines_csv_data: tuple[list[str], list[dict[str, str]]],
    ) -> None:
        """Import all 5000 rows and validate against cellar display."""
        page = authenticated_page
        _, rows = xwines_csv_data

        # Build a set of Description values from the CSV for validation
        csv_descriptions = {row["Description"] for row in rows if row["Description"].strip()}

        _navigate_to_import(page)
        _upload_and_remap(page, xwines_csv_path)

        # Click confirm and wait for import to complete (180s for 5000 inserts)
        _confirm_and_wait_for_import(page)

        # Extract result statistics from dashboard or results step
        dash = page.locator("#import-step-dashboard")
        if dash.is_visible():
            # Wait for dashboard content to load (async API call populates stats)
            page.wait_for_selector(
                "#import-step-dashboard .stat-value", state="visible", timeout=30000
            )
            stat_values = page.locator("#import-step-dashboard .stat-value").all()
            assert len(stat_values) >= 2, "Expected at least 2 stat values in dashboard"
            # Dashboard: first stat is total bottles, second is unique wines (or cases if present)
            # Find the "Unique Wines" stat by label
            wines_created = 0
            for i, sv in enumerate(stat_values):
                parent = sv.locator("..")
                label = parent.locator(".stat-label").text_content() or ""
                if "Unique Wines" in label:
                    wines_created = int((sv.text_content() or "0").replace(",", ""))
                    break
            if wines_created == 0:
                # Fallback: second stat value (original layout without cases)
                wines_created = int((stat_values[1].text_content() or "0").replace(",", ""))
        else:
            stat_values = page.locator("#import-step-results .stat-value").all()
            assert len(stat_values) >= 2, "Expected at least 2 stat values in results"
            wines_created = int((stat_values[0].text_content() or "0").replace(",", ""))

        # Verify wines_created is close to 5000
        assert wines_created > 4500, (
            f"Expected > 4500 wines created, got {wines_created}"
        )

        # Navigate to cellar Search tab and verify imported wines
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible")
        page.click("[data-cellar-tab='search']")
        page.wait_for_selector("#cellar-panel-search", state="visible", timeout=5000)

        # Search for a known imported wine
        page.fill("#search-q", next(iter(csv_descriptions))[:30])
        page.press("#search-q", "Enter")
        page.wait_for_selector(".wine-card", state="visible", timeout=15000)

        wine_cards = page.locator(".wine-card").all()
        assert len(wine_cards) > 0, "No wine cards found in search results"

        # Spot-check wine detail modal
        page.locator(".wine-card").first.click()
        page.wait_for_selector(".modal.active", state="visible", timeout=5000)

        modal = page.locator(".modal.active")
        modal_text = modal.text_content() or ""

        # Get the first wine card's name for matching
        first_wine_name = (wine_cards[0].text_content() or "").strip()
        assert first_wine_name in modal_text, (
            f"Modal should contain wine name '{first_wine_name}'"
        )

        # Find matching CSV rows (same Description may appear with different vintages)
        matching_rows = [
            r for r in rows if r["Description"].strip() == first_wine_name
        ]
        if matching_rows:
            # Verify country appears (same across all rows with this Description)
            countries = {r["Country"] for r in matching_rows if r["Country"]}
            for country in countries:
                if country in modal_text:
                    break
            else:
                if countries:
                    assert False, (
                        f"Modal should contain one of countries {countries}"
                    )

            # Verify region appears
            regions = {r["Region"] for r in matching_rows if r["Region"]}
            for region in regions:
                if region in modal_text:
                    break
            else:
                if regions:
                    assert False, (
                        f"Modal should contain one of regions {regions}"
                    )

            # Verify vintage from modal matches at least one CSV row
            vintages = {r["Vintage"] for r in matching_rows if r["Vintage"]}
            found_vintage = any(v in modal_text for v in vintages)
            if vintages:
                assert found_vintage, (
                    f"Modal should contain one of vintages {vintages}"
                )

    def test_import_preserves_country_distribution(
        self,
        authenticated_page: Page,
        xwines_csv_path: Path,
        xwines_csv_data: tuple[list[str], list[dict[str, str]]],
    ) -> None:
        """Verify that imported wines span multiple distinct countries."""
        page = authenticated_page
        _, rows = xwines_csv_data

        # Count distinct countries in the CSV
        csv_countries = {row["Country"] for row in rows if row["Country"].strip()}

        _navigate_to_import(page)
        _upload_and_remap(page, xwines_csv_path)

        _confirm_and_wait_for_import(page)

        # Use the API to check imported wines (must use fetchWithAuth for auth)
        api_result = page.evaluate(
            """async () => {
                const resp = await fetchWithAuth('/api/wines?limit=200');
                const data = await resp.json();
                return data;
            }"""
        )

        # GET /api/wines returns list[WineWithInventory]
        wines = api_result if isinstance(api_result, list) else []
        api_countries = {
            w.get("country", "") for w in wines if w.get("country")
        }

        # The CSV has ~21 distinct countries; we should see many in the import
        assert len(api_countries) >= 5, (
            f"Expected at least 5 distinct countries, got {len(api_countries)}: {api_countries}"
        )
