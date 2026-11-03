"""Top-down funnel read of the WHOLE S&P 500, LOG ONLY (owner, 1 Nov 2026). Nothing is blocked or bought from it yet.

Every FUNNEL_EVERY_S seconds in the regular session (New York clock) one background thread downloads 2 days of 5-minute bars for all
~500 members in a few bulk calls (measured on the owner's PC: 503 of 503 stocks in about 60 s, 5-day version), works out each stock's
change since yesterday's close, and judges the market, then each sector, then each industry:
  market    a crash stop only: fewer than CRASH_UP of the stocks up
  sector    at least MIN_SECTOR stocks read, at least half up, the middle stock not down
  industry  the same, with at least MIN_INDUSTRY stocks (a smaller industry is judged at sector level only)
It also keeps the last readings, so a sector can be seen as improving or fading against an hour ago.
Each new entry of Quick and New call is then stamped with what the funnel said at that minute (`funnel_gate` on the trade).
Missing or stale data is "no read", never "unhealthy". It runs on its own thread and is skipped while the S&P scan is running.
Replay of Friday 30 Oct on the full list: Information Technology (75 stocks, 20% up, -4.4%) never healthy; Energy, Staples, Utilities
healthy all day; Materials healthy from about 13:00. One day, so log first.
"""
from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from datetime import datetime

from .data import NY, us_session

log = logging.getLogger("stockwatch.funnel")
KEY = "funnel_state"
FUNNEL_EVERY_S = 300
STALE_BAR_MIN = 20            # a stock whose last bar is older than this is not read
STATE_MAX_AGE_MIN = 15        # an older picture is not used to stamp an entry
MIN_SECTOR, MIN_INDUSTRY = 3, 4
MIN_UP, MIN_MEDIAN = 0.5, 0.0
CRASH_UP, CRASH_MIN_NAMES = 0.25, 100
TREND_MIN, TREND_STEP = 45, 0.05      # compare with a reading at least 45 minutes old; +-5 points of "share up" counts as a move
KEEP_READINGS = 16
CHUNK = 100

_lock = threading.Lock()
_running = False
_last_try = 0.0


def _healthy(v: list, minimum: int) -> bool | None:
    if len(v) < minimum:
        return None                                              # too few names: unknown, not unhealthy
    return sum(x > 0 for x in v) / len(v) >= MIN_UP and statistics.median(v) >= MIN_MEDIAN


def _row(v: list, minimum: int) -> dict:
    h = _healthy(v, minimum)
    return {"names": len(v), "up": round(sum(x > 0 for x in v) / len(v), 3), "median": round(statistics.median(v) * 100, 2), "healthy": h}


def changes(frames: dict, now: datetime) -> dict:
    """{ticker: change since yesterday's last close} for stocks with a fresh bar today. Anything missing is left out, never zero."""
    out = {}
    for t, df in frames.items():
        try:
            close = df["Close"].dropna()
            if close.empty:
                continue
            last_t = close.index[-1]
            if last_t.date() != now.date() or (now - last_t).total_seconds() > STALE_BAR_MIN * 60:
                continue
            prev = close[close.index.date < now.date()]
            if prev.empty or prev.iloc[-1] <= 0:
                continue
            out[t] = float(close.iloc[-1] / prev.iloc[-1] - 1)
        except Exception:
            continue
    return out


def summarize(ch: dict, labels: dict, at: datetime, history: list | None = None) -> dict:
    """The market, sector and industry picture from `ch` ({ticker: change}) and `labels` ({ticker: [sector, industry]})."""
    allv = list(ch.values())
    sec: dict[str, list] = {}
    ind: dict[str, list] = {}
    for t, c in ch.items():
        lab = labels.get(t)
        if lab and lab[0]:
            sec.setdefault(lab[0], []).append(c)
            if lab[1]:
                ind.setdefault(f"{lab[0]}|{lab[1]}", []).append(c)
    market = {"names": len(allv)}
    if allv:
        market.update({"up": round(sum(x > 0 for x in allv) / len(allv), 3), "median": round(statistics.median(allv) * 100, 2)})
        market["crash"] = len(allv) >= CRASH_MIN_NAMES and market["up"] < CRASH_UP
    hist = [h for h in (history or []) if isinstance(h, dict)][-KEEP_READINGS:]
    sectors = {s: _row(v, MIN_SECTOR) for s, v in sec.items()}
    for s, r in sectors.items():
        r["trend"] = trend(hist, s, r["up"], at)
    state = {"at": at.isoformat(), "market": market, "sectors": sectors,
             "industries": {k: _row(v, MIN_INDUSTRY) for k, v in ind.items()},
             "labels": labels, "history": hist + [{"at": at.isoformat(), "sectors": {s: r["up"] for s, r in sectors.items()}}]}
    state["history"] = state["history"][-KEEP_READINGS:]
    return state


