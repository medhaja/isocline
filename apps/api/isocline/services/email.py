"""Transactional email. Without SMTP configured, messages are logged (development) — tokens are never logged in production."""
from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from isocline.core.config import get_settings
from isocline.core.logging import log


def _send_sync(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password or "")
        smtp.send_message(msg)


async def send_email(to: str, subject: str, body: str) -> bool:
    s = get_settings()
    if not s.smtp_host:
        if s.env != "production":
            log.info("email_not_sent_dev", to=to, subject=subject, body=body)
        else:
            log.warning("email_not_configured", to=to, subject=subject)
        return False
    try:
        await asyncio.to_thread(_send_sync, to, subject, body)
        return True
    except Exception as e:
        log.error("email_failed", to=to, error=str(e))
        return False
