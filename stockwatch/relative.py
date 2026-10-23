"""Relative strength: is the stock leading or lagging the market and its own sector?"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import momentum
from .signals import OPPORTUNITY, RISK, Signal


def _rel_return(stock: pd.Series, bench: pd.Series, bars: int) -> float:
    both = pd.concat([stock, bench], axis=1, join="inner").dropna()
    if len(both) <= bars:
        return np.nan
    s, b = both.iloc[:, 0], both.iloc[:, 1]
    return (s.iloc[-1] / s.iloc[-bars - 1]) / (b.iloc[-1] / b.iloc[-bars - 1]) - 1


def _rs_line_rising(stock: pd.Series, bench: pd.Series) -> bool | None:
    both = pd.concat([stock, bench], axis=1, join="inner").dropna()
    if len(both) < 50:
        return None
    ratio = both.iloc[:, 0] / both.iloc[:, 1]
    return bool(ratio.iloc[-1] > ratio.rolling(50).mean().iloc[-1])


def analyze(stock: pd.DataFrame, market: pd.DataFrame | None, sector: pd.DataFrame | None,
            sector_etf: str | None, tier: int) -> tuple[float, dict, list[Signal]]:
    """Return (technical score adjustment, metrics, signals)."""
    out: list[Signal] = []
    m = {"rs_spy_1m": np.nan, "rs_spy_3m": np.nan, "rs_sector_3m": np.nan,
         "rs_line_rising": None, "sector_etf": sector_etf}
    adj = 0.0
    c = stock["Close"]
    if market is not None:
        m["rs_spy_1m"] = _rel_return(c, market["Close"], 21)
        m["rs_spy_3m"] = _rel_return(c, market["Close"], 63)
        m["rs_line_rising"] = _rs_line_rising(c, market["Close"])
        rs = m["rs_spy_3m"]
        if not np.isnan(rs):
            adj = float(np.clip(rs * 30, -8, 8))
            if rs >= 0.10 and m["rs_line_rising"]:
                out.append(Signal(OPPORTUNITY, "relative", "leading_market",
                                  f"Leading the market: {rs:+.0%} vs SPY over 3 months", 1))
            elif rs <= -0.15:
                out.append(Signal(RISK, "relative", "lagging_market",
                                  f"Lagging the market: {rs:+.0%} vs SPY over 3 months", 2 if tier == 1 else 1))
    if sector is not None and sector_etf:
        m["rs_sector_3m"] = rs_sec = _rel_return(c, sector["Close"], 63)
        if not np.isnan(rs_sec) and rs_sec <= -0.15:
            out.append(Signal(RISK, "relative", "lagging_sector",
                              f"Lagging its sector ({sector_etf}) by {-rs_sec:.0%} over 3 months - stock-specific weakness", 1))
    return adj, m, out


def market_regime(market: pd.DataFrame, now=None) -> dict:
    """Risk-on / risk-off / caution from the benchmark. The trend rule is slow (the 200-day), so a market that is
    clearly deteriorating can still read risk-on for weeks. A short-term check closes that gap: a trend-based
    RISK-ON becomes CAUTION, with the reason, when SPY is below its 50-day average or its momentum is weak or falling
    or sustained selling is showing (momentum.py). Display only; no score reads it."""
    c = market["Close"]
    sma200 = c.rolling(200).mean().iloc[-1]
    sma50 = c.rolling(50).mean().iloc[-1]
    price = float(c.iloc[-1])
    if price > sma200 and sma50 > sma200:
        state = "RISK-ON"
    elif price < sma200 and sma50 < sma200:
        state = "RISK-OFF"
    else:
        state = "CAUTION"
    trend_state, reasons = state, []
    if state == "RISK-ON":
        if price < sma50:
            reasons.append("below its 50-day average")
        try:
            mo = momentum.assess(market, None, None, now)
        except Exception:      # a failed momentum read never blocks the tile: it just adds no reason
            mo = None
        if mo and mo.get("known"):
            if mo["momentum"] in ("falling", "weak"):
                reasons.append(f"momentum {mo['momentum']} ({mo['facts']['ret20']:+.1%} in 20 sessions)")
            if mo["cause"] == "distribution" or "distribution" in mo.get("also", []):
                reasons.append("sustained selling")
        if reasons:
            state = "CAUTION"
    return {"state": state, "trend_state": trend_state, "reason": ", ".join(reasons) or None, "price": price,
            "vs_200d": price / sma200 - 1, "day_change": price / float(c.iloc[-2]) - 1}
