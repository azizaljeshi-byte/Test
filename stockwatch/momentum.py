"""How the move is happening: its momentum, and what kind of move it is. Display only; it never changes a score,
status, call or alert.

Momentum (from the last completed daily bars): RSI(14), the 20-day return and MACD against its signal line.
  strong       up 8%+ over 20 sessions with MACD above its signal
  building     up over 20 sessions with MACD above its signal
  stabilising  down over 20 sessions but MACD has turned up
  fading       up over 20 sessions but MACD has turned down
  weak         down over 20 sessions with MACD below its signal
  falling      down 10%+ over 20 sessions with RSI under 40

Kind of move, first match wins (the others that also hit are listed in `also`):
  event          one session in the last 10 moved 6%+ (and 2.5 ATRs) on 2x its usual volume, the way the 20-day move went
  market         the market (benchmark) is itself 3%+ against the stock's direction over 20 sessions and the stock has not moved
                 more than 3 points further than it: the stock is going with the market
  sector         same test against the sector fund, when the market doesn't explain it
  distribution   5+ distribution days in 25 sessions (down 0.2%+ on higher volume than the day before) and more volume
                 on down days than up days over 20 sessions: sustained selling
  accumulation   the mirror: 5+ heavy-volume up days and more volume on up days
  drift          none of the above while momentum is negative: no event, no heavy selling, not the market
  none           nothing unusual while momentum is positive

Distribution days are the standard IBD count; RSI and MACD are the standard definitions. Unknown is unknown: too
little or unusable history gives `known` False with the reason, never a guess.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import technical
from .cis import decision

MIN_SESSIONS = 70
WINDOW = 420
EVENT_DAYS = 10
EVENT_MOVE = 0.06
EVENT_ATRS = 2.5
EVENT_VOLUME = 2.0
MARKET_MOVE = 0.03
DIST_DAYS = 25
DIST_MOVE = 0.002
DIST_COUNT = 5

MOMENTUM_LABEL = {"strong": "STRONG", "building": "BUILDING", "stabilising": "STABILISING", "fading": "FADING",
                  "weak": "WEAK", "falling": "FALLING"}
CAUSE_LABEL = {"event": "event-driven", "market": "market-wide", "sector": "sector-wide",
               "distribution": "distribution (sustained selling)", "accumulation": "accumulation (sustained buying)",
               "drift": "stock-specific drift", "none": "nothing unusual"}
NEGATIVE = ("falling", "weak", "fading")


def _unknown(why: str) -> dict:
    return {"known": False, "why": why, "momentum": None, "cause": None, "also": [], "facts": {}}


def _ret(close: pd.Series, n: int) -> float | None:
    return float(close.iloc[-1] / close.iloc[-1 - n] - 1) if len(close) > n and close.iloc[-1 - n] > 0 else None


def _benchmark_ret(hist, last_day, n: int = 20) -> float | None:
    """The benchmark's n-session return up to the stock's last session, from completed bars only."""
    try:
        close = hist["Close"].astype(float).dropna()
        idx = close.index.tz_localize(None) if getattr(close.index, "tz", None) is not None else close.index
        close = close[idx.normalize() <= pd.Timestamp(last_day)]
        close = close[close > 0]
        return _ret(close, n)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def assess(hist, market_hist=None, sector_hist=None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    recent = hist.iloc[-WINDOW:] if hist is not None and len(hist) else hist
    done, note, last_session = decision.current_bars(recent, now)
    if done is None:
        return _unknown(f"Price history unusable: {note}.")
    if len(done) < MIN_SESSIONS:
        return _unknown(f"Only {len(done)} daily bars; momentum needs {MIN_SESSIONS}.")
    vol = done["Volume"].astype(float)
    if not (np.isfinite(vol.iloc[-DIST_DAYS:]).all() and (vol.iloc[-DIST_DAYS:] > 0).all()):
        return _unknown("Volume is missing in the last 25 sessions, so selling pressure can't be measured.")
    ind = technical.indicators(done)
    close = done["Close"].astype(float)
    last = ind.iloc[-1]
    rsi, macd, sig = float(last["RSI"]), float(last["MACD"]), float(last["MACD_signal"])
    atr_pct = float(last["ATR"] / close.iloc[-1]) if close.iloc[-1] > 0 else float("nan")
    ret20, ret60 = _ret(close, 20), _ret(close, 60)
    if not all(np.isfinite(x) for x in (rsi, macd, sig, ret20)):
        return _unknown("The momentum indicators couldn't be computed.")
    macd_up = macd > sig
    if ret20 <= -0.10 and rsi < 40:
        mom = "falling"
    elif ret20 < 0 and not macd_up:
        mom = "weak"
    elif ret20 < 0:
        mom = "stabilising"
    elif ret20 >= 0.08 and macd_up:
        mom = "strong"
    elif macd_up:
        mom = "building"
    else:
        mom = "fading"
    sign = -1 if ret20 < 0 else 1

    # ---- the kind of move
    r = close.pct_change()
    avg_before = ind["VolAvg20"].shift(1)
    hits: dict[str, str] = {}
    gap_floor = max(EVENT_MOVE, EVENT_ATRS * atr_pct) if np.isfinite(atr_pct) else EVENT_MOVE
    event = None
    for i in range(1, EVENT_DAYS + 1):
        ratio = vol.iloc[-i] / avg_before.iloc[-i] if avg_before.iloc[-i] and np.isfinite(avg_before.iloc[-i]) else 0
        if np.sign(r.iloc[-i]) == sign and abs(r.iloc[-i]) >= gap_floor and ratio >= EVENT_VOLUME:
            if event is None or abs(r.iloc[-i]) > abs(event[1]):
                event = (done.index[-i].date().isoformat(), float(r.iloc[-i]), float(ratio))
    if event:
        hits["event"] = f"a {event[1]:+.0%} day on {event[2]:.1f}x its usual volume ({event[0]})"
    m_ret = _benchmark_ret(market_hist, done.index[-1].date()) if market_hist is not None else None
    s_ret = _benchmark_ret(sector_hist, done.index[-1].date()) if sector_hist is not None else None
    for key, b, name in (("market", m_ret, "the market"), ("sector", s_ret, "its sector")):
        if b is not None and np.sign(b) == sign and abs(b) >= MARKET_MOVE and (ret20 - b) * sign <= MARKET_MOVE:
            hits[key] = f"{name} is {b:+.0%} over 20 sessions, the stock {ret20:+.0%}"
    last25 = slice(-DIST_DAYS, None)
    heavier = vol > vol.shift(1)
    dist = int(((r <= -DIST_MOVE) & heavier).iloc[last25].sum())
    accum = int(((r >= DIST_MOVE) & heavier).iloc[last25].sum())
    up_v = float(vol[r > 0].iloc[-20:].sum())
    down_v = float(vol[r < 0].iloc[-20:].sum())
    ud = up_v / down_v if down_v > 0 else float("inf")
    if dist >= DIST_COUNT and ud < 1.0:
        hits["distribution"] = f"{dist} heavy-volume down days in {DIST_DAYS} sessions, {ud:.2f}x as much volume rising as falling"
    if accum >= DIST_COUNT and ud > 1.0:
        hits["accumulation"] = f"{accum} heavy-volume up days in {DIST_DAYS} sessions, {ud:.2f}x as much volume rising as falling"
    order = [k for k in ("event", "market", "sector", "distribution", "accumulation") if k in hits]
    if mom in NEGATIVE or ret20 < 0:
        order = [k for k in order if k != "accumulation"]
    else:
        order = [k for k in order if k != "distribution"]
    cause = order[0] if order else ("drift" if ret20 < 0 or mom in NEGATIVE else "none")
    also = order[1:]
    why = {"drift": "No big event day, no run of heavy selling, and the market isn't doing the same: it is the stock itself.",
           "none": "Nothing unusual in the volume, the market or the gaps."}.get(cause) or f"{hits[cause][0].upper()}{hits[cause][1:]}."
    if also:
        why += " Also: " + "; ".join(hits[k] for k in also) + "."
    tone = f"RSI {rsi:.0f}" + (" (oversold)" if rsi < 30 else " (overbought)" if rsi > 70 else "")
    return {"known": True, "momentum": mom, "momentum_label": MOMENTUM_LABEL[mom], "cause": cause,
            "cause_label": CAUSE_LABEL[cause], "also": also, "why": why,
            "facts": {"rsi": round(rsi, 1), "ret20": round(ret20, 4), "ret60": None if ret60 is None else round(ret60, 4),
                      "macd_above_signal": bool(macd_up), "distribution_days": dist, "accumulation_days": accum,
                      "up_down_volume": None if not np.isfinite(ud) else round(ud, 2),
                      "market_ret20": None if m_ret is None else round(m_ret, 4),
                      "sector_ret20": None if s_ret is None else round(s_ret, 4), "as_of": last_session},
            "summary": f"{MOMENTUM_LABEL[mom].title()} · {CAUSE_LABEL[cause]}", "tone": tone}
