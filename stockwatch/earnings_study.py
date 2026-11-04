"""Study: is the app's BUY zone a better buy in the first days AFTER earnings than at other times? STUDY ONLY, never touches the app.

A stock-day is "in the buy zone" by the app's own one-call rule (onecall.py): the close is at or above the exit line and within
ENTRY_ATRS normal daily swings of it, the day was an up day with RSI rising, and no earnings in the next 2 days. The exit line is the app's own
(status.assess) as it stood that day. Trade from that close: stop half a swing under the exit line (where the app says EXIT), target
R_MULT times the risk above the entry, judged on daily highs and lows (stop first if both in one day), within HORIZON sessions.
Every STEP-th session is looked at (speed). Groups (earnings dates are Yahoo's): AFTER = 1 to AFTER_MAX sessions after an earnings date; FELL = AFTER, and the stock had fallen over the
10 sessions into the report (the sold-off-then-recovers story); OTHER = no earnings within 3 sessions before or 10 sessions after.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import technical
from .onecall import BAND_ATRS, ENTRY_ATRS
from .reclaim_study import exit_line

R_MULT, HORIZON, AFTER_MAX, FAR_BEFORE, FAR_AFTER, MIN_BARS = 2.0, 20, 5, 3, 10, 210
STEP = 3          # look at every 3rd session: the exit line is the slow part, and neighbouring days overlap anyway


def _positions(dates: np.ndarray, earnings: list) -> list:
    out = []
    for e in earnings:
        p = int(np.searchsorted(dates, np.datetime64(pd.Timestamp(e).date()), side="left"))
        if 0 < p < len(dates):
            out.append(p)
    return sorted(set(out))


def cases(df: pd.DataFrame, earnings: list, horizon: int = HORIZON, with_line: bool = True, line_fn=exit_line, step: int = STEP) -> pd.DataFrame:
    ind = technical.indicators(df)
    c, hi, lo = (df[k].astype(float).to_numpy() for k in ("Close", "High", "Low"))
    atr, rsi = ind["ATR"].to_numpy(), ind["RSI"].to_numpy()
    dates = np.array([d.date() for d in df.index], dtype="datetime64[D]")
    pe = _positions(dates, earnings)
    rows = []
    for i in range(MIN_BARS, len(c) - horizon - 1, step):
        if not (c[i] > c[i - 1] and rsi[i] > rsi[i - 1]) or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        if any(0 < p - i <= 2 for p in pe):            # the app never calls BUY with earnings in the next 2 days
            continue
        line = line_fn(df, i) if with_line else None
        if line is None or c[i] < line or (c[i] - line) / atr[i] > ENTRY_ATRS:
            continue
        stop = line - BAND_ATRS * atr[i]
        risk = c[i] - stop
        target = c[i] + R_MULT * risk
        out = 0
        for k in range(i + 1, i + 1 + horizon):
            if lo[k] <= stop:
                out = -1
                break
            if hi[k] >= target:
                out = 1
                break
        after = [p for p in pe if 1 <= i - p <= AFTER_MAX]
        near = any(-FAR_BEFORE <= i - p <= FAR_AFTER for p in pe)
        fell = bool(after) and after[-1] >= 11 and c[after[-1] - 1] < c[after[-1] - 11]
        rows.append({"date": df.index[i], "hit": out == 1, "stopped": out == -1, "ret": float(c[i + horizon] / c[i] - 1),
                     "after": bool(after), "fell": fell, "other": (not near) and bool(pe)})
    return pd.DataFrame(rows)


def study(frames: dict, earnings: dict, progress=None) -> dict:
    parts = []
    for n, (t, df) in enumerate(frames.items()):
        e = earnings.get(t)
        if e:
            try:
                x = cases(df, e)
                if len(x):
                    x["ticker"] = t
                    parts.append(x)
            except Exception:
                pass
        if progress and (n + 1) % 25 == 0:
            progress(n + 1, len(frames))
    return {"cases": pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(),
            "stocks_with_dates": sum(1 for v in earnings.values() if v), "stocks": len(frames),
            "oldest": min((min(v) for v in earnings.values() if v), default=None)}


def _line(g: pd.DataFrame):
    if len(g) < 30:
        return None
    return {"n": len(g), "hit": float(g["hit"].mean()), "stopped": float(g["stopped"].mean()), "median_ret": float(g["ret"].median())}


def report(res: dict) -> str:
    allc = res["cases"]
    if allc.empty:
        return "No data."
    def p(v):
        return "  n/a" if v is None else f"{v * 100:5.1f}%"
    def cell(d):
        return "too few cases" if d is None else f"{d['n']:>6,} cases | target first {p(d['hit'])} | stopped first {p(d['stopped'])} | 20-day median {p(d['median_ret'])}"
    mid = allc["date"].sort_values().iloc[len(allc) // 2]
    halves = (("all", allc), ("first half", allc[allc["date"] < mid]), ("second half", allc[allc["date"] >= mid]))
    lines = ["IS THE BUY ZONE BETTER JUST AFTER EARNINGS?",
             "Buy zone = the app's one-call rule: close at or above the exit line and within 1.5 normal swings of it, an up day with RSI rising, no earnings in the next 2 days.",
             f"Trade from that close: stop half a swing under the exit line, target {R_MULT:g}x the risk above, within {HORIZON} sessions (daily highs/lows; stop first if both in one day).",
             f"Earnings dates (Yahoo) found for {res['stocks_with_dates']} of {res['stocks']} stocks, oldest {res['oldest']}.",
             "AFTER = 1 to 5 sessions after an earnings date. FELL = AFTER and the stock had fallen over the 10 sessions into the report. OTHER = no earnings within 3 sessions before or 10 after.", ""]
    for label, col in (("every buy-zone day (all)", None), ("AFTER earnings", "after"), ("AFTER earnings and fell into it", "fell"), ("OTHER times", "other")):
        lines.append(f"=== {label} ===")
        for period, sub in halves:
            s = sub if col is None else sub[sub[col]]
            lines.append(f"{period:<11} {cell(_line(s))}")
        lines.append("")
    lines.append("Read: AFTER (or FELL) only matters if 'target first' is clearly HIGHER than OTHER in BOTH halves with enough cases. Otherwise a buy zone is just a buy zone.")
    return "\n".join(lines)
