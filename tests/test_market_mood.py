"""The market tile: a slow trend rule plus a short-term check, so a deteriorating SPY stops reading plain RISK-ON."""
import numpy as np

from stockwatch import briefing, momentum, relative

from test_status import NOW, bars, ramp


def spy(tail=None, n=320, daily=0.0015):
    base = ramp(n, daily)
    if tail is not None:
        base = np.concatenate([base[:-len(tail)], base[-len(tail) - 1] * np.asarray(tail)])
    return bars(base)


def test_a_steady_uptrend_is_plain_risk_on():
    r = relative.market_regime(spy(), NOW)
    assert r["state"] == "RISK-ON" and r["trend_state"] == "RISK-ON" and r["reason"] is None


def test_a_sharp_drop_through_the_50_day_is_caution_with_the_reason_while_the_200_day_is_still_far_below():
    r = relative.market_regime(spy(np.linspace(0.99, 0.90, 20)), NOW)
    assert r["trend_state"] == "RISK-ON" and r["state"] == "CAUTION" and r["vs_200d"] > 0
    assert "below its 50-day average" in r["reason"]


def test_weak_momentum_above_the_50_day_is_also_caution():
    r = relative.market_regime(spy(np.linspace(0.995, 0.97, 20), daily=0.004), NOW)
    assert r["state"] == "CAUTION" and "momentum" in r["reason"]


def test_risk_off_and_a_missing_short_term_read_are_left_as_they_were():
    down = bars(ramp(320, -0.002))
    r = relative.market_regime(down, NOW)
    assert r["state"] == "RISK-OFF" and r["reason"] is None
    stale = relative.market_regime(spy(np.linspace(0.99, 0.90, 20)), None)    # real clock: these bars are old, so no momentum read
    assert stale["state"] in ("RISK-ON", "CAUTION")


def test_a_failing_momentum_read_never_breaks_the_tile(monkeypatch):
    monkeypatch.setattr(momentum, "assess", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = relative.market_regime(spy(), NOW)
    assert r["state"] == "RISK-ON"


def test_the_briefing_says_why_it_is_cautious():
    reg = {"state": "CAUTION", "reason": "below its 50-day average", "day_change": -0.005}
    line = briefing.portfolio([], {}, reg)[0]
    assert "mixed (below its 50-day average)" in line
    assert "mixed (SPY trend unclear)" in briefing.portfolio([], {}, {"state": "CAUTION", "day_change": 0.0})[0]
