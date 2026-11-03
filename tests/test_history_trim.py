import numpy as np
import pandas as pd

from stockwatch import briefing
from stockwatch.data import trim_unfinished


def bars(n=5):
    idx = pd.date_range("2026-10-19", periods=n, freq="B")
    return pd.DataFrame({"Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.5, "Volume": 1000.0}, index=idx)


def test_an_empty_trailing_bar_is_dropped_and_nothing_is_filled():
    df = bars()
    df.iloc[-1, :4] = np.nan
    out = trim_unfinished(df)
    assert len(out) == 4 and out.index[-1] == df.index[-2] and np.isfinite(out[["Open", "High", "Low", "Close"]].to_numpy()).all()


def test_two_trailing_bad_bars_go_but_an_interior_bad_bar_is_left_for_the_quality_check_to_refuse():
    df = bars(6)
    df.iloc[-2:, :4] = np.nan
    assert len(trim_unfinished(df)) == 4
    mid = bars(6)
    mid.iloc[2, 3] = np.nan
    assert len(trim_unfinished(mid)) == 6 and np.isnan(trim_unfinished(mid).iloc[2]["Close"])


def test_good_history_is_untouched_and_all_bad_gives_empty():
    assert len(trim_unfinished(bars())) == 5
    df = bars(2)
    df[["Open", "High", "Low", "Close"]] = np.nan
    assert trim_unfinished(df).empty


def test_the_brief_does_not_crash_when_the_latest_price_is_missing():
    snap = {"ticker": "INTC", "tier": 1, "price": None, "verdict": "WATCH", "fundamental_score": 50.0, "composite": 50.0,
            "payload": {"technical": {}, "fundamental": {}, "events": {}, "research": {}, "plan": {}, "signals": []}}
    prev = {"price": 90.0, "verdict": "WATCH", "composite": 50.0, "payload": {"signals": []}}
    assert briefing.stock(snap, prev)["headline"]
