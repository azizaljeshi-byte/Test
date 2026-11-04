import numpy as np
import pandas as pd

from stockwatch import earnings_study as es


def _frame(n=700, seed=4):
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(0.0004, 0.015, n)))
    idx = pd.bdate_range(end="2026-10-30", periods=n)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=idx)


def fake_line(df, i):                 # a stand-in exit line 3% under the close, so the test is fast and deterministic
    return float(df["Close"].iloc[i]) * 0.97


def test_groups_and_outcomes():
    df = _frame()
    ed = [df.index[300].date(), df.index[400].date()]
    x = es.cases(df, ed, line_fn=fake_line)
    assert len(x) > 20 and {"hit", "stopped", "after", "fell", "other"} <= set(x.columns)
    assert not (x["hit"] & x["stopped"]).any()
    assert x["after"].sum() > 0 and x["other"].sum() > 0
    assert not (x["after"] & x["other"]).any()


def test_no_buy_just_before_earnings_and_no_peeking():
    df = _frame()
    e = df.index[350].date()
    x = es.cases(df, [e], line_fn=fake_line)
    before = x[(x["date"] >= df.index[348]) & (x["date"] < df.index[350])]
    assert before.empty                                   # earnings within 2 days: the app never says BUY
    df2 = df.copy(); df2.iloc[-1] = df2.iloc[-1] * 5
    y = es.cases(df2, [e], line_fn=fake_line)
    assert x.iloc[:30].reset_index(drop=True).equals(y.iloc[:30].reset_index(drop=True))


def test_report_runs():
    f = {"AAA": _frame(seed=1)}
    res = es.study(f, {"AAA": [f["AAA"].index[300].date()]})
    assert "BUY ZONE BETTER" in es.report(res) or res["cases"].empty
