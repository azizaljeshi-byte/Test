"""The seven-step price status (stockwatch/status.py). Synthetic bars only: not market data."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from stockwatch import status

from cis_helpers import synthetic

END = pd.Timestamp("2026-10-22")                              # a Thursday: the last completed session
NOW = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)      # Friday 11:00 New York: that bar is the latest


def bars(closes) -> pd.DataFrame:
    c = np.asarray(closes, float)
    idx = pd.bdate_range(end=END, periods=len(c))
    return pd.DataFrame({"Open": c, "High": c * 1.004, "Low": c * 0.996, "Close": c,
                         "Volume": np.full(len(c), 1_000_000.0)}, index=idx)


def ramp(n=400, daily=0.004):
    """A steady climb, so the 50-day average sits well under the price and the last close is the high."""
    return 100 * (1 + daily) ** np.arange(n)


def with_floor(monkeypatch, low, high, failure=None, major=None):
    """Fix the support levels instead of deriving them, so each status is tested exactly."""
    dn = {"zone": {"low": low, "high": high}, "warning": low,
          "failure": failure if failure is not None else low * 0.97,
          "major_damage": major if major is not None else low * 0.90}
    monkeypatch.setattr(status.candidates, "extract", lambda df, sym, src, *a, **k: ({"downside": dn}, {}))


def no_floor(monkeypatch, why="no zone found"):
    monkeypatch.setattr(status.candidates, "extract", lambda df, sym, src, *a, **k: (None, {"why": why}))


def test_record_high(monkeypatch):
    c = ramp()
    with_floor(monkeypatch, c[-1] * 0.8, c[-1] * 0.82)
    r = status.assess(bars(c), NOW)
    assert r["code"] == "record_high" and r["label"] == "RECORD HIGH"
    assert r["levels"]["high"] == round(c[-1], 2) and r["floor_known"]


def test_strong_uptrend(monkeypatch):
    c = ramp()
    c[-1] = c[-2] * 0.97                                    # 3% below the high, still far above both averages
    with_floor(monkeypatch, c[-1] * 0.7, c[-1] * 0.72)
    assert status.assess(bars(c), NOW)["code"] == "strong_uptrend"


def test_pullback(monkeypatch):
    c = ramp()
    c[-1] = c[-2] * 0.93                                    # 7% off the high, above the 50-day (about 9% under it)
    with_floor(monkeypatch, c[-1] * 0.7, c[-1] * 0.72)
    r = status.assess(bars(c), NOW)
    assert r["code"] == "pullback" and "7% below the high" in r["why"]


def test_weakening_below_50_day(monkeypatch):
    c = ramp()
    c[-3:] = c[-4] * np.array([0.9, 0.88, 0.86])            # through the 50-day, still above the support zone
    with_floor(monkeypatch, c[-1] * 0.8, c[-1] * 0.82)
    r = status.assess(bars(c), NOW)
    assert r["code"] == "weakening" and "50-day" in r["why"]


def test_weakening_when_far_below_high_even_above_averages(monkeypatch):
    c = ramp(daily=0.01)                                    # a very steep run: averages sit far below the price
    c[-1] = c[-2] * 0.80                                    # 20% off the high but above both averages
    with_floor(monkeypatch, c[-1] * 0.5, c[-1] * 0.52)
    r = status.assess(bars(c), NOW)
    assert r["code"] == "weakening" and "20% below the high" in r["why"]


def test_testing_support_inside_the_zone(monkeypatch):
    c = ramp()
    price = c[-1]
    with_floor(monkeypatch, price * 0.97, price * 1.03)
    r = status.assess(bars(c), NOW)
    assert r["code"] == "testing_support" and "A close below" in r["action"]


def test_breakdown_below_the_zone(monkeypatch):
    c = ramp()
    price = c[-1]
    with_floor(monkeypatch, price * 1.02, price * 1.05, failure=price * 0.95, major=price * 0.90)
    r = status.assess(bars(c), NOW)
    assert r["code"] == "breakdown" and r["action"].startswith("Closed below support")
    assert "not reviewed" in r["action"] and "Exit" not in r["action"]          # a fact, not an instruction, by default
    monkeypatch.setattr(status, "EXIT_ON_BREAKDOWN", True)
    assert status.assess(bars(c), NOW)["action"].startswith("Exit the trade")


def test_breakdown_below_failure_level_is_still_breakdown(monkeypatch):
    c = ramp()
    price = c[-1]
    with_floor(monkeypatch, price * 1.10, price * 1.13, failure=price * 1.05, major=price * 0.90)
    assert status.assess(bars(c), NOW)["code"] == "breakdown"


def test_deep_breakdown_below_the_major_level(monkeypatch):
    c = ramp()
    price = c[-1]
    with_floor(monkeypatch, price * 1.20, price * 1.25, failure=price * 1.10, major=price * 1.05)
    r = status.assess(bars(c), NOW)
    assert r["code"] == "deep_breakdown" and r["action"].startswith("Closed below the deeper level")
    assert "Exit" not in r["action"]
    monkeypatch.setattr(status, "EXIT_ON_BREAKDOWN", True)
    assert status.assess(bars(c), NOW)["action"].startswith("Exit now")


def test_equal_to_a_level_is_not_below_it(monkeypatch):
    c = ramp()
    price = round(c[-1], 2)
    c[-1] = price
    with_floor(monkeypatch, price, price * 1.05, failure=price * 0.95, major=price * 0.90)
    assert status.assess(bars(c), NOW)["code"] == "testing_support"        # at the zone's low edge, not below it


def test_no_floor_keeps_trend_statuses_but_says_breakdown_cant_be_confirmed(monkeypatch):
    no_floor(monkeypatch, "no zone with 2+ anchors")
    c = ramp()
    r = status.assess(bars(c), NOW)
    assert r["code"] == "record_high" and r["floor_known"] is False
    assert "breakdown can't be confirmed" in r["why"] and "no zone with 2+ anchors" in r["why"]


def test_a_malformed_candidate_is_no_floor_not_a_crash(monkeypatch):
    def boom(*a, **k):
        raise status.level_packet.PacketError("levels can't be ordered")
    monkeypatch.setattr(status.candidates, "extract", boom)
    r = status.assess(bars(ramp()), NOW)
    assert r["floor_known"] is False and "levels can't be ordered" in r["why"]


def test_too_few_bars_is_unknown_with_the_reason():
    r = status.assess(bars(ramp(n=120)), NOW)
    assert r["code"] == "unknown" and "120 daily bars" in r["why"]
    assert r["label"] == "NO READ" and r["provisional"] is None


def test_stale_history_is_unknown_not_a_guess(monkeypatch):
    with_floor(monkeypatch, 1, 2)
    later = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)             # four weeks after the last bar
    r = status.assess(bars(ramp()), later)
    assert r["code"] == "unknown" and "behind" in r["why"]


def test_empty_history_is_unknown():
    assert status.assess(pd.DataFrame(), NOW)["code"] == "unknown"
    assert status.assess(None, NOW)["code"] == "unknown"


def test_a_live_quote_below_support_is_provisional_and_does_not_change_the_status(monkeypatch):
    c = ramp()
    price = c[-1]
    with_floor(monkeypatch, price * 0.90, price * 0.92)
    r = status.assess(bars(c), NOW, quote_price=price * 0.85)
    assert r["code"] == "record_high"
    assert r["provisional"]["code"] == "breakdown" and "only if a session closes there" in r["provisional"]["note"]


def test_a_better_or_equal_quote_adds_no_provisional_note(monkeypatch):
    c = ramp()
    price = c[-1]
    with_floor(monkeypatch, price * 1.02, price * 1.05, failure=price * 0.95, major=price * 0.90)   # confirmed breakdown
    assert status.assess(bars(c), NOW, quote_price=price * 1.10)["provisional"] is None
    assert status.assess(bars(c), NOW, quote_price=price)["provisional"] is None
    assert status.assess(bars(c), NOW, quote_price=float("nan"))["provisional"] is None


def test_ordering_helpers():
    assert status.rank("record_high") == 0 and status.rank("deep_breakdown") == 6 and status.rank("unknown") is None
    assert status.is_worse("breakdown", "pullback") and not status.is_worse("pullback", "breakdown")
    assert not status.is_worse("breakdown", "breakdown")
    assert not status.is_worse("unknown", "pullback") and not status.is_worse("breakdown", None)


def test_every_status_has_a_label_and_the_ladder_is_complete():
    assert set(status.LABEL) == set(status.ORDER) | {"unknown"}
    assert len(status.ORDER) == 7


def test_runs_against_the_real_floor_builder():
    start = pd.bdate_range(end=END, periods=600)[0]
    r = status.assess(synthetic(600, seed=7, start=str(start.date())), NOW)
    assert r["code"] in status.ORDER, r
    assert r["levels"]["as_of"] == "2026-10-22" and r["levels"]["years_of_data"] == pytest.approx(2.4, abs=0.1)
    if r["floor_known"]:
        lv = r["levels"]
        assert lv["deep_below"] < lv["failure"] < lv["support_low"] < lv["support_high"]


def test_one_bad_bar_years_ago_does_not_blank_the_status_and_the_old_high_still_counts(monkeypatch):
    c = np.concatenate([np.full(100, 5000.0), ramp(n=600)])         # a spike of old closes, then a long climb
    df = bars(c)
    df.iloc[5, df.columns.get_loc("High")] = df.iloc[5]["Low"] * 0.5    # a malformed bar far outside the window
    with_floor(monkeypatch, c[-1] * 0.5, c[-1] * 0.52)
    r = status.assess(df, NOW)
    assert r["code"] != "unknown", r
    assert r["levels"]["high"] == 5000.0 and r["code"] != "record_high"   # measured from the old high, not the window


def test_a_bad_bar_inside_the_window_still_means_no_read():
    df = bars(ramp(n=300))
    df.iloc[-10, df.columns.get_loc("High")] = df.iloc[-10]["Low"] * 0.5
    r = status.assess(df, NOW)
    assert r["code"] == "unknown" and "high/low don't contain open and close" in r["why"]


def test_the_exit_switch_is_off_by_default():
    assert status.EXIT_ON_BREAKDOWN is False
