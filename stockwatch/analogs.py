"""Older scenarios: how did this stock behave the last times it looked like it does today?

Finds past days with the same trend state, a similar RSI and the same position relative to
the 52-week high, then replays the current plan's stop and target distances forward from
each one: which was hit first, and how long it took.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import technical

HORIZON = {1: 126, 2: 30}   # trading days: ~6 months for core holdings, ~6 weeks for tactical


def _trend(ind: pd.DataFrame) -> pd.Series:
    up = (ind["Close"] > ind["SMA200"]) & (ind["SMA50"] > ind["SMA200"])
    down = (ind["Close"] < ind["SMA200"]) & (ind["SMA50"] < ind["SMA200"])
    return pd.Series(np.where(up, "up", np.where(down, "down", "mixed")), index=ind.index)


def replay(hist: pd.DataFrame, stop_pct: float, target_pct: float, tier: int) -> dict | None:
    """stop_pct / target_pct are distances from the entry (0.08 = 8%)."""
    if stop_pct <= 0 or target_pct <= 0 or len(hist) < 320:
        return None
    ind = technical.indicators(hist).dropna(subset=["SMA200", "RSI"])
    horizon = HORIZON.get(tier, 30)
    trend = _trend(ind)
    near_high = ind["Close"] >= ind["Close"].rolling(252, min_periods=60).max() * 0.97
    now = ind.iloc[-1]
    want_trend, want_rsi, want_high = trend.iloc[-1], float(now["RSI"]), bool(near_high.iloc[-1])

    def pick(rsi_band, use_high):
        mask = (trend == want_trend) & ((ind["RSI"] - want_rsi).abs() <= rsi_band)
        if use_high:
            mask &= near_high == want_high
        return [i for i, ok in enumerate(mask.iloc[:-horizon].to_numpy()) if ok]

    days, loose = pick(10, True), False
    if len(days) < 8:
        days, loose = pick(20, False), True

    close, high, low = ind["Close"].to_numpy(), ind["High"].to_numpy(), ind["Low"].to_numpy()
    results, last = [], -10**9
    for i in days:
        if i - last < 5:      # neighbouring days are the same episode; count it once
            continue
        last = i
        entry = close[i]
        tgt, stp = entry * (1 + target_pct), entry * (1 - stop_pct)
        outcome, when = "neither", horizon
        for k in range(1, horizon + 1):
            if low[i + k] <= stp:      # a day that touches both counts as a loss
                outcome, when = "stop", k
                break
            if high[i + k] >= tgt:
                outcome, when = "target", k
                break
        results.append({"date": ind.index[i].date().isoformat(), "outcome": outcome, "days": when,
                        "return": close[i + horizon] / entry - 1})
    if not results:
        return None
    n = len(results)
    wins = [r for r in results if r["outcome"] == "target"]
    losses = [r for r in results if r["outcome"] == "stop"]
    return {
        "n": n, "loose": loose, "horizon_days": horizon,
        "win_rate": len(wins) / n, "loss_rate": len(losses) / n, "neither_rate": 1 - (len(wins) + len(losses)) / n,
        "median_days_to_target": float(np.median([r["days"] for r in wins])) if wins else None,
        "median_days_to_stop": float(np.median([r["days"] for r in losses])) if losses else None,
        "median_return": float(np.median([r["return"] for r in results])),
        "recent": results[-5:],
        "match": f"{want_trend} trend, RSI {want_rsi:.0f}" + ("" if loose else (", near the 52-week high" if want_high else "")),
    }
