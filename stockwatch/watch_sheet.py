"""Owner's close watchlist. Sheet I/O runs only on the tracker's worker thread."""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KEY = "watch_sheet"
EVERY_S = 300
MAX_ROWS = 60  # technical ceiling on additions to the normal Yahoo sweep, not a trading rule
TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
LOCAL = ZoneInfo("Asia/Riyadh")


def sheet_env(env=None):
    env = dict(os.environ if env is None else env)
    env["STOCKWATCH_SMALLCAP_SHEET_URL"] = (env.get("STOCKWATCH_WATCH_SHEET_URL") or
                                           env.get("STOCKWATCH_SMALLCAP_SHEET_URL") or "").strip()
    return env


def configured(env=None):
    return bool(sheet_env(env)["STOCKWATCH_SMALLCAP_SHEET_URL"])


def state(store):
    try:
        saved = json.loads(store.get_setting(KEY) or "{}")
        return saved if isinstance(saved, dict) else {}
    except (TypeError, ValueError):
        return {}


def read(sheet, feedback=None):
    """Return unique valid {ticker, comment} items in sheet order.

    Optional feedback collects physical row numbers, including invalid/duplicate/over-limit
    rows, so status writes never shift the owner's rows. First 60 distinct valid tickers join.
    """
    items, seen = [], set()
    for row_num, cells in enumerate(sheet.worksheet("Watch").get("A2:B"), 2):
        ticker = str(cells[0]).strip().upper() if cells else ""
        if not ticker:
            continue
        comment = str(cells[1]).strip() if len(cells) > 1 else ""
        status = "Not a ticker" if not TICKER.fullmatch(ticker) else ""
        if not status and ticker not in seen:
            if len(items) >= MAX_ROWS:
                status = "Over the 60 limit"
            else:
                seen.add(ticker)
                items.append({"ticker": ticker, "comment": comment})
        if feedback is not None:
            feedback.append({"row": row_num, "ticker": ticker, "status": status})
    return items


def write_back(sheet, rows):
    """One RAW batch, C:H only. Never clear, reorder or write the owner's A:B cells."""
    data = [{"range": f"C{r['row']}:H{r['row']}", "values": [r["values"]]}
            for r in rows if r.get("ticker")]
    if data:
        sheet.worksheet("Watch").batch_update(data, value_input_option="RAW")


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _values(store, ticker, known, now, status=""):
    checked = now.astimezone(LOCAL).strftime("%d %b %H:%M")
    if status:
        return [status, "", "unknown", "unknown", "unknown", checked]
    from . import ui
    snap = store.snapshot(ticker)
    pp = ui.price_parts(snap) if snap else {}
    price, day = _number(pp.get("price")), _number(pp.get("day"))
    p = (snap or {}).get("payload") or {}
    oc = ui.new_call(snap) if snap else {}
    status = "Already in your list" if ticker in known else "Watching"
    if price is None or price <= 0:
        status = "No prices found"
        price = None
    return [status, (p.get("profile") or {}).get("name") or p.get("name") or "unknown",
            price if price is not None else "unknown", f"{day * 100:+.1f}%" if day is not None else "unknown",
            oc.get("call") if oc.get("known") and oc.get("call") else "unknown", checked]


def record_failure(store):
    previous = state(store)
    result = {"at": previous.get("at"), "items": previous.get("items") or [],
              "error": "Watch tab could not be read; check the link, service-account key and access."}
    store.set_setting(KEY, json.dumps(result))
    return result


def sync(store, known=(), sheet=None, now=None):
    """Successful reads replace the list, even if empty. Failed reads keep the previous list.

    Only cached snapshots are read for feedback; this function never calls a market provider.
    All exception text is discarded because it can contain the private URL or credentials.
    """
    now = now or datetime.now(timezone.utc)
    try:
        if sheet is None:
            from .smallcap_sheet import connect
            sheet = connect(sheet_env())
        rows = []
        items = read(sheet, rows)
    except Exception:
        return record_failure(store)
    result = {"at": now.isoformat(), "items": items, "error": None}
    # Keep a successful read even if writing feedback fails.
    store.set_setting(KEY, json.dumps(result))
    try:
        for row in rows:
            row["values"] = _values(store, row["ticker"], known, now, row["status"])
        write_back(sheet, rows)
    except Exception:
        result["error"] = "Watch tab read, but status cells could not be updated; check edit access and connection."
        store.set_setting(KEY, json.dumps(result))
    return result


def items(store):
    """Validate stored items too, so a malformed cache can never add invalid symbols to a sweep."""
    out, seen = [], set()
    for item in state(store).get("items") or []:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").strip().upper()
        if TICKER.fullmatch(ticker) and ticker not in seen:
            out.append({"ticker": ticker, "comment": str(item.get("comment") or "")})
            seen.add(ticker)
        if len(out) >= MAX_ROWS:
            break
    return out


def status_line(store):
    saved = state(store)
    if saved.get("error"):
        return saved["error"]
    try:
        at = datetime.fromisoformat(saved["at"]).astimezone(LOCAL).strftime("%H:%M")
    except (KeyError, TypeError, ValueError):
        return "Watch tab: waiting for first read" if configured() else "Watch tab: not configured"
    return f"Watch tab: {len(items(store))} stocks, read {at} (Riyadh)"
