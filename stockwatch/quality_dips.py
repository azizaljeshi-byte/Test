"""Quality dips: companies with strong fundamentals whose chart has deteriorated, on the owner's Google Sheet (owner, 23 Nov).

The owner's words, as numbers (all in the constants below, change them there and nowhere else):
  A stock is flagged when ANY of these is true on its last completed session:
    1  near or below its 52-week low          (closing within NEAR_LOW_PCT % above the lowest low of the last 252 sessions)
    2  below its 50-day exponential average
    3  down for the last DOWN_DAYS sessions in a row AND RSI at or under LOW_RSI
  and it is listed only if its fundamentals are strong (`quality`): no pillar fails, at least MIN_KNOWN of the 5 are known, and the app's
  own fundamental score (`fundamental.analyze`, unchanged) is at least SCORE_MIN.
Rows are ordered by how many of the three signs are present, then by the fundamental score.

Missing data is unknown, never a fail and never a zero: a stock whose fundamentals have not been fetched yet is not listed, and the count
of those still waiting is written under the table. Fundamentals are fetched a few dozen per scan (most-damaged charts first) and kept
FUND_TTL_DAYS, so the whole flagged list fills in over a few scans.

Display only. No score, signal, verdict, trade plan, alert or paper rule reads any of this; it uses the daily bars the whole-S&P scan
already downloaded (stocks the app tracks are not in that scan, they have their own cards). Today's unfinished bar is never used.
The sheet is rewritten from the stored result at each scan; errors are logged by type only, so a link or key can never reach a log line.

Live during the regular session (owner, 23 Nov): every LIVE_SECONDS the companies already in the table get one bulk price download and their
signs are recomputed from that price on top of the last completed bar (`live`: the 50-day average and RSI take one more step, the 52-week
range widens if the price breaks it). A company whose signs have all cleared drops out of the table. New names still join only at the
30-minute whole-S&P scan, which judges the last completed session. Nothing is invented: a company with no live price shows its last completed session.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import fundamental, smallcap, technical
from .data import NY

log = logging.getLogger("stockwatch.quality_dips")

# --- the owner's words, as numbers
NEAR_LOW_PCT = 5.0        # "below or near the 52-week low": at most this % above it
EMA_DAYS = 50             # "below the 50 average"
DOWN_DAYS = 2             # "down for the last 2 sessions"
LOW_RSI = 35.0            # "low RSI"
GROWTH_MIN = 0.0          # revenue not shrinking
EARNINGS_MIN = -0.15      # profit not down more than 15% a year
MARGIN_MIN = 0.0          # operating (else profit) margin above zero
DEBT_MAX = 1.5            # debt to equity
CURRENT_MIN = 1.0         # current ratio
MIN_KNOWN = 3             # of the 5 pillars
SCORE_MIN = 60.0          # the app's own 0-100 fundamental score
MIN_BARS = 220
KEY, FUND_KEY, ERROR_KEY = "quality_dips", "quality_dips_fund", "quality_dips_sheet_error"
CANDS_KEY = "quality_dips_cands"
LIVE_SECONDS = 300        # how often the table is repriced while the market is open
SEED_MAX_DAYS = 5         # a seed older than this (app was off) is not repriced
FUND_PER_RUN = 60
SHEET_ROWS = 300
TAB = "Quality dips"
KEYS = ("name", "sector", "market_cap", "pe_trailing", "pe_forward", "peg", "revenue_growth", "earnings_growth", "operating_margin",
        "profit_margin", "roe", "debt_to_equity", "current_ratio", "free_cash_flow", "target_mean_price", "recommendation_mean")
FLAGS = {"low": "Near its 52-week low", "ema": "Below its 50-day average", "rsi": "Down 2 sessions with low RSI"}
COLS = ["Ticker", "Company", "Sector", "Price", "Last session %", "Why it is flagged", "Signs present", "Above 52-week low %",
        "Below 52-week high %", "vs 50-day average %", "RSI", "Down sessions in a row", "Fundamentals score", "Revenue growth %",
        "Profit margin %", "Free cash flow ($M)", "Debt / equity", "Analyst target upside %", "Fundamentals"]
WIDTHS = [70, 170, 130, 76, 82, 260, 70, 84, 92, 92, 56, 84, 92, 84, 84, 92, 76, 92, 420]


def sheet_env() -> str | None:
    """The Windows variable that holds the owner's Google Sheet link (the same sheet as the other tabs)."""
    for env in ("STOCKWATCH_QUALITYDIPS_SHEET_URL", "STOCKWATCH_BREAKWATCH_SHEET_URL", "STOCKWATCH_BUYSIGNALS_SHEET_URL",
                "STOCKWATCH_BUYSETUP_SHEET_URL", "STOCKWATCH_SMALLCAP_SHEET_URL"):
        if os.environ.get(env, "").strip():
            return env
    return None


