"""End-to-end tests for X-Wines CSV import validation using Playwright.

Imports tests/data/xwines-test-data.csv (5000 rows of real wine data) and
validates that what the UI displays matches the actual CSV content.

These tests require a running WineBox server. Start the server with:
    invoke start-background

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

# Server URL - can be overridden with WINEBOX_TEST_URL env var
BASE_URL = os.environ.get("WINEBOX_TEST_URL", "http://localhost:8000")

# Project directory for running CLI commands
PROJECT_DIR = Path(__file__).parent.parent

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

# Columns expected to default to "skip"
EXPECTED_SKIP = [
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
    """Navigate to the import page."""
    page.click("a[data-page='import']")
    page.wait_for_selector("#page-import", state="visible")


def _upload_file(page: Page, csv_path: Path) -> None:
    """Upload a CSV file and wait for the mapping step."""
    page.set_input_files("#import-file-input", str(csv_path))
    page.wait_for_selector("#import-step-map", state="visible", timeout=30000)


def _upload_and_remap(page: Page, csv_path: Path) -> None:
    """Upload file and remap Description from 'notes' to 'name'."""
    _upload_file(page, csv_path)
    # Remap Description → name (required for the import to have wine names)
    desc_select = page.locator('.import-mapping-select[data-header="Description"]')
    desc_select.select_option("name")
    expect(desc_select).to_have_value("name")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    worker_id = _get_worker_id(request)
    email = f"e2e_xwines_{worker_id}@test.example.com"
    password = "testpass123"

    max_retries = 3
    created = False
    result = None
    for attempt in range(max_retries):
        result = subprocess.run(
            ["uv", "run", "winebox-admin", "add", email, "--password", password],
            cwd=PROJECT_DIR,
            capture_output=True,
            timeout=30,
            text=True,
        )
        combined_output = result.stdout + result.stderr
        if result.returncode == 0 or "already exists" in combined_output or "already in use" in combined_output:
            created = True
            break
        if attempt < max_retries - 1:
            time.sleep(1.0)

    if not created:
        import sys

        print(f"WARNING: Failed to create user {email}", file=sys.stderr)
        if result:
            print(f"  stdout: {result.stdout}", file=sys.stderr)
            print(f"  stderr: {result.stderr}", file=sys.stderr)

    time.sleep(0.5)
    yield email, password


@pytest.fixture(scope="function")
def test_user(worker_user: tuple[str, str]) -> tuple[str, str]:
    """Return the worker's test user credentials."""
    return worker_user


@pytest.fixture(scope="function")
def authenticated_page(page: Page, test_user: tuple[str, str]) -> Page:
    """Log in and return an authenticated page."""
    email, password = test_user

    page.context.clear_cookies()
    page.goto(BASE_URL)
    page.evaluate("localStorage.clear()")
    page.reload()

    page.wait_for_selector("#login-form", state="visible", timeout=10000)
    page.fill("#login-email", email)
    page.fill("#login-password", password)
    page.click("#login-form button[type='submit']")

    try:
        page.wait_for_selector("#main-content", state="visible", timeout=15000)
    except Exception:
        error_elem = page.locator("#login-error")
        if error_elem.is_visible():
            error_text = error_elem.text_content()
            raise AssertionError(f"Login failed for user '{email}': {error_text}")
        raise

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

        # Check a sample of unmapped columns default to "skip"
        for header in EXPECTED_SKIP[:5]:
            select = page.locator(f'.import-mapping-select[data-header="{header}"]')
            expect(select).to_have_value("skip")

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

        # Click confirm and wait for results (180s for 5000 inserts)
        page.click("#import-confirm-mapping-btn")
        page.wait_for_selector(
            "#import-step-results", state="visible", timeout=180000
        )

        # Extract result statistics (scoped to results step to avoid dashboard stats)
        stat_values = page.locator("#import-step-results .stat-value").all()
        assert len(stat_values) >= 2, "Expected at least 2 stat values in results"

        wines_created_text = stat_values[0].text_content() or "0"
        rows_skipped_text = stat_values[1].text_content() or "0"
        wines_created = int(wines_created_text.replace(",", ""))
        rows_skipped = int(rows_skipped_text.replace(",", ""))

        # Verify wines_created is close to 5000
        assert wines_created > 4500, (
            f"Expected > 4500 wines created, got {wines_created}"
        )
        # Verify total approximately equals 5000
        total = wines_created + rows_skipped
        assert abs(total - 5000) <= 50, (
            f"Expected wines_created + rows_skipped ~= 5000, got {total}"
        )

        # Navigate to cellar
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible")
        page.wait_for_selector(".wine-card", state="visible", timeout=15000)

        # Collect displayed wine card titles
        wine_cards = page.locator(".wine-card-title").all()
        assert len(wine_cards) > 0, "No wine cards found in cellar"

        # Verify each displayed wine name exists in the CSV descriptions
        for card in wine_cards[:20]:  # Check first 20 cards
            card_name = (card.text_content() or "").strip()
            assert card_name in csv_descriptions, (
                f"Wine card title '{card_name}' not found in CSV Description column"
            )

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

        page.click("#import-confirm-mapping-btn")
        page.wait_for_selector(
            "#import-step-results", state="visible", timeout=180000
        )

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
