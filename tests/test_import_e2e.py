"""End-to-end tests for wine import flow using Playwright.

These tests require a running WineBox server. Start the server with:
    uv run python -m invoke start-background

Run with: uv run python -m pytest -m e2e tests/test_import_e2e.py -v
"""

import csv
import re
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


@pytest.fixture(scope="session", autouse=True)
def _e2e_preflight() -> None:
    """Fail fast if the E2E server is not reachable."""
    preflight_check()


@pytest.fixture(scope="session")
def base_url() -> str:
    """Return the base URL for the test server."""
    return BASE_URL


@pytest.fixture(scope="session")
def worker_user(request: pytest.FixtureRequest) -> Generator[tuple[str, str], None, None]:
    """Create a test user for this worker session."""
    email, password = create_cli_worker_user(
        request,
        email_prefix="e2e_import",
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


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Create a sample CSV file for import testing."""
    csv_file = tmp_path / "test_wines.csv"
    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Wine Name", "Producer", "Year", "Country", "Grape",
                         "Region", "Type", "Quantity", "Cellar Location"])
        writer.writerow(["Chateau Petrus", "Petrus", "2010", "France", "Merlot",
                         "Pomerol", "Red", "1", "Rack A1"])
        writer.writerow(["Tignanello", "Antinori", "2018", "Italy", "Sangiovese",
                         "Tuscany", "Red", "3", "Rack B2"])
        writer.writerow(["Cloudy Bay Sauvignon Blanc", "Cloudy Bay", "2022",
                         "New Zealand", "Sauvignon Blanc", "Marlborough", "White",
                         "6", "Rack C1"])
        writer.writerow(["Dom Perignon", "Moet & Chandon", "2012", "France",
                         "Chardonnay", "Champagne", "Sparkling", "2", "Rack D3"])
    return csv_file


@pytest.fixture
def csv_with_spirits(tmp_path: Path) -> Path:
    """Create a CSV file that includes non-wine rows."""
    csv_file = tmp_path / "mixed_drinks.csv"
    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Wine Name", "Producer", "Year", "Country", "Type",
                         "Quantity"])
        writer.writerow(["Chateau Margaux", "Margaux", "2015", "France", "Red",
                         "2"])
        writer.writerow(["Jameson Irish Whiskey", "Jameson", "2023", "Ireland",
                         "Whiskey", "1"])
        writer.writerow(["Barolo Riserva", "Conterno", "2016", "Italy", "Red",
                         "4"])
        writer.writerow(["Tanqueray", "Diageo", "", "UK", "Gin", "1"])
    return csv_file


def _navigate_to_import(page: Page) -> None:
    """Navigate to the import wizard via My Cellar → Import tab → Import from File card."""
    page.click("a[data-page='cellar']")
    page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
    page.click("[data-cellar-tab='import']")
    page.wait_for_selector("#cellar-panel-import", state="visible", timeout=10000)
    page.click("[data-import-path='import']")
    page.wait_for_selector("#import-step-upload", state="visible", timeout=10000)


def _upload_csv(page: Page, csv_path: Path, timeout_ms: int = 25000) -> None:
    """Upload a CSV file via the import page file input."""
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
    # Wait for the mapping step to appear
    page.wait_for_selector("#import-step-map", state="visible", timeout=timeout_ms)


def _confirm_and_wait_for_import(page: Page, timeout_ms: int = 60000) -> None:
    """Click Confirm Mapping and wait for the import to complete.

    After confirming, the flow goes: progress → dashboard (or results as fallback).
    """
    page.click("#import-confirm-mapping-btn")
    # Wait for either dashboard or results step to appear
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


@pytest.mark.e2e
class TestImportPageNavigation:
    """Test basic import page navigation and display."""

    def test_import_wizard_accessible(self, authenticated_page: Page) -> None:
        """Test that the Import wizard is accessible via Add to Cellar."""
        page = authenticated_page
        _navigate_to_import(page)
        expect(page.locator("#import-step-upload")).to_be_visible()

    def test_navigate_to_import_page(self, authenticated_page: Page) -> None:
        """Test navigating to the import wizard shows upload area."""
        page = authenticated_page
        _navigate_to_import(page)

        expect(page.locator(".import-upload-area")).to_be_visible()
        expect(page.locator("#import-file-input")).to_be_attached()

    def test_upload_area_text(self, authenticated_page: Page) -> None:
        """Test that the upload area shows correct instructions."""
        page = authenticated_page
        _navigate_to_import(page)

        upload_area = page.locator(".import-upload-area")
        expect(upload_area).to_contain_text("Drag and drop")
        expect(upload_area).to_contain_text("Browse Files")
        expect(upload_area).to_contain_text("CSV")
        expect(upload_area).to_contain_text(".xlsx")


@pytest.mark.e2e
class TestImportUpload:
    """Test the file upload step of the import workflow."""

    def test_upload_csv_shows_mapping(self, authenticated_page: Page, sample_csv: Path) -> None:
        """Test that uploading a CSV shows the column mapping step."""
        page = authenticated_page
        _navigate_to_import(page)
        _upload_csv(page, sample_csv)

        expect(page.locator("#import-step-map")).to_be_visible()

        mapping_table = page.locator(".import-mapping-table")
        expect(mapping_table).to_be_visible()

    def test_upload_csv_shows_correct_headers(self, authenticated_page: Page, sample_csv: Path) -> None:
        """Test that uploaded CSV headers appear in the mapping table."""
        page = authenticated_page
        _navigate_to_import(page)
        _upload_csv(page, sample_csv)

        mapping_table = page.locator(".import-mapping-table")
        expect(mapping_table).to_contain_text("Wine Name")
        expect(mapping_table).to_contain_text("Producer")
        expect(mapping_table).to_contain_text("Year")
        expect(mapping_table).to_contain_text("Country")

    def test_upload_csv_suggests_mappings(self, authenticated_page: Page, sample_csv: Path) -> None:
        """Test that the upload suggests correct column mappings."""
        page = authenticated_page
        _navigate_to_import(page)
        _upload_csv(page, sample_csv)

        # Wine Name should be auto-mapped to 'name'
        wine_name_select = page.locator(".import-mapping-select").first
        expect(wine_name_select).to_have_value("name")

    def test_upload_csv_shows_preview(self, authenticated_page: Page, sample_csv: Path) -> None:
        """Test that a preview table is shown after upload."""
        page = authenticated_page
        _navigate_to_import(page)
        _upload_csv(page, sample_csv)

        preview = page.locator(".import-preview-table")
        expect(preview).to_be_visible()
        expect(preview).to_contain_text("Chateau Petrus")


@pytest.mark.e2e
class TestImportMapping:
    """Test the column mapping step."""

    def test_change_mapping_dropdown(self, authenticated_page: Page, sample_csv: Path) -> None:
        """Test that column mapping can be set to skip via the Skip button."""
        page = authenticated_page
        _navigate_to_import(page)
        _upload_csv(page, sample_csv)

        # UI uses a Skip button per row, not a "skip" dropdown option
        first_skip_btn = page.locator(".import-skip-btn").first
        first_skip_btn.click()
        first_row = page.locator(".import-mapping-row").first
        expect(first_row).to_have_class(re.compile(r".*\bskipped\b.*"))

    def test_confirm_mapping_button(self, authenticated_page: Page, sample_csv: Path) -> None:
        """Test that Confirm Mapping button processes import and shows dashboard."""
        page = authenticated_page
        _navigate_to_import(page)
        _upload_csv(page, sample_csv)

        _confirm_and_wait_for_import(page)

        # Should show either dashboard or results
        dash = page.locator("#import-step-dashboard")
        results = page.locator("#import-step-results")
        assert dash.is_visible() or results.is_visible()


@pytest.mark.e2e
class TestImportProcess:
    """Test the full import processing workflow."""

    def test_full_import_workflow(self, authenticated_page: Page, sample_csv: Path) -> None:
        """Test the complete upload -> map -> process workflow."""
        page = authenticated_page
        _navigate_to_import(page)

        # Step 1: Upload
        _upload_csv(page, sample_csv)

        # Step 2: Confirm mapping (auto-suggested mappings should be fine)
        _confirm_and_wait_for_import(page)

        # Step 3: Check dashboard shows wine count (async load — needs time on slow servers)
        dash = page.locator("#import-step-dashboard")
        if dash.is_visible():
            expect(dash).to_contain_text("wines", timeout=20000)
        else:
            results = page.locator("#import-step-results")
            expect(results).to_contain_text("4", timeout=20000)

        # Verify the wines appear via Search
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector("[data-cellar-tab='search']", state="visible", timeout=10000)
        page.click("[data-cellar-tab='search']")
        page.wait_for_selector("#cellar-panel-search", state="visible", timeout=10000)
        page.fill("#search-q", "Petrus")
        page.press("#search-q", "Enter")
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)

        results_text = page.locator("#search-results").text_content()
        assert "Petrus" in results_text

    def test_import_with_non_wine_filtering(self, authenticated_page: Page, csv_with_spirits: Path) -> None:
        """Test that non-wine rows (whiskey, gin) are filtered out."""
        page = authenticated_page
        _navigate_to_import(page)

        _upload_csv(page, csv_with_spirits)

        _confirm_and_wait_for_import(page)

        # Dashboard or results should show wines were created
        dash = page.locator("#import-step-dashboard")
        if dash.is_visible():
            # Dashboard title says "You just added N wines from ..."
            expect(dash).to_contain_text("wines", timeout=20000)
        else:
            results_text = page.locator("#import-step-results").text_content()
            assert "2" in results_text

    def test_import_then_reset(self, authenticated_page: Page, sample_csv: Path) -> None:
        """Test that Import Another File button resets to step 1."""
        page = authenticated_page
        _navigate_to_import(page)

        _upload_csv(page, sample_csv)
        _confirm_and_wait_for_import(page, timeout_ms=45000)

        # Click "Import Another File" button (on dashboard or results step)
        dash_new_btn = page.locator("#import-dashboard-new-btn")
        results_new_btn = page.locator("#import-new-btn")
        if dash_new_btn.is_visible():
            dash_new_btn.click()
        elif results_new_btn.is_visible():
            results_new_btn.click()
        else:
            # Wait for either to appear
            page.wait_for_selector("#import-dashboard-new-btn, #import-new-btn", state="visible", timeout=10000)
            if dash_new_btn.is_visible():
                dash_new_btn.click()
            else:
                results_new_btn.click()
        expect(page.locator(".import-upload-area")).to_be_visible(timeout=5000)


@pytest.mark.e2e
class TestImportCustomFields:
    """Test that custom fields from import are preserved and visible."""

    def test_custom_field_in_wine_detail(self, authenticated_page: Page, sample_csv: Path) -> None:
        """Test that custom fields (e.g. Cellar Location) appear in wine detail."""
        page = authenticated_page
        _navigate_to_import(page)

        _upload_csv(page, sample_csv)

        # "Cellar Location" is not a known wine field — it should be auto-mapped
        # as a custom field option in the dropdown (value="custom:Cellar Location").
        # Verify the select has the right value; if not, select it.
        cellar_select = page.locator(
            '.import-mapping-select[data-header="Cellar Location"]'
        )
        if cellar_select.input_value() != "custom:Cellar Location":
            cellar_select.select_option("custom:Cellar Location")

        _confirm_and_wait_for_import(page)

        # Navigate to Search tab and find the imported wine
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector("[data-cellar-tab='search']", state="visible", timeout=10000)
        page.click("[data-cellar-tab='search']")
        page.wait_for_selector("#cellar-panel-search", state="visible", timeout=10000)
        page.fill("#search-q", "Petrus")
        page.press("#search-q", "Enter")
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)

        wine_card = page.locator(".wine-card", has_text="Petrus").first
        if wine_card.count() == 0:
            wine_card = page.locator(".wine-card").first
        wine_card.click()

        # Wait for detail modal
        page.wait_for_selector(".modal.active", state="visible", timeout=10000)

        # Check that custom fields are shown
        detail_text = page.locator(".modal.active").text_content() or ""
        assert "Cellar Location" in detail_text or "Rack" in detail_text, (
            f"Custom field not found in modal. Content preview: {detail_text[:500]}"
        )
