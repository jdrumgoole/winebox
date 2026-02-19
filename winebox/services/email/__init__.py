"""Email service module for WineBox."""

from winebox.services.email.base import EmailService, get_email_service
from winebox.services.email.console import ConsoleEmailService
from winebox.services.email.ses import SESEmailService

__all__ = [
    "EmailService",
    "ConsoleEmailService",
    "SESEmailService",
    "get_email_service",
]
