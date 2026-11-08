import numpy as np
import pandas as pd

from stockwatch import stab_study as ss


def frame(closes):
    c = np.array(closes, float)
    idx = pd.bdate_range("2024-01-01", periods=len(c))
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c}, index=idx)


def test_flat_base_after_a_fall_then_recovery_is_not_a_fresh_low():
    closes = list(np.linspace(100, 70, 40)) + [70.0] * 6 + list(np.linspace(70, 80, 12))     # long fall, flat base, rebound
    f = frame(closes)
    x = ss.cases(f, windows=(3,), flats=(1.0,))
    flat = x[x["flat"] & (x["date"] >= f.index[43]) & (x["date"] <= f.index[45])]     # inside the base
    assert len(flat) > 0 and not flat["fresh_low"].any() and (flat["ret"] > 0).all()


def test_pause_then_another_leg_is_a_fresh_low_and_a_clear_one():
    closes = list(np.linspace(100, 70, 40)) + [70.0] * 6 + list(np.linspace(70, 50, 15))
    f = frame(closes)
    x = ss.cases(f, windows=(3,), flats=(1.0,))
    flat = x[x["flat"] & (x["date"] >= f.index[43]) & (x["date"] <= f.index[45])]
    assert len(flat) > 0 and flat["fresh_low"].all() and flat["lower_1atr"].all()


def test_rows_need_a_full_horizon_and_the_report_builds():
    closes = list(np.linspace(100, 70, 60))
    x = ss.cases(frame(closes), windows=(3, 5), flats=(0.6,))
    assert x["date"].max() <= frame(closes).index[-1 - ss.HORIZON]
    rng = np.random.default_rng(3)
    frames = {f"T{i}": frame(100 * np.exp(np.cumsum(rng.normal(-0.004, 0.02, 700)))) for i in range(25)}
    txt = ss.report(ss.study(frames))
    assert "AFTER A HARD FALL" in txt and "window  3 sessions" in txt
