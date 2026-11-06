"""Study: after a hard fall, does a close back ABOVE a ceiling mean the fall is over? STUDY ONLY, never touches the app.

Sample: every stock-day in the app's "falling" state (down 10%+ over 20 sessions, RSI(14) under 40). Call that day D.
Event: the next close (D+1) is above (a) the highest close of the last 5 / 10 / 20 sessions (a plain ceiling), or
(b) the app's own exit line as it stood on D (status.assess, the same code the dashboard runs), for days that closed under it.
Control: the other falling days (no reclaim), measured over the same horizon from D+1.
Outcome, from the D+1 close over the next 10 sessions: a fresh closing low (under the lowest close of the 10 sessions up to D+1),
a clearly lower one (1+ daily range under it), and the return. Two halves of history so one period cannot carry the result.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import status
from .stab_study import FALL_20D, FALL_RSI, HORIZON, atr, rsi

CEILINGS = (5, 10, 20)
LOOKBACK = 10


def _now(ts) -> object:
    return (pd.Timestamp(ts.date(), tz="UTC") + pd.Timedelta(hours=22)).to_pydatetime()


def exit_line(df: pd.DataFrame, j: int):
    """The app's exit line using only bars up to position j; None if it cannot be built."""
    try:
        r = status.assess(df.iloc[: j + 1], now=_now(df.index[j]), owned=False)
        v = (r.get("levels") or {}).get("exit_below")
        return float(v) if v is not None else None
    except Exception:
        return None


def cases(df: pd.DataFrame, horizon: int = HORIZON, with_line: bool = True) -> pd.DataFrame:
    c = df["Close"].astype(float)
    a = atr(df)
    falling = ((c / c.shift(20) - 1) <= FALL_20D) & (rsi(c) < FALL_RSI)
    n = len(c)
    cv = c.to_numpy()
    out = []
    ceil = {k: c.rolling(k).max().to_numpy() for k in CEILINGS}
    low10 = c.rolling(LOOKBACK).min().to_numpy()
    av = a.to_numpy()
    for j in np.flatnonzero(falling.to_numpy()):
        if j + 1 + horizon >= n or not np.isfinite(av[j]) or av[j] <= 0:
            continue
        k0 = j + 1
        lo = min(low10[k0], cv[k0])
        fwd = cv[k0 + 1: k0 + 1 + horizon]
        row = {"date": c.index[k0], "fresh_low": bool(fwd.min() < lo), "lower_1atr": bool(fwd.min() <= lo - av[k0]),
               "ret": float(cv[k0 + horizon] / cv[k0] - 1)}
        for k in CEILINGS:
            row[f"c{k}"] = bool(cv[k0] > ceil[k][j])
        L = exit_line(df, j) if with_line else None
        row["has_line"] = L is not None
        row["under_line"] = bool(L is not None and cv[j] < L)
        row["line_back"] = bool(L is not None and cv[k0] > L)
        out.append(row)
    return pd.DataFrame(out)


def study(frames: dict, progress=None, with_line: bool = True) -> dict:
    parts = []
    for i, (t, df) in enumerate(frames.items()):
        try:
            x = cases(df, with_line=with_line)
            if len(x):
                x["ticker"] = t
                parts.append(x)
        except Exception:
            pass
        if progress and (i + 1) % 25 == 0:
            progress(i + 1, len(frames))
    return {"cases": pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()}


def _line(g: pd.DataFrame):
    if len(g) < 30:
        return None
    return {"n": len(g), "fresh_low": float(g["fresh_low"].mean()), "lower_1atr": float(g["lower_1atr"].mean()),
            "median_ret": float(g["ret"].median()), "up": float((g["ret"] > 0).mean())}


def tests(allc: pd.DataFrame) -> list:
    """(label, universe, event mask name) triples: the event group is compared with the rest of the same universe."""
    t = [(f"closes above the highest close of the last {k} sessions", allc, f"c{k}") for k in CEILINGS]
    u = allc[allc["under_line"]]
    t.append(("closes back above the exit line (was under it)", u, "line_back"))
    return t


def report(res: dict) -> str:
    allc = res["cases"]
    if allc.empty:
        return "No data."
    def p(v):
        return "  n/a" if v is None else f"{v * 100:5.1f}%"
    def cell(d):
        return "too few cases" if d is None else f"{d['n']:>7,} cases | fresh low {p(d['fresh_low'])} | 1+ range lower {p(d['lower_1atr'])} | 10-day median {p(d['median_ret'])} | up {p(d['up'])}"
    mid = allc["date"].sort_values().iloc[len(allc) // 2]
    lines = ["AFTER A HARD FALL: does a close back above a ceiling mean it is over?",
             "Sample: every stock-day down 10%+ over 20 sessions with RSI under 40 (the app's 'falling' momentum). Day D = that day. Next close = D+1.",
             "Outcome: next 10 sessions after D+1. 'fresh low' = closes under the lowest close of the 10 sessions to D+1; '1+ range lower' = a daily range under it.",
             "'Closes above' means the D+1 close is above the ceiling as it stood on D. The exit line is the app's own (status.assess), tested on days that closed under it.", ""]
    for label, uni, col in tests(allc):
        lines.append(f"=== {label} ===")
        for period, sub in (("all", uni), ("first half", uni[uni["date"] < mid]), ("second half", uni[uni["date"] >= mid])):
            lines.append(f"{period}")
            lines.append(f"      all of these days : {cell(_line(sub))}")
            lines.append(f"      reclaimed         : {cell(_line(sub[sub[col]]))}")
            lines.append(f"      did not reclaim   : {cell(_line(sub[~sub[col]]))}")
        lines.append("")
    lines.append("Read: a ceiling is a real signal if 'reclaimed' makes a clearly lower low LESS often than 'did not reclaim' in BOTH halves, with enough cases. "
                 "If both fall again about as often, a close above it is only a bounce.")
    return "\n".join(lines)
