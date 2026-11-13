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
TECH_KEYS = ["support", "major_support", "resistance", "sma50", "sma200", "ema10", "ema20", "rsi", "macd", "atr_pct", "vol_x", "from_high"]
COLS = ["Date (NY)", "Time (NY)", "Ticker", "Name", "Sector", "Price", "Score", "Why", "Plan", "Earnings in (days)", "Risks",
        "Support", "Major support (exit line)", "Resistance", "SMA 50", "SMA 200", "EMA 10", "EMA 20", "RSI", "MACD", "Daily swing %",
        "Volume vs normal (x)", "From 52w high %"]


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
            sigs, plan, r.get("earnings_days") if r.get("earnings_days") is not None else "", "; ".join((r.get("top_risks") or [])[:2])] + [
        (r.get("tech") or {}).get(k, "") for k in TECH_KEYS]


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
        if not new:
            with open(path, newline="", encoding="utf-8-sig") as f:
                old = list(csv.reader(f))
            if old and old[0] != COLS:                       # columns were added: rewrite the file with the new header, old rows padded
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f)
                    w.writerow(COLS)
                    for r in old[1:]:
                        w.writerow(r + [""] * (len(COLS) - len(r)))
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
    if not env:
        return ("Google Sheet not set up: this app window does not see STOCKWATCH_SMALLCAP_SHEET_URL (or STOCKWATCH_BUYSETUP_SHEET_URL). "
                "Set it in Windows, then close and reopen the app. The CSV file still gets every setup.")
    if not waiting:
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
            have = {tuple(str(x) for x in r[:3]) for r in waiting}
            waiting = [r for r in csv_rows() if tuple(r[:3]) not in have] + waiting   # a new tab starts with every setup the CSV holds
        if tab.col_count < len(COLS):                       # columns were added since the tab was made: widen it and rewrite the header
            tab.add_cols(len(COLS) - tab.col_count)
        tab.update(range_name="A1", values=[COLS], value_input_option="RAW")
        tab.append_rows(waiting, value_input_option="RAW")
        style_tab(tab, sheet)
        store.set_setting(PENDING_KEY, "[]")
        return ""
    except Exception as e:
        store.set_setting(PENDING_KEY, json.dumps(waiting[-500:], default=str))
        name = type(e).__name__
        log.warning("buy setups Google Sheet not written (%s)", name)
        return f"Google Sheet not written ({name}); {len(waiting)} row(s) wait for the next scan"


def csv_rows(folder: Path | None = None) -> list[list]:
    """Rows already in the CSV file (without its header); [] if there is none."""
    try:
        if folder is None:
            from . import quick
            folder = quick.log_dir()
        with open(folder / FILE, newline="", encoding="utf-8-sig") as f:
            return [r for r in list(csv.reader(f))[1:] if r]
    except Exception:
        return []


# ---- look of the Google tab (matches the Shortlist tab: navy header, Roboto, no gridlines)
NAVY = {"red": 0.11, "green": 0.176, "blue": 0.298}
WIDTHS = [88, 58, 72, 190, 150, 78, 62, 340, 300, 88, 280, 82, 96, 90, 74, 74, 74, 74, 56, 76, 82, 92, 92]            # one per column in COLS


def _rgb(r, g, b):
    return {"red": r, "green": g, "blue": b}


