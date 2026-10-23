"""Completed daily bars: data quality and the framework's indicator measurements.

Everything here is read-only and works on completed sessions only. A live or partial quote is never mixed
into these numbers; `state` evaluates quotes separately against fixed levels.

Indicator conventions (INDICATORS, versioned) reproduce the 23 October 2026 reference fixtures exactly:
- SMA20/50/200: arithmetic rolling means of the close.
- RSI14: Wilder smoothing, an exponential mean with alpha 1/14 and adjust=False, seeded with the first
  close-to-close change. Zero loss with a gain gives 100, zero gain with a loss gives 0, a flat history
  gives 50. Fewer than 14 changes is unavailable.
- ATR14: true range max(high-low, |high-prev close|, |low-prev close|) (the first bar uses high-low), then
  the same alpha 1/14 exponential mean. Fewer than 14 true ranges is unavailable. No SMA seeding.
- MACD: EMA12 - EMA26 (adjust=False), signal EMA9, histogram = line - signal.
- Relative volume: the day's volume / the mean of the PREVIOUS 20 completed sessions (the signal day is
  excluded; the main StockWatch scanner includes it, so the two differ on purpose).
- Relative return over N sessions: (stock_end/stock_start) / (bench_end/bench_start) - 1 on common dates,
  start = N sessions before the end.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

NY = ZoneInfo("America/New_York")
INDICATORS = {"version": "cis-indicators-v1", "sma": (20, 50, 200), "rsi": 14, "atr": 14, "macd": (12, 26, 9),
              "rel_volume_lookback": 20, "relative_return": (21, 63), "weekly_sma": (10, 40),
              "smoothing": "exponential alpha=1/n, adjust=False, seeded with the first value"}
OHLC = ["Open", "High", "Low", "Close"]


@dataclass
class Quality:
    """What was checked on a daily series, and why it can't be used if it can't."""
    symbol: str
    rows: int = 0
    first: str | None = None
    last: str | None = None
    sha256: str | None = None
    problems: list[str] = field(default_factory=list)       # any problem refuses the series
    limitations: list[str] = field(default_factory=list)    # usable, but say so on screen

    @property
    def usable(self) -> bool:
        return not self.problems


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date")


def check(df: pd.DataFrame, symbol: str, sha256: str | None = None) -> Quality:
    """Refuse malformed daily bars instead of repairing them. Nothing is filled or invented."""
    q = Quality(symbol, rows=len(df), sha256=sha256)
    if df.empty:
        q.problems.append("no rows")
        return q
    q.first, q.last = str(df.index[0].date()), str(df.index[-1].date())
    missing = [c for c in OHLC + ["Volume"] if c not in df.columns]
    if missing:
        q.problems.append(f"missing columns: {', '.join(missing)}")
        return q
    px = df[OHLC].to_numpy(dtype=float)
    if not np.isfinite(px).all() or (px <= 0).any():
        q.problems.append("non-finite or non-positive prices")
    o, h, l, c = (df[k].astype(float) for k in OHLC)
    if ((h < l) | (h < np.maximum(o, c)) | (l > np.minimum(o, c))).any():
        q.problems.append("high/low don't contain open and close")
    vol = df["Volume"].astype(float)
    if not np.isfinite(vol).all() or (vol < 0).any():
        q.problems.append("missing or negative volume")
    if df.index.has_duplicates:
        q.problems.append("duplicate dates")
    if not df.index.is_monotonic_increasing:
        q.problems.append("dates not in ascending order")
    if len(df) > 1:
        gaps = pd.Series(df.index).diff().dt.days.dropna()
        if gaps.median() > 4:            # a requested daily interval can come back weekly or monthly
            q.problems.append(f"not daily bars (median gap {gaps.median():.0f} days)")
    zero = int((vol == 0).sum())
    if zero:
        q.limitations.append(f"{zero} zero-volume sessions; relative volume is unavailable where they matter")
    return q


def completed(df: pd.DataFrame, through: str | date) -> pd.DataFrame:
    """Only sessions on or before the last completed session. A forming bar never enters indicators.
    Compares calendar dates, so timezone-aware (Yahoo) and naive (fixture) indexes both work."""
    return df[df.index.date <= pd.Timestamp(through).date()]


def default_boundary(index: pd.DatetimeIndex, now: datetime) -> date | None:
    """Conservative completed-session boundary without an exchange calendar: the latest bar dated before
    today's New York date (the reference fixtures exclude the current date's row the same way)."""
    today = now.astimezone(NY).date()
    done = [d.date() for d in index if d.date() < today]
    return done[-1] if done else None


def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    gain, loss = _wilder(d.clip(lower=0), n), _wilder(-d.clip(upper=0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100 - 100 / (1 + gain / loss)
    out = out.where(~((loss == 0) & (gain > 0)), 100.0)
    out = out.where(~((gain == 0) & (loss > 0)), 0.0)
    out = out.where(~((gain == 0) & (loss == 0)), 50.0)
    out.iloc[:n] = np.nan                 # fewer than n changes: unavailable
    return out


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["Close"].shift()
    return pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    out = _wilder(true_range(df), n)
    out.iloc[:n - 1] = np.nan
    return out


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Per-session indicators on completed bars. Each row uses only that row and earlier rows."""
    c, v = df["Close"].astype(float), df["Volume"].astype(float)
    f = pd.DataFrame(index=df.index)
    f["close"], f["high"], f["low"] = c, df["High"].astype(float), df["Low"].astype(float)
    for n in INDICATORS["sma"]:
        f[f"ma{n}"] = c.rolling(n).mean()
    f["rsi"] = rsi(c, INDICATORS["rsi"])
    f["atr"] = atr(df, INDICATORS["atr"])
    f["atr_pct"] = f["atr"] / c
    fast, slow, sig = INDICATORS["macd"]
    f["macd"] = c.ewm(span=fast, adjust=False).mean() - c.ewm(span=slow, adjust=False).mean()
    f["signal"] = f["macd"].ewm(span=sig, adjust=False).mean()
    f["histogram"] = f["macd"] - f["signal"]
    base = v.shift().rolling(INDICATORS["rel_volume_lookback"]).mean()
    f["volavg20"] = base
    f["rv"] = (v / base).where(base > 0)
    f["volume"] = v
    f["drawdown"] = c / c.rolling(252).max() - 1              # from the trailing 252-session CLOSING high
    f["dist50"], f["dist200"] = c / f["ma50"] - 1, c / f["ma200"] - 1
    f["ret5"] = c / c.shift(5) - 1
    f["rebound"] = c / f["low"].rolling(20).min() - 1         # above the trailing 20-session intraday low
    return f


