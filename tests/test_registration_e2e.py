"""End-to-end tests for user registration flow using Playwright.

These tests require a running WineBox server with email verification disabled:
    WINEBOX_AUTH_EMAIL_VERIFICATION_REQUIRED=false invoke start-background

For parallel execution, run with: pytest -n auto tests/test_registration_e2e.py
"""

import os
import uuid

import pytest
from playwright.sync_api import Page, expect

# Server URL - can be overridden with WINEBOX_TEST_URL env var
BASE_URL = os.environ.get("WINEBOX_TEST_URL", "http://localhost:8000")


def generate_unique_email() -> str:
    """Generate a unique email for testing."""
    return f"e2e_reg_{uuid.uuid4().hex[:8]}@test.example.com"


@pytest.fixture
def unique_user_data() -> dict:
    """Generate unique user credentials for each test."""
    return {
        "email": generate_unique_email(),
        "password": "TestPassword123!",
    }


@pytest.fixture
def registration_page(page: Page) -> Page:
    """Navigate to the registration page."""
    # Clear browser state
    page.context.clear_cookies()
    page.goto(BASE_URL)
    page.evaluate("localStorage.clear()")
    page.reload()

    # Wait for login page
    page.wait_for_selector("#login-card", state="visible", timeout=10000)

    # Click "Create account" link to show registration form
    page.click("#show-register")

    # Wait for registration form
    page.wait_for_selector("#register-card", state="visible", timeout=5000)

    return page