def format_requests(sheet_id: int) -> list[dict]:
    """spreadsheets.batchUpdate requests that style the tab: frozen header and ticker columns, navy header, banded rows, a number format
    for price and score, wrapped text, and colour on the plan (green buy, amber wait, red don't), score and near earnings."""
    n = len(COLS)

    def rng(r0=0, r1=2000, c0=0, c1=n):
        return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1}

    def cond(c, kind, text, bg, fg=None, bold=False):
        fmt = {"backgroundColor": bg, "textFormat": {"bold": bold, **({"foregroundColor": fg} if fg else {})}}
        return {"addConditionalFormatRule": {"index": 0, "rule": {"ranges": [rng(1, 2000, c, c + 1)], "booleanRule": {
            "condition": {"type": kind, "values": [{"userEnteredValue": text}]}, "format": fmt}}}}

    out = [
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "tabColorStyle": {"rgbColor": _rgb(0.16, 0.38, 0.75)},
                                                  "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 3, "hideGridlines": True}},
                                   "fields": "tabColorStyle,gridProperties.frozenRowCount,gridProperties.frozenColumnCount,gridProperties.hideGridlines"}},
        {"repeatCell": {"range": rng(), "cell": {"userEnteredFormat": {
            "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP", "textFormat": {"fontFamily": "Roboto", "fontSize": 10}}},
            "fields": "userEnteredFormat(verticalAlignment,wrapStrategy,textFormat)"}},
        {"repeatCell": {"range": rng(0, 1), "cell": {"userEnteredFormat": {
            "backgroundColor": NAVY, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP",
            "textFormat": {"foregroundColor": _rgb(1, 1, 1), "fontFamily": "Roboto", "fontSize": 10, "bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat)"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": 38}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 1, "endIndex": 2000},
                                       "properties": {"pixelSize": 44}, "fields": "pixelSize"}},
        {"addBanding": {"bandedRange": {"range": rng(1, 2000), "rowProperties": {
            "firstBandColorStyle": {"rgbColor": _rgb(1, 1, 1)}, "secondBandColorStyle": {"rgbColor": _rgb(0.94, 0.96, 0.98)}}}}},
        {"repeatCell": {"range": rng(1, 2000, 2, 3), "cell": {"userEnteredFormat": {
            "horizontalAlignment": "CENTER", "textFormat": {"bold": True, "fontSize": 11}}},
            "fields": "userEnteredFormat(horizontalAlignment,textFormat.bold,textFormat.fontSize)"}},
        {"repeatCell": {"range": rng(1, 2000, 5, 6), "cell": {"userEnteredFormat": {
            "horizontalAlignment": "RIGHT", "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}}},
            "fields": "userEnteredFormat(horizontalAlignment,numberFormat)"}},
        {"repeatCell": {"range": rng(1, 2000, 6, 7), "cell": {"userEnteredFormat": {
            "horizontalAlignment": "CENTER", "numberFormat": {"type": "NUMBER", "pattern": "0.0"}, "textFormat": {"bold": True}}},
            "fields": "userEnteredFormat(horizontalAlignment,numberFormat,textFormat.bold)"}},
        {"repeatCell": {"range": rng(1, 2000, 9, 10), "cell": {"userEnteredFormat": {
            "horizontalAlignment": "CENTER", "numberFormat": {"type": "NUMBER", "pattern": "0"}}},
            "fields": "userEnteredFormat(horizontalAlignment,numberFormat)"}},
        {"repeatCell": {"range": rng(1, 2000, 0, 2), "cell": {"userEnteredFormat": {
            "horizontalAlignment": "CENTER", "textFormat": {"foregroundColor": _rgb(0.4, 0.45, 0.55)}}},
            "fields": "userEnteredFormat(horizontalAlignment,textFormat.foregroundColor)"}},
        {"repeatCell": {"range": rng(1, 2000, 11, 17), "cell": {"userEnteredFormat": {
            "horizontalAlignment": "RIGHT", "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}}},
            "fields": "userEnteredFormat(horizontalAlignment,numberFormat)"}},
        {"repeatCell": {"range": rng(1, 2000, 17, 23), "cell": {"userEnteredFormat": {
            "horizontalAlignment": "CENTER", "numberFormat": {"type": "NUMBER", "pattern": "0.0"}}},
            "fields": "userEnteredFormat(horizontalAlignment,numberFormat)"}},
        {"setBasicFilter": {"filter": {"range": rng(0, 2000)}}},
    ]
    out += [{"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                                           "properties": {"pixelSize": w}, "fields": "pixelSize"}} for i, w in enumerate(WIDTHS)]
    # colours (first rule added ends up on top; they never overlap)
    out += [cond(8, "TEXT_STARTS_WITH", "don't buy", _rgb(0.99, 0.89, 0.88), _rgb(0.70, 0.15, 0.12)),
            cond(8, "TEXT_STARTS_WITH", "wait", _rgb(1, 0.96, 0.83), _rgb(0.55, 0.38, 0.0)),
            cond(8, "TEXT_STARTS_WITH", "buy", _rgb(0.85, 0.94, 0.87), _rgb(0.09, 0.42, 0.20), True),
            cond(6, "NUMBER_GREATER_THAN_EQ", "80", _rgb(0.78, 0.92, 0.82), _rgb(0.09, 0.42, 0.20), True),
            cond(17, "NUMBER_GREATER_THAN_EQ", "70", _rgb(1, 0.96, 0.83), _rgb(0.55, 0.38, 0.0), True),
            cond(17, "NUMBER_LESS_THAN_EQ", "30", _rgb(0.86, 0.92, 0.99), _rgb(0.10, 0.30, 0.65), True),
            cond(18, "TEXT_EQ", "bullish", _rgb(0.85, 0.94, 0.87), _rgb(0.09, 0.42, 0.20)),
            cond(18, "TEXT_EQ", "bearish", _rgb(0.99, 0.89, 0.88), _rgb(0.70, 0.15, 0.12)),
            cond(20, "NUMBER_GREATER_THAN_EQ", "1.3", _rgb(0.85, 0.94, 0.87), _rgb(0.09, 0.42, 0.20), True),
            cond(9, "NUMBER_LESS_THAN_EQ", "7", _rgb(0.99, 0.89, 0.88), _rgb(0.70, 0.15, 0.12), True)]
    for r in out:                                           # plain dotted field masks (a.b,a.c): every client accepts those
        body = next(iter(r.values()))
        if isinstance(body, dict) and "fields" in body:
            body["fields"] = _dotted(body["fields"])
    return out


def _dotted(mask: str) -> str:
    """'userEnteredFormat(a,b)' -> 'userEnteredFormat.a,userEnteredFormat.b'."""
    import re
    return re.sub(r"(\w+)\(([^)]*)\)", lambda m: ",".join(f"{m.group(1)}.{x}" for x in m.group(2).split(",")), mask)


def style_tab(tab, sheet) -> None:
    """Style a tab once (when it is new, or has never been given a frozen header). Never raises: looks are not worth a lost row."""
    try:
        if getattr(tab, "frozen_row_count", 0):
            return
        sheet.batch_update({"requests": format_requests(tab.id)})
    except Exception as e:
        log.warning("buy setups tab not styled (%s)", type(e).__name__)