def trend(history: list, sector: str, up_now: float, at: datetime) -> str | None:
    """"improving", "fading" or "flat" against the reading closest to an hour ago (at least TREND_MIN old); None without one."""
    best = None
    for h in history:
        try:
            age = (at - datetime.fromisoformat(h["at"])).total_seconds() / 60
        except Exception:
            continue
        old = (h.get("sectors") or {}).get(sector)
        if old is not None and age >= TREND_MIN and (best is None or abs(age - 60) < abs(best[0] - 60)):
            best = (age, old)
    if best is None:
        return None
    d = up_now - best[1]
    return "improving" if d >= TREND_STEP else "fading" if d <= -TREND_STEP else "flat"


def verdict(ticker: str, state: dict | None, now: datetime | None = None) -> str | None:
    """One line for a trade record, or None when there is no usable read (the caller then uses its own note)."""
    if not state or ticker not in (state.get("labels") or {}):
        return None
    try:
        age = ((now or datetime.now(NY)) - datetime.fromisoformat(state["at"])).total_seconds() / 60
    except Exception:
        return None
    if age > STATE_MAX_AGE_MIN:
        return None
    mk = state.get("market") or {}
    s, i = state["labels"][ticker][0], state["labels"][ticker][1]
    sr = (state.get("sectors") or {}).get(s)
    ir = (state.get("industries") or {}).get(f"{s}|{i}")
    if mk.get("crash"):
        return f"WOULD BLOCK at market level: only {mk['up']:.0%} of {mk['names']} stocks up"
    if not sr or sr["healthy"] is None:
        return f"no read: {s}, too few stocks with a fresh price"
    head = f"{s} {sr['up']:.0%} of {sr['names']} up, median {sr['median']:+.2f}%" + (f", {sr['trend']}" if sr.get("trend") else "")
    if not sr["healthy"]:
        return f"WOULD BLOCK at sector level: {head}"
    if ir and ir["healthy"] is False:
        return f"WOULD BLOCK at industry level: {head} > {i} {ir['up']:.0%} of {ir['names']} up, median {ir['median']:+.2f}%"
    tail = f" > {i} {ir['up']:.0%} of {ir['names']} up" if ir and ir["healthy"] else f" (industry too small to judge: {i})"
    return f"PASS: {head}{tail}"


def load(store) -> dict | None:
    raw = store.get_setting(KEY)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def fetch(tickers: list) -> dict:
    """2 days of 5-minute bars, one bulk call per CHUNK stocks. Same download the S&P scan uses, on this one thread."""
    import pandas as pd
    import yfinance as yf
    frames: dict = {}
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        df = yf.download(chunk, period="2d", interval="5m", group_by="ticker", auto_adjust=True, threads=True, progress=False)
        for t in chunk:
            try:
                sub = df[t][["Close"]].dropna(how="all")
                if len(sub) > 5:
                    idx = pd.to_datetime(sub.index)
                    sub.index = idx.tz_convert("America/New_York") if idx.tz is not None else idx.tz_localize("America/New_York")
                    frames[t] = sub
            except Exception:
                continue
    return frames


def refresh(store, now: datetime | None = None, frames: dict | None = None, labels: dict | None = None) -> dict:
    now = (now or datetime.now(NY)).astimezone(NY)
    if labels is None:
        from .market import load_universe
        uni = load_universe()
        labels = {r.ticker: [r.sector, r.industry] for r in uni.itertuples()}
    if frames is None:
        frames = fetch(list(labels))
    old = load(store) or {}
    state = summarize(changes(frames, now), labels, now, old.get("history"))
    store.set_setting(KEY, json.dumps(state, default=str))
    return state


def run_async(store_path) -> bool:
    """Start a refresh on its own thread when one is due (regular session only). Returns at once; never raises."""
    global _running, _last_try
    try:
        if us_session() != "REGULAR" or _running or time.time() - _last_try < FUNNEL_EVERY_S:
            return False
        from .live import MARKET_LOCK
        if MARKET_LOCK.locked():
            return False                                         # the S&P scan is downloading: do not double the load
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
                log.info("funnel read: %s stocks in %.0f s", (state.get("market") or {}).get("names"), time.time() - t0)
            except Exception:
                log.exception("funnel refresh failed")
            finally:
                _running = False

        threading.Thread(target=work, name="stockwatch-funnel", daemon=True).start()
        return True
    except Exception:
        log.exception("funnel start failed")
        return False