def _num(v) -> float | None:
    ok = isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool)
    return float(v) if ok and math.isfinite(v) else None


def metrics(df: pd.DataFrame) -> dict:
    """The last completed session's measurements. Unavailable values are None, never 0."""
    f = indicators(df)
    last, prev = f.iloc[-1], f.iloc[-2] if len(f) > 1 else None
    out = {k: _num(df[k].iloc[-1]) for k in OHLC + ["Volume"]}
    out["session"] = str(df.index[-1].date())
    for k in ("ma20", "ma50", "ma200", "rsi", "atr", "atr_pct", "rv", "volavg20", "macd", "signal", "histogram",
              "drawdown", "dist50", "dist200", "ret5", "rebound"):
        out[k] = _num(last[k])
    out["daily_change"] = _num(last["close"] / prev["close"] - 1) if prev is not None else None
    out["histogram_change"] = _num(last["histogram"] - prev["histogram"]) if prev is not None else None
    year = df.iloc[-252:]
    out["close_high_252"] = _num(year["Close"].max())          # close-only: not an intraday high
    out["intraday_high_252"], out["intraday_low_252"] = _num(year["High"].max()), _num(year["Low"].min())
    wk = weekly(df)
    done = wk[~wk["incomplete"]]
    out["weekly_change"] = _num(done["Close"].iloc[-1] / done["Close"].iloc[-2] - 1) if len(done) > 1 else None
    return out


def relative_return(stock: pd.DataFrame, bench: pd.DataFrame | None, n: int) -> float | None:
    """Stock return relative to a benchmark over the last n common sessions; None when not enough data."""
    if bench is None or bench.empty:
        return None
    common = stock.index.intersection(bench.index)
    if len(common) <= n:
        return None
    s, b = stock["Close"].reindex(common), bench["Close"].reindex(common)
    return _num((s.iloc[-1] / s.iloc[-1 - n]) / (b.iloc[-1] / b.iloc[-1 - n]) - 1)


def weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Weekly bars labelled by week-ending Friday, with the last actual session kept alongside.

    The last week is flagged incomplete when its last session is before Friday. Without an exchange calendar
    a holiday-shortened week (e.g. Thursday 2 July 2026) also reads as incomplete; that's the safe side."""
    g = df.groupby(pd.Grouper(freq="W-FRI"))
    wk = pd.DataFrame({"Open": g["Open"].first(), "High": g["High"].max(), "Low": g["Low"].min(),
                       "Close": g["Close"].last(), "Volume": g["Volume"].sum(),
                       "last_session": g.apply(lambda x: x.index[-1] if len(x) else pd.NaT, include_groups=False)})
    wk = wk.dropna(subset=["Close"])
    wk["incomplete"] = False
    if len(wk):
        wk.iloc[-1, wk.columns.get_loc("incomplete")] = wk["last_session"].iloc[-1].weekday() < 4
    done = wk[~wk["incomplete"]]
    for n in INDICATORS["weekly_sma"]:
        wk[f"ma{n}w"] = done["Close"].rolling(n).mean()
    return wk
