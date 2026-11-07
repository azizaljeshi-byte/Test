"""The Momentum list (owner, 7 Nov 2026): stocks whose RSI is rising, MACD is improving and volume is building, read on 5-minute bars like a chart.
LOG AND DISPLAY ONLY. Scope: the whole S&P 500 list bundled with the app (tracked stocks are marked). It places no trade and changes no score, call or rule.

Every run reads five days of 5-minute bars for every stock (one bulk call per CHUNK, Yahoo throttle) and works out, on the latest bar (the one still
forming counts, as on a chart):
  RSI rising         RSI(14) on 5-minute bars is above its value on the previous bar and above its value 15 minutes ago
  MACD improving     the MACD(12, 26, 9) histogram on 5-minute bars is higher than on the previous bar (it may still be below zero)
  volume building    shares traded since 09:30 (finished bars only) are at least VOL_X times what this stock traded by the same bar on the earlier
                     days in the same download
A stock on the main list passes all three. The WATCH group passes two of three and names the missing one, so a rising RSI is never lost.
Both need price at least MIN_PRICE and an average day of at least MIN_AVG_VOL shares. The daily RSI is shown beside the 5-minute one for context.
Nothing is dropped silently: a stock that fails to download is tried once more in the same run; stocks still without data are counted and named
("no data this run"). Missing, old or short data is "unknown", never a pass and never a zero.

The first run is at 09:35 New York, then every EVERY_S seconds until the close; runs before 09:45 say volume is still settling. Each run is saved
(setting `rising_day_<date>`, every day kept for KEEP_DAYS) with what changed since the run before it:
  NEW (not on the previous run), arrows (price, RSI, MACD, volume up or down since the previous run), FADING (still passes but price, RSI and MACD
  are all lower than on the previous run), and the stocks that left with the first test they fail.
One background thread, through the same Yahoo throttle as the rest of the app, so a slow answer never delays the tracker. Once a day (before the open)
a second read of three months of daily closes feeds the daily RSI; if it is missing the daily RSI shows "none" and nothing else changes.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import datetime
from pathlib import Path

from .data import NY, _yahoo, us_session

log = logging.getLogger("stockwatch.rising")
KEY_STATE, KEY_DAILY, KEY_DAYS, KEY_DAY = "rising_state", "rising_daily", "rising_days", "rising_day_"
BUNDLED = Path(__file__).parent / "universe" / "sp500.csv"
FIRST_MIN = 9 * 60 + 35            # first run, minutes after midnight New York
EARLY_BEFORE = 9 * 60 + 45         # runs before this say the volume is still settling
OPEN_MIN = 9 * 60 + 30
EVERY_S = 300
VOL_X = 1.5
MIN_PRICE = 5.0
MIN_AVG_VOL = 500_000
MAX_BAR_AGE_MIN = 10               # a stock whose last bar started longer ago than this is unknown
MIN_BARS = 60
FULL_DAY_BARS = 70                 # an earlier day with fewer 5-minute bars (half day, halt) is not a usual day
MIN_PAST_DAYS = 2
CHUNK = 50
KEEP_DAYS = 180
CLOSES_KEPT = 70
TOL = {"price": 0.0, "rsi": 0.05, "hist": 0.005, "vol": 0.05}   # a change smaller than this is "flat"


def universe() -> list[str]:
    import pandas as pd
    return sorted(set(pd.read_csv(BUNDLED)["ticker"].astype(str)))


# ---------------------------------------------------------------- data (injected in tests)
@_yahoo
def _download(tickers, period, interval):
    import yfinance as yf
    return yf.download(list(tickers), period=period, interval=interval, group_by="ticker", auto_adjust=True, prepost=False,
                       threads=False, progress=False, timeout=15)


def _split(frame, tickers) -> dict:
    import pandas as pd
    out = {}
    for t in tickers:
        try:
            sub = frame[t] if isinstance(frame.columns, pd.MultiIndex) else frame
            sub = sub.reindex(columns=["Open", "High", "Low", "Close", "Volume"]).dropna(how="all")
            if len(sub):
                idx = pd.to_datetime(sub.index)
                sub.index = idx.tz_convert("America/New_York") if idx.tz is not None else idx.tz_localize("America/New_York")
                out[t] = sub
        except (KeyError, ValueError):
            continue
    return out


def fetch(tickers, period: str, interval: str) -> dict:
    out: dict = {}
    for i in range(0, len(tickers), CHUNK):
        chunk = list(tickers[i:i + CHUNK])
        try:
            out.update(_split(_download(chunk, period, interval), chunk))
        except Exception:
            log.warning("a chunk of %s stocks failed to download", len(chunk))
    return out


def fetch_frames(names: list[str]) -> dict:
    """Five days of 5-minute bars. Stocks that came back empty or short are tried once more, so a hiccup does not hide a stock."""
    out = fetch(names, "5d", "5m")
    again = [t for t in names if t not in out or len(out[t]) < MIN_BARS]
    if again:
        out.update({t: f for t, f in fetch(again, "5d", "5m").items() if len(f) >= MIN_BARS})
    return out


def build_daily(now: datetime, names=None, daily=None) -> dict:
    """Daily closes up to yesterday (for the daily RSI shown beside the 5-minute one)."""
    names = names or universe()
    today = now.astimezone(NY).date()
    daily = daily if daily is not None else fetch(names, "3mo", "1d")
    closes = {}
    for t, d in daily.items():
        c = d["Close"].dropna()
        c = c[[x.date() < today for x in c.index]]
        if len(c) >= 30:
            closes[t] = [round(float(v), 4) for v in c.iloc[-CLOSES_KEPT:]]
    return {"built_on": str(today), "closes": closes}


# ---------------------------------------------------------------- one stock
def _slot(t) -> int:
    return ((t.hour * 60 + t.minute) - OPEN_MIN) // 5


def evaluate(ticker: str, frame, now: datetime, daily_closes=None) -> dict:
    """Numbers for one stock now. {"t", "unknown": reason} when it cannot be read; otherwise the row with "miss" (tests not met) and "blocked"."""
    import pandas as pd
    from . import technical as ta
    if frame is None or len(frame) < MIN_BARS:
        return {"t": ticker, "unknown": "too little history"}
    now = now.astimezone(NY)
    frame = frame.dropna(subset=["Close"])
    dates = [t.date() for t in frame.index]
    today = now.date()
    tb = frame[[d == today for d in dates]]
    if tb.empty:
        return {"t": ticker, "unknown": "no price today"}
    if (now - tb.index[-1].to_pydatetime()).total_seconds() / 60 > MAX_BAR_AGE_MIN:
        return {"t": ticker, "unknown": "last trade is old"}
    pasts = [frame[[d == x for d in dates]] for x in sorted(set(dates)) if x < today]
    pasts = [p for p in pasts if len(p) >= FULL_DAY_BARS]
    if len(pasts) < MIN_PAST_DAYS:
        return {"t": ticker, "unknown": "too little history"}
    k = int(((now.hour * 60 + now.minute) - OPEN_MIN) // 5)           # finished 5-minute slots so far today
    prev_k = [float(p[[_slot(t) < k for t in p.index]]["Volume"].fillna(0).sum()) for p in pasts]
    avg_prev = sum(prev_k) / len(prev_k)
    avg_day = sum(float(p["Volume"].fillna(0).sum()) for p in pasts) / len(pasts)
    today_vol = float(tb[[_slot(t) < k for t in tb.index]]["Volume"].fillna(0).sum())
    vol_x = today_vol / avg_prev if k >= 1 and avg_prev > 0 else None
    c = frame["Close"]
    r = ta.rsi(c)
    line, sig = ta.macd(c)
    h = line - sig
    price = float(c.iloc[-1])
    if not math.isfinite(price) or price <= 0:
        return {"t": ticker, "unknown": "no price today"}
    rsi_day = None
    if daily_closes:
        rsi_day = round(float(ta.rsi(pd.Series(list(daily_closes) + [price])).iloc[-1]), 1)
    row = {"t": ticker, "price": round(price, 4), "chg": round((price / float(pasts[-1]["Close"].iloc[-1]) - 1) * 100, 2),
           "rsi": round(float(r.iloc[-1]), 2), "rsi_d": round(float(r.iloc[-1] - r.iloc[-4]), 2), "hist": round(float(h.iloc[-1]), 3),
           "hist_d": round(float(h.iloc[-1] - h.iloc[-2]), 3), "vol_x": None if vol_x is None else round(vol_x, 2), "rsi_day": rsi_day}
    miss = []
    if not (r.iloc[-1] > r.iloc[-2] and r.iloc[-1] > r.iloc[-4]):
        miss.append("RSI not rising")
    if not h.iloc[-1] > h.iloc[-2]:
        miss.append("MACD not improving")
    if vol_x is None:
        miss.append("volume unknown")
    elif not vol_x >= VOL_X:
        miss.append(f"volume {vol_x:.1f}x, under {VOL_X:g}x")
    row["miss"] = miss
    row["blocked"] = f"price under ${MIN_PRICE:g}" if price < MIN_PRICE else ("trades too little in a day" if avg_day < MIN_AVG_VOL else None)
    return row


def _dir(new, old, key) -> int:
    d = new - old
    return 0 if abs(d) <= TOL[key] else (1 if d > 0 else -1)


# ---------------------------------------------------------------- one run
def build_run(names: list[str], frames: dict, now: datetime, prev: dict | None, tracked=(), daily: dict | None = None) -> dict:
    now = now.astimezone(NY)
    daily = daily or {}
    rows, nodata = {}, []
    for t in names:
        r = evaluate(t, frames.get(t), now, daily.get(t))
        if "unknown" in r:
            nodata.append(t)
        else:
            rows[t] = r
    usable = [r for r in rows.values() if not r["blocked"]]
    on = sorted((r for r in usable if not r["miss"]), key=lambda r: -(r["vol_x"] or 0))
    watch = sorted((r for r in usable if len(r["miss"]) == 1), key=lambda r: -(r["vol_x"] or 0))
    tr = set(tracked)
    keys = ("t", "price", "chg", "rsi", "rsi_d", "hist", "hist_d", "vol_x", "rsi_day")
    prev_rows = {r["t"]: r for r in (prev or {}).get("rows", [])}
    out = []
    for r in on:
        x = {k: r[k] for k in keys}
        x["tracked"] = r["t"] in tr
        p = prev_rows.get(r["t"])
        if prev is None or p is None:
            x["tag"], x["dir"] = ("NEW" if prev is not None else ""), None
        else:
            x["dir"] = {"price": _dir(r["price"], p["price"], "price"), "rsi": _dir(r["rsi"], p["rsi"], "rsi"),
                        "hist": _dir(r["hist"], p["hist"], "hist"), "vol": _dir(r["vol_x"], p["vol_x"] or 0, "vol")}
            x["tag"] = "FADING" if x["dir"]["price"] < 0 and x["dir"]["rsi"] < 0 and x["dir"]["hist"] < 0 else ""
        out.append(x)
    wout = []
    for r in watch:
        x = {k: r[k] for k in keys}
        x["tracked"], x["miss"], x["tag"], x["dir"] = r["t"] in tr, r["miss"][0], "", None
        wout.append(x)
    left, now_on = [], {r["t"] for r in on}
    for p in (prev or {}).get("rows", []):
        if p["t"] not in now_on:
            cur = rows.get(p["t"])
            left.append({"t": p["t"], "why": (cur["blocked"] or (cur["miss"][0] if cur["miss"] else "no fresh data")) if cur else "no data this run"})
    minute = now.hour * 60 + now.minute
    return {"at": now.isoformat(timespec="seconds"), "day": str(now.date()), "early": minute < EARLY_BEFORE, "status": "ok", "read": len(rows),
            "unknown": len(nodata), "nodata": nodata, "pass": len(out), "rows": out, "watch": wout, "left": left}


# ---------------------------------------------------------------- storage
def _get(store, key, default):
    try:
        raw = store.get_setting(key)
        return json.loads(raw) if raw else default
    except ValueError:
        return default


def load_state(store) -> dict | None:
    return _get(store, KEY_STATE, None)


def runs(store, day: str) -> list:
    d = _get(store, KEY_DAY + day, [])
    return d if isinstance(d, list) else []


def days(store) -> list:
    d = _get(store, KEY_DAYS, [])
    return d if isinstance(d, list) else []


def load_daily(store, today: str) -> dict | None:
    b = _get(store, KEY_DAILY, None)
    return b if isinstance(b, dict) and b.get("built_on") == today else None


def compact(state: dict) -> dict:
    """What a past run keeps: the full main list, and for the watch group only the stock and the test it misses."""
    return {**state, "watch": [{"t": w["t"], "miss": w["miss"]} for w in state.get("watch", [])]}


def save_run(store, state: dict) -> None:
    store.set_setting(KEY_STATE, json.dumps(state))
    day = state["day"]
    store.set_setting(KEY_DAY + day, json.dumps(runs(store, day) + [compact(state)]))
    known = days(store)
    if day not in known:
        known.append(day)
        for old in known[:-KEEP_DAYS]:
            store.set_setting(KEY_DAY + old, "[]")
        store.set_setting(KEY_DAYS, json.dumps(known[-KEEP_DAYS:]))


def refresh(store, now: datetime | None = None, frames: dict | None = None, tracked=None, names=None) -> dict | None:
    """One run. None outside the list's hours."""
    now = (now or datetime.now(NY)).astimezone(NY)
    if us_session(now) != "REGULAR" or now.hour * 60 + now.minute < FIRST_MIN:
        return None
    names = names or (sorted(frames) if frames is not None else universe())
    if frames is None:
        frames = fetch_frames(names)
    if tracked is None:
        try:
            tracked = [s["ticker"] for s in store.latest_snapshots()]
        except Exception:
            tracked = []
    d = load_daily(store, str(now.date()))
    today = runs(store, str(now.date()))
    state = build_run(names, frames, now, today[-1] if today else None, tracked, (d or {}).get("closes"))
    save_run(store, state)
    return state


