"""Market data providers.

Every provider returns:
  * history(ticker)      -> DataFrame indexed by date with Open/High/Low/Close/Volume
  * fundamentals(ticker) -> dict with the normalized keys listed in FUNDAMENTAL_KEYS
                            (missing values are None)
"""
from __future__ import annotations

import logging
import zlib
from typing import Protocol

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

FUNDAMENTAL_KEYS = [
    "name", "sector", "market_cap",
    "pe_trailing", "pe_forward", "peg",
    "revenue_growth", "earnings_growth",          # fractions, 0.12 = 12%
    "gross_margin", "operating_margin", "profit_margin", "roe",
    "debt_to_equity",                             # ratio, 1.5 = 150%
    "current_ratio", "free_cash_flow",
    "target_mean_price", "recommendation_mean",   # 1 = strong buy ... 5 = sell
]


class DataProvider(Protocol):
    def history(self, ticker: str, period: str = "2y") -> pd.DataFrame: ...
    def fundamentals(self, ticker: str) -> dict: ...


class YahooProvider:
    """Free data via yfinance. Fine for personal use; not an official feed."""

    _MAP = {
        "name": "shortName", "sector": "sector", "market_cap": "marketCap",
        "pe_trailing": "trailingPE", "pe_forward": "forwardPE",
        "peg": "trailingPegRatio", "revenue_growth": "revenueGrowth",
        "earnings_growth": "earningsGrowth", "gross_margin": "grossMargins",
        "operating_margin": "operatingMargins", "profit_margin": "profitMargins",
        "roe": "returnOnEquity", "debt_to_equity": "debtToEquity",
        "current_ratio": "currentRatio", "free_cash_flow": "freeCashflow",
        "target_mean_price": "targetMeanPrice",
        "recommendation_mean": "recommendationMean",
    }

    def __init__(self):
        import yfinance  # imported lazily so the demo provider works without it
        self._yf = yfinance

    def history(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        df = self._yf.Ticker(ticker).history(period=period, auto_adjust=True)
        if df.empty:
            raise ValueError(f"No price history for {ticker}")
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df[["Open", "High", "Low", "Close", "Volume"]]

    def fundamentals(self, ticker: str) -> dict:
        info = self._yf.Ticker(ticker).info or {}
        out = {k: info.get(src) for k, src in self._MAP.items()}
        if out["peg"] is None:
            out["peg"] = info.get("pegRatio")
        if out["debt_to_equity"] is not None:
            out["debt_to_equity"] = out["debt_to_equity"] / 100.0  # Yahoo reports percent
        return out


class DemoProvider:
    """Deterministic synthetic data so the app can run offline / in tests."""

    def _rng(self, ticker: str) -> np.random.Generator:
        return np.random.default_rng(zlib.crc32(ticker.encode()))

    def history(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        rng = self._rng(ticker)
        n = 504
        drift = rng.uniform(-0.0006, 0.0012)
        vol = rng.uniform(0.012, 0.03)
        rets = rng.normal(drift, vol, n)
        # inject a regime change in the last ~60 bars so signals vary by ticker
        rets[-60:] += rng.choice([-0.004, -0.002, 0.0, 0.002, 0.004])
        close = rng.uniform(40, 400) * np.exp(np.cumsum(rets))
        spread = np.abs(rng.normal(0, vol, n)) * close
        high = close + spread
        low = close - spread
        open_ = np.r_[close[0], close[:-1]]
        volume = rng.lognormal(15, 0.35, n)
        volume[-1] *= rng.choice([1.0, 1.0, 2.8])
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
        return pd.DataFrame({"Open": open_, "High": high, "Low": low,
                             "Close": close, "Volume": volume}, index=idx)

    def fundamentals(self, ticker: str) -> dict:
        rng = self._rng(ticker + ":f")
        price = float(self.history(ticker)["Close"].iloc[-1])
        return {
            "name": f"{ticker} (demo)", "sector": rng.choice(["Technology", "Healthcare", "Energy"]),
            "market_cap": float(rng.uniform(2e10, 3e12)),
            "pe_trailing": float(rng.uniform(8, 60)), "pe_forward": float(rng.uniform(7, 45)),
            "peg": float(rng.uniform(0.6, 3.5)),
            "revenue_growth": float(rng.uniform(-0.1, 0.4)),
            "earnings_growth": float(rng.uniform(-0.3, 0.6)),
            "gross_margin": float(rng.uniform(0.2, 0.75)),
            "operating_margin": float(rng.uniform(-0.05, 0.45)),
            "profit_margin": float(rng.uniform(-0.05, 0.35)),
            "roe": float(rng.uniform(-0.05, 0.5)),
            "debt_to_equity": float(rng.uniform(0.0, 2.8)),
            "current_ratio": float(rng.uniform(0.7, 3.0)),
            "free_cash_flow": float(rng.uniform(-2e9, 5e10)),
            "target_mean_price": price * float(rng.uniform(0.85, 1.4)),
            "recommendation_mean": float(rng.uniform(1.4, 3.6)),
        }


def get_provider(name: str) -> DataProvider:
    if name == "demo":
        return DemoProvider()
    if name == "yahoo":
        return YahooProvider()
    raise ValueError(f"Unknown data provider: {name}")
