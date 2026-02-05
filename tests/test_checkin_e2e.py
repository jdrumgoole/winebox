"""End-to-end tests for wine checkin flow using Playwright.

These tests require a running WineBox server. Start the server with:
    invoke start-background

Note: These tests use real wine label images and will call the configured
OCR/Vision API if WINEBOX_ANTHROPIC_API_KEY is set.

For parallel execution, run with: pytest -n auto tests/test_checkin_e2e.py
Each worker gets its own test user to avoid conflicts.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

# Test data directory containing wine label images
TEST_DATA_DIR = Path(__file__).parent / "data" / "wine_labels"

# Server URL - can be overridden with WINEBOX_TEST_URL env var
BASE_URL = os.environ.get("WINEBOX_TEST_URL", "http://localhost:8000")


def get_worker_id(request: pytest.FixtureRequest) -> str:
    """Get the pytest-xdist worker ID, or 'main' if not running in parallel."""
    if hasattr(request.config, "workerinput"):
        return request.config.workerinput["workerid"]
    return "main"


@pytest.fixture(scope="session")
def base_url() -> str:
    """Return the base URL for the test server."""
    return BASE_URL


@pytest.fixture(scope="function")
def test_user(request: pytest.FixtureRequest) -> tuple[str, str]:
    """Create a unique test user for this test function.

    Returns (username, password) tuple.
    Uses worker ID + test name to create unique users for parallel execution.
    """
    import time

    worker_id = get_worker_id(request)
    # Create a unique username based on worker and test name
    test_name = request.node.name.replace("[", "_").replace("]", "_").replace("-", "_")
    # Keep it short but unique
    username = f"e2e_{worker_id}_{hash(test_name) % 10000:04d}"
    password = "testpass123"

    # Create the user via CLI (ignore errors if user exists)
    project_dir = Path(__file__).parent.parent
    try:
        result = subprocess.run(
            ["uv", "run", "winebox-admin", "add", username, "--password", password],
            cwd=project_dir,
            capture_output=True,
            timeout=30,
        )
        # Small delay to ensure database commits the user
        time.sleep(0.5)
    except subprocess.TimeoutExpired:
        pass

    yield username, password

    # Cleanup: remove the test user after the test
    try:
        subprocess.run(
            ["uv", "run", "winebox-admin", "remove", username, "--force"],
            cwd=project_dir,
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        pass


@pytest.fixture(scope="function")
def authenticated_page(page: Page, test_user: tuple[str, str]) -> Page:
    """Log in and return an authenticated page with a unique test user."""
    username, password = test_user

    page.goto(BASE_URL)

    # Wait for login form
    page.wait_for_selector("#login-form", state="visible")

    # Fill in credentials (correct IDs from index.html)
    page.fill("#login-username", username)
    page.fill("#login-password", password)

    # Click login
    page.click("#login-form button[type='submit']")

    # Wait for main content to become visible (login successful)
    page.wait_for_selector("#main-content", state="visible", timeout=10000)

    return page


@pytest.fixture
def wine_images() -> list[Path]:
    """Return list of wine label image paths from test data."""
    if not TEST_DATA_DIR.exists():
        pytest.skip(f"Test data directory not found: {TEST_DATA_DIR}")

    images = list(TEST_DATA_DIR.glob("*"))
    images = [img for img in images if img.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]

    if not images:
        pytest.skip(f"No wine images found in {TEST_DATA_DIR}")

    return images


class TestCheckinFlow:
    """Test the complete wine checkin flow."""

    def test_login(self, page: Page, test_user: tuple[str, str]) -> None:
        """Test that login works correctly."""
        username, password = test_user

        page.goto(BASE_URL)

        # Should see login form
        expect(page.locator("#login-form")).to_be_visible()

        # Fill credentials
        page.fill("#login-username", username)
        page.fill("#login-password", password)
        page.click("#login-form button[type='submit']")

        # Should show main content after login
        expect(page.locator("#main-content")).to_be_visible(timeout=10000)

    def test_navigate_to_checkin(self, authenticated_page: Page) -> None:
        """Test navigating to the checkin page."""
        page = authenticated_page

        # Click Check In nav link (uses data-page attribute)
        page.click("a[data-page='checkin']")

        # Should show checkin page
        expect(page.locator("#page-checkin")).to_be_visible()
        expect(page.locator("#front-label")).to_be_visible()

    def test_upload_image_triggers_scan(self, authenticated_page: Page, wine_images: list[Path]) -> None:
        """Test that uploading an image triggers a label scan."""
        page = authenticated_page

        # Navigate to checkin
        page.click("a[data-page='checkin']")
        page.wait_for_selector("#page-checkin", state="visible")

        # Upload first wine image
        image_path = wine_images[0]
        page.set_input_files("#front-label", str(image_path))

        # Should show scanning status or results
        # Wait for either the preview or form fields to be populated
        page.wait_for_selector("#front-preview img, #wine-name:not([value=''])",
                               state="visible", timeout=30000)

    def test_checkin_button_opens_confirmation_dialog(
        self, authenticated_page: Page, wine_images: list[Path]
    ) -> None:
        """Test that clicking Check In opens confirmation dialog without saving."""
        page = authenticated_page

        # Navigate to checkin
        page.click("a[data-page='checkin']")
        page.wait_for_selector("#page-checkin", state="visible")

        # Upload image
        image_path = wine_images[0]
        page.set_input_files("#front-label", str(image_path))

        # Wait for scan to complete (either preview shows or we have form data)
        page.wait_for_timeout(3000)  # Give time for OCR/scan

        # Fill in quantity
        page.fill("#quantity", "2")

        # Click Check In button
        page.click("#checkin-form button[type='submit']")

        # Confirmation dialog should appear
        expect(page.locator("#checkin-confirm-modal")).to_have_class(re.compile(r"active"))

        # Confirm and Cancel buttons should be visible
        expect(page.locator("#checkin-confirm-btn")).to_be_visible()
        expect(page.locator("#checkin-cancel-btn")).to_be_visible()

    def test_cancel_closes_dialog_without_saving(
        self, authenticated_page: Page, wine_images: list[Path]
    ) -> None:
        """Test that Cancel closes the dialog and returns to form."""
        page = authenticated_page

        # Navigate to checkin
        page.click("a[data-page='checkin']")
        page.wait_for_selector("#page-checkin", state="visible")

        # Upload image
        image_path = wine_images[0]
        page.set_input_files("#front-label", str(image_path))
        page.wait_for_timeout(3000)

        # Fill quantity and click Check In
        page.fill("#quantity", "1")
        page.click("#checkin-form button[type='submit']")

        # Wait for confirmation dialog
        page.wait_for_selector("#checkin-confirm-modal.active", state="visible")

        # Click Cancel
        page.click("#checkin-cancel-btn")

        # Dialog should close
        expect(page.locator("#checkin-confirm-modal")).not_to_have_class(re.compile(r"active"))

        # Should still be on checkin page
        expect(page.locator("#page-checkin")).to_be_visible()

    def test_confirm_saves_wine_to_database(
        self, authenticated_page: Page, wine_images: list[Path]
    ) -> None:
        """Test that Confirm actually saves the wine to the database."""
        page = authenticated_page

        # Navigate to checkin
        page.click("a[data-page='checkin']")
        page.wait_for_selector("#page-checkin", state="visible")

        # Upload image
        image_path = wine_images[0]
        page.set_input_files("#front-label", str(image_path))
        page.wait_for_timeout(3000)

        # Fill in details
        page.fill("#quantity", "3")
        page.fill("#wine-name", f"E2E Test Wine - {image_path.stem}")

        # Click Check In
        page.click("#checkin-form button[type='submit']")

        # Wait for confirmation dialog
        page.wait_for_selector("#checkin-confirm-modal.active", state="visible")

        # Click Confirm
        page.click("#checkin-confirm-btn")

        # Should show cellar page after successful checkin
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)

        # The wine should now appear in the cellar
        # Look for at least one wine card (use .first to avoid strict mode error)
        expect(page.locator(".wine-card").first).to_be_visible(timeout=5000)

    def test_confirmation_dialog_has_editable_fields(
        self, authenticated_page: Page, wine_images: list[Path]
    ) -> None:
        """Test that the confirmation dialog fields are editable."""
        page = authenticated_page

        # Navigate to checkin
        page.click("a[data-page='checkin']")
        page.wait_for_selector("#page-checkin", state="visible")

        # Upload image
        image_path = wine_images[0]
        page.set_input_files("#front-label", str(image_path))
        page.wait_for_timeout(3000)

        # Fill initial data
        page.fill("#wine-name", "Initial Name")
        page.fill("#quantity", "1")

        # Open confirmation dialog
        page.click("#checkin-form button[type='submit']")
        page.wait_for_selector("#checkin-confirm-modal.active", state="visible")

        # Edit fields in the confirmation dialog
        confirm_name_field = page.locator("#confirm-wine-name")
        expect(confirm_name_field).to_be_editable()

        # Change the name in the dialog
        confirm_name_field.fill("Modified Name in Dialog")

        # Click Confirm
        page.click("#checkin-confirm-btn")

        # Wait for save and navigation
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)


class TestWineImageUploads:
    """Test uploading each wine label image from test data."""

    @pytest.mark.parametrize("image_name", [
        "damaged.jpg",
        "Jo_Pithon_Clos_des_Bois_SGN_1994_label.jpg",
        "Reading_Wine_Labels01.webp",
        "rounded label.jpg",
    ])
    def test_upload_wine_image(self, authenticated_page: Page, image_name: str) -> None:
        """Test uploading a specific wine label image."""
        image_path = TEST_DATA_DIR / image_name
        if not image_path.exists():
            pytest.skip(f"Image not found: {image_path}")

        page = authenticated_page

        # Navigate to checkin
        page.click("a[data-page='checkin']")
        page.wait_for_selector("#page-checkin", state="visible")

        # Upload the image
        page.set_input_files("#front-label", str(image_path))

        # Wait for image preview to appear
        expect(page.locator("#front-preview img")).to_be_visible(timeout=10000)

        # Wait a bit for OCR/scan if enabled
        page.wait_for_timeout(2000)

        # Should be able to fill quantity and click Check In
        page.fill("#quantity", "1")
        page.click("#checkin-form button[type='submit']")

        # Confirmation dialog should appear
        expect(page.locator("#checkin-confirm-modal")).to_have_class(re.compile(r"active"))

        # Cancel to clean up (don't actually save during parameterized tests)
        page.click("#checkin-cancel-btn")