# ---------------------------------------------------------------- background
_lock = threading.Lock()
_running = False
_last_start = 0.0


def run_async(store_path) -> bool:
    """Start a run (or the daily-close read) on its own thread when one is due. Returns at once; never raises."""
    global _running, _last_start
    try:
        if us_session() not in ("PRE", "REGULAR") or _running or time.time() - _last_start < EVERY_S:
            return False
        with _lock:
            if _running:
                return False
            _running, _last_start = True, time.time()

        def work():
            global _running
            try:
                from .store import Store
                t0 = time.time()
                st = Store(store_path) if store_path else Store()
                state = refresh(st)
                if state:
                    log.info("momentum list: %s read, %s on the list, %s watch, %s no data, %.0f s", state["read"], state["pass"],
                             len(state["watch"]), state["unknown"], time.time() - t0)
                now = datetime.now(NY)
                if load_daily(st, str(now.date())) is None:
                    st.set_setting(KEY_DAILY, json.dumps(build_daily(now)))
                    log.info("momentum daily closes read in %.0f s", time.time() - t0)
            except Exception:
                log.exception("momentum list failed")
            finally:
                _running = False

        threading.Thread(target=work, name="stockwatch-rising", daemon=True).start()
        return True
    except Exception:
        log.exception("momentum list start failed")
        return False
