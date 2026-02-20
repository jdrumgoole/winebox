"""Tests for email service module."""

import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from winebox.services.email import (
    ConsoleEmailService,
    SESEmailService,
    get_email_service,
)
from winebox.services.email.base import EmailService


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    settings = MagicMock()
    settings.email_sender = "test@example.com"
    settings.email_sender_name = "Test App"
    settings.frontend_url = "http://localhost:8000"
    settings.app_name = "TestApp"
    settings.email_backend = "console"
    settings.aws_region = "us-east-1"
    settings.aws_access_key_id = "test-key-id"
    settings.aws_secret_access_key = "test-secret-key"
    return settings




class TestConsoleEmailService:
    """Tests for ConsoleEmailService."""

    def test_init(self, mock_settings):
        """Test service initialization."""
        service = ConsoleEmailService(mock_settings)
        assert service.sender == "test@example.com"
        assert service.sender_name == "Test App"
        assert service.frontend_url == "http://localhost:8000"

    async def test_send_email(self, mock_settings, caplog):
        """Test sending email logs to console."""
        caplog.set_level(logging.INFO)
        service = ConsoleEmailService(mock_settings)

        result = await service.send_email(
            to_email="user@example.com",
            subject="Test Subject",
            html_content="<p>Test HTML</p>",
            text_content="Test Text",
        )

        assert result is True
        # Check that email was logged
        assert "user@example.com" in caplog.text
        assert "Test Subject" in caplog.text

    async def test_send_verification_email(self, mock_settings, caplog):
        """Test sending verification email."""
        caplog.set_level(logging.INFO)
        service = ConsoleEmailService(mock_settings)

        result = await service.send_verification_email(
            to_email="user@example.com",
            token="test-token-123",
        )

        assert result is True
        assert "user@example.com" in caplog.text
        assert "verify" in caplog.text.lower()

    async def test_send_password_reset_email(self, mock_settings, caplog):
        """Test sending password reset email."""
        caplog.set_level(logging.INFO)
        service = ConsoleEmailService(mock_settings)

        result = await service.send_password_reset_email(
            to_email="user@example.com",
            token="reset-token-456",
        )

        assert result is True
        assert "user@example.com" in caplog.text
        assert "reset" in caplog.text.lower()


class TestSESEmailService:
    """Tests for SESEmailService."""

    def test_init(self, mock_settings):
        """Test service initialization."""
        service = SESEmailService(mock_settings)
        assert service.region == "us-east-1"
        assert service.access_key_id == "test-key-id"
        assert service.secret_access_key == "test-secret-key"

    async def test_send_email_success(self, mock_settings):
        """Test successful email send via SES."""
        service = SESEmailService(mock_settings)

        # Mock the SES client
        mock_ses_client = AsyncMock()
        mock_ses_client.send_email = AsyncMock(return_value={"MessageId": "test-123"})

        # Create a mock context manager
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_ses_client)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        with patch.object(service.session, "client", return_value=mock_context):
            result = await service.send_email(
                to_email="user@example.com",
                subject="Test Subject",
                html_content="<p>Test</p>",
            )

        assert result is True
        mock_ses_client.send_email.assert_called_once()

    async def test_send_email_failure(self, mock_settings):
        """Test email send failure via SES."""
        service = SESEmailService(mock_settings)

        # Mock the SES client to raise an error
        from botocore.exceptions import ClientError

        mock_ses_client = AsyncMock()
        mock_ses_client.send_email = AsyncMock(
            side_effect=ClientError(
                {"Error": {"Code": "MessageRejected", "Message": "Test error"}},
                "SendEmail",
            )
        )

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_ses_client)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        with patch.object(service.session, "client", return_value=mock_context):
            result = await service.send_email(
                to_email="user@example.com",
                subject="Test Subject",
                html_content="<p>Test</p>",
            )

        assert result is False


class TestGetEmailService:
    """Tests for get_email_service factory function."""

    def test_get_console_service(self):
        """Test getting console email service."""
        with patch("winebox.config.settings") as mock_settings:
            mock_settings.email_backend = "console"
            mock_settings.email_sender = "test@example.com"
            mock_settings.email_sender_name = "Test"
            mock_settings.frontend_url = "http://localhost"
            mock_settings.app_name = "Test"

            service = get_email_service()
            assert isinstance(service, ConsoleEmailService)

    def test_get_ses_service(self):
        """Test getting SES email service."""
        with patch("winebox.config.settings") as mock_settings:
            mock_settings.email_backend = "ses"
            mock_settings.email_sender = "test@example.com"
            mock_settings.email_sender_name = "Test"
            mock_settings.frontend_url = "http://localhost"
            mock_settings.app_name = "Test"
            mock_settings.aws_region = "us-east-1"
            mock_settings.aws_access_key_id = None
            mock_settings.aws_secret_access_key = None

            service = get_email_service()
            assert isinstance(service, SESEmailService)
