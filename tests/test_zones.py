"""Graded support and resistance zones (stockwatch/zones.py). Synthetic bars only."""
import numpy as np

from stockwatch import zones

from test_status import NOW, bars


def wave(n=400, period=40, amp=10.0, base=100.0):
    return base + amp * np.sin(np.arange(n) * 2 * np.pi / period)


def test_a_range_gives_a_graded_zone_on_each_side():
    c = wave()
    c[-1] = 100.0
    z = zones.assess(bars(c), NOW)
    assert z["known"]
    sup, res = z["support"][0], z["resistance"][0]
    assert 88 <= sup["low"] <= sup["high"] <= 92 and 108 <= res["low"] <= res["high"] <= 112
    assert sup["grade"] == "HIGH" and res["grade"] == "HIGH"
    assert sup["touches"] >= 4 and "round number" in sup["reasons"] and "recent" in sup["reasons"]


def test_zones_are_on_the_right_side_of_the_price_and_nearest_first():
    c = wave()
    c[-1] = 100.0
    z = zones.assess(bars(c), NOW)
    assert all(s["high"] < 100 for s in z["support"]) and all(r["low"] > 100 for r in z["resistance"])
    highs = [s["high"] for s in z["support"]]
    assert highs == sorted(highs, reverse=True)


def test_a_single_old_touch_is_low():
    c = np.concatenate([np.full(60, 100.0), [60.0] * 3, np.full(5, 100.0), np.linspace(100, 140, 330)])
    z = zones.assess(bars(c), NOW)
    old = [s for s in z["support"] if s["low"] < 70]
    assert old and old[0]["grade"] == "LOW" and old[0]["touches"] == 1


def test_too_little_history_says_why_and_returns_no_levels():
    z = zones.assess(bars(wave(n=60)), NOW)
    assert z["known"] is False and "zones need" in z["why"] and not z["support"] and not z["resistance"]


def test_no_history_is_unknown_not_an_error():
    assert zones.assess(None, NOW)["known"] is False


def test_the_engine_stores_the_zones():
    from stockwatch.config import Holding
    from stockwatch.data import DemoProvider
    from stockwatch.engine import evaluate
    from test_stockwatch import make_portfolio
    e = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    assert "zones" in e.technical
