"""Alert delivery. Configure channels with environment variables:

  NTFY_TOPIC (+ optional NTFY_SERVER, NTFY_TOKEN, DASHBOARD_URL) -> phone push via the ntfy app
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

MAX_PUSH_LINES = 15

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


def _ntfy(alerts: list[tuple[str, float, str, Signal]]) -> None:
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        return
    risks = [a for a in alerts if a[3].kind == RISK]
    urgent = any(a[3].severity >= 3 for a in risks)
    tickers = list(dict.fromkeys(a[0] for a in alerts))
    # one push per sweep: a first scan can produce dozens of alerts
    lines = [format_alert(*a) for a in alerts[:MAX_PUSH_LINES]]
    if len(alerts) > MAX_PUSH_LINES:
        lines.append(f"+{len(alerts) - MAX_PUSH_LINES} more in the dashboard log")
    headers = {
        # HTTP headers must be latin-1, so the title stays plain ASCII
        "Title": f"StockWatch: {len(alerts)} alert{'s' if len(alerts) != 1 else ''} - {', '.join(tickers[:5])}"
                 + ("..." if len(tickers) > 5 else ""),
        "Priority": "5" if urgent else "4" if risks else "3",
        "Tags": "rotating_light" if urgent else "warning" if risks else "chart_with_upwards_trend",
    }
    if os.getenv("DASHBOARD_URL"):
        headers["Click"] = os.environ["DASHBOARD_URL"]
    if os.getenv("NTFY_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['NTFY_TOKEN']}"
    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    req = urllib.request.Request(f"{server}/{topic}", data="\n".join(lines).encode(), headers=headers)
    urllib.request.urlopen(req, timeout=10).read()


def send(alerts: list[tuple[str, float, str, Signal]]) -> None:
    """alerts: (ticker, price, verdict, signal) for each new alert in this sweep."""
    if not alerts:
        return
    alerts = sorted(alerts, key=lambda a: (-a[3].severity, a[3].kind != RISK))
    text = "\n".join(format_alert(*a) for a in alerts)
    print(text, flush=True)
    for name, deliver in (("ntfy", lambda: _ntfy(alerts)), ("telegram", lambda: _telegram(text)),
                          ("email", lambda: _email(text))):
        try:
            deliver()
        except Exception as e:
            log.warning("%s delivery failed: %s", name, e)
