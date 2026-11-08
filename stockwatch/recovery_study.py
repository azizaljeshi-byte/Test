"""Study: while a beaten stock is recovering, is there a pattern that separates a real recovery from a bounce? STUDY ONLY.

Sample: every stock-day in the app's "falling" state (down 10%+ over 20 sessions, RSI(14) under 40). Trade from that close:
stop STOP_ATR daily swings under it, target TARGET_ATR over it, judged on daily highs and lows (stop first if both in one day),
within HORIZON sessions; neither = open at the end, counted as a miss. The base rate is the hit rate over all falling days.
Patterns are read from past bars only: higher lows, volume on up days, momentum turning, strength against the market, held a big gap day.
A pattern counts only if its hit rate beats all falling days clearly in BOTH halves of the history, with enough cases.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stab_study import FALL_20D, FALL_RSI, atr, rsi

STOP_ATR, TARGET_ATR, HORIZON = 1.5, 3.0, 20
PATTERNS = {
    "higher_lows": "higher lows (last 3 sessions' lowest low above the 3 before)",
    "vol_on_up": "more volume on up days than down days (last 5 sessions)",
    "momentum_turn": "RSI and MACD both rising over 3 sessions, price still under its 20-day average",
    "beats_market": "up 2%+ more than the S&P over 5 sessions",
    "held_gap": "held a big gap day (4%+ gap on 2x volume, last 8 sessions): earnings proxy, not confirmed",
}


def _outcome(h, l, c, a, i, horizon=HORIZON):
    """+1 target first, -1 stop first, 0 neither, within `horizon` sessions after i."""
    tgt, stp = c[i] + TARGET_ATR * a[i], c[i] - STOP_ATR * a[i]
    for k in range(i + 1, min(i + 1 + horizon, len(c))):
        if l[k] <= stp:
            return -1
        if h[k] >= tgt:
            return 1
    return 0


def features(df: pd.DataFrame, mkt: pd.Series | None) -> pd.DataFrame:
    c, h, l, o = (df[k].astype(float) for k in ("Close", "High", "Low", "Open"))
    v = df["Volume"].astype(float) if "Volume" in df else pd.Series(0.0, index=df.index)
    f = pd.DataFrame(index=df.index)
    f["higher_lows"] = l.rolling(3).min() > l.shift(3).rolling(3).min()
    up = (c > c.shift(1)).astype(float)
    f["vol_on_up"] = (v * up).rolling(5).sum() > (v * (1 - up)).rolling(5).sum()
    ef = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    hist = ef - ef.ewm(span=9, adjust=False).mean()
    r = rsi(c)
    f["momentum_turn"] = (r > r.shift(3)) & (hist > hist.shift(3)) & (c < c.rolling(20).mean())
    if mkt is not None:
        m5 = mkt.reindex(df.index).ffill().pct_change(5)
        f["beats_market"] = (c.pct_change(5) - m5) >= 0.02
    else:
        f["beats_market"] = False
    gap = ((o / c.shift(1) - 1).abs() >= 0.04) & (v >= 2 * v.rolling(20).mean().shift(1))
    cv, gv = c.to_numpy(), gap.to_numpy()
    hv = np.zeros(len(c), bool)
    for i in range(len(c)):
        for k in range(max(0, i - 7), i):
            if gv[k] and cv[i] >= cv[k]:
                hv[i] = True
                break
    f["held_gap"] = pd.Series(hv, index=df.index)
    f["n_patterns"] = f[list(PATTERNS)].sum(axis=1)
    return f.fillna(False)


def cases(df: pd.DataFrame, mkt: pd.Series | None = None) -> pd.DataFrame:
    c = df["Close"].astype(float)
    a = atr(df)
    falling = ((c / c.shift(20) - 1) <= FALL_20D) & (rsi(c) < FALL_RSI)
    f = features(df, mkt)
    cv, hv, lv, av = c.to_numpy(), df["High"].astype(float).to_numpy(), df["Low"].astype(float).to_numpy(), a.to_numpy()
    rows = []
    for i in np.flatnonzero(falling.to_numpy()):
        if i + HORIZON >= len(c) or not np.isfinite(av[i]) or av[i] <= 0:
            continue
        o = _outcome(hv, lv, cv, av, i)
        row = {"date": c.index[i], "hit": o == 1, "stopped": o == -1}
        row.update({k: bool(f[k].iloc[i]) for k in PATTERNS})
        row["n_patterns"] = int(f["n_patterns"].iloc[i])
        rows.append(row)
    return pd.DataFrame(rows)


def study(frames: dict, mkt: pd.Series | None = None, progress=None) -> dict:
    parts = []
    for i, (t, df) in enumerate(frames.items()):
        try:
            x = cases(df, mkt)
            if len(x):
                x["ticker"] = t
                parts.append(x)
        except Exception:
            pass
        if progress and (i + 1) % 50 == 0:
            progress(i + 1, len(frames))
    return {"cases": pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()}


def _line(g: pd.DataFrame):
    if len(g) < 30:
        return None
    return {"n": len(g), "hit": float(g["hit"].mean()), "stopped": float(g["stopped"].mean())}


def report(res: dict) -> str:
    allc = res["cases"]
    if allc.empty:
        return "No data."
    def p(v):
        return "  n/a" if v is None else f"{v * 100:5.1f}%"
    def cell(d):
        return "too few cases" if d is None else f"{d['n']:>7,} cases | reached target first {p(d['hit'])} | stopped first {p(d['stopped'])}"
    mid = allc["date"].sort_values().iloc[len(allc) // 2]
    halves = (("all", allc), ("first half", allc[allc["date"] < mid]), ("second half", allc[allc["date"] >= mid]))
    lines = ["WHILE A BEATEN STOCK RECOVERS: is there a pattern that separates a real recovery from a bounce?",
             "Sample: every stock-day down 10%+ over 20 sessions with RSI under 40. Trade from that close: "
             f"stop {STOP_ATR:g} daily swings under, target {TARGET_ATR:g} over, within {HORIZON} sessions (daily highs/lows; stop first if both in one day).",
             "Compare each pattern with 'every falling day' (the base rate): the hit rate must rise clearly above it.", ""]
    tests = [("every falling day", None)] + [(v, k) for k, v in PATTERNS.items()] + \
            [("two or more patterns at once", "n2"), ("three or more patterns at once", "n3"), ("no pattern at all", "n0")]
    for label, col in tests:
        lines.append(f"=== {label} ===")
        for period, sub in halves:
            if col is None:
                s, r = sub, None
            elif col == "n2":
                s, r = sub[sub["n_patterns"] >= 2], sub[sub["n_patterns"] < 2]
            elif col == "n3":
                s, r = sub[sub["n_patterns"] >= 3], sub[sub["n_patterns"] < 3]
            elif col == "n0":
                s, r = sub[sub["n_patterns"] == 0], sub[sub["n_patterns"] > 0]
            else:
                s, r = sub[sub[col]], sub[~sub[col]]
            lines.append(f"{period:<11} with it   : {cell(_line(s))}")
            if r is not None:
                lines.append(f"{'':<11} without   : {cell(_line(r))}")
        lines.append("")
    lines.append("Read: a pattern is useful only if 'with it' reaches the target first clearly MORE often than 'every falling day' in BOTH halves, "
                 "with enough cases. Otherwise it is just a description of a bounce.")
    return "\n".join(lines)
