"""Sending email. Phase 1 writes emails to the log; a real sender plugs in behind the protocol."""

import logging
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    """One plain-text email."""

    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    """Anything that can deliver an `EmailMessage`. Tests use an in-memory fake."""

    def send(self, message: EmailMessage) -> None:
        """Deliver the message, or raise."""
        ...


class ConsoleEmailSender:
    """Writes each email to the log, so sign-up works locally with no mail account.

    The log line contains the whole body, including one-time tokens. That's intended for
    development only; a deployment that sends real mail uses a different sender.
    """

    def send(self, message: EmailMessage) -> None:
        """Log the message."""
        logger.info("email to=%s subject=%r\n%s", message.to, message.subject, message.body)


def create_email_sender(settings: Settings) -> EmailSender:
    """The sender selected by `EMAIL_BACKEND`."""
    # "console" is the only backend in Phase 1; Settings rejects any other value.
    return ConsoleEmailSender()
