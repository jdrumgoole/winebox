"""AWS SES email service for production use."""

import logging
from typing import TYPE_CHECKING

import aioboto3
from botocore.exceptions import ClientError

from winebox.services.email.base import EmailService

if TYPE_CHECKING:
    from winebox.config import Settings

logger = logging.getLogger(__name__)


class SESEmailService(EmailService):
    """Email service using AWS Simple Email Service (SES).

    This service sends real emails via AWS SES. Requires valid
    AWS credentials and a verified domain or email address in SES.
    """

    def __init__(self, settings: "Settings") -> None:
        """Initialize the SES email service.

        Args:
            settings: Application settings.
        """
        super().__init__(settings)

        self.region = settings.aws_region
        self.access_key_id = settings.aws_access_key_id
        self.secret_access_key = settings.aws_secret_access_key

        # Create session with credentials if provided
        self.session = aioboto3.Session(
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.region,
        )

        logger.info("Using AWS SES email backend (region: %s)", self.region)

    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: str | None = None,
    ) -> bool:
        """Send an email via AWS SES.

        Args:
            to_email: Recipient email address.
            subject: Email subject.
            html_content: HTML email body.
            text_content: Plain text email body (optional).

        Returns:
            True if email was sent successfully, False otherwise.
        """
        try:
            async with self.session.client("ses") as ses_client:
                # Build the email body
                body = {"Html": {"Data": html_content, "Charset": "UTF-8"}}

                if text_content:
                    body["Text"] = {"Data": text_content, "Charset": "UTF-8"}

                # Send the email
                response = await ses_client.send_email(
                    Source=self._format_sender(),
                    Destination={"ToAddresses": [to_email]},
                    Message={
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": body,
                    },
                )

                message_id = response.get("MessageId")
                logger.info(
                    "Email sent successfully via SES: to=%s, subject=%s, message_id=%s",
                    to_email,
                    subject,
                    message_id,
                )
                return True

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                "Failed to send email via SES: to=%s, error_code=%s, error=%s",
                to_email,
                error_code,
                error_message,
            )
            return False

        except Exception as e:
            logger.exception("Unexpected error sending email via SES: to=%s", to_email)
            return False
