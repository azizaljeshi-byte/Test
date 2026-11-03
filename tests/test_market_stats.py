import numpy as np
import pandas as pd

from stockwatch import market


def _hist(n=40, price=100.0, rng=2.0, vol=1000):
    idx = pd.date_range("2026-09-01", periods=n, freq="B")
    c = np.full(n, price)
    return pd.DataFrame({"Open": c, "High": c + rng / 2, "Low": c - rng / 2, "Close": c, "Volume": np.full(n, vol)}, index=idx)


def test_universe_stats_have_range_volume_and_sector():
    names = pd.DataFrame({"sector": ["Energy"]}, index=["AAA"])
    out = market.universe_stats({"AAA": _hist(), "BAD": _hist(n=3)}, names)
    assert out["AAA"] == {"atr": 2.0, "avg_vol": 1000, "sector": "Energy"}
    assert "BAD" not in out                      # too little history: no range, not guessed
