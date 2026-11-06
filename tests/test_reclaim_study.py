import numpy as np
import pandas as pd

from stockwatch import reclaim_study as rs


def _frame(n=420, seed=3):
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(-0.004, 0.02, n)))
    idx = pd.bdate_range(end="2026-10-30", periods=n)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=idx)


def test_cases_columns_and_no_peeking():
    df = _frame()
    x = rs.cases(df, with_line=False)
    assert len(x) > 30 and {"fresh_low", "c5", "c10", "c20", "ret", "under_line"} <= set(x.columns)
    # the outcome uses only later bars: changing the last bar never changes an early row
    df2 = df.copy(); df2.iloc[-1, df2.columns.get_loc("Close")] *= 3
    y = rs.cases(df2, with_line=False)
    assert x.iloc[:20].reset_index(drop=True).equals(y.iloc[:20].reset_index(drop=True))


def test_exit_line_uses_only_past_bars():
    df = _frame()
    a = rs.exit_line(df, 300)
    df2 = df.copy(); df2.iloc[301:, df2.columns.get_loc("Close")] *= 5
    assert a == rs.exit_line(df2, 300)


def test_report_runs():
    res = rs.study({"AAA": _frame(seed=1), "BBB": _frame(seed=2)}, with_line=False)
    assert "does a close back above a ceiling" in rs.report(res)
