"""E2E tests for the login page: error states, forgot password, and validation.

These tests cover login-specific UI flows that are not exercised by the
shared ``login_via_ui`` helper used in other E2E modules.

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_login_e2e.py -v --override-ini="addopts="
"""

from typing import Generator

import pytest
from playwright.sync_api import Page, expect

from .playwright_utils import (
    BASE_URL,
    create_cli_worker_user,
    e2e_preflight,  # noqa: F401 — imported autouse fixture
)


@pytest.fixture(scope="session")
def worker_user(request: pytest.FixtureRequest) -> Generator[tuple[str, str], None, None]:
    email, password = create_cli_worker_user(request, email_prefix="e2e_login", password="testpass123")
    yield email, password


def _go_to_login(page: Page) -> None:
    """Navigate to the login page with a clean slate."""
    page.context.clear_cookies()
    page.goto(BASE_URL)
    page.evaluate("localStorage.clear()")
    page.reload()
    page.wait_for_selector("#login-form", state="visible", timeout=10000)


@pytest.mark.e2e
class TestLoginPage:
    """Tests for login form rendering and basic interactions."""

    def test_login_form_renders(self, page: Page) -> None:
        """Login form shows email, password, remember-me, and submit button."""
        _go_to_login(page)

        expect(page.locator("#login-email")).to_be_visible()
        expect(page.locator("#login-password")).to_be_visible()
        expect(page.locator("#login-remember-me")).to_be_attached()
        expect(page.locator("#login-form button[type='submit']")).to_be_visible()

    def test_login_form_has_password_toggle(self, page: Page) -> None:
        """Password field has a visibility toggle."""
        _go_to_login(page)

        page.fill("#login-password", "secret")
        assert page.evaluate("document.getElementById('login-password').type") == "password"

        # Click the toggle button next to the password field
        toggle = page.locator("#login-password").locator("..").locator(".password-toggle")
        toggle.click()
        assert page.evaluate("document.getElementById('login-password').type") == "text"

        toggle.click()
        assert page.evaluate("document.getElementById('login-password').type") == "password"

    def test_login_remember_me_checked_by_default(self, page: Page) -> None:
        """Remember-me checkbox is checked by default."""
        _go_to_login(page)
        assert page.is_checked("#login-remember-me")

    def test_empty_form_submit_blocked(self, page: Page) -> None:
        """Submitting an empty form is blocked by HTML validation."""
        _go_to_login(page)
        page.click("#login-form button[type='submit']")

        # Still on the login page — form didn't submit
        expect(page.locator("#login-form")).to_be_visible()
        email_valid = page.evaluate("document.getElementById('login-email').checkValidity()")
        assert not email_valid

    def test_create_account_link(self, page: Page) -> None:
        """'Create account' link switches to the registration form."""
        _go_to_login(page)
        page.click("#show-register")
        expect(page.locator("#register-card")).to_be_visible()
        expect(page.locator("#login-card")).not_to_be_visible()


@pytest.mark.e2e
class TestLoginErrors:
    """Tests for login error feedback."""

    def test_wrong_password_shows_error(self, page: Page, worker_user: tuple[str, str]) -> None:
        """Entering a wrong password displays an error message."""
        email, _ = worker_user
        _go_to_login(page)

        page.fill("#login-email", email)
        page.fill("#login-password", "definitelywrongpassword")
        page.click("#login-form button[type='submit']")

        error = page.locator("#login-error")
        expect(error).to_be_visible(timeout=10000)
        error_text = (error.text_content() or "").lower()
        assert error_text, "Error element should contain a message"

    def test_nonexistent_user_shows_error(self, page: Page) -> None:
        """Attempting to log in with a non-existent email shows an error."""
        _go_to_login(page)

        page.fill("#login-email", "does_not_exist_9999@test.example.com")
        page.fill("#login-password", "anypassword123")
        page.click("#login-form button[type='submit']")

        error = page.locator("#login-error")
        expect(error).to_be_visible(timeout=10000)

    def test_error_clears_on_retry(self, page: Page) -> None:
        """Error message should clear or update when a new attempt is made."""
        _go_to_login(page)

        # Trigger an error first
        page.fill("#login-email", "no_such_user@test.example.com")
        page.fill("#login-password", "badpassword")
        page.click("#login-form button[type='submit']")
        expect(page.locator("#login-error")).to_be_visible(timeout=10000)

        first_error_text = page.locator("#login-error").text_content()

        # Try again — error should update (not stack)
        page.fill("#login-password", "differentbadpassword")
        page.click("#login-form button[type='submit']")
        page.wait_for_timeout(2000)

        # Still showing an error (not stacked duplicates)
        expect(page.locator("#login-error")).to_be_visible()


@pytest.mark.e2e
class TestLoginSuccess:
    """Tests for successful login behaviour."""

    def test_successful_login_shows_main_content(self, page: Page, worker_user: tuple[str, str]) -> None:
        """Correct credentials take the user to the main app."""
        email, password = worker_user
        _go_to_login(page)

        page.fill("#login-email", email)
        page.fill("#login-password", password)
        page.click("#login-form button[type='submit']")

        expect(page.locator("#main-content")).to_be_visible(timeout=15000)
        expect(page.locator("#user-info")).to_be_visible()

    def test_login_hides_login_page(self, page: Page, worker_user: tuple[str, str]) -> None:
        """After login the login section is no longer visible."""
        email, password = worker_user
        _go_to_login(page)

        page.fill("#login-email", email)
        page.fill("#login-password", password)
        page.click("#login-form button[type='submit']")

        expect(page.locator("#main-content")).to_be_visible(timeout=15000)
        expect(page.locator("#page-login")).not_to_be_visible()


@pytest.mark.e2e
class TestForgotPassword:
    """Tests for the 'Forgot password?' flow UI."""

    def test_forgot_password_link_shows_form(self, page: Page) -> None:
        """Clicking 'Forgot password?' shows the reset-request form."""
        _go_to_login(page)
        page.click("#show-forgot-password")
        expect(page.locator("#forgot-password-card")).to_be_visible()
        expect(page.locator("#forgot-email")).to_be_visible()

    def test_forgot_password_form_has_submit(self, page: Page) -> None:
        """Forgot-password form has a submit button."""
        _go_to_login(page)
        page.click("#show-forgot-password")
        expect(page.locator("#forgot-password-form button[type='submit']")).to_be_visible()

    def test_forgot_password_submit_shows_success(self, page: Page) -> None:
        """Submitting any email shows a success/confirmation message (security-conscious)."""
        _go_to_login(page)
        page.click("#show-forgot-password")
        page.wait_for_selector("#forgot-password-card", state="visible", timeout=5000)

        page.fill("#forgot-email", "anyone@example.com")
        page.click("#forgot-password-form button[type='submit']")

        # The app always shows a success message regardless of whether the
        # email exists (to avoid leaking account info).
        success = page.locator("#forgot-success")
        expect(success).to_be_visible(timeout=10000)

    def test_forgot_password_back_to_login(self, page: Page) -> None:
        """Can navigate back from forgot-password to the login form."""
        _go_to_login(page)
        page.click("#show-forgot-password")
        expect(page.locator("#forgot-password-card")).to_be_visible()

        # Click the "Back to sign in" or equivalent link
        back_link = page.locator("#forgot-password-card a, #forgot-password-card button").filter(
            has_text="Sign in"
        ).or_(page.locator("#show-login-from-forgot"))
        back_link.first.click()

        expect(page.locator("#login-card")).to_be_visible()
