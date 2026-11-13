"""Every "New buy signal" / "Add signal" the app pushes, one row each, on a Google Sheet tab (owner, 13 Nov: "only buy signals",
with a date field to see what came on each day).

These are the verdict changes on stocks the app already tracks (`events.call_flips`), not the whole-S&P scan setups (those go to
`buy_setups_log`). Rows go to `Buy signals.csv` beside the Quick sheets and to the "Buy signals" tab of the Google Sheet (env
STOCKWATCH_BUYSIGNALS_SHEET_URL, else the same links the buy-setup log uses). A second tab, "Buy signals by day", has a date
picker in B1 and shows only that day's rows (a FILTER formula), so nothing is copied twice.

Readings come from the stock's stored snapshot (no market request). Anything missing is left blank, never 0. Nothing here may stop
the sweep: errors are logged by type only, so a link or key can never reach a log line, and unsent rows wait for the next try.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from .data import NY

log = logging.getLogger("stockwatch.buy_signals")
FILE = "Buy signals.csv"
TAB = "Buy signals"
DAY_TAB = "Buy signals by day"
PENDING_KEY = "buy_signals_pending"
ERROR_KEY = "buy_signals_sheet_error"
COLS = ["Date (NY)", "Time (NY)", "Ticker", "Name", "Sector", "Signal", "Previous call", "You own it", "Price", "Why",
        "Entry plan", "Support", "Major support (exit line)", "Resistance", "SMA 20", "SMA 50", "SMA 200", "RSI", "MACD",
        "Daily swing %", "Volume vs normal (x)", "From 52w high %"]
WORDS = {"BUY": "New buy signal", "ADD": "Add signal"}
_lock = threading.Lock()


def _num(v, d=2):
    return round(v, d) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf") else ""


def _first(zones: dict, kind: str, edge: str):
    try:
        z = (zones.get(kind) or [])[0]
        return z.get(edge)
    except (IndexError, AttributeError, TypeError):
        return None


def row_of(snap: dict, before: str | None, owned: bool, now: datetime | None = None) -> list:
    """One sheet row from a stored snapshot. Unknown readings are blank."""
    now = (now or datetime.now(NY)).astimezone(NY)
    p = snap.get("payload") or {}
    t = p.get("technical") or {}
    oc = t.get("one_call") if isinstance(t.get("one_call"), dict) else {}
    zones = t.get("zones") if isinstance(t.get("zones"), dict) and t["zones"].get("known") else {}
    facts = ((t.get("momentum") or {}).get("facts") or {}) if isinstance(t.get("momentum"), dict) else {}
    plan = p.get("plan") or {}
    price = t.get("price") if isinstance(t.get("price"), (int, float)) else snap.get("price")
    hi = t.get("high_52w")
    atr = t.get("atr")
    macd = facts.get("macd_above_signal")
    entry = plan.get("trigger") or ""
    if plan.get("stop") and entry:
        entry += f" · stop {_num(plan['stop'])}"
    profile = p.get("profile") if isinstance(p.get("profile"), dict) else {}
    call = oc.get("call")
    return [now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), snap.get("ticker"), p.get("name") or profile.get("name") or "",
            profile.get("sector") or "", WORDS.get(call, str(call or "")), WORDS.get(before, str(before or "")), "yes" if owned else "no",
            _num(price), str(oc.get("why") or "")[:300], entry, _num(_first(zones, "support", "high")), _num(oc.get("exit_line")),
            _num(_first(zones, "resistance", "low")), _num(plan.get("sma20")), _num(t.get("sma50")), _num(t.get("sma200")),
            _num(t.get("rsi"), 1), "bullish" if macd is True else "bearish" if macd is False else "",
            _num(atr / price * 100, 1) if isinstance(atr, (int, float)) and isinstance(price, (int, float)) and price else "",
            _num(t.get("volume_ratio")), _num((price / hi - 1) * 100, 1) if isinstance(hi, (int, float)) and hi and isinstance(price, (int, float)) else ""]


def append(rows: list[list], folder: Path | None = None) -> str:
    """Add rows to the CSV. Returns '' or why it could not."""
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
            w.writerows(rows)
        return ""
    except Exception as e:
        log.warning("buy signals file not written (%s)", type(e).__name__)
        return f"could not write the file ({type(e).__name__})"


def sheet_env() -> str | None:
    for env in ("STOCKWATCH_BUYSIGNALS_SHEET_URL", "STOCKWATCH_BUYSETUP_SHEET_URL", "STOCKWATCH_SMALLCAP_SHEET_URL"):
        if os.environ.get(env, "").strip():
            return env
    return None


def _rgb(r, g, b):
    return {"red": r, "green": g, "blue": b}


NAVY = _rgb(0.11, 0.176, 0.298)
WIDTHS = [88, 58, 72, 190, 140, 110, 110, 62, 76, 320, 260, 82, 96, 90, 74, 74, 74, 56, 76, 82, 92, 92]


def format_requests(sheet_id: int) -> list[dict]:
    """Same look as the other tabs: navy header, Roboto, banded rows, frozen header and ticker columns, filter, colour on RSI and MACD."""
    n = len(COLS)

    def rng(r0=0, r1=2000, c0=0, c1=n):
        return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1}

    def cell(r, fmt, fields):
        return {"repeatCell": {"range": r, "cell": {"userEnteredFormat": fmt}, "fields": fields}}

    def cond(c, kind, text, bg, fg, bold=False):
        return {"addConditionalFormatRule": {"index": 0, "rule": {"ranges": [rng(1, 2000, c, c + 1)], "booleanRule": {
            "condition": {"type": kind, "values": [{"userEnteredValue": text}]},
            "format": {"backgroundColor": bg, "textFormat": {"bold": bold, "foregroundColor": fg}}}}}}

    out = [
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "tabColorStyle": {"rgbColor": _rgb(0.09, 0.42, 0.20)},
                                                  "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 3, "hideGridlines": True}},
                                   "fields": "tabColorStyle,gridProperties.frozenRowCount,gridProperties.frozenColumnCount,gridProperties.hideGridlines"}},
        cell(rng(), {"verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP", "textFormat": {"fontFamily": "Roboto", "fontSize": 10}},
             "userEnteredFormat.verticalAlignment,userEnteredFormat.wrapStrategy,userEnteredFormat.textFormat"),
        cell(rng(0, 1), {"backgroundColor": NAVY, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP",
                         "textFormat": {"foregroundColor": _rgb(1, 1, 1), "fontFamily": "Roboto", "fontSize": 10, "bold": True}},
             "userEnteredFormat.backgroundColor,userEnteredFormat.horizontalAlignment,userEnteredFormat.verticalAlignment,"
             "userEnteredFormat.wrapStrategy,userEnteredFormat.textFormat"),
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": 38}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 1, "endIndex": 2000},
                                       "properties": {"pixelSize": 44}, "fields": "pixelSize"}},
        {"addBanding": {"bandedRange": {"range": rng(1, 2000), "rowProperties": {
            "firstBandColorStyle": {"rgbColor": _rgb(1, 1, 1)}, "secondBandColorStyle": {"rgbColor": _rgb(0.94, 0.96, 0.98)}}}}},
        cell(rng(1, 2000, 2, 3), {"horizontalAlignment": "CENTER", "textFormat": {"bold": True, "fontSize": 11}},
             "userEnteredFormat.horizontalAlignment,userEnteredFormat.textFormat.bold,userEnteredFormat.textFormat.fontSize"),
        cell(rng(1, 2000, 0, 2), {"horizontalAlignment": "CENTER", "textFormat": {"foregroundColor": _rgb(0.4, 0.45, 0.55)}},
             "userEnteredFormat.horizontalAlignment,userEnteredFormat.textFormat.foregroundColor"),
        cell(rng(1, 2000, 8, 9), {"horizontalAlignment": "RIGHT", "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}},
             "userEnteredFormat.horizontalAlignment,userEnteredFormat.numberFormat"),
        cell(rng(1, 2000, 11, 17), {"horizontalAlignment": "RIGHT", "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}},
             "userEnteredFormat.horizontalAlignment,userEnteredFormat.numberFormat"),
        cell(rng(1, 2000, 17, 22), {"horizontalAlignment": "CENTER", "numberFormat": {"type": "NUMBER", "pattern": "0.0"}},
             "userEnteredFormat.horizontalAlignment,userEnteredFormat.numberFormat"),
        {"setBasicFilter": {"filter": {"range": rng(0, 2000)}}},
    ]
    out += [{"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                                           "properties": {"pixelSize": w}, "fields": "pixelSize"}} for i, w in enumerate(WIDTHS)]
    out += [cond(5, "TEXT_EQ", "New buy signal", _rgb(0.85, 0.94, 0.87), _rgb(0.09, 0.42, 0.20), True),
            cond(5, "TEXT_EQ", "Add signal", _rgb(0.86, 0.92, 0.99), _rgb(0.10, 0.30, 0.65), True),
            cond(17, "NUMBER_GREATER_THAN_EQ", "70", _rgb(1, 0.96, 0.83), _rgb(0.55, 0.38, 0.0), True),
            cond(17, "NUMBER_LESS_THAN_EQ", "30", _rgb(0.86, 0.92, 0.99), _rgb(0.10, 0.30, 0.65), True),
            cond(18, "TEXT_EQ", "bullish", _rgb(0.85, 0.94, 0.87), _rgb(0.09, 0.42, 0.20)),
            cond(18, "TEXT_EQ", "bearish", _rgb(0.99, 0.89, 0.88), _rgb(0.70, 0.15, 0.12))]
    return out


def day_tab_formulas(last_col: str) -> list[tuple[str, str]]:
    """(cell, content) pairs for the day-picker tab: B1 the date, D1 a count, row 2 the headers, A3 the filtered rows."""
    src = f"'{TAB}'"
    return [("A1", "Pick a day"),
            ("B1", "=TODAY()"),
            ("D1", f'=IFERROR(COUNTIF({src}!A2:A,TEXT($B$1,"yyyy-mm-dd"))&" buy signals on this day (New York date)","")'),
            ("A2", f"={src}!A1:{last_col}1"),
            ("A3", f'=IFERROR(FILTER({src}!A2:{last_col},{src}!A2:A=TEXT($B$1,"yyyy-mm-dd")),"No buy signals on this day")')]


def style_day_tab(tab, sheet) -> None:
    """Date picker in B1 (dropdown calendar), navy header row, the same column widths as the log."""
    r = {"sheetId": tab.id}
    n = len(COLS)
    reqs = [
        {"setDataValidation": {"range": {**r, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 1, "endColumnIndex": 2},
                               "rule": {"condition": {"type": "DATE_IS_VALID"}, "showCustomUi": True, "strict": True,
                                        "inputMessage": "Pick a day (New York date) to see its buy signals"}}},
        {"updateSheetProperties": {"properties": {**r, "tabColorStyle": {"rgbColor": _rgb(0.09, 0.42, 0.20)},
                                                  "gridProperties": {"frozenRowCount": 2, "hideGridlines": True}},
                                   "fields": "tabColorStyle,gridProperties.frozenRowCount,gridProperties.hideGridlines"}},
        {"repeatCell": {"range": {**r, "startRowIndex": 0, "endRowIndex": 2000, "startColumnIndex": 0, "endColumnIndex": n},
                        "cell": {"userEnteredFormat": {"verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP",
                                                       "textFormat": {"fontFamily": "Roboto", "fontSize": 10}}},
                        "fields": "userEnteredFormat.verticalAlignment,userEnteredFormat.wrapStrategy,userEnteredFormat.textFormat"}},
        {"repeatCell": {"range": {**r, "startRowIndex": 1, "endRowIndex": 2, "startColumnIndex": 0, "endColumnIndex": n},
                        "cell": {"userEnteredFormat": {"backgroundColor": NAVY, "horizontalAlignment": "CENTER",
                                                       "textFormat": {"foregroundColor": _rgb(1, 1, 1), "bold": True, "fontFamily": "Roboto", "fontSize": 10}}},
                        "fields": "userEnteredFormat.backgroundColor,userEnteredFormat.horizontalAlignment,userEnteredFormat.textFormat"}},
        {"repeatCell": {"range": {**r, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 2},
                        "cell": {"userEnteredFormat": {"backgroundColor": _rgb(0.85, 0.94, 0.87), "horizontalAlignment": "CENTER",
                                                       "numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"},
                                                       "textFormat": {"bold": True, "fontSize": 12, "fontFamily": "Roboto"}}},
                        "fields": "userEnteredFormat.backgroundColor,userEnteredFormat.horizontalAlignment,userEnteredFormat.numberFormat,userEnteredFormat.textFormat"}},
        {"updateDimensionProperties": {"range": {**r, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": 40}, "fields": "pixelSize"}},
    ]
    reqs += [{"updateDimensionProperties": {"range": {**r, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                                            "properties": {"pixelSize": w}, "fields": "pixelSize"}} for i, w in enumerate(WIDTHS)]
    try:
        sheet.batch_update({"requests": reqs})
    except Exception as e:
        log.warning("buy signals day tab not styled (%s)", type(e).__name__)


def _col_letter(n: int) -> str:
    s = ""
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def to_google(store, rows: list[list] | None = None, connect=None) -> str:
    """Send the rows (and any that failed before) to the tab. Returns '' (sent, nothing to send, or not configured) or why not."""
    with _lock:
        raw = store.get_setting(PENDING_KEY)
        try:
            waiting = json.loads(raw) if raw else []
        except ValueError:
            waiting = []
        waiting += rows or []
        if waiting:
            store.set_setting(PENDING_KEY, json.dumps(waiting[-500:], default=str))        # saved first: a crash cannot lose them
        env = sheet_env()
        if not env:
            return ("Google Sheet not set up: this app window does not see STOCKWATCH_SMALLCAP_SHEET_URL. Set it in Windows, "
                    "then close and reopen the app. The CSV file still gets every signal.")
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
            tab.append_rows(waiting, value_input_option="RAW")
            store.set_setting(PENDING_KEY, "[]")
            _ensure_formatting(tab, sheet)
            return ""
        except Exception as e:
            log.warning("buy signals Google Sheet not written (%s)", type(e).__name__)
            return f"Google Sheet not written ({type(e).__name__}); {len(waiting)} row(s) wait for the next try"


def _ensure_formatting(tab, sheet) -> None:
    """Style the log once, and create the day-picker tab once. Looks are never worth a lost row."""
    try:
        import gspread
        if not getattr(tab, "frozen_row_count", 0):
            sheet.batch_update({"requests": format_requests(tab.id)})
        try:
            sheet.worksheet(DAY_TAB)
        except gspread.WorksheetNotFound:
            day = sheet.add_worksheet(title=DAY_TAB, rows=2000, cols=len(COLS))
            last = _col_letter(len(COLS))
            for cell_name, content in day_tab_formulas(last):
                day.update(range_name=cell_name, values=[[content]], value_input_option="USER_ENTERED")
            style_day_tab(day, sheet)
    except Exception as e:
        log.warning("buy signals tabs not styled (%s)", type(e).__name__)


def record(store, items: list[tuple[dict, str | None, bool]], now: datetime | None = None, background: bool = True) -> str:
    """Called by `events.call_flips` with (snapshot, previous call, owned) for each buy or add signal. The CSV is written at once;
    the Google part runs on its own thread so a slow Google can never hold up a sweep. Returns the CSV error ('' if fine)."""
    rows = []
    for snap, before, owned in items:
        try:
            rows.append(row_of(snap, before, owned, now))
        except Exception as e:
            log.warning("buy signal row skipped (%s)", type(e).__name__)
    err = append(rows)
    if not rows and not store.get_setting(PENDING_KEY):
        return err

    def send():
        try:
            gerr = to_google(store, rows)
            store.set_setting(ERROR_KEY, "; ".join(x for x in (err, gerr) if x))
        except Exception as e:
            log.warning("buy signals send failed (%s)", type(e).__name__)

    if background:
        threading.Thread(target=send, name="stockwatch-buy-signals", daemon=True).start()
    else:
        send()
    return err
