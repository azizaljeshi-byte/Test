"""Same-stock historical analogues: what happened after earlier sessions that met a fixed, declared rule.

Each policy below was declared for one observed setup in the 23 October 2026 reference round. There is no
validated automatic rule selector, and these aren't a rule library: each is kept exactly as recorded, with
its ID. Selection is causal and fixed before outcomes are looked at:
- a session qualifies using only that session's completed indicators;
- the first qualifying session is kept, then the next 20 sessions are skipped;
- an episode whose full 20-session outcome would overlap the current formation (or, for ISRG, the
  current 100-session context) is excluded;
- matches are ranked by a declared feature distance, never by outcome.
Each match reports 5/10/20-session close returns, the best and worst excursion over 20 sessions (highs and
lows), its 20-session endpoint category against that date's own ATR band, and, where the policy records them,
the first close below a fixed support (the lowest low of the signal day and the sessions before it; the
window reproduces the reference fixtures, the rule texts don't state it) and the first close back above the
signal day's average. Outcomes that haven't happened are None, never 0. Rates are descriptions of the past, not probabilities.

This is a different method from the Research lab's shape matching (`research_lab` / `chart_patterns`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from . import features

HORIZONS = (5, 10, 20)
FEATURES = ("rsi", "drawdown", "dist50", "dist200", "ret5", "rebound", "atr_pct", "rv")
SUPPRESS = 20
YEARS = 5


@dataclass(frozen=True)
class Policy:
    id: str
    symbol: str
    text: str
    qualifies: Callable[[pd.DataFrame], pd.Series]
    weights: dict                # feature -> denominator for the additive normalised distance
    reserved: int                # recent sessions an episode's outcome must not reach
    reclaim: str | None          # the signal-day average a later close must reclaim, if the policy reports one
    support_window: int | None   # fixed support: the lowest low of the signal day and the sessions before it


def _between(s, lo, hi):
    return (s >= lo) & (s <= hi)


POLICIES = {p.symbol: p for p in (
    Policy("isrg-recovery-v1", "ISRG",
           "Prior five years; close above SMA200, SMA50 below SMA200, RSI14 60–75, close 0–6% above SMA200, "
           "five-session return above 3%, ATR14/close 2–4%, volume/prior-20 average 0.8–2.0. First qualifying "
           "day, then skip 20 sessions. Excludes any episode whose 20-session outcome reaches the current "
           "100-session context.",
           lambda f: (f.close > f.ma200) & (f.ma50 < f.ma200) & _between(f.rsi, 60, 75) & _between(f.dist200, 0, 0.06)
           & (f.ret5 > 0.03) & _between(f.atr_pct, 0.02, 0.04) & _between(f.rv, 0.8, 2.0),
           {"rsi": 15, "dist200": 0.06}, reserved=100, reclaim=None, support_window=None),
    Policy("fico-rebound-in-downtrend-v1", "FICO",
           "FICO only; prior five years; close < SMA50 < SMA200; RSI14 45–60; at least 30% below the trailing "
           "252-session closing high; at least 15% above the trailing 20-session intraday low; ATR14/close 3–8%. "
           "First qualifying date, skip the next 20 sessions; the 20-session outcome must end before the current "
           "20-session formation begins. Ranked by RSI, drawdown, rebound and ATR distance.",
           lambda f: (f.close < f.ma50) & (f.ma50 < f.ma200) & _between(f.rsi, 45, 60) & (f.drawdown <= -0.30)
           & (f.rebound >= 0.15) & _between(f.atr_pct, 0.03, 0.08),
           {"rsi": 15, "drawdown": 0.30, "rebound": 0.40, "atr_pct": 0.05}, reserved=20, reclaim="ma50", support_window=5),
    Policy("crdo-breakdown-v1", "CRDO",
           "CRDO only, listed history within five years; close below SMA200 while SMA50 stays above SMA200; RSI14 "
           "30–45; at least 30% below the trailing 252-session closing high; five-session return at most -8%; "
           "ATR14/close 6–14%. First qualifying day, skip the next 20 sessions; the full 20-session outcome must "
           "end before the current 20-session formation starts. Ranked by RSI, drawdown, five-session return and "
           "ATR percentage.",
           lambda f: (f.close < f.ma200) & (f.ma50 > f.ma200) & _between(f.rsi, 30, 45) & (f.drawdown <= -0.30)
           & (f.ret5 <= -0.08) & _between(f.atr_pct, 0.06, 0.14),
           {"rsi": 15, "drawdown": 0.30, "ret5": 0.20, "atr_pct": 0.08}, reserved=20, reclaim="ma200", support_window=20),
    Policy("podd-recovery-below-200-v1", "PODD",
           "PODD only; prior five years; SMA50 < close < SMA200; RSI14 55–70; close no more than 10% above SMA50; "
           "at least 30% below the trailing 252-session closing high; five-session return above 3%; ATR14/close "
           "2–6%. First qualifying date, skip the next 20 sessions; the complete 20-session outcome must end "
           "before the current 20-session formation begins. Ranked by RSI, distance to SMA50, drawdown and ATR "
           "percentage.",
           lambda f: (f.ma50 < f.close) & (f.close < f.ma200) & _between(f.rsi, 55, 70) & (f.dist50 <= 0.10)
           & (f.drawdown <= -0.30) & (f.ret5 > 0.03) & _between(f.atr_pct, 0.02, 0.06),
           {"rsi": 15, "dist50": 0.10, "drawdown": 0.30, "atr_pct": 0.04}, reserved=20, reclaim="ma200", support_window=5),
)}


def _num(v):
    return float(v) if v is not None and np.isfinite(v) else None


def select(f: pd.DataFrame, policy: Policy) -> list[int]:
    """Row positions of the kept signals, in date order. Uses only each row's own completed indicators."""
    n = len(f)
    start = f.index[-1] - pd.DateOffset(years=YEARS)
    ok = policy.qualifies(f).fillna(False).to_numpy() & (f.index > start)
    kept, next_allowed = [], 0
    for i in np.flatnonzero(ok):
        if i < next_allowed:
            continue
        kept.append(int(i))
        next_allowed = i + SUPPRESS + 1
    return [i for i in kept if i + max(HORIZONS) < n - policy.reserved]


