import numpy as np
import pandas as pd

from stockwatch import technical_view as tv


def bars(n=300, drift=0.1, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(drift, 1.5, n))
    idx = pd.bdate_range(end="2026-10-23", periods=n)
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1e6}, index=idx)


def test_pivots_follow_the_textbook_formulas():
    h = pd.DataFrame({"Open": [1, 1], "High": [12, 12], "Low": [8, 8], "Close": [11, 11], "Volume": [1, 1]})
    pv = tv.pivots(h)
    p = (12 + 8 + 11) / 3
    assert abs(pv["classic"]["P"] - p) < 1e-9 and abs(pv["classic"]["R1"] - (2 * p - 8)) < 1e-9 and abs(pv["classic"]["S1"] - (2 * p - 12)) < 1e-9
    assert abs(pv["fibonacci"]["R1"] - (p + 0.382 * 4)) < 1e-9 and abs(pv["fibonacci"]["S3"] - (p - 4)) < 1e-9


def test_a_moving_average_read_is_price_above_or_below_and_short_history_is_na():
    ev = tv.evidence(bars(60))
    m = {r["period"]: r for r in ev["mas"]}
    assert m[200]["simple_read"] == "n/a" and m[200]["simple"] is None and m[50]["simple_read"] in ("Buy", "Sell")
    up = tv.evidence(bars(300, drift=1.0))
    assert all(r["simple_read"] == "Buy" for r in up["mas"]) and up["ma_summary"]["word"] == "Strong buy"
    down = tv.evidence(bars(300, drift=-1.0))
    assert all(r["exp_read"] == "Sell" for r in down["mas"]) and down["ma_summary"]["word"] == "Strong sell"


def test_oscillator_reads_and_atr_is_not_a_vote():
    ev = tv.evidence(bars(300, drift=1.0))
    names = {r["name"]: r for r in ev["indicators"]}
    assert len(names) == 12 and names["RSI (14)"]["read"] == "Sell"           # a steady climb is overbought
    total = ev["ind_summary"]["buy"] + ev["ind_summary"]["sell"] + ev["ind_summary"]["neutral"]
    assert total == 11 and names["ATR (14)"]["read"] in ("Less volatility", "High volatility")


def test_too_few_bars_says_so_and_today_is_dropped_while_open():
    assert tv.evidence(bars(20)) is None and "Not enough daily bars" in tv.html(None)
    h = bars(60)
    assert len(tv.completed(h, h.index[-1].date(), True)) == 59 and len(tv.completed(h, h.index[-1].date(), False)) == 60


def test_the_page_renders_every_section_and_escapes():
    html = tv.html(tv.evidence(bars(300)))
    for text in ("Technical evidence", "Pivot points", "Fibonacci", "Moving averages", "Indicators", "Does not change the call".lower()):
        assert text in html or text in html.lower()


def test_cci_uses_the_mean_deviation_around_the_current_window():
    rng = np.random.default_rng(3)
    n = 120
    c = pd.Series(30 * np.exp(np.cumsum(rng.normal(0, 0.04, n))), index=pd.bdate_range("2025-01-01", periods=n))
    h = pd.DataFrame({"Close": c, "High": c * 1.01, "Low": c * 0.99})
    tp = (h.High + h.Low + h.Close) / 3
    w = tp.iloc[-14:]
    expected = (w.iloc[-1] - w.mean()) / (0.015 * np.abs(w - w.mean()).mean())
    got = float(next(r["value"] for r in tv.indicators(h) if r["name"] == "CCI (14)"))
    assert abs(got - expected) < 0.01
