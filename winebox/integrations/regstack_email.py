"""Email transports that adapt WineBox's credentials to regstack's interface.

regstack's bundled SES backend reads AWS credentials from boto3's default
chain (env vars / instance profile / ~/.aws/credentials). WineBox already
loads explicit access keys into Settings from secrets.env; this module
wires those through directly so deployers don't have to populate a
parallel set of environment variables for boto3 to pick up.
"""

from __future__ import annotations

import logging

import aioboto3
from regstack.email.base import EmailMessage, EmailService

logger = logging.getLogger(__name__)


class WineboxConsoleEmailService(EmailService):
    """Logs composed emails to the application logger. Used in dev/test."""

    async def send(self, message: EmailMessage) -> None:
        logger.info(
            "EMAIL [%s -> %s] %s\n%s",
            message.from_header,
            message.to,
            message.subject,
            message.text,
        )


class WineboxSesEmailService(EmailService):
    """SES backend that uses WineBox's explicit AWS credentials.

    Mirrors regstack.email.ses.SesEmailService but constructs the
    aioboto3 session with credentials sourced from Settings rather
    than relying on the default boto3 credential chain.
    """

    def __init__(
        self,
        *,
        region: str,
        access_key_id: str | None,
        secret_access_key: str | None,
    ) -> None:
        self._session = aioboto3.Session(
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )
        self._region = region

    async def send(self, message: EmailMessage) -> None:
        async with self._session.client("ses") as client:
            await client.send_email(
                Source=message.from_header,
                Destination={"ToAddresses": [message.to]},
                Message={
                    "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": message.text, "Charset": "UTF-8"},
                        "Html": {"Data": message.html, "Charset": "UTF-8"},
                    },
                },
            )
