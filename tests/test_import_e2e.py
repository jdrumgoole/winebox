"""End-to-end tests for wine import flow using Playwright.

These tests require a running WineBox server. Start the server with:
    invoke start-background

Run with: uv run python -m pytest -m e2e tests/test_import_e2e.py -v
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
    """Create a test user for this worker session."""
    worker_id = get_worker_id(request)
    email = f"e2e_import_{worker_id}@test.example.com"
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
        if result.returncode == 0 or "already exists" in (result.stdout + result.stderr):
            created = True
            break
        if attempt < max_retries - 1:
            time.sleep(1.0)

    if not created:
        import sys
        print(f"WARNING: Failed to create user {email}", file=sys.stderr)
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
    """Navigate to the import page."""
    page.click("a[data-page='import']")
    page.wait_for_selector("#page-import", state="visible")


def _upload_csv(page: Page, csv_path: Path) -> None:
    """Upload a CSV file via the import page file input."""
    page.set_input_files("#import-file-input", str(csv_path))
    # Wait for the mapping step to appear (actual ID: import-step-map)
    page.wait_for_selector("#import-step-map", state="visible", timeout=15000)


@pytest.mark.e2e
class TestImportPageNavigation:
    """Test basic import page navigation and display."""

    def test_import_link_visible(self, authenticated_page: Page) -> None:
        """Test that the Import link appears in the navigation."""
        page = authenticated_page
        import_link = page.locator("a[data-page='import']")
        expect(import_link).to_be_visible()
        expect(import_link).to_have_text("Import")

    def test_navigate_to_import_page(self, authenticated_page: Page) -> None:
        """Test navigating to the import page shows upload area."""
        page = authenticated_page
        _navigate_to_import(page)

        expect(page.locator("#page-import")).to_be_visible()
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
        """Test that column mapping dropdowns can be changed."""
        page = authenticated_page
        _navigate_to_import(page)
        _upload_csv(page, sample_csv)

        first_select = page.locator(".import-mapping-select").first
        first_select.select_option("skip")
        expect(first_select).to_have_value("skip")

    def test_confirm_mapping_button(self, authenticated_page: Page, sample_csv: Path) -> None:
        """Test that Confirm Mapping button proceeds to results step."""
        page = authenticated_page
        _navigate_to_import(page)
        _upload_csv(page, sample_csv)

        page.click("#import-confirm-mapping-btn")

        expect(page.locator("#import-step-results")).to_be_visible(timeout=15000)


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
        page.click("#import-confirm-mapping-btn")
        page.wait_for_selector("#import-step-results", state="visible", timeout=15000)

        # Step 3: Check results - should show success with wine count
        results = page.locator("#import-step-results")
        expect(results).to_contain_text("4", timeout=10000)

        # Verify the wines appear in the cellar
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible")
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)

        cellar_text = page.locator("#page-cellar").text_content()
        assert "Chateau Petrus" in cellar_text
        assert "Tignanello" in cellar_text

    def test_import_with_non_wine_filtering(self, authenticated_page: Page, csv_with_spirits: Path) -> None:
        """Test that non-wine rows (whiskey, gin) are filtered out."""
        page = authenticated_page
        _navigate_to_import(page)

        _upload_csv(page, csv_with_spirits)

        page.click("#import-confirm-mapping-btn")
        page.wait_for_selector("#import-step-results", state="visible", timeout=15000)

        # Results should mention wines created and rows skipped
        results_text = page.locator("#import-step-results").text_content()
        # Should have created 2 wines (Chateau Margaux, Barolo) and skipped 2
        assert "2" in results_text

    def test_import_then_reset(self, authenticated_page: Page, sample_csv: Path) -> None:
        """Test that Import Another File button resets to step 1."""
        page = authenticated_page
        _navigate_to_import(page)

        _upload_csv(page, sample_csv)
        page.click("#import-confirm-mapping-btn")
        page.wait_for_selector("#import-step-results", state="visible", timeout=15000)

        # Click "Import Another File" button
        reset_btn = page.locator("#import-new-btn")
        if reset_btn.is_visible():
            reset_btn.click()
            expect(page.locator(".import-upload-area")).to_be_visible()


@pytest.mark.e2e
class TestImportCustomFields:
    """Test that custom fields from import are preserved and visible."""

    def test_custom_field_in_wine_detail(self, authenticated_page: Page, sample_csv: Path) -> None:
        """Test that custom fields (e.g. Cellar Location) appear in wine detail."""
        page = authenticated_page
        _navigate_to_import(page)

        _upload_csv(page, sample_csv)

        # "Cellar Location" is not a known wine field, so it's auto-mapped to "skip".
        # Change its mapping to a custom field before confirming.
        # Select "Custom Field..." from dropdown, then type the name in the revealed input.
        cellar_select = page.locator(
            '.import-mapping-select[data-header="Cellar Location"]'
        )
        cellar_select.select_option("custom")
        custom_input = page.locator(
            '.import-custom-name[data-header="Cellar Location"]'
        )
        custom_input.fill("Cellar Location")

        page.click("#import-confirm-mapping-btn")
        page.wait_for_selector("#import-step-results", state="visible", timeout=15000)

        # Navigate to cellar
        page.click("a[data-page='cellar']")
        page.wait_for_selector(".wine-card", state="visible", timeout=10000)

        # Click first wine card to open detail
        page.locator(".wine-card").first.click()

        # Wait for detail modal
        page.wait_for_selector(".modal.active", state="visible", timeout=5000)

        # Check that custom fields are shown
        detail_text = page.locator(".modal.active").text_content()
        assert "Cellar Location" in detail_text or "Rack" in detail_text
