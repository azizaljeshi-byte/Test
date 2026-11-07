"""Extended-hours monitor (pre-market 04:00-09:30 and after-hours 16:00-20:00, New York clock). LOG ONLY: no trade, no score (owner, 3 Nov 2026).

Every EXT_EVERY_S seconds in PRE or POST one background thread downloads 5 days of 1-minute bars WITH pre/post-market for the tracked stocks
(one bulk call per CHUNK, Yahoo, same download style as the rest of the app) and works out, per stock, for the current extended window:
  move %         last price against the last regular-session close (PRE: yesterday's, POST: today's)
  ext volume     shares traded in the window so far, and as a share of the stock's average regular day (last days in the same download)
  dollar volume  sum of price x volume in the window
  VWAP, high, low, minutes with trades, age of the last bar
A stock is "thin" (shown, never ranked as tradable) when it has too little trading: under MIN_DOLLARS, under MIN_TRADE_MINUTES minutes
with trades, or its last bar is older than MAX_BAR_AGE_MIN. Missing data is "unknown", never 0.
The latest picture is saved in the `extended_state` setting; a short per-run history of the biggest movers is kept in `extended_log` so the
first days can be read back (how a pre-market gap carried into the open). Overnight (20:00-04:00 New York) is not in Yahoo's data.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime

from .data import NY, us_session

log = logging.getLogger("stockwatch.extended")
KEY, KEY_LOG = "extended_state", "extended_log"
EXT_EVERY_S = 300
CHUNK = 100
MIN_DOLLARS = 250_000          # a window with less trading than this is "thin"
MIN_TRADE_MINUTES = 10
MAX_BAR_AGE_MIN = 10
KEEP_RUNS = 120                # about two extended windows of 5-minute runs
LOG_TOP = 15
OPEN_MIN, CLOSE_MIN = 9 * 60 + 30, 16 * 60


def _mins(ts) -> int:
    return ts.hour * 60 + ts.minute


def stats(df, now: datetime, session: str) -> dict | None:
    """Extended-window numbers for one stock from its 1-minute bars (index in New York time, columns Close/Volume). None = no read."""
    try:
        df = df.dropna(subset=["Close"])
        if df.empty:
            return None
        idx = df.index
        today = now.date()
        regular = df[[OPEN_MIN <= _mins(t) < CLOSE_MIN for t in idx]]
        if session == "PRE":
            win = df[[t.date() == today and _mins(t) < OPEN_MIN for t in idx]]
            ref = regular[[t.date() < today for t in regular.index]]
        else:
            win = df[[t.date() == today and _mins(t) >= CLOSE_MIN for t in idx]]
            ref = regular[[t.date() == today for t in regular.index]]
        if ref.empty or ref["Close"].iloc[-1] <= 0:
            return None
        ref_close = float(ref["Close"].iloc[-1])
        days = regular[[t.date() < today for t in regular.index]]
        daily = days.groupby([t.date() for t in days.index])["Volume"].sum() if len(days) else None
        avg_day = float(daily.mean()) if daily is not None and len(daily) and daily.mean() > 0 else None
        if win.empty:
            return {"ref_close": ref_close, "price": None, "move": None, "volume": 0, "dollars": 0.0, "vwap": None, "high": None,
                    "low": None, "trade_min": 0, "age_min": None, "pct_of_day": None, "thin": True, "why": "no trades yet"}
        vol = win["Volume"].fillna(0)
        dollars = float((win["Close"] * vol).sum())
        v = float(vol.sum())
        trade_min = int((vol > 0).sum())
        last_t = win.index[-1]
        age = (now - last_t).total_seconds() / 60
        price = float(win["Close"].iloc[-1])
        thin, why = False, None
        if dollars < MIN_DOLLARS:
            thin, why = True, "very little trading"
        elif trade_min < MIN_TRADE_MINUTES:
            thin, why = True, "trades in too few minutes"
        elif age > MAX_BAR_AGE_MIN:
            thin, why = True, "last trade is old"
        return {"ref_close": round(ref_close, 4), "price": round(price, 4), "move": round((price / ref_close - 1) * 100, 2),
                "volume": int(v), "dollars": round(dollars), "vwap": round(dollars / v, 4) if v > 0 else None,
                "high": round(float(win["High"].max()), 4) if "High" in win else None,
                "low": round(float(win["Low"].min()), 4) if "Low" in win else None,
                "trade_min": trade_min, "age_min": round(age, 1),
                "pct_of_day": None if avg_day is None else round(v / avg_day * 100, 2), "thin": thin, "why": why}
    except Exception:
        return None


def build(frames: dict, now: datetime, session: str) -> dict:
    rows = {}
    for t, df in frames.items():
        s = stats(df, now, session)
        if s:
            rows[t] = s
    live = [r for r in rows.values() if not r["thin"]]
    return {"at": now.isoformat(timespec="seconds"), "session": session, "names": len(frames), "read": len(rows), "active": len(live), "rows": rows}


def fetch(tickers: list) -> dict:
    """5 days of 1-minute bars with pre/post-market, one bulk call per CHUNK stocks. Index converted to New York time."""
    import pandas as pd
    import yfinance as yf
    frames: dict = {}
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        df = yf.download(chunk, period="5d", interval="1m", prepost=True, group_by="ticker", auto_adjust=False, threads=True, progress=False)
        for t in chunk:
            try:
                sub = (df[t] if len(chunk) > 1 else df)[["Close", "High", "Low", "Volume"]].dropna(how="all")
                if len(sub) > 5:
                    idx = pd.to_datetime(sub.index)
                    sub.index = idx.tz_convert("America/New_York") if idx.tz is not None else idx.tz_localize("America/New_York")
                    frames[t] = sub
            except Exception:
                continue
    return frames


def load(store) -> dict | None:
    try:
        raw = store.get_setting(KEY)
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def history(store) -> list:
    try:
        raw = store.get_setting(KEY_LOG)
        d = json.loads(raw) if raw else []
        return d if isinstance(d, list) else []
    except ValueError:
        return []


def ranked(state: dict | None) -> list:
    """[(ticker, row)] of stocks with real trading, biggest move first (up or down)."""
    rows = (state or {}).get("rows") or {}
    live = [(t, r) for t, r in rows.items() if not r.get("thin") and r.get("move") is not None]
    return sorted(live, key=lambda x: -abs(x[1]["move"]))


def refresh(store, now: datetime | None = None, frames: dict | None = None, tickers: list | None = None) -> dict | None:
    now = (now or datetime.now(NY)).astimezone(NY)
    session = us_session(now)
    if session not in ("PRE", "POST"):
        return None
    if frames is None:
        tickers = tickers or [s["ticker"] for s in store.latest_snapshots()]
        frames = fetch(tickers)
    state = build(frames, now, session)
    store.set_setting(KEY, json.dumps(state))
    top = [{"t": t, "move": r["move"], "price": r["price"], "dollars": r["dollars"], "pct_of_day": r["pct_of_day"]} for t, r in ranked(state)[:LOG_TOP]]
    log_rows = history(store)
    log_rows.append({"at": state["at"], "session": session, "active": state["active"], "read": state["read"], "top": top})
    store.set_setting(KEY_LOG, json.dumps(log_rows[-KEEP_RUNS:]))
    return state


_lock = threading.Lock()
_running = False
_last_try = 0.0


def run_async(store_path) -> bool:
    """Start a refresh on its own thread when one is due (PRE or POST only). Returns at once; never raises."""
    global _running, _last_try
    try:
        if us_session() not in ("PRE", "POST") or _running or time.time() - _last_try < EXT_EVERY_S:
            return False
        from .live import MARKET_LOCK
        if MARKET_LOCK.locked():
            return False
        with _lock:
            if _running:
                return False
            _running, _last_try = True, time.time()

        def work():
            global _running
            try:
                from .store import Store
                t0 = time.time()
                st = Store(store_path) if store_path else Store()
                state = refresh(st)
                if state:
                    log.info("extended read: %s of %s stocks, %s active, %.0f s", state["read"], state["names"], state["active"], time.time() - t0)
            except Exception:
                log.exception("extended refresh failed")
            finally:
                _running = False

        threading.Thread(target=work, name="stockwatch-extended", daemon=True).start()
        return True
    except Exception:
        log.exception("extended start failed")
        return False
