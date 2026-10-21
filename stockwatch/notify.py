"""Alert delivery. Configure channels with environment variables:

  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID       -> Telegram message
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO -> email
Console output is always on.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import urllib.request
from email.message import EmailMessage

from .signals import RISK, Signal

log = logging.getLogger(__name__)


def format_alert(ticker: str, price: float, verdict: str, s: Signal) -> str:
    icon = "🔴" if s.kind == RISK else "🟢"
    return f"{icon} {ticker} @ {price:.2f} [{verdict}] {s.message}"


def _telegram(text: str) -> None:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat, "text": text}).encode(),
        headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()


def _email(text: str) -> None:
    host, to = os.getenv("SMTP_HOST"), os.getenv("ALERT_EMAIL_TO")
    if not (host and to):
        return
    msg = EmailMessage()
    msg["Subject"] = "StockWatch alerts"
    msg["From"] = os.getenv("SMTP_USER", to)
    msg["To"] = to
    msg.set_content(text)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=15) as smtp:
        smtp.starttls()
        if os.getenv("SMTP_USER"):
            smtp.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(msg)


def send(lines: list[str]) -> None:
    if not lines:
        return
    text = "\n".join(lines)
    print(text, flush=True)
    for channel in (_telegram, _email):
        try:
            channel(text)
        except Exception as e:
            log.warning("%s delivery failed: %s", channel.__name__.strip("_"), e)