def _rgb(r, g, b):
    return {"red": r, "green": g, "blue": b}


NAVY = _rgb(0.11, 0.176, 0.298)


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


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _bars(h: pd.DataFrame | None, now: datetime | None) -> pd.DataFrame | None:
    """Completed daily bars only (today's bar is dropped until 16:10 New York time)."""
    try:
        h = h[["High", "Low", "Close"]].dropna()
    except Exception:
        return None
    now = (now or datetime.now(NY)).astimezone(NY)
    if len(h) and pd.Timestamp(h.index[-1]).date() >= now.date() and (now.hour, now.minute) < (16, 10):
        h = h.iloc[:-1]
    return h if len(h) >= MIN_BARS else None


def technicals(h: pd.DataFrame | None, now: datetime | None = None) -> dict | None:
    """The three signs for one stock from its daily bars, or None when there is too little history to say."""
    b = _bars(h, now)
    if b is None:
        return None
    c = b["Close"]
    close = float(c.iloc[-1])
    low52, high52 = float(b["Low"].tail(252).min()), float(b["High"].tail(252).max())
    ema50 = float(technical.ema(c, EMA_DAYS).iloc[-1])
    rsi = float(technical.rsi(c).iloc[-1])
    down = 0
    for a, p in zip(c.iloc[::-1].iloc[:-1], c.iloc[::-1].iloc[1:]):
        if a < p:
            down += 1
        else:
            break
    if min(close, low52, high52, ema50) <= 0 or not np.isfinite(rsi):
        return None
    d = c.diff()
    ag = float(d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
    al = float((-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
    seed = {"pc": close, "low": low52, "high": high52, "ema": ema50, "ag": ag, "al": al, "down": down,
            "asof": pd.Timestamp(b.index[-1]).date().isoformat()}
    return {**_signs(close, float(c.iloc[-2]), low52, high52, ema50, rsi, down), "seed": seed}


def _signs(price, prev, low52, high52, ema50, rsi, down) -> dict:
    above_low = (price / low52 - 1) * 100
    flags = []
    if above_low <= NEAR_LOW_PCT:
        flags.append("low")
    if price < ema50:
        flags.append("ema")
    if down >= DOWN_DAYS and rsi <= LOW_RSI:
        flags.append("rsi")
    return {"price": round(price, 2), "day": round((price / prev - 1) * 100, 2), "above_low": round(above_low, 1),
            "below_high": round((price / high52 - 1) * 100, 1), "vs_ema": round((price / ema50 - 1) * 100, 1), "rsi": round(rsi, 1),
            "down": down, "flags": flags}


def live(c: dict, price: float) -> dict:
    """The candidate re-judged at a live price: today's price is treated as one more bar on top of the last completed one."""
    s = c["seed"]
    low52, high52 = min(s["low"], price), max(s["high"], price)
    ema50 = s["ema"] + (price - s["ema"]) * 2 / (EMA_DAYS + 1)
    delta = price - s["pc"]
    ag = s["ag"] * 13 / 14 + max(delta, 0) / 14
    al = s["al"] * 13 / 14 + max(-delta, 0) / 14
    rsi = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    down = s["down"] + 1 if price < s["pc"] else 0
    return {**c, **_signs(price, s["pc"], low52, high52, ema50, rsi, down)}


def candidates(histories: dict, now: datetime | None = None) -> list[dict]:
    """Every stock in the bulk download with at least one sign, most signs and nearest its low first."""
    out = []
    for t, h in histories.items():
        try:
            x = technicals(h, now)
        except Exception:
            continue
        if x and x["flags"]:
            out.append({"t": t, **x})
    out.sort(key=lambda r: (-len(r["flags"]), r["above_low"]))
    return out


def quality(f: dict | None, price: float | None = None) -> dict:
    """Strong fundamentals? Each pillar is pass, fail or None (unknown); unknown never fails. Strong = nothing fails, at least MIN_KNOWN
    known, and the app's fundamental score (not changed here) at least SCORE_MIN."""
    f = f or {}
    rg, eg, fcf = _num(f.get("revenue_growth")), _num(f.get("earnings_growth")), _num(f.get("free_cash_flow"))
    margin = _num(f.get("operating_margin"))
    if margin is None:
        margin = _num(f.get("profit_margin"))
    de, cr = _num(f.get("debt_to_equity")), _num(f.get("current_ratio"))
    pillars = {
        "growth": None if rg is None else rg >= GROWTH_MIN,
        "profit": None if margin is None else margin > MARGIN_MIN and (eg is None or eg > EARNINGS_MIN),
        "cash": None if fcf is None else fcf > 0,
        "debt": None if de is None and cr is None else not ((de is not None and de > DEBT_MAX) or (cr is not None and cr < CURRENT_MIN)),
        "earnings": None if eg is None else eg > EARNINGS_MIN,
    }
    known = sum(v is not None for v in pillars.values())
    failed = [k for k, v in pillars.items() if v is False]
    score = None
    if known:
        try:
            score = round(float(fundamental.analyze(f, price or 0)[0]), 1)
        except Exception:
            score = None
    if failed:
        why_not = "fails: " + ", ".join(failed)
    elif known < MIN_KNOWN:
        why_not = f"only {known} of 5 fundamentals known"
    elif score is None or score < SCORE_MIN:
        why_not = "fundamental score below the bar"
    else:
        why_not = ""
    bits = []
    if rg is not None:
        bits.append(f"revenue {rg * 100:+.0f}%")
    if margin is not None:
        bits.append(f"margin {margin * 100:.0f}%")
    if eg is not None:
        bits.append(f"profit {eg * 100:+.0f}%")
    if fcf is not None:
        bits.append("cash flow positive" if fcf > 0 else "burning cash")
    if de is not None:
        bits.append(f"debt/equity {de:.1f}")
    return {"passed": not why_not, "why_not": why_not, "known": known, "score": score, "text": "; ".join(bits) or "no figures yet"}


def row_of(c: dict, f: dict, q: dict) -> list:
    g = lambda k: _num(f.get(k))
    pct = lambda v: "" if v is None else round(v * 100, 1)
    tgt = g("target_mean_price")
    fcf = g("free_cash_flow")
    return [c["t"], f.get("name") or "", f.get("sector") or "", c["price"], c["day"], " | ".join(FLAGS[k] for k in c["flags"]), len(c["flags"]),
            c["above_low"], c["below_high"], c["vs_ema"], c["rsi"], c["down"], q["score"], pct(g("revenue_growth")),
            pct(g("operating_margin") if g("operating_margin") is not None else g("profit_margin")),
            "" if fcf is None else round(fcf / 1e6), "" if g("debt_to_equity") is None else round(g("debt_to_equity"), 2),
            "" if not tgt else round((tgt / c["price"] - 1) * 100, 1), q["text"]]


def build(cands: list[dict], cache: dict) -> dict:
    """Join the flagged stocks with their cached fundamentals: the rows to show and how many are still waiting for a check."""
    rows, waiting = [], 0
    for c in cands:
        e = cache.get(c["t"])
        f = (e or {}).get("f") or {}
        if not f:
            waiting += 1
            continue
        q = quality(f, c["price"])
        if q["passed"]:
            rows.append((-len(c["flags"]), -(q["score"] or 0), row_of(c, f, q)))
    rows.sort(key=lambda r: (r[0], r[1]))
    return {"rows": [r[2] for r in rows[:SHEET_ROWS]], "waiting": waiting, "flagged": len(cands), "strong": len(rows)}


def table_format(tab_id: int, nrows: int = SHEET_ROWS + 1) -> list[dict]:
    green, red, amber = (_rgb(0.85, 0.94, 0.87), _rgb(0.09, 0.42, 0.20)), (_rgb(0.99, 0.89, 0.88), _rgb(0.70, 0.15, 0.12)), \
        (_rgb(1, 0.96, 0.83), _rgb(0.55, 0.38, 0.0))

    def fmt(c0, c1, pattern=None, bold=False, center=True):
        f = {"textFormat": {"bold": bold}} if bold else {}
        if center:
            f["horizontalAlignment"] = "CENTER"
        if pattern:
            f["numberFormat"] = {"type": "NUMBER", "pattern": pattern}
        return {"repeatCell": {"range": {"sheetId": tab_id, "startRowIndex": 1, "endRowIndex": nrows, "startColumnIndex": c0, "endColumnIndex": c1},
                               "cell": {"userEnteredFormat": f}, "fields": ",".join("userEnteredFormat." + k for k in f)}}

    def num_rule(col, op, value, bg, fg):
        return {"addConditionalFormatRule": {"index": 0, "rule": {"ranges": [{"sheetId": tab_id, "startRowIndex": 1, "endRowIndex": nrows,
                                                                              "startColumnIndex": col, "endColumnIndex": col + 1}], "booleanRule": {
            "condition": {"type": op, "values": [{"userEnteredValue": str(value)}]},
            "format": {"backgroundColor": bg, "textFormat": {"foregroundColor": fg}}}}}}

    extra = [{"setBasicFilter": {"filter": {"range": {"sheetId": tab_id, "startRowIndex": 0, "endRowIndex": nrows, "startColumnIndex": 0,
                                                       "endColumnIndex": len(COLS)}}}},
             fmt(0, 1, bold=True), fmt(3, 4, "#,##0.00", center=False), fmt(4, 5, "0.0"), fmt(6, 18, "0.0"), fmt(6, 7, "0"), fmt(11, 12, "0"),
             fmt(12, 13, "0", True), fmt(15, 16, "#,##0")]
    extra += [num_rule(4, "NUMBER_LESS", 0, red[0], red[1]), num_rule(4, "NUMBER_GREATER", 0, green[0], green[1]),
              num_rule(6, "NUMBER_GREATER_THAN_EQ", 3, red[0], red[1]), num_rule(6, "NUMBER_EQ", 2, amber[0], amber[1]),
              num_rule(12, "NUMBER_GREATER_THAN_EQ", 75, green[0], green[1]), num_rule(10, "NUMBER_LESS_THAN_EQ", LOW_RSI, red[0], red[1])]
    return _table_requests(tab_id, len(COLS), WIDTHS, nrows, extra)


def to_google(state: dict, connect=None) -> str:
    """Rewrite the tab from the stored result. Returns '' (done, or not configured) or why not."""
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
        try:
            tab = sheet.worksheet(TAB)
        except gspread.WorksheetNotFound:
            tab = sheet.add_worksheet(title=TAB, rows=SHEET_ROWS + 20, cols=len(COLS))
        rows = state.get("rows") or []
        when = (f"Prices live at {state['live_at'][11:16]} UTC (new names join at the next scan)." if state.get("live_at")
                else "Last completed session only.")
        note = (f"{state.get('strong', 0)} strong companies of {state.get('flagged', 0)} flagged charts; {state.get('waiting', 0)} still waiting "
                f"for a fundamentals check. Last scan {state.get('at', '')[:16].replace('T', ' ')} UTC. {when}")
        tab.clear()
        tab.update(range_name="A1", values=[COLS] + rows, value_input_option="RAW")
        tab.update(range_name=f"A{len(rows) + 3}", values=[[note]], value_input_option="RAW")
        if not getattr(tab, "frozen_row_count", 0):
            try:
                sheet.batch_update({"requests": table_format(tab.id)})
            except Exception as e:
                log.warning("quality dips tab not styled (%s)", type(e).__name__)
        return ""
    except Exception as e:
        log.warning("quality dips Google Sheet not written (%s)", type(e).__name__)
        return f"Google Sheet not written ({type(e).__name__}); it is rewritten at the next whole-S&P scan"


_LOCK = threading.Lock()
_state = {"last": 0.0, "running": False}


def _load(store, key, default):
    try:
        raw = store.get_setting(key)
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


def work(store, cands: list[dict], provider, now: datetime | None = None) -> str:
    """Fetch a few dozen missing fundamentals (most-damaged charts first), rebuild the table, save it and write the sheet."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cache = _load(store, FUND_KEY, {})
    try:
        smallcap.refresh_fundamentals(provider, [c["t"] for c in cands], cache, now, keys=KEYS, per_run=FUND_PER_RUN)
        store.set_setting(FUND_KEY, json.dumps(cache))
    except Exception as e:
        log.warning("quality dips fundamentals step failed (%s)", type(e).__name__)
    state = {"at": now.isoformat(timespec="seconds"), **build(cands, cache)}
    with _LOCK:
        store.set_setting(CANDS_KEY, json.dumps(cands))
        store.set_setting(KEY, json.dumps(state))
        err = to_google(state)
        store.set_setting(ERROR_KEY, err)
    return err


def record(store, cands: list[dict], provider, now: datetime | None = None, background: bool = True) -> str:
    """Called after each whole-S&P scan with the flagged stocks. Everything slow (fundamentals, Google) runs on its own thread so the
    scan is never held up. Returns '' or a short reason."""
    def go():
        try:
            work(store, cands, provider, now)
        except Exception as e:
            log.warning("quality dips step failed (%s)", type(e).__name__)

    if background:
        import threading
        threading.Thread(target=go, name="stockwatch-quality-dips", daemon=True).start()
        return ""
    return work(store, cands, provider, now)


def reprice(store, provider, now: datetime | None = None) -> str:
    """Live pass during the regular session: new prices for the companies in the table, signs recomputed, sheet rewritten.
    Returns '' when done or a short reason it did nothing."""
    from .data import us_session
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if us_session(now) != "REGULAR":
        return "market not open"
    cands, cache = _load(store, CANDS_KEY, []), _load(store, FUND_KEY, {})
    today = now.astimezone(NY).date()

    def fresh(c):
        try:
            d = datetime.fromisoformat(c["seed"]["asof"]).date()
        except (KeyError, TypeError, ValueError):
            return False
        return d < today and (today - d).days <= SEED_MAX_DAYS

    shown = [c["t"] for c in cands if fresh(c) and (cache.get(c["t"]) or {}).get("f") and quality(cache[c["t"]]["f"], c["price"])["passed"]]
    if not shown:
        return "nothing to reprice"
    quotes = provider.bulk_quotes(shown)
    with _LOCK:
        cands = _load(store, CANDS_KEY, [])                   # a scan may have landed while the prices downloaded
        moved = []
        for c in cands:
            q = quotes.get(c["t"]) or {}
            p = _num(q.get("live_price"))
            if p and p > 0 and fresh(c):
                try:
                    c = live(c, p)
                except Exception:
                    pass
            moved.append(c)
        flagged = [c for c in moved if c["flags"]]
        before = _load(store, KEY, {})
        state = {**build(flagged, cache), "at": before.get("at") or now.isoformat(timespec="seconds"),
                 "live_at": now.isoformat(timespec="seconds")}
        state["flagged"], state["waiting"] = before.get("flagged", state["flagged"]), before.get("waiting", state["waiting"])
        store.set_setting(KEY, json.dumps(state))
        err = to_google(state)
        store.set_setting(ERROR_KEY, err)
    return err


def run_async(store_path, provider, now: float | None = None) -> bool:
    """Tracker hook: a live pass every LIVE_SECONDS while the market is open, on its own thread so a sweep is never held up."""
    from .data import us_session
    now = time.time() if now is None else now
    if us_session() != "REGULAR" or _state["running"] or now - _state["last"] < LIVE_SECONDS:
        return False
    _state["running"], _state["last"] = True, now

    def go():
        try:
            from .store import Store
            reprice(Store(store_path) if store_path else Store(), provider)
        except Exception as e:
            log.warning("quality dips live pass failed (%s)", type(e).__name__)
        finally:
            _state["running"] = False

    threading.Thread(target=go, name="stockwatch-quality-live", daemon=True).start()
    return True
