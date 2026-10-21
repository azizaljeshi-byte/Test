"""Technical indicators and signals."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .signals import OPPORTUNITY, RISK, Signal


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def macd(close: pd.Series, fast=12, slow=26, signal=9) -> tuple[pd.Series, pd.Series]:
    line = ema(close, fast) - ema(close, slow)
    return line, ema(line, signal)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(),
                    (df["Low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def crossed_above(a: pd.Series, b: pd.Series, within: int) -> bool:
    """True if `a` crossed above `b` in the last `within` bars and is still above it."""
    diff = (a - b).dropna().iloc[-(within + 1):]
    return len(diff) > 1 and diff.iloc[-1] > 0 and bool(((diff.shift() <= 0) & (diff > 0)).any())


def crossed_below(a: pd.Series, b: pd.Series, within: int) -> bool:
    """True if `a` crossed below `b` in the last `within` bars and is still below it."""
    return crossed_above(b, a, within)


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = out["Close"]
    out["SMA20"], out["SMA50"], out["SMA200"] = sma(c, 20), sma(c, 50), sma(c, 200)
    out["RSI"] = rsi(c)
    out["MACD"], out["MACD_signal"] = macd(c)
    std = c.rolling(20).std()
    out["BB_upper"], out["BB_lower"] = out["SMA20"] + 2 * std, out["SMA20"] - 2 * std
    out["ATR"] = atr(out)
    out["VolAvg20"] = out["Volume"].rolling(20).mean()
    return out


def analyze(df: pd.DataFrame, trailing_atr_mult: float = 3.0, owned: bool = True) -> tuple[float, dict, list[Signal]]:
    """Return (score 0-100, key metrics, signals) for a price history."""
    ind = indicators(df)
    last = ind.iloc[-1]
    c = ind["Close"]
    price = float(last["Close"])
    signals: list[Signal] = []
    score = 50.0

    hi52 = float(c.iloc[-252:].max())
    lo52 = float(c.iloc[-252:].min())
    ret_1m = price / float(c.iloc[-22]) - 1 if len(c) > 22 else np.nan
    ret_3m = price / float(c.iloc[-64]) - 1 if len(c) > 64 else np.nan
    vol_ratio = float(last["Volume"] / last["VolAvg20"]) if last["VolAvg20"] else np.nan
    day_move = price / float(c.iloc[-2]) - 1

    above50 = price > last["SMA50"]
    above200 = price > last["SMA200"]
    uptrend = bool(above200 and last["SMA50"] > last["SMA200"])
    downtrend = bool(not above200 and last["SMA50"] < last["SMA200"])

    # --- trend (the backbone of the score)
    score += 12 if above200 else -12
    score += 8 if above50 else -8
    score += 6 if last["SMA50"] > last["SMA200"] else -6

    if crossed_above(ind["SMA50"], ind["SMA200"], 5):
        signals.append(Signal(OPPORTUNITY, "technical", "golden_cross",
                              "Golden cross: 50-day SMA crossed above 200-day", 2))
    if crossed_below(ind["SMA50"], ind["SMA200"], 5):
        signals.append(Signal(RISK, "technical", "death_cross",
                              "Death cross: 50-day SMA crossed below 200-day", 2))
    if crossed_below(c, ind["SMA200"], 3):
        signals.append(Signal(RISK, "technical", "lost_200d",
                              f"Closed below the 200-day SMA ({last['SMA200']:.2f})", 2))
    if crossed_above(c, ind["SMA200"], 3):
        signals.append(Signal(OPPORTUNITY, "technical", "reclaimed_200d",
                              f"Reclaimed the 200-day SMA ({last['SMA200']:.2f})", 2))

    # --- momentum
    r = float(last["RSI"])
    if r < 30:
        score += 4  # oversold: potential entry, but only an opportunity if the trend agrees
        signals.append(Signal(OPPORTUNITY if not downtrend else RISK, "technical", "rsi_oversold",
                              f"RSI {r:.0f} oversold" + (" inside a downtrend" if downtrend else ""),
                              2 if uptrend else 1))
    elif r > 75:
        score -= 4
        signals.append(Signal(RISK, "technical", "rsi_overbought",
                              f"RSI {r:.0f} overbought - extended, consider trimming", 1))
    elif 50 <= r <= 70:
        score += 4

    if crossed_above(ind["MACD"], ind["MACD_signal"], 3):
        score += 4
        signals.append(Signal(OPPORTUNITY, "technical", "macd_bull", "MACD bullish crossover", 1))
    elif crossed_below(ind["MACD"], ind["MACD_signal"], 3):
        score -= 4
        signals.append(Signal(RISK, "technical", "macd_bear", "MACD bearish crossover", 1))
    score += 4 if last["MACD"] > last["MACD_signal"] else -4

    if not np.isnan(ret_3m):
        score += float(np.clip(ret_3m * 40, -10, 10))

    # --- price location
    if price <= last["BB_lower"] and uptrend:
        signals.append(Signal(OPPORTUNITY, "technical", "bb_pullback",
                              "Pulled back to the lower Bollinger band within an uptrend", 2))
    if price >= hi52 * 0.999:
        signals.append(Signal(OPPORTUNITY, "technical", "new_52w_high", "Breaking out to a 52-week high", 1))
    drawdown = price / hi52 - 1
    if drawdown < -0.30:
        score -= 6
        signals.append(Signal(RISK, "technical", "deep_drawdown",
                              f"{-drawdown:.0%} below its 52-week high", 2))

    # --- volume
    if vol_ratio >= 2 and abs(day_move) > 0.03:
        kind = OPPORTUNITY if day_move > 0 else RISK
        signals.append(Signal(kind, "technical", "volume_" + ("surge_up" if day_move > 0 else "surge_down"),
                              f"{vol_ratio:.1f}x average volume on a {day_move:+.1%} day", 2))

    # --- trailing ATR stop
    recent_high = float(c.iloc[-22:].max())
    trail = recent_high - trailing_atr_mult * float(last["ATR"])
    if owned and price < trail:
        signals.append(Signal(RISK, "technical", "atr_trailing_stop",
                              f"Below ATR trailing stop {trail:.2f} ({trailing_atr_mult}x ATR off the 1-month high)", 3))

    metrics = {
        "price": price, "rsi": r, "sma50": float(last["SMA50"]), "sma200": float(last["SMA200"]),
        "atr": float(last["ATR"]), "high_52w": hi52, "low_52w": lo52, "drawdown_52w": drawdown,
        "ret_1m": ret_1m, "ret_3m": ret_3m, "volume_ratio": vol_ratio, "day_change": day_move,
        "trend": "up" if uptrend else "down" if downtrend else "mixed", "trailing_stop": trail,
    }
    return float(np.clip(score, 0, 100)), metrics, signals