def outcome(df: pd.DataFrame, f: pd.DataFrame, i: int, policy: Policy) -> dict:
    """What followed signal row i. A horizon past the end of the data is None."""
    c, h, lo = (df[k].to_numpy(dtype=float) for k in ("Close", "High", "Low"))
    p0, n = c[i], len(c)
    rets = {str(k): (_num(c[i + k] / p0 - 1) if i + k < n else None) for k in HORIZONS}
    end = min(i + max(HORIZONS), n - 1)
    window = slice(i + 1, end + 1)
    done = i + max(HORIZONS) < n
    out = {"date": str(df.index[i].date()), "price": float(p0), "returns": rets,
           "mfe": _num(h[window].max() / p0 - 1) if end > i else None,
           "mae": _num(lo[window].min() / p0 - 1) if end > i else None,
           "path": [round(float(x), 4) for x in c[i:end + 1] / p0 * 100]}
    if policy.support_window:
        support = float(lo[max(0, i - policy.support_window + 1):i + 1].min())
        out["support"] = support
        out["support_first_close_break_session"] = next((k for k in range(1, end - i + 1) if c[i + k] < support), None)
    if policy.reclaim:
        level = f[policy.reclaim].iloc[i]
        out[f"recovery_above_signal_{policy.reclaim}_session"] = next(
            (k for k in range(1, end - i + 1) if c[i + k] > level), None)
    band = f["atr"].iloc[i]                      # that date's own ATR is the neutral band
    out["category"] = None if not done else (
        "up" if c[i + 20] > p0 + band else "down" if c[i + 20] < p0 - band else "sideways")
    return out


def distance(f: pd.DataFrame, i: int, q: int, policy: Policy) -> float:
    return float(sum(abs(f[k].iloc[i] - f[k].iloc[q]) / d for k, d in policy.weights.items()))


def analogues(df: pd.DataFrame, policy: Policy) -> dict:
    """All matches under the policy for the last completed session, ranked by distance, with a summary."""
    f = features.indicators(df)
    q = len(f) - 1
    rows = []
    for i in select(f, policy):
        r = outcome(df, f, i, policy)
        r["distance"] = distance(f, i, q, policy)
        r.update({k: _num(f[k].iloc[i]) for k in FEATURES})
        rows.append(r)
    rows.sort(key=lambda r: r["distance"])
    return {"policy_id": policy.id, "rule": policy.text, "as_of": str(df.index[-1].date()),
            "query": {k: _num(f[k].iloc[q]) for k in policy.weights}, "analogues": rows, "summary": summary(rows)}


def summary(rows: list[dict]) -> dict:
    """Full-sample counts and medians/ranges. Each horizon counts only the matches where it was observed."""
    out = {"n": len(rows), "counts": {k: sum(r["category"] == k for r in rows) for k in ("up", "sideways", "down")},
           "returns": {}}
    for h in HORIZONS:
        vals = [r["returns"][str(h)] for r in rows if r["returns"][str(h)] is not None]
        out["returns"][str(h)] = ({"n": len(vals), "median": float(np.median(vals)), "min": min(vals), "max": max(vals)}
                                  if vals else {"n": 0, "median": None, "min": None, "max": None})
    for k in ("mfe", "mae"):
        vals = [r[k] for r in rows if r[k] is not None]
        out[f"median_{k}"] = float(np.median(vals)) if vals else None
    return out

