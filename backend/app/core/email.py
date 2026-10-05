"""Отправка уведомлений по email (в демо — Mailpit). Ошибки доставки не ломают бизнес-операцию."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import get_settings

log = logging.getLogger("email")


def send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not s.email_enabled or not to:
        return
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=5) as smtp:
            smtp.send_message(msg)
    except Exception as e:  # noqa: BLE001
        log.warning("email to %s failed: %s", to, e)
