"""The Momentum list (owner, 7 Nov 2026): stocks whose RSI is rising, MACD is improving and volume is building, during the session. LOG AND DISPLAY ONLY.

Scope: the whole S&P 500 list bundled with the app (tracked stocks are marked). It places no trade and changes no score, call or rule.

A stock is on the list when ALL of these hold, using yesterday's close and today's price so far:
  RSI rising         RSI(14) is above its level at yesterday's close and above its level three sessions ago
  MACD improving     the MACD histogram (12, 26, 9) is higher than at yesterday's close (it may still be below zero)
  volume building    shares traded since 09:30 are at least VOL_X times what this stock usually trades by the same minute
  and the stock costs at least MIN_PRICE and trades at least MIN_AVG_VOL shares a day (keeps penny and thin stocks out)
Missing, old or short data is "unknown" and the stock is left out with a count, never scored as a pass or a zero.

The first run is at 09:35 New York, then every EVERY_S seconds until the close. Runs before 09:45 say the volume is still settling.
Each run is saved (setting `rising_day_<date>`, every day kept for KEEP_DAYS) with what changed since the run before it:
  NEW      it was not on the previous run
  arrows   price, RSI, MACD and volume up or down since the previous run
  FADING   still passes, but price, RSI and MACD are all lower than on the previous run
  left     stocks that dropped off, and the first test they fail

Once a day (before or at the open, `rising_base`) a background pass reads three months of daily closes and five days of 1-minute bars to work
out each stock's usual volume by every 5th minute of the session. Until it is built the page says so and no list is made.
Everything runs on its own thread, through the same Yahoo throttle as the rest of the app, so a slow answer never delays the tracker.
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
KEY_STATE, KEY_BASE, KEY_DAYS, KEY_DAY = "rising_state", "rising_base", "rising_days", "rising_day_"
BUNDLED = Path(__file__).parent / "universe" / "sp500.csv"
FIRST_MIN = 9 * 60 + 35            # first run, minutes after midnight New York
EARLY_BEFORE = 9 * 60 + 45         # runs before this say the volume is still settling
OPEN_MIN = 9 * 60 + 30
EVERY_S = 300
VOL_X = 1.5
MIN_PRICE = 5.0
MIN_AVG_VOL = 500_000
MAX_BAR_AGE_MIN = 8                # a stock whose last bar is older than this is unknown
CHUNK = 50
MARK = 5                           # baseline kept at every 5th minute of the session
SESSION_MIN = 390
KEEP_DAYS = 180
CLOSES_KEPT = 70
MIN_BASE_DAYS = 2
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
        out.update(_split(_download(chunk, period, interval), chunk))
    return out


# ---------------------------------------------------------------- the daily baseline
def _cum_marks(df, day) -> list[int] | None:
    """Cumulative shares traded at minute 5, 10 ... 390 of one regular session, or None when the day is not a full read."""
    d = df[[t.date() == day for t in df.index]]
    mins = [(t.hour * 60 + t.minute) - OPEN_MIN for t in d.index]
    vol = [0.0] * SESSION_MIN
    for m, v in zip(mins, d["Volume"].fillna(0)):
        if 0 <= m < SESSION_MIN:
            vol[m] += float(v)
    if sum(vol) <= 0 or len(d) < 370:                                # a half day or a halt is not a normal day
        return None
    run, out = 0.0, []
    for m in range(SESSION_MIN):
        run += vol[m]
        if (m + 1) % MARK == 0:
            out.append(run)
    return out


def build_base(now: datetime, tickers=None, daily=None, minutes=None) -> dict:
    """Closes up to yesterday, usual cumulative volume by minute, and the usual daily volume, for every stock. Slow (minutes): own thread."""
    tickers = tickers or universe()
    today = now.astimezone(NY).date()
    daily = daily if daily is not None else fetch(tickers, "3mo", "1d")
    minutes = minutes if minutes is not None else fetch(tickers, "5d", "1m")
    closes, cum, avg_day = {}, {}, {}
    for t in tickers:
        d = daily.get(t)
        if d is not None:
            c = d["Close"].dropna()
            c = c[[x.date() < today for x in c.index]]
            if len(c) >= 40:
                closes[t] = [round(float(v), 4) for v in c.iloc[-CLOSES_KEPT:]]
        m = minutes.get(t)
        if m is not None:
            days = sorted({x.date() for x in m.index if x.date() < today})
            curves = [c for c in (_cum_marks(m, x) for x in days) if c]
            if len(curves) >= MIN_BASE_DAYS:
                cum[t] = [round(sum(c[k] for c in curves) / len(curves)) for k in range(len(curves[0]))]
                avg_day[t] = round(sum(c[-1] for c in curves) / len(curves))
    return {"built_on": str(today), "built_at": now.astimezone(NY).isoformat(timespec="seconds"), "closes": closes, "cum": cum, "avg_day": avg_day}


def expected_volume(marks: list, minute: int) -> float | None:
    """The usual shares traded by `minute` minutes into the session, between the stored 5-minute marks."""
    if not marks or minute <= 0:
        return None
    pos = min(minute, SESSION_MIN) / MARK
    lo = int(pos)
    if lo <= 0:
        return marks[0] * pos
    if lo >= len(marks):
        return float(marks[-1])
    return marks[lo - 1] + (marks[lo] - marks[lo - 1]) * (pos - lo)


# ---------------------------------------------------------------- one stock
def evaluate(ticker: str, base: dict, bars, now: datetime) -> dict:
    """Numbers for one stock now. {"t", "unknown": reason} when it cannot be read; otherwise the row with a "fails" list (empty = on the list)."""
    import pandas as pd
    from . import technical as ta
    closes, marks, avg = base["closes"].get(ticker), base["cum"].get(ticker), base["avg_day"].get(ticker)
    if not closes or not marks or not avg:
        return {"t": ticker, "unknown": "no usual-volume or daily history"}
    if bars is None or not len(bars):
        return {"t": ticker, "unknown": "no price today"}
    now = now.astimezone(NY)
    minute = int((now.hour * 60 + now.minute) - OPEN_MIN)
    done = bars[[(t.hour * 60 + t.minute) - OPEN_MIN < minute and t.date() == now.date() for t in bars.index]].dropna(subset=["Close"])
    if not len(done):
        return {"t": ticker, "unknown": "no price today"}
    age = (now - done.index[-1].to_pydatetime()).total_seconds() / 60
    if age > MAX_BAR_AGE_MIN:
        return {"t": ticker, "unknown": "last trade is old"}
    price = float(done["Close"].iloc[-1])
    exp = expected_volume(marks, minute)
    if not exp or exp <= 0 or price <= 0 or not math.isfinite(price):
        return {"t": ticker, "unknown": "no usual volume for this minute"}
    c2 = pd.Series(closes + [price])
    r = ta.rsi(c2)
    line, sig = ta.macd(c2)
    h = line - sig
    row = {"t": ticker, "price": round(price, 4), "chg": round((price / closes[-1] - 1) * 100, 2), "rsi": round(float(r.iloc[-1]), 2),
           "rsi_1d": round(float(r.iloc[-1] - r.iloc[-2]), 2), "rsi_3d": round(float(r.iloc[-1] - r.iloc[-4]), 2),
           "hist": round(float(h.iloc[-1]), 3), "hist_1d": round(float(h.iloc[-1] - h.iloc[-2]), 3),
           "vol_x": round(float(done["Volume"].fillna(0).sum()) / exp, 2), "age_min": round(age, 1)}
    fails = []
    if price < MIN_PRICE:
        fails.append(f"price under ${MIN_PRICE:g}")
    if avg < MIN_AVG_VOL:
        fails.append("trades too little in a day")
    if not (row["rsi_1d"] > 0 and row["rsi_3d"] > 0):
        fails.append("RSI is no longer rising")
    if not row["hist_1d"] > 0:
        fails.append("MACD is no longer improving")
    if not row["vol_x"] >= VOL_X:
        fails.append(f"volume is {row['vol_x']:.1f}x, under {VOL_X:g}x")
    row["fails"] = fails
    return row


def _dir(new, old, key) -> int:
    d = new - old
    return 0 if abs(d) <= TOL[key] else (1 if d > 0 else -1)


# ---------------------------------------------------------------- one run
def build_run(base: dict, frames: dict, now: datetime, prev: dict | None, tracked=()) -> dict:
    now = now.astimezone(NY)
    rows, unknown = {}, 0
    for t in base["closes"]:
        r = evaluate(t, base, frames.get(t), now)
        if "unknown" in r:
            unknown += 1
        else:
            rows[t] = r
    on = sorted((r for r in rows.values() if not r["fails"]), key=lambda r: -r["vol_x"])
    prev_rows = {r["t"]: r for r in (prev or {}).get("rows", [])}
    out = []
    for r in on:
        x = {k: r[k] for k in ("t", "price", "chg", "rsi", "rsi_1d", "rsi_3d", "hist", "hist_1d", "vol_x")}
        x["tracked"] = r["t"] in set(tracked)
        p = prev_rows.get(r["t"])
        if prev is None or p is None:
            x["tag"], x["dir"] = ("NEW" if prev is not None else ""), None
        else:
            x["dir"] = {"price": _dir(r["price"], p["price"], "price"), "rsi": _dir(r["rsi"], p["rsi"], "rsi"),
                        "hist": _dir(r["hist"], p["hist"], "hist"), "vol": _dir(r["vol_x"], p["vol_x"], "vol")}
            x["tag"] = "FADING" if x["dir"]["price"] < 0 and x["dir"]["rsi"] < 0 and x["dir"]["hist"] < 0 else ""
        out.append(x)
    left = []
    now_on = {r["t"] for r in on}
    for p in (prev or {}).get("rows", []):
        if p["t"] not in now_on:
            cur = rows.get(p["t"])
            left.append({"t": p["t"], "why": (cur["fails"][0] if cur and cur["fails"] else "no fresh data")})
    minute = now.hour * 60 + now.minute
    return {"at": now.isoformat(timespec="seconds"), "day": str(now.date()), "early": minute < EARLY_BEFORE, "status": "ok",
            "read": len(rows), "unknown": unknown, "pass": len(out), "rows": out, "left": left}


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


def load_base(store, today: str) -> dict | None:
    b = _get(store, KEY_BASE, None)
    return b if isinstance(b, dict) and b.get("built_on") == today else None


def save_run(store, state: dict) -> None:
    store.set_setting(KEY_STATE, json.dumps(state))
    day = state["day"]
    store.set_setting(KEY_DAY + day, json.dumps(runs(store, day) + [state]))
    known = days(store)
    if day not in known:
        known.append(day)
        for old in known[:-KEEP_DAYS]:
            store.set_setting(KEY_DAY + old, "[]")
        store.set_setting(KEY_DAYS, json.dumps(known[-KEEP_DAYS:]))


def refresh(store, now: datetime | None = None, frames: dict | None = None, tracked=None) -> dict | None:
    """One run. None outside the list's hours. {"status": "baseline"} while the daily volume baseline is not built."""
    now = (now or datetime.now(NY)).astimezone(NY)
    if us_session(now) != "REGULAR" or now.hour * 60 + now.minute < FIRST_MIN:
        return None
    base = load_base(store, str(now.date()))
    if base is None:
        state = {"at": now.isoformat(timespec="seconds"), "day": str(now.date()), "status": "baseline", "rows": [], "left": [], "pass": 0, "read": 0, "unknown": 0}
        store.set_setting(KEY_STATE, json.dumps(state))
        return state
    if frames is None:
        frames = fetch(list(base["closes"]), "1d", "1m")
    if tracked is None:
        try:
            tracked = [s["ticker"] for s in store.latest_snapshots()]
        except Exception:
            tracked = []
    today = runs(store, str(now.date()))
    state = build_run(base, frames, now, today[-1] if today else None, tracked)
    save_run(store, state)
    return state


# ---------------------------------------------------------------- background
_lock = threading.Lock()
_running = False
_last_start = 0.0


def run_async(store_path) -> bool:
    """Start the baseline build or a run on its own thread when one is due. Returns at once; never raises."""
    global _running, _last_start
    try:
        session = us_session()
        if session not in ("PRE", "REGULAR") or _running or time.time() - _last_start < EVERY_S:
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
                now = datetime.now(NY)
                if load_base(st, str(now.date())) is None:
                    st.set_setting(KEY_BASE, json.dumps(build_base(now)))
                    log.info("momentum baseline built in %.0f s", time.time() - t0)
                state = refresh(st)
                if state and state.get("status") == "ok":
                    log.info("momentum list: %s read, %s on the list, %.0f s", state["read"], state["pass"], time.time() - t0)
            except Exception:
                log.exception("momentum list failed")
            finally:
                _running = False

        threading.Thread(target=work, name="stockwatch-rising", daemon=True).start()
        return True
    except Exception:
        log.exception("momentum list start failed")
        return False
