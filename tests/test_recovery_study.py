import numpy as np
import pandas as pd

from stockwatch import recovery_study as rs


def _frame(n=500, seed=3):
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(-0.003, 0.02, n)))
    idx = pd.bdate_range(end="2026-10-30", periods=n)
    return pd.DataFrame({"Open": c * 1.001, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": r.integers(1e6, 3e6, n).astype(float)}, index=idx)


def test_outcome_stop_first_and_target_first():
    c = np.array([100.0, 100, 100, 100]); a = np.array([1.0] * 4)
    assert rs._outcome(np.array([100, 104, 100, 100.0]), np.array([100, 99, 100, 100.0]), c, a, 0, 3) == 1      # +3 hit, stop (-1.5) not
    assert rs._outcome(np.array([100, 104, 100, 100.0]), np.array([100, 98, 100, 100.0]), c, a, 0, 3) == -1     # both same day: stop first
    assert rs._outcome(np.array([100, 101, 100, 100.0]), np.array([100, 99.5, 100, 100.0]), c, a, 0, 3) == 0


def test_features_use_past_only_and_cases():
    df = _frame(); mkt = df["Close"].rename("m")
    f1 = rs.features(df, mkt)
    df2 = df.copy(); df2.iloc[-1] = df2.iloc[-1] * 4
    f2 = rs.features(df2, mkt)
    assert f1.iloc[:-1].equals(f2.iloc[:-1])
    x = rs.cases(df, mkt)
    assert len(x) > 20 and {"hit", "stopped", "n_patterns", *rs.PATTERNS} <= set(x.columns)


def test_report_runs():
    res = rs.study({"AAA": _frame(seed=1), "BBB": _frame(seed=2)})
    assert "recovery" in rs.report(res).lower()
