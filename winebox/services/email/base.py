"""Base email service protocol and factory."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader

if TYPE_CHECKING:
    from winebox.config import Settings

logger = logging.getLogger(__name__)

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"


class EmailService(ABC):
    """Abstract base class for email services."""

    def __init__(self, settings: "Settings") -> None:
        """Initialize the email service.

        Args:
            settings: Application settings.
        """
        self.settings = settings
        self.sender = settings.email_sender
        self.sender_name = settings.email_sender_name
        self.frontend_url = settings.frontend_url

        # Initialize Jinja2 template environment
        self.template_env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=True,
        )

    def _render_template(self, template_name: str, **context: object) -> str:
        """Render a Jinja2 template.

        Args:
            template_name: Name of the template file.
            **context: Template context variables.

        Returns:
            Rendered template string.
        """
        template = self.template_env.get_template(template_name)
        return template.render(**context)

    def _format_sender(self) -> str:
        """Format the sender email with name.

        Returns:
            Formatted sender string like "WineBox <support@winebox.app>".
        """
        return f"{self.sender_name} <{self.sender}>"

    @abstractmethod
    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: str | None = None,
    ) -> bool:
        """Send an email.

        Args:
            to_email: Recipient email address.
            subject: Email subject.
            html_content: HTML email body.
            text_content: Plain text email body (optional).

        Returns:
            True if email was sent successfully, False otherwise.
        """
        pass

    async def send_verification_email(self, to_email: str, token: str) -> bool:
        """Send an email verification email.

        Args:
            to_email: Recipient email address.
            token: Verification token.

        Returns:
            True if email was sent successfully, False otherwise.
        """
        verify_url = f"{self.frontend_url}/static/index.html#verify?token={token}"

        html_content = self._render_template(
            "verification.html",
            verify_url=verify_url,
            app_name=self.settings.app_name,
        )

        text_content = f"""
Welcome to {self.settings.app_name}!

Please verify your email address by clicking the link below:

{verify_url}

If you did not create an account, please ignore this email.

Best regards,
The {self.settings.app_name} Team
"""

        return await self.send_email(
            to_email=to_email,
            subject=f"Verify your {self.settings.app_name} account",
            html_content=html_content,
            text_content=text_content.strip(),
        )

    async def send_password_reset_email(self, to_email: str, token: str) -> bool:
        """Send a password reset email.

        Args:
            to_email: Recipient email address.
            token: Password reset token.

        Returns:
            True if email was sent successfully, False otherwise.
        """
        reset_url = f"{self.frontend_url}/static/index.html#reset-password?token={token}"

        html_content = self._render_template(
            "password_reset.html",
            reset_url=reset_url,
            app_name=self.settings.app_name,
        )

        text_content = f"""
{self.settings.app_name} Password Reset

You requested a password reset for your account.

Click the link below to reset your password:

{reset_url}

If you did not request a password reset, please ignore this email.

This link will expire in 1 hour.

Best regards,
The {self.settings.app_name} Team
"""

        return await self.send_email(
            to_email=to_email,
            subject=f"Reset your {self.settings.app_name} password",
            html_content=html_content,
            text_content=text_content.strip(),
        )


def get_email_service() -> EmailService:
    """Get the configured email service instance.

    Returns:
        EmailService instance based on settings.
    """
    from winebox.config import settings

    if settings.email_backend == "ses":
        from winebox.services.email.ses import SESEmailService

        return SESEmailService(settings)
    else:
        from winebox.services.email.console import ConsoleEmailService

        return ConsoleEmailService(settings)
