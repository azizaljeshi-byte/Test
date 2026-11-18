"""Break watch: a live test of the owner's break hypothesis on real stocks, shown on his Google Sheet (owner, 18 Nov).

What is watched: a stock's first close beyond its prior 20-day closing high ("up", it broke resistance) or low ("down", it broke support).
The `Break watch` tab lists only the breaks that are live now (inside their 5 sessions), each with a plain call and the share of similar
breaks that went on in the 5-year back-test, so it says what is likely to keep moving. A finished break leaves that list and is counted in
the `Break scorecard`, which keeps checking the idea against real days (live results beside the back-test).

The rules were fixed in advance from 5 years of the 150 most-traded S&P stocks (18,524 breaks) and are not tuned afterwards:
  qualified (known on the break day) : closes at least 0.5 normal daily swings beyond the level AND volume at least 1.2x its 20-day
                                       average for an up break (1.3x for a down break).
  confirmed (known after day 1)      : qualified, and day 1 closes beyond the level, in the strong half of its range (upper half for up,
                                       lower half for down), on volume of at least 1.0x.
  continued                          : no close back across the level in 5 sessions and a further move in the break direction by day 5.
  reversed                           : a close back across the level within 5 sessions (known as soon as it happens).
The back-test numbers are in BASELINE so the scorecard shows them next to the live ones. Information only: no score, signal,
verdict, trade plan or paper rule reads any of this.

Only completed daily bars count: today's bar is dropped until the New York session is over. Unknown data (too little history, zero
volume) is skipped, never scored as 0. The sheet is rewritten from the stored results at each whole-S&P scan, so a failed write loses
nothing; errors are logged by type only, so a link or key can never reach a log line.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .data import NY

log = logging.getLogger("stockwatch.break_watch")
N = 20                  # lookback for the level: the prior 20 closes
WINDOW = 12             # a break is watched while it is within this many sessions of the last bar (5 to resolve, a few spare)
HOLD = 5                # sessions followed after the break
SIZE_MIN = 0.5          # normal daily swings beyond the level
VOL_MIN = {"up": 1.2, "down": 1.3}
KEY = "break_watch"
ERROR_KEY = "break_watch_sheet_error"
KEEP = 800
SHEET_ROWS = 500
TAB, SCORE_TAB = "Break watch", "Break scorecard"
# 5-year back-test (2021-26, 150 most-traded S&P stocks): % that continued, % that reversed, and the average 5-day price change in %.
BASELINE = {("up", "All breaks"): (40, 54, 0.54), ("up", "Qualified"): (50, 33, 0.72), ("up", "Confirmed"): (67, 16, 2.83),
            ("down", "All breaks"): (33, 60, 0.67), ("down", "Qualified"): (40, 39, 0.75), ("down", "Confirmed"): (54, 24, -0.93)}
COLS = ["Ticker", "Direction", "Call", "Chance it continues", "Break date (NY)", "Sessions since break", "Last close", "Level broken",
        "Change since break %", "Beyond level (normal swings)", "Volume (x normal)", "Qualified on break day", "Day-1 tell strong", "Why"]
# Chance that a break goes on to finish its 5 sessions further in the break direction, from the same 5-year back-test (fixed, never tuned):
# on the break day by "qualified" or not; from day 1 on by the day-1 tell (held beyond the level, closed in the strong half, volume >= 1.0x)
# and by how many sessions it has already held without a close back across the level.
ODDS = {"up": {"q0": 50, "n0": 37, "strong": [66, 73, 79, 84], "weak": [48, 60, 70, 77]},
        "down": {"q0": 40, "n0": 31, "strong": [57, 64, 71, 77], "weak": [40, 51, 61, 71]}}


def _bars(h: pd.DataFrame, now: datetime | None) -> pd.DataFrame | None:
    """Completed daily bars only (today's bar is dropped until 16:10 New York time)."""
    try:
        h = h[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except Exception:
        return None
    if len(h) < N + 40:
        return None
    now = (now or datetime.now(NY)).astimezone(NY)
    last = pd.Timestamp(h.index[-1]).date()
    if last >= now.date() and (now.hour, now.minute) < (16, 10):
        h = h.iloc[:-1]
    return h if len(h) >= N + 40 else None


def judge(ev: dict) -> dict:
    """Fill the day-1 checks, the status and the outcome from the stored follow-up closes. Pure: same input, same answer."""
    up = ev["side"] == "up"
    days = ev["days"]
    seen = len(days)
    ev["seen"] = seen
    back = next((j + 1 for j, d in enumerate(days) if (d["close"] < ev["level"] if up else d["close"] > ev["level"])), None)
    d1 = days[0] if days else None
    if d1:
        ev["d1_ret"] = round((d1["close"] / ev["close"] - 1) * 100, 1)
        ev["d1_held"] = (d1["close"] > ev["level"]) if up else (d1["close"] < ev["level"])
        ev["d1_strong"] = d1["pos"] >= 0.5
        ev["d1_vol"] = d1["vol_x"]
        ev["d1_tell"] = bool(ev["d1_held"] and ev["d1_strong"] and d1["vol_x"] >= 1.0)
        ev["confirmed"] = bool(ev["qualified"] and ev["d1_tell"])
    else:
        ev["d1_ret"] = ev["d1_held"] = ev["d1_strong"] = ev["d1_vol"] = ev["confirmed"] = ev["d1_tell"] = None
    ev["now_ret"] = round((days[-1]["close"] / ev["close"] - 1) * 100, 1) if days else None
    ev["outcome"] = ""
    word = "under" if up else "over"
    if back:
        ev["outcome"] = "Reversed"
        ev["status"] = f"Failed: closed back {word} the level on day {back}"
    elif seen >= HOLD:
        further = days[HOLD - 1]["close"] > ev["close"] if up else days[HOLD - 1]["close"] < ev["close"]
        ev["outcome"] = "Continued" if further else "Neither"
        ev["status"] = ("Continued: stayed " + ("above" if up else "below") + " the level and moved further") if further else \
            "Neither: stayed beyond the level but ended the 5 sessions on the other side of the break close"
    elif seen == 0:
        ev["status"] = "Break day: waiting for day 1"
    else:
        ev["status"] = f"Holding: day {seen} of {HOLD}"
    return ev


def call_of(ev: dict) -> tuple[str, int, str]:
    """(call, chance %, why) for a break that is still open. The chance is the share of similar breaks in the 5-year back-test that
    went on to finish the 5 sessions further in the break direction; the call follows the day-1 tell, not the number alone."""
    up = ev["side"] == "up"
    o = ODDS[ev["side"]]
    keep, fade = ("rising", "fall back") if up else ("falling", "bounce")
    seen = ev["seen"]
    base = (f"Closed {ev['size']:.1f} normal swings {'above' if up else 'below'} its 20-day {'high' if up else 'low'} ({ev['level']:g}) "
            f"on {ev['vol_x']:.1f}x normal volume.")
    if seen == 0:
        if ev["qualified"]:
            return "Possible: wait for day 1", o["q0"], base + " A clear break on volume; day 1 decides."
        return f"Likely to {fade}", o["n0"], base + " Not a clear, heavy-volume break, which usually fades."
    k = min(seen, 4) - 1
    d1 = (f" Day 1 {'held' if ev['d1_held'] else 'did not hold'} the level, closed in the {'strong' if ev['d1_strong'] else 'weak'} half "
          f"on {ev['d1_vol']:.1f}x volume.")
    if ev["d1_tell"]:
        return f"Likely to keep {keep}", o["strong"][k], base + d1
    chance = o["weak"][k]
    return ("Could go either way" if chance >= 45 else f"Likely to {fade}"), chance, base + d1


def events(histories: dict, now: datetime | None = None) -> list[dict]:
    """Every break in the last WINDOW sessions, judged. Stocks with too little or unusable history are skipped."""
    out = []
    for t, h0 in (histories or {}).items():
        try:
            h = _bars(h0, now)
            if h is None:
                continue
            c, hi, lo, v = (h[k].values.astype(float) for k in ("Close", "High", "Low", "Volume"))
            cs = h["Close"]
            top = cs.shift(1).rolling(N).max().values
            bot = cs.shift(1).rolling(N).min().values
            prev = np.roll(c, 1)
            atr = pd.Series(np.maximum(hi - lo, np.maximum(abs(hi - prev), abs(lo - prev)))).rolling(14).mean().values
            va = pd.Series(v).rolling(20).mean().shift(1).values
            op = h["Open"].values.astype(float)
            n = len(c)
            for i in range(max(N + 1, n - WINDOW), n):
                for side in ("up", "down"):
                    lvl = top[i] if side == "up" else bot[i]
                    lvl0 = top[i - 1] if side == "up" else bot[i - 1]
                    if not (np.isfinite(lvl) and np.isfinite(lvl0) and np.isfinite(atr[i]) and atr[i] > 0 and np.isfinite(va[i]) and va[i] > 0):
                        continue
                    broke = c[i] > lvl and c[i - 1] <= lvl0 if side == "up" else c[i] < lvl and c[i - 1] >= lvl0
                    if not broke:
                        continue
                    sign = 1 if side == "up" else -1
                    size = (c[i] - lvl) * sign / atr[i]
                    vx = v[i] / va[i]
                    days = []
                    for j in range(i + 1, min(i + 1 + HOLD, n)):
                        rng_ = hi[j] - lo[j]
                        pos = (c[j] - lo[j]) / rng_ if rng_ > 0 else 0.5
                        days.append({"close": round(float(c[j]), 4), "pos": round(float(pos if side == "up" else 1 - pos), 3),
                                     "vol_x": round(float(v[j] / va[i]), 2)})
                    ev = {"t": t, "side": side, "date": pd.Timestamp(h.index[i]).date().isoformat(), "level": round(float(lvl), 4),
                          "close": round(float(c[i]), 4), "size": round(float(size), 2), "vol_x": round(float(vx), 2),
                          "gap": round(float((op[i] / c[i - 1] - 1) * 100), 1), "days": days,
                          "qualified": bool(size >= SIZE_MIN and vx >= VOL_MIN[side])}
                    out.append(judge(ev))
        except Exception as e:
            log.warning("break watch skipped a stock (%s)", type(e).__name__)
    return out


def key_of(ev: dict) -> str:
    return f"{ev['t']}|{ev['date']}|{ev['side']}"


def merge(stored: dict | None, fresh: list[dict], now: datetime | None = None) -> dict:
    """Keep every resolved break (so the record keeps growing after a break leaves the 12-session window) and the live ones."""
    state = stored if isinstance(stored, dict) else {}
    resolved = dict(state.get("resolved") or {})
    active = []
    for ev in fresh:
        if ev["outcome"]:
            resolved[key_of(ev)] = ev
        else:
            active.append(ev)
    if len(resolved) > KEEP:
        for k in sorted(resolved, key=lambda k: resolved[k]["date"])[:len(resolved) - KEEP]:
            resolved.pop(k)
    return {"updated": (now or datetime.now(NY)).isoformat(timespec="seconds"), "resolved": resolved, "active": active}


def all_events(state: dict) -> list[dict]:
    evs = list((state.get("resolved") or {}).values()) + list(state.get("active") or [])
    return sorted(evs, key=lambda e: (e["date"], e["t"]), reverse=True)


def scorecard(evs: list[dict]) -> list[list]:
    """Rows: direction, group, resolved, continued, reversed, avg 5-day change, back-test continued %, back-test reversed %, and a note."""
    rows = []
    for side in ("up", "down"):
        mine = [e for e in evs if e["side"] == side]
        for group, pick in (("All breaks", lambda e: True), ("Qualified", lambda e: e["qualified"]), ("Confirmed", lambda e: bool(e["confirmed"]))):
            g = [e for e in mine if pick(e)]
            done = [e for e in g if e["outcome"]]
            five = [e for e in done if e["seen"] >= HOLD]
            n = len(done)
            cont = sum(e["outcome"] == "Continued" for e in done)
            rev = sum(e["outcome"] == "Reversed" for e in done)
            avg = round(float(np.mean([(e["days"][HOLD - 1]["close"] / e["close"] - 1) * 100 for e in five])), 2) if five else ""
            b = BASELINE[(side, group)]
            rows.append([("Up: broke resistance" if side == "up" else "Down: broke support"), group, len(g), n,
                         round(cont / n, 3) if n else "", round(rev / n, 3) if n else "", avg, b[0] / 100, b[1] / 100,
                         "too few to judge (fewer than 30 resolved)" if n < 30 else
                         ("above the back-test" if cont / n * 100 > b[0] + 5 else "below the back-test" if cont / n * 100 < b[0] - 5 else "in line with the back-test")])
    return rows


SCORE_COLS = ["Direction", "Group", "Breaks seen", "Resolved", "Continued", "Reversed", "Avg price change after 5 sessions %",
              "Back-test: continued", "Back-test: reversed", "Live vs back-test (continued)"]


def live_events(state: dict) -> list[dict]:
    """Open breaks only (still inside their 5 sessions), the most likely to keep going first. Finished ones stay in the scorecard."""
    order = {"Likely to keep": 0, "Possible": 1, "Could go": 2}
    rows = []
    for ev in (state.get("active") or []):
        call, chance, why = call_of(ev)
        rows.append((order.get(next((k for k in order if call.startswith(k)), ""), 3), -chance, ev["date"], ev, call, chance, why))
    rows.sort(key=lambda r: (r[0], r[1], r[2]), reverse=False)
    return [(r[3], r[4], r[5], r[6]) for r in rows]


def row_of(ev: dict, call: str, chance: int, why: str) -> list:
    yn = lambda x: "" if x is None else ("Yes" if x else "No")
    days = ev["days"]
    return [ev["t"], "Up: broke resistance" if ev["side"] == "up" else "Down: broke support", call, chance / 100, ev["date"], ev["seen"],
            days[-1]["close"] if days else ev["close"], ev["level"], "" if ev["now_ret"] is None else ev["now_ret"], ev["size"], ev["vol_x"],
            yn(ev["qualified"]), yn(ev["d1_tell"]), why]


def sheet_env() -> str | None:
    for env in ("STOCKWATCH_BREAKWATCH_SHEET_URL", "STOCKWATCH_BUYSIGNALS_SHEET_URL", "STOCKWATCH_BUYSETUP_SHEET_URL", "STOCKWATCH_SMALLCAP_SHEET_URL"):
        if os.environ.get(env, "").strip():
            return env
    return None


def _rgb(r, g, b):
    return {"red": r, "green": g, "blue": b}


NAVY = _rgb(0.11, 0.176, 0.298)
WIDTHS = [70, 150, 170, 92, 92, 84, 84, 84, 92, 96, 82, 92, 84, 420]
SCORE_WIDTHS = [160, 96, 84, 84, 90, 90, 130, 110, 110, 260]


def _table_requests(sheet_id: int, ncols: int, widths: list[int], nrows: int, extra: list[dict]) -> list[dict]:
    def rng(r0=0, r1=nrows, c0=0, c1=ncols):
        return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1}

    out = [
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "tabColorStyle": {"rgbColor": _rgb(0.55, 0.30, 0.75)},
                                                  "gridProperties": {"frozenRowCount": 1, "hideGridlines": True}},
                                   "fields": "tabColorStyle,gridProperties.frozenRowCount,gridProperties.hideGridlines"}},
        {"repeatCell": {"range": rng(), "cell": {"userEnteredFormat": {"verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP",
                                                                      "textFormat": {"fontFamily": "Roboto", "fontSize": 10}}},
                        "fields": "userEnteredFormat.verticalAlignment,userEnteredFormat.wrapStrategy,userEnteredFormat.textFormat"}},
        {"repeatCell": {"range": rng(0, 1), "cell": {"userEnteredFormat": {
            "backgroundColor": NAVY, "horizontalAlignment": "CENTER", "textFormat": {"foregroundColor": _rgb(1, 1, 1), "bold": True,
                                                                                    "fontFamily": "Roboto", "fontSize": 10}}},
            "fields": "userEnteredFormat.backgroundColor,userEnteredFormat.horizontalAlignment,userEnteredFormat.textFormat"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": 48}, "fields": "pixelSize"}},
        {"addBanding": {"bandedRange": {"range": rng(1, nrows), "rowProperties": {
            "firstBandColorStyle": {"rgbColor": _rgb(1, 1, 1)}, "secondBandColorStyle": {"rgbColor": _rgb(0.94, 0.96, 0.98)}}}}},
    ]
    out += [{"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                                           "properties": {"pixelSize": w}, "fields": "pixelSize"}} for i, w in enumerate(widths)]
    return out + extra


def _cond(sheet_id, col, kind, text, bg, fg, nrows, bold=False):
    return {"addConditionalFormatRule": {"index": 0, "rule": {"ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": nrows,
                                                                          "startColumnIndex": col, "endColumnIndex": col + 1}], "booleanRule": {
        "condition": {"type": kind, "values": [{"userEnteredValue": text}]},
        "format": {"backgroundColor": bg, "textFormat": {"bold": bold, "foregroundColor": fg}}}}}}


def table_format(tab_id: int, nrows: int = SHEET_ROWS + 1) -> list[dict]:
    green, red, amber = (_rgb(0.85, 0.94, 0.87), _rgb(0.09, 0.42, 0.20)), (_rgb(0.99, 0.89, 0.88), _rgb(0.70, 0.15, 0.12)), \
        (_rgb(1, 0.96, 0.83), _rgb(0.55, 0.38, 0.0))
    blue = (_rgb(0.86, 0.92, 0.99), _rgb(0.10, 0.30, 0.65))

    def fmt(c0, c1, pattern=None, bold=False, center=True):
        f = {"textFormat": {"bold": bold}} if bold else {}
        if center:
            f["horizontalAlignment"] = "CENTER"
        if pattern:
            f["numberFormat"] = {"type": "PERCENT" if "%" in pattern else "NUMBER", "pattern": pattern}
        return {"repeatCell": {"range": {"sheetId": tab_id, "startRowIndex": 1, "endRowIndex": nrows, "startColumnIndex": c0, "endColumnIndex": c1},
                               "cell": {"userEnteredFormat": f}, "fields": ",".join("userEnteredFormat." + k for k in f)}}

    extra = [{"setBasicFilter": {"filter": {"range": {"sheetId": tab_id, "startRowIndex": 0, "endRowIndex": nrows, "startColumnIndex": 0,
                                                       "endColumnIndex": len(COLS)}}}},
             fmt(0, 1, bold=True), fmt(3, 4, "0%", True), fmt(4, 6), fmt(6, 8, "#,##0.00", center=False), fmt(8, 11, "0.0"), fmt(11, 13)]
    extra += [_cond(tab_id, 1, "TEXT_STARTS_WITH", "Up", *green, nrows), _cond(tab_id, 1, "TEXT_STARTS_WITH", "Down", *red, nrows),
              _cond(tab_id, 2, "TEXT_STARTS_WITH", "Likely to keep", *green, nrows, True), _cond(tab_id, 2, "TEXT_STARTS_WITH", "Possible", *blue, nrows),
              _cond(tab_id, 2, "TEXT_STARTS_WITH", "Could go", *amber, nrows), _cond(tab_id, 2, "TEXT_STARTS_WITH", "Likely to", *red, nrows)]
    for col in (11, 12):
        extra.append(_cond(tab_id, col, "TEXT_EQ", "Yes", *green, nrows, True))
    return _table_requests(tab_id, len(COLS), WIDTHS, nrows, extra)


def score_format(tab_id: int) -> list[dict]:
    pct = lambda c0, c1: {"repeatCell": {"range": {"sheetId": tab_id, "startRowIndex": 1, "endRowIndex": 7, "startColumnIndex": c0, "endColumnIndex": c1},
                                         "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER", "numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
                                         "fields": "userEnteredFormat.horizontalAlignment,userEnteredFormat.numberFormat"}}
    return _table_requests(tab_id, len(SCORE_COLS), SCORE_WIDTHS, 7, [pct(4, 6), pct(7, 9)])


def to_google(state: dict, connect=None) -> str:
    """Rewrite both tabs from the stored results. Returns '' (done, or not configured) or why not."""
    env = sheet_env()
    if not env:
        return ("Google Sheet not set up: this app window does not see STOCKWATCH_SMALLCAP_SHEET_URL. Set it in Windows, then close and "
                "reopen the app.")
    try:
        if connect is None:
            from . import smallcap_sheet
            sheet = smallcap_sheet.connect(env)
        else:
            sheet = connect(env)
        import gspread
        evs = all_events(state)
        for title, values, fmt, cols in ((SCORE_TAB, [SCORE_COLS] + scorecard(evs), score_format, len(SCORE_COLS)),
                                         (TAB, [COLS] + [row_of(*x) for x in live_events(state)[:SHEET_ROWS]], table_format, len(COLS))):
            try:
                tab = sheet.worksheet(title)
            except gspread.WorksheetNotFound:
                tab = sheet.add_worksheet(title=title, rows=SHEET_ROWS + 20, cols=cols)
            tab.clear()
            tab.update(range_name="A1", values=values, value_input_option="RAW")
            if not getattr(tab, "frozen_row_count", 0):
                try:
                    sheet.batch_update({"requests": fmt(tab.id)})
                except Exception as e:
                    log.warning("break watch tab not styled (%s)", type(e).__name__)
        return ""
    except Exception as e:
        log.warning("break watch Google Sheet not written (%s)", type(e).__name__)
        return f"Google Sheet not written ({type(e).__name__}); it is rewritten at the next whole-S&P scan"


def record(store, fresh: list[dict], now: datetime | None = None, background: bool = True) -> str:
    """Called after each whole-S&P scan with the breaks found in it. Saves the record first, then writes the sheet on its own thread
    so a slow Google can never hold up the scan. Returns '' or a short reason."""
    try:
        raw = store.get_setting(KEY)
        state = merge(json.loads(raw) if raw else None, fresh, now)
        store.set_setting(KEY, json.dumps(state))
    except Exception as e:
        log.warning("break watch not saved (%s)", type(e).__name__)
        return f"not saved ({type(e).__name__})"

    def send():
        try:
            store.set_setting(ERROR_KEY, to_google(state))
        except Exception as e:
            log.warning("break watch send failed (%s)", type(e).__name__)

    if background:
        import threading
        threading.Thread(target=send, name="stockwatch-break-watch", daemon=True).start()
    else:
        send()
    return ""
