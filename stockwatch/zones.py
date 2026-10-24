"""Support and resistance as graded zones, from independent reasons that land on the same price. Display only: it feeds
no score, status, call, stop or alert.

A zone is built from swing highs and lows (a bar that is the highest or lowest of the 5 bars either side) over about
two years of completed daily bars, grouped when within 1.5% of each other. Each zone is graded from:
  touches   2 points for 4+ swing points in the zone, 1 for 2 or 3 (a lone point is a weak level)
  average   +1 when the 50-day or 200-day average sits inside the zone
  round     +1 when a round number sits inside the zone
  volume    +1 when the swing bars carried 1.3x the usual volume
  recent    +1 when it last reacted within 90 days; -1 when the last reaction was over 400 days ago
HIGH is 4+ points, MEDIUM is 2 or 3, LOW is 0 or 1. Unknown stays unknown: too little history gives `known` False with
the reason, never an invented level.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import technical
from .cis import decision

MIN_SESSIONS = 120
WINDOW = 520
PIVOT = 5
JOIN = 0.015
HEAVY = 1.3
RECENT_DAYS, OLD_DAYS = 90, 400


def _round_step(price: float) -> float:
    return 0.5 if price < 10 else 1.0 if price < 50 else 5.0 if price < 200 else 10.0 if price < 1000 else 50.0


def _pivots(done: pd.DataFrame) -> list[tuple[float, pd.Timestamp, float, str]]:
    """(price, date, volume ratio, 'high' | 'low') for each swing point."""
    hi, lo = done["High"].astype(float), done["Low"].astype(float)
    vol = done["Volume"].astype(float)
    avg = vol.rolling(20).mean().shift(1)
    out = []
    last_at = {"high": -10 * PIVOT, "low": -10 * PIVOT}       # a flat top or bottom is one touch, not several
    for i in range(PIVOT, len(done) - PIVOT):
        window = slice(i - PIVOT, i + PIVOT + 1)
        ratio = float(vol.iloc[i] / avg.iloc[i]) if avg.iloc[i] and np.isfinite(avg.iloc[i]) else 1.0
        for kind, series, test in (("high", hi, hi.iloc[i] >= hi.iloc[window].max()),
                                   ("low", lo, lo.iloc[i] <= lo.iloc[window].min())):
            if test and i - last_at[kind] > PIVOT:
                out.append((float(series.iloc[i]), done.index[i], ratio, kind))
                last_at[kind] = i
    return out


def _cluster(points: list) -> list[list]:
    points = sorted(points, key=lambda p: p[0])
    groups: list[list] = []
    for p in points:
        if groups and p[0] <= groups[-1][0][0] * (1 + JOIN):
            groups[-1].append(p)
        else:
            groups.append([p])
    return groups


def _grade(group: list, ind_last, last_day: pd.Timestamp) -> dict:
    lows = [p[0] for p in group]
    low, high = min(lows), max(lows)
    reasons, pts = [], 0
    n = len(group)
    if n >= 4:
        pts += 2
    elif n >= 2:
        pts += 1
    reasons.append(f"{n} touch{'es' if n != 1 else ''}")
    for col, name in (("SMA50", "50-day average"), ("SMA200", "200-day average")):
        v = float(ind_last[col]) if np.isfinite(ind_last[col]) else None
        if v and low * (1 - JOIN / 2) <= v <= high * (1 + JOIN / 2):
            pts += 1
            reasons.append(name)
            break
    mid = (low + high) / 2
    step = _round_step(mid)
    near = round(mid / step) * step
    if near > 0 and low * (1 - JOIN / 2) <= near <= high * (1 + JOIN / 2):
        pts += 1
        reasons.append("round number")
    if np.mean([p[2] for p in group]) >= HEAVY:
        pts += 1
        reasons.append("heavy volume")
    age = int((last_day - max(p[1] for p in group)).days)
    if age <= RECENT_DAYS:
        pts += 1
        reasons.append("recent")
    elif age > OLD_DAYS:
        pts -= 1
        reasons.append(f"{age // 30} months old")
    grade = "HIGH" if pts >= 4 else "MEDIUM" if pts >= 2 else "LOW"
    return {"low": round(low, 2), "high": round(high, 2), "touches": n, "age_days": age, "grade": grade,
            "points": pts, "reasons": reasons}


def _unknown(why: str) -> dict:
    return {"known": False, "why": why, "support": [], "resistance": []}


def assess(hist, now: datetime | None = None, price: float | None = None) -> dict:
    """The two nearest zones below and above the last close, each graded, or `known` False with the reason."""
    now = now or datetime.now(timezone.utc)
    recent = hist.iloc[-WINDOW:] if hist is not None and len(hist) else hist
    done, note, last_session = decision.current_bars(recent, now)
    if done is None:
        return _unknown(f"Price history unusable: {note}.")
    if len(done) < MIN_SESSIONS:
        return _unknown(f"Only {len(done)} daily bars; zones need {MIN_SESSIONS}.")
    ind = technical.indicators(done)
    last = ind.iloc[-1]
    close = float(price if price and np.isfinite(price) else done["Close"].iloc[-1])
    zones = [_grade(g, last, done.index[-1]) for g in _cluster(_pivots(done))]
    below = sorted((z for z in zones if z["high"] < close), key=lambda z: -z["high"])[:2]
    above = sorted((z for z in zones if z["low"] > close), key=lambda z: z["low"])[:2]
    return {"known": True, "close": round(close, 2), "support": below, "resistance": above, "as_of": last_session}
