"""Console email service for development and testing."""

import logging
from typing import TYPE_CHECKING

from winebox.services.email.base import EmailService

if TYPE_CHECKING:
    from winebox.config import Settings

logger = logging.getLogger(__name__)


class ConsoleEmailService(EmailService):
    """Email service that logs emails to console instead of sending.

    This is useful for development and testing where you don't want
    to actually send emails but want to see what would be sent.
    """

    def __init__(self, settings: "Settings") -> None:
        """Initialize the console email service.

        Args:
            settings: Application settings.
        """
        super().__init__(settings)
        logger.info("Using console email backend (emails will be logged, not sent)")

    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: str | None = None,
    ) -> bool:
        """Log an email to the console instead of sending.

        Args:
            to_email: Recipient email address.
            subject: Email subject.
            html_content: HTML email body.
            text_content: Plain text email body (optional).

        Returns:
            Always returns True.
        """
        separator = "=" * 60
        logger.info(
            "\n%s\n"
            "EMAIL (console backend - not actually sent)\n"
            "%s\n"
            "From: %s\n"
            "To: %s\n"
            "Subject: %s\n"
            "%s\n"
            "%s\n"
            "%s",
            separator,
            separator,
            self._format_sender(),
            to_email,
            subject,
            separator,
            text_content or "(no text content)",
            separator,
        )

        return True