@pytest.mark.e2e
class TestRegistrationE2E:
    """Test the complete registration flow."""

    def test_registration_page_loads(self, page: Page) -> None:
        """Verify registration form is accessible."""
        page.goto(BASE_URL)

        # Should see login form first
        expect(page.locator("#login-card")).to_be_visible()

        # Click "Create account" link
        page.click("#show-register")

        # Should show registration form
        expect(page.locator("#register-card")).to_be_visible()

        # Verify form fields are present (no username field)
        expect(page.locator("#register-email")).to_be_visible()
        expect(page.locator("#register-password")).to_be_visible()
        expect(page.locator("#register-confirm-password")).to_be_visible()

        # Verify submit button
        expect(page.locator("#register-form button[type='submit']")).to_be_visible()
        expect(page.locator("#register-form button[type='submit']")).to_have_text("Create Account")

    def test_successful_registration(self, registration_page: Page, unique_user_data: dict) -> None:
        """Complete registration flow without email verification."""
        page = registration_page

        # Fill in registration form (email only, no username)
        page.fill("#register-email", unique_user_data["email"])
        page.fill("#register-password", unique_user_data["password"])
        page.fill("#register-confirm-password", unique_user_data["password"])

        # Submit registration
        page.click("#register-form button[type='submit']")

        # Wait for success - should redirect to login or show success message
        page.wait_for_timeout(2000)

        # Check if we got redirected back to login form or if there's a success indicator
        login_visible = page.locator("#login-card").is_visible()
        main_content_visible = page.locator("#main-content").is_visible()

        assert login_visible or main_content_visible, \
            "Expected to see login form or main content after registration"

    def test_registration_duplicate_email(self, registration_page: Page, unique_user_data: dict) -> None:
        """Verify error message for duplicate email."""
        page = registration_page

        # First registration
        page.fill("#register-email", unique_user_data["email"])
        page.fill("#register-password", unique_user_data["password"])
        page.fill("#register-confirm-password", unique_user_data["password"])
        page.click("#register-form button[type='submit']")

        # Wait for first registration to complete
        page.wait_for_timeout(2000)

        # Navigate back to registration page
        page.goto(BASE_URL)
        page.evaluate("localStorage.clear()")
        page.wait_for_selector("#login-card", state="visible", timeout=10000)
        page.click("#show-register")
        page.wait_for_selector("#register-card", state="visible", timeout=5000)

        # Try to register with same email
        page.fill("#register-email", unique_user_data["email"])
        page.fill("#register-password", unique_user_data["password"])
        page.fill("#register-confirm-password", unique_user_data["password"])
        page.click("#register-form button[type='submit']")

        # Should show error message
        page.wait_for_timeout(2000)

        # Check for error message
        error_element = page.locator("#register-error")
        expect(error_element).to_be_visible(timeout=5000)

        error_text = error_element.text_content() or ""
        assert "already" in error_text.lower() or "exists" in error_text.lower() or \
               "registered" in error_text.lower(), \
            f"Expected duplicate email error, got: {error_text}"

    def test_registration_invalid_email_format(self, registration_page: Page) -> None:
        """Verify browser validation for invalid email."""
        page = registration_page

        # Fill form with invalid email
        page.fill("#register-email", "not-a-valid-email")
        page.fill("#register-password", "TestPassword123!")
        page.fill("#register-confirm-password", "TestPassword123!")

        # Try to submit - browser validation should prevent submission
        page.click("#register-form button[type='submit']")

        # The form should not be submitted - email field should be invalid
        expect(page.locator("#register-card")).to_be_visible()

        # Check email field validity using JavaScript
        is_valid = page.evaluate(
            "document.getElementById('register-email').checkValidity()"
        )
        assert not is_valid, "Email field should be invalid for 'not-a-valid-email'"

    def test_registration_password_mismatch(self, registration_page: Page) -> None:
        """Verify password confirmation validation."""
        page = registration_page

        # Fill form with mismatched passwords
        page.fill("#register-email", generate_unique_email())
        page.fill("#register-password", "TestPassword123!")
        page.fill("#register-confirm-password", "DifferentPassword456!")

        # Submit form
        page.click("#register-form button[type='submit']")

        # Should show error or not submit
        page.wait_for_timeout(1000)

        # Either error message should be visible OR we're still on registration page
        error_visible = page.locator("#register-error").is_visible()
        still_on_registration = page.locator("#register-card").is_visible()

        assert error_visible or still_on_registration, \
            "Password mismatch should show error or prevent submission"

        if error_visible:
            error_text = page.locator("#register-error").text_content() or ""
            assert "password" in error_text.lower() or "match" in error_text.lower(), \
                f"Expected password mismatch error, got: {error_text}"

    def test_registration_short_password(self, registration_page: Page) -> None:
        """Verify password minimum length validation."""
        page = registration_page

        # Fill form with short password (less than 8 chars)
        page.fill("#register-email", generate_unique_email())
        page.fill("#register-password", "short")
        page.fill("#register-confirm-password", "short")

        # Try to submit
        page.click("#register-form button[type='submit']")

        # Check that form validation prevents submission
        expect(page.locator("#register-card")).to_be_visible()

        # Check password field validity
        is_valid = page.evaluate(
            "document.getElementById('register-password').checkValidity()"
        )
        assert not is_valid, "Password field should be invalid for short password"

    def test_login_after_registration(self, registration_page: Page, unique_user_data: dict) -> None:
        """Register then immediately login (email verification disabled)."""
        page = registration_page

        # Register new user
        page.fill("#register-email", unique_user_data["email"])
        page.fill("#register-password", unique_user_data["password"])
        page.fill("#register-confirm-password", unique_user_data["password"])
        page.click("#register-form button[type='submit']")

        # Wait for registration to complete
        page.wait_for_timeout(2000)

        # Navigate to login if not already there
        if not page.locator("#login-card").is_visible():
            page.goto(BASE_URL)
            page.evaluate("localStorage.clear()")
            page.wait_for_selector("#login-card", state="visible", timeout=10000)

        # Now login with registered credentials (email in the email field)
        page.fill("#login-email", unique_user_data["email"])
        page.fill("#login-password", unique_user_data["password"])
        page.click("#login-form button[type='submit']")

        # Should show main content after successful login
        expect(page.locator("#main-content")).to_be_visible(timeout=15000)

        # Verify user info shows
        expect(page.locator("#user-info")).to_be_visible()

    def test_back_to_login_link(self, registration_page: Page) -> None:
        """Verify 'Already have an account? Sign in' link works."""
        page = registration_page

        # Should be on registration form
        expect(page.locator("#register-card")).to_be_visible()

        # Click the back to login link
        page.click("#show-login-from-register")

        # Should show login form
        expect(page.locator("#login-card")).to_be_visible()
        expect(page.locator("#register-card")).not_to_be_visible()

    def test_registration_empty_fields(self, registration_page: Page) -> None:
        """Verify form requires all fields to be filled."""
        page = registration_page

        # Try to submit empty form
        page.click("#register-form button[type='submit']")

        # Should still be on registration page (form validation prevents submission)
        expect(page.locator("#register-card")).to_be_visible()

        # Check that required fields are invalid when empty
        email_valid = page.evaluate(
            "document.getElementById('register-email').checkValidity()"
        )
        password_valid = page.evaluate(
            "document.getElementById('register-password').checkValidity()"
        )

        assert not email_valid, "Empty email should be invalid"
        assert not password_valid, "Empty password should be invalid"

    def test_password_toggle_visibility(self, registration_page: Page) -> None:
        """Verify password visibility toggle buttons work."""
        page = registration_page

        # Fill password
        page.fill("#register-password", "TestPassword123!")

        # Password should be hidden by default
        password_type = page.evaluate(
            "document.getElementById('register-password').type"
        )
        assert password_type == "password", "Password should be hidden by default"

        # Click toggle button (first one in the password wrapper)
        password_wrapper = page.locator("#register-password").locator("..").locator(".password-toggle")
        password_wrapper.click()

        # Password should now be visible
        password_type = page.evaluate(
            "document.getElementById('register-password').type"
        )
        assert password_type == "text", "Password should be visible after toggle"

        # Click again to hide
        password_wrapper.click()

        # Password should be hidden again
        password_type = page.evaluate(
            "document.getElementById('register-password').type"
        )
        assert password_type == "password", "Password should be hidden after second toggle"


@pytest.mark.e2e
class TestRegistrationValidationMessages:
    """Test that validation messages are user-friendly."""

    def test_email_validation_message(self, registration_page: Page) -> None:
        """Verify email field shows appropriate validation message."""
        page = registration_page

        # Fill invalid email
        email_input = page.locator("#register-email")
        email_input.fill("invalid-email")
        email_input.blur()

        # Get the validation message
        validation_message = page.evaluate(
            "document.getElementById('register-email').validationMessage"
        )

        # Should have a validation message
        assert validation_message, "Should have validation message for invalid email"
