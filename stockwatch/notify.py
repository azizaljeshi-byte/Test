"""Alert delivery. Configure channels with environment variables:

  NTFY_TOPIC (+ optional NTFY_SERVER, NTFY_TOKEN, DASHBOARD_URL) -> phone push via the ntfy app
  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID       -> Telegram message
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO -> email
Console output is on unless the caller asks for quiet (public CI logs).

send() returns each channel's outcome: "sent", "not configured" or "failed: <reason>". Reasons never
contain the bot token, chat ID or ntfy credentials.
"""
from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import time
import urllib.error
import urllib.request
from email.message import EmailMessage

from .signals import RISK, Signal

MAX_PUSH_LINES = 15
TELEGRAM_LIMIT = 4096                 # Telegram rejects longer messages outright
TELEGRAM_MAX_WAIT = 10                # seconds we'll wait on a rate limit before reporting it instead
_TOKEN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
_CHAT = re.compile(r"^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$")

log = logging.getLogger(__name__)


class DeliveryError(Exception):
    """A delivery failure whose message is safe to show in public logs."""


def format_alert(ticker: str, price: float, verdict: str, s: Signal) -> str:
    icon = "🔴" if s.kind == RISK else "🟢"
    return f"{icon} {ticker} @ {price:.2f} [{verdict}] {s.message}"


def _capped(alerts) -> list[str]:
    lines = [format_alert(*a) for a in alerts[:MAX_PUSH_LINES]]
    if len(alerts) > MAX_PUSH_LINES:
        lines.append(f"+{len(alerts) - MAX_PUSH_LINES} more in the dashboard log")
    return lines


def _scrub(text: str) -> str:
    """Remove every configured secret from a message before it can reach a log."""
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "NTFY_TOPIC", "NTFY_TOKEN", "SMTP_PASSWORD"):
        value = (os.getenv(var) or "").strip()
        if value:
            text = text.replace(value, f"<{var}>")
    return text


def telegram_config() -> str:
    """"configured", "not configured", or what's wrong. Never returns the values themselves."""
    token, chat = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip(), (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token and not chat:
        return "not configured"
    if not chat:
        return "incomplete: TELEGRAM_BOT_TOKEN set but TELEGRAM_CHAT_ID missing"
    if not token:
        return "incomplete: TELEGRAM_CHAT_ID set but TELEGRAM_BOT_TOKEN missing"
    if not _TOKEN.match(token):
        return "invalid: TELEGRAM_BOT_TOKEN doesn't look like a BotFather token (digits:letters)"
    if not _CHAT.match(chat):
        return "invalid: TELEGRAM_CHAT_ID should be a number (e.g. 123456789) or an @channel name"
    return "configured"


def _telegram_post(text: str) -> None:
    if len(text) > TELEGRAM_LIMIT:   # refuse rather than cut: a clipped message could lose its stop or warning
        raise DeliveryError(f"message is {len(text)} characters, over Telegram's {TELEGRAM_LIMIT}; not sent")
    token, chat = os.environ["TELEGRAM_BOT_TOKEN"].strip(), os.environ["TELEGRAM_CHAT_ID"].strip()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode(),
        headers={"Content-Type": "application/json"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                body = json.loads(r.read() or b"{}")
            if not body.get("ok"):
                raise DeliveryError(_scrub(f"Telegram refused the message: {body.get('description', 'no reason given')}"))
            return
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read() or b"{}")
            except ValueError:
                body = {}
            e.close()
            wait = (body.get("parameters") or {}).get("retry_after")
            if e.code == 429 and attempt == 0 and isinstance(wait, int) and 0 <= wait <= TELEGRAM_MAX_WAIT:
                time.sleep(wait)
                continue
            if e.code == 429:
                raise DeliveryError(f"Telegram rate limit: retry after {wait if wait is not None else '?'} s") from None
            raise DeliveryError(_scrub(f"Telegram HTTP {e.code}: {body.get('description', 'no reason given')}")) from None
        except urllib.error.URLError as e:
            raise DeliveryError(_scrub(f"Telegram unreachable: {e.reason}")) from None
        except (TimeoutError, OSError) as e:
            raise DeliveryError(_scrub(f"Telegram unreachable: {type(e).__name__}")) from None


def _telegram(alerts) -> str:
    status = telegram_config()
    if status == "not configured":
        return status
    if status != "configured":
        raise DeliveryError(f"Telegram {status}")
    _telegram_post(_fit(f"StockWatch: {len(alerts)} alert{'s' if len(alerts) != 1 else ''}",
                        [format_alert(*a) for a in alerts]))
    return "sent"


def _fit(header: str, lines: list[str], limit: int = TELEGRAM_LIMIT) -> str:
    """As many whole alert lines as fit (at most MAX_PUSH_LINES), then how many were left out."""
    for shown in range(min(len(lines), MAX_PUSH_LINES), -1, -1):
        rest = len(lines) - shown
        text = "\n".join([header, *lines[:shown]] + ([f"+{rest} more in the dashboard log"] if rest else []))
        if len(text) <= limit:
            return text
    return header[:limit]


def telegram_send(text: str) -> str:
    """Send one message; raises DeliveryError (safe to log) unless Telegram accepted it."""
    status = telegram_config()
    if status != "configured":
        raise DeliveryError(f"Telegram {status}")
    _telegram_post(text)
    return "sent"


def telegram_test(stamp: str) -> str:
    """Send one fixed message with no holdings in it, to prove the bot and chat work."""
    status = telegram_config()
    if status != "configured":
        raise DeliveryError(f"Telegram {status}")
    _telegram_post(f"StockWatch test message ({stamp}). Telegram delivery works. No holdings are included.")
    return "sent"


def _email(text: str) -> str:
    host, to = os.getenv("SMTP_HOST"), os.getenv("ALERT_EMAIL_TO")
    if not (host and to):
        return "not configured"
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
    return "sent"


def _ntfy(alerts: list[tuple[str, float, str, Signal]]) -> str:
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        return "not configured"
    risks = [a for a in alerts if a[3].kind == RISK]
    urgent = any(a[3].severity >= 3 for a in risks)
    tickers = list(dict.fromkeys(a[0] for a in alerts))
    # one push per sweep: a first scan can produce dozens of alerts
    lines = _capped(alerts)
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
    return "sent"


def send(alerts: list[tuple[str, float, str, Signal]], quiet: bool = False) -> dict[str, str]:
    """alerts: (ticker, price, verdict, signal) for each new alert in this sweep.

    quiet=True keeps alert text (tickers, prices) out of stdout, for public CI logs."""
    if not alerts:
        return {}
    alerts = sorted(alerts, key=lambda a: (-a[3].severity, a[3].kind != RISK))
    text = "\n".join(format_alert(*a) for a in alerts)
    if not quiet:
        print(text, flush=True)
    results = {}
    for name, deliver in (("ntfy", lambda: _ntfy(alerts)), ("telegram", lambda: _telegram(alerts)),
                          ("email", lambda: _email(text))):
        try:
            results[name] = deliver()
        except DeliveryError as e:
            results[name] = f"failed: {e}"
        except Exception as e:
            results[name] = "failed: " + _scrub(f"{type(e).__name__}: {e}")
        if results[name].startswith("failed"):
            log.warning("%s delivery %s", name, results[name])
    return results
