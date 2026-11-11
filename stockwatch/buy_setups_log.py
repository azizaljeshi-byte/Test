"""New S&P 500 buy setups, one row each, in `S&P buy setups.csv` beside the Quick sheets (owner, 11 Nov: "put them on a sheet").

Appended by the app whenever the whole-S&P scan finds a buy setup that is new (the same de-duplicated list that becomes an alert).
If a Google Sheet is set up (env STOCKWATCH_BUYSETUP_SHEET_URL, or else the small-cap sheet's STOCKWATCH_SMALLCAP_SHEET_URL, with the same
service-account key) the rows also go to its "S&P buy setups" tab; rows that could not be sent wait in the settings table and go with
the next scan. A missing Drive folder or a locked file never stops the scan: the reason is logged and the rows are tried again with the next scan's
(they are not lost: the stored scan still lists them). Plain CSV, so it opens as a sheet; no key, link or topic is involved.
"""
from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from . import tradeplan
from .data import NY

log = logging.getLogger("stockwatch.buy_setups")
FILE = "S&P buy setups.csv"
COLS = ["Date (NY)", "Time (NY)", "Ticker", "Name", "Sector", "Price", "Score", "Why", "Plan", "Earnings in (days)", "Risks"]


def row_of(r: dict, now: datetime | None = None) -> list:
    now = (now or datetime.now(NY)).astimezone(NY)
    sigs = "; ".join((r.get("triggers") or [])[:2]) or "; ".join((r.get("top_signals") or [])[:2])
    plan = ""
    try:
        plan = tradeplan.summary(r.get("plan")) if r.get("plan") else ""
    except Exception:
        pass
    price = r.get("price")
    return [now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), r.get("ticker"), r.get("name") or "", r.get("sector") or "",
            round(price, 2) if isinstance(price, (int, float)) else "", round(r["composite"], 1) if isinstance(r.get("composite"), (int, float)) else "",
            sigs, plan, r.get("earnings_days") if r.get("earnings_days") is not None else "", "; ".join((r.get("top_risks") or [])[:2])]


def append(rows: list[dict], folder: Path | None = None, now: datetime | None = None) -> str:
    """Add the rows to the sheet file. Returns '' or why it could not."""
    if not rows:
        return ""
    try:
        if folder is None:
            from . import quick
            folder = quick.log_dir()
        if not (folder.parent.is_dir() or folder.is_dir()):
            return f"the Drive folder was not found: {folder.parent}"
        folder.mkdir(exist_ok=True)
        path = folder / FILE
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(COLS)
            for r in rows:
                w.writerow(row_of(r, now))
        return ""
    except Exception as e:
        log.warning("buy setups sheet not written: %s", e)
        return f"could not write the sheet file: {e}"[:200]


TAB = "S&P buy setups"
PENDING_KEY = "buy_setups_pending"


def sheet_env() -> str | None:
    """Which link variable is set: a sheet of its own first, otherwise the small-cap sheet (a new tab in it)."""
    for env in ("STOCKWATCH_BUYSETUP_SHEET_URL", "STOCKWATCH_SMALLCAP_SHEET_URL"):
        if os.environ.get(env, "").strip():
            return env
    return None


def to_google(store, rows: list[dict], now: datetime | None = None, connect=None) -> str:
    """Append the rows (and any that failed before) to the Google Sheet tab. Returns '' (sent or not configured) or why not.
    Nothing here is allowed to stop the scan; the error text never holds the link or the key."""
    raw = store.get_setting(PENDING_KEY)
    waiting = json.loads(raw) if raw else []
    waiting += [row_of(r, now) for r in rows]
    env = sheet_env()
    if not env or not waiting:
        return ""
    try:
        if connect is None:
            from . import smallcap_sheet
            sheet = smallcap_sheet.connect(env)
        else:
            sheet = connect(env)
        import gspread
        try:
            tab = sheet.worksheet(TAB)
        except gspread.WorksheetNotFound:
            tab = sheet.add_worksheet(title=TAB, rows=2000, cols=len(COLS))
            tab.update(range_name="A1", values=[COLS], value_input_option="RAW")
        tab.append_rows(waiting, value_input_option="RAW")
        store.set_setting(PENDING_KEY, "[]")
        return ""
    except Exception as e:
        store.set_setting(PENDING_KEY, json.dumps(waiting[-500:], default=str))
        name = type(e).__name__
        log.warning("buy setups Google Sheet not written (%s)", name)
        return f"Google Sheet not written ({name}); {len(waiting)} row(s) wait for the next scan"
