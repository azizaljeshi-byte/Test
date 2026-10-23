"""Shared helpers for the CIS tests."""
import numpy as np
import pandas as pd


def synthetic(n=600, seed=7, start="2024-01-02"):
    """Deterministic synthetic daily OHLCV (a seeded random walk on business days): not market data."""
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n)))
    opn = close * np.exp(rng.normal(0, 0.005, n))
    high = np.maximum(opn, close) * (1 + rng.uniform(0, 0.01, n))
    low = np.minimum(opn, close) * (1 - rng.uniform(0, 0.01, n))
    vol = rng.integers(500_000, 2_000_000, n).astype(float)
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"Open": opn, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)
