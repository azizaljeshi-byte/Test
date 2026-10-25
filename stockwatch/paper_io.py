"""Where the paper account lives outside the app (owner, 2026-10-25). Streamlit Cloud wipes the app's database on every reboot,
so the book is also pushed to a Google Sheet through a small Apps Script web link (docs/paper_sheet_script.gs), and read back
when the app starts empty. The test list is read from the Sheet's Test list tab, the same way the holdings Sheet is read.

Three settings, all optional, all secrets (never committed; the repo is public):
  STOCKWATCH_PAPER_LIST_URL   the Test list tab's link (General access: Anyone with the link, Viewer)
  STOCKWATCH_PAPER_WEBHOOK    the Apps Script web app link
  STOCKWATCH_PAPER_TOKEN      a shared password the script checks
Without the list link nothing trades. Without the webhook the book lives in the app's database only, and the Paper tab says so.
"""
from __future__ import annotations

import csv
import io
import json
import os
import urllib.parse
import urllib.request

from .config import fetch_sheet_csv

MAX_TICKERS = 20


def configured() -> dict:
    return {"list": os.getenv("STOCKWATCH_PAPER_LIST_URL", "").strip(), "webhook": os.getenv("STOCKWATCH_PAPER_WEBHOOK", "").strip(),
            "token": os.getenv("STOCKWATCH_PAPER_TOKEN", "").strip()}


def parse_list(text: str) -> list[str]:
    """Tickers with Paper = yes (or true, y, 1), upper case, no repeats, at most MAX_TICKERS."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    head = [c.strip().lower() for c in rows[0]]
    if "ticker" not in head:
        return []
    ti = head.index("ticker")
    pi = head.index("paper") if "paper" in head else None
    out: list[str] = []
    for r in rows[1:]:
        if len(r) <= ti or not r[ti].strip():
            continue
        on = True if pi is None else (len(r) > pi and r[pi].strip().lower() in ("yes", "y", "true", "1", "paper"))
        t = r[ti].strip().upper()
        if on and t not in out:
            out.append(t)
    return out[:MAX_TICKERS]


def load_list(url: str) -> list[str]:
    return parse_list(fetch_sheet_csv(url))


def _call(url: str, body: dict | None, timeout: float = 25) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        txt = r.read().decode("utf-8", "replace")
    return json.loads(txt) if txt.strip().startswith("{") else {"ok": False, "error": "the link did not return data"}


def push(webhook: str, token: str, book: dict, report: dict) -> dict:
    """Send the whole book and today's report; the script rewrites the Trades, Blocked buys and Daily report tabs."""
    return _call(webhook, {"token": token, "book": book, "report": report})


def pull(webhook: str, token: str) -> dict | None:
    """The book the script last saved, or None when there is none or the link failed."""
    try:
        res = _call(webhook + ("&" if "?" in webhook else "?") + urllib.parse.urlencode({"token": token}), None)
    except Exception:
        return None
    return res.get("book") if res.get("ok") else None
