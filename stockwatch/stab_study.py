"""Study: after a stock has fallen hard, does "flat for N sessions" mean the fall is over, or a pause before another leg down? STUDY ONLY.

The sample is every stock-day in the app's own "falling" momentum state (down 10%+ over 20 sessions, RSI(14) under 40; see momentum.py).
On each of those days we ask: were the last N daily closes flat (highest minus lowest close at most K daily ranges)?
Then, over the next HORIZON sessions: did it make a fresh closing low (under the lowest close of those N sessions), a clearly lower one
(1 daily range or more under it), and what was the return? Flat days are compared with all falling days and, to show what flatness adds
beyond how long ago the drop was, with not-flat days. Two halves of the history, so one period cannot carry the result.
Needs only daily Open/High/Low/Close (the same download as the candle-break study); never touches the app.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WINDOWS = (3, 4, 5, 6, 7, 8, 10)
FLATS = (0.6, 1.0)
HORIZON = 10
FALL_20D, FALL_RSI = -0.10, 40.0


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def cases(df: pd.DataFrame, windows=WINDOWS, flats=FLATS, horizon: int = HORIZON) -> pd.DataFrame:
    """One row per (falling day, window, flat limit): flat?, fresh low?, clearly lower?, forward return. Rows need `horizon` sessions ahead."""
    c = df["Close"].astype(float)
    a = atr(df)
    falling = ((c / c.shift(20) - 1) <= FALL_20D) & (rsi(c) < FALL_RSI)
    fwd_min = pd.concat([c.shift(-i) for i in range(1, horizon + 1)], axis=1).min(axis=1)
    fwd_ret = c.shift(-horizon) / c - 1
    out = []
    for n in windows:
        hi, lo = c.rolling(n).max(), c.rolling(n).min()
        spread = (hi - lo) / a
        for k in flats:
            m = falling & fwd_ret.notna() & spread.notna() & (a > 0)
            if not m.any():
                continue
            out.append(pd.DataFrame({"n": n, "k": k, "flat": (spread[m] <= k).to_numpy(), "fresh_low": (fwd_min[m] < lo[m]).to_numpy(),
                                     "lower_1atr": (fwd_min[m] <= lo[m] - a[m]).to_numpy(), "ret": fwd_ret[m].to_numpy(),
                                     "date": c.index[m.to_numpy()]}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["n", "k", "flat", "fresh_low", "lower_1atr", "ret", "date"])


def study(frames: dict) -> dict:
    parts = []
    for t, df in frames.items():
        try:
            x = cases(df)
            x["ticker"] = t
            parts.append(x)
        except Exception:
            continue
    allc = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    return {"cases": allc}


def _line(g: pd.DataFrame) -> dict | None:
    if len(g) < 30:
        return None
    return {"n": len(g), "fresh_low": float(g["fresh_low"].mean()), "lower_1atr": float(g["lower_1atr"].mean()),
            "median_ret": float(g["ret"].median()), "up": float((g["ret"] > 0).mean())}


def table(allc: pd.DataFrame) -> pd.DataFrame:
    rows = []
    mid = allc["date"].sort_values().iloc[len(allc) // 2] if len(allc) else None
    for (n, k), g in allc.groupby(["n", "k"]):
        for label, sub in (("all", g), ("first half", g[g["date"] < mid]), ("second half", g[g["date"] >= mid])):
            base, flat, notflat = _line(sub), _line(sub[sub["flat"]]), _line(sub[~sub["flat"]])
            rows.append({"window": n, "flat_limit": k, "period": label, "base": base, "flat": flat, "not_flat": notflat})
    return pd.DataFrame(rows)


def report(res: dict) -> str:
    allc = res["cases"]
    if allc.empty:
        return "No data."
    def p(v):
        return "  n/a" if v is None else f"{v * 100:5.1f}%"
    def cell(d):
        return "too few cases" if d is None else f"{d['n']:>7,} cases | fresh low {p(d['fresh_low'])} | 1+ range lower {p(d['lower_1atr'])} | 10-day median {p(d['median_ret'])} | up {p(d['up'])}"
    t = table(allc)
    lines = ["AFTER A HARD FALL: does 'flat for N sessions' mean it is over?",
             "Sample: every stock-day down 10%+ over 20 sessions with RSI under 40 (the app's 'falling' momentum). Outcome: the next 10 sessions.",
             "'fresh low' = closes under the lowest close of the N flat sessions; '1+ range lower' = at least one daily range under it.", ""]
    for k in sorted(t["flat_limit"].unique()):
        lines.append(f"=== flat means: highest minus lowest close within {k} daily ranges ===")
        for n in sorted(t["window"].unique()):
            for period in ("all", "first half", "second half"):
                r = t[(t["window"] == n) & (t["flat_limit"] == k) & (t["period"] == period)].iloc[0]
                lines.append(f"window {n:>2} sessions, {period:<11}")
                lines.append(f"      every falling day : {cell(r['base'])}")
                lines.append(f"      flat              : {cell(r['flat'])}")
                lines.append(f"      not flat          : {cell(r['not_flat'])}")
            lines.append("")
    lines.append("Read: a window is useful if 'flat' makes a clearly lower low LESS often than 'not flat' in BOTH halves, with enough cases. "
                 "If flat days fall again about as often as the rest, flatness is only a pause.")
    return "\n".join(lines)
