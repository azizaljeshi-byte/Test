"""New S&P 500 buy setups, one row each, in `S&P buy setups.csv` beside the Quick sheets (owner, 11 Nov: "put them on a sheet").

Appended by the app whenever the whole-S&P scan finds a buy setup that is new (the same de-duplicated list that becomes an alert).
A missing Drive folder or a locked file never stops the scan: the reason is logged and the rows are tried again with the next scan's
(they are not lost: the stored scan still lists them). Plain CSV, so it opens as a sheet; no key, link or topic is involved.
"""
from __future__ import annotations

import csv
import logging
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
