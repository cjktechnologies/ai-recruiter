"""Outbound messaging adapters: e-mail (SMTP / console), SMS & WhatsApp (Twilio / console)."""

from __future__ import annotations

import smtplib
import ssl
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.core.errors import ExternalServiceError
from app.core.logging import get_logger, log_event

logger = get_logger(__name__)


@dataclass
class SendResult:
    external_id: str
    delivered: bool = True


class EmailSender(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> SendResult: ...


class SmsSender(Protocol):
    def send(self, *, to: str, body: str, whatsapp: bool = False) -> SendResult: ...


class ConsoleEmailSender:
    """Development adapter: logs a redacted record of the e-mail instead of sending it."""

    outbox: list[dict[str, str]] = []

    def send(self, *, to: str, subject: str, body: str) -> SendResult:
        ConsoleEmailSender.outbox.append({"to": to, "subject": subject, "body": body})
        log_event(logger, "email_console", to=to, subject=subject)
        return SendResult(external_id=f"console-{uuid.uuid4().hex[:12]}")


class SmtpEmailSender:
    def __init__(self) -> None:
        self.s = get_settings()

    def send(self, *, to: str, subject: str, body: str) -> SendResult:
        s = self.s
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s.email_from, to, subject
        msg_id = f"<{uuid.uuid4().hex}@ai-recruiter>"
        msg["Message-ID"] = msg_id
        msg.set_content(body)
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
                if s.smtp_use_tls:
                    smtp.starttls(context=ssl.create_default_context())
                if s.smtp_username and s.smtp_password:
                    smtp.login(s.smtp_username, s.smtp_password.get_secret_value())
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise ExternalServiceError(f"SMTP delivery failed: {type(exc).__name__}") from exc
        return SendResult(external_id=msg_id)


class ConsoleSmsSender:
    outbox: list[dict[str, str]] = []

    def send(self, *, to: str, body: str, whatsapp: bool = False) -> SendResult:
        ConsoleSmsSender.outbox.append({"to": to, "body": body, "whatsapp": str(whatsapp)})
        log_event(logger, "sms_console", whatsapp=whatsapp)
        return SendResult(external_id=f"console-{uuid.uuid4().hex[:12]}")


class TwilioSmsSender:
    def __init__(self) -> None:
        s = get_settings()
        if not (s.twilio_account_sid and s.twilio_auth_token and s.twilio_from_number):
            raise RuntimeError("Twilio credentials are not configured")
        self.sid, self.token, self.sender = s.twilio_account_sid, s.twilio_auth_token.get_secret_value(), \
            s.twilio_from_number

    def send(self, *, to: str, body: str, whatsapp: bool = False) -> SendResult:
        prefix = "whatsapp:" if whatsapp else ""
        try:
            resp = httpx.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json",
                data={"To": prefix + to, "From": prefix + self.sender, "Body": body[:1600]},
                auth=(self.sid, self.token), timeout=20,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalServiceError("SMS delivery failed") from exc
        return SendResult(external_id=resp.json().get("sid", ""))


@lru_cache
def get_email_sender() -> EmailSender:
    return SmtpEmailSender() if get_settings().email_backend == "smtp" else ConsoleEmailSender()


@lru_cache
def get_sms_sender() -> SmsSender:
    return TwilioSmsSender() if get_settings().sms_backend == "twilio" else ConsoleSmsSender()
