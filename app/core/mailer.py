"""Envio de e-mails transacionais (US16-US18) pelo Resend.

O envio nunca derruba a requisição que o originou: falhas são registradas no log.
"""

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings

logger = logging.getLogger("app.mailer")

RESEND_URL = "https://api.resend.com/emails"


@dataclass(frozen=True, slots=True)
class Email:
    to: str
    subject: str
    text: str


class Mailer(Protocol):
    def send(self, email: Email) -> None: ...


class LogMailer:
    """Usado sem RESEND_API_KEY (desenvolvimento e testes): só registra no log."""

    def send(self, email: Email) -> None:
        logger.info("e-mail não enviado (sem RESEND_API_KEY) para %s: %s", email.to, email.subject)


class ResendMailer:
    def __init__(self, api_key: str, sender: str, timeout: float = 10.0) -> None:
        self.api_key = api_key
        self.sender = sender
        self.timeout = timeout

    def send(self, email: Email) -> None:
        body = json.dumps(
            {"from": self.sender, "to": [email.to], "subject": email.subject, "text": email.text}
        ).encode()
        request = urllib.request.Request(
            RESEND_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "clube-tenis-api",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            response.read()


def build_mailer(settings: Settings) -> Mailer:
    if settings.resend_api_key is None or not settings.resend_api_key.get_secret_value():
        return LogMailer()
    return ResendMailer(settings.resend_api_key.get_secret_value(), settings.mail_from)


def send_all(mailer: Mailer, emails: Iterable[Email]) -> None:
    """Envia cada e-mail; uma falha não impede os demais."""
    for email in emails:
        try:
            mailer.send(email)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            logger.exception("falha ao enviar e-mail para %s: %s", email.to, email.subject)
