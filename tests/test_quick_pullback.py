"""The 7 Nov Quick rules: buy the pullback not the signal, 1.5% hard stop, +1% target unless riding, 3 entries in the first 15 minutes."""
from datetime import datetime, timedelta

import pytest

from stockwatch import quick
from stockwatch.data import NY
from test_quick import ENTRY, T0, multi, snap

pytestmark = pytest.mark.new_rules


def feed(book, marks, prices, start, every=20, s=None, t="AAA"):
    for i, px in enumerate(prices):
        quick.step(book, marks, {t: s or snap()}, {t: px}, start + timedelta(seconds=every * i))
    return start + timedelta(seconds=every * len(prices))


def signal():
    """ENTRY up to the moment the bounce setup first fires: returns (book, marks, now, signal price)."""
    book, marks, now = quick.new_book(), {}, T0
    for i, px in enumerate(ENTRY):
        quick.step(book, marks, {"AAA": snap()}, {"AAA": px}, T0 + timedelta(seconds=20 * i))
        now = T0 + timedelta(seconds=20 * (i + 1))
        if book.get("watch"):
            return book, marks, now, book["watch"]["AAA"]["p0"]
    raise AssertionError("no setup fired")


def ramp(a, b, n):
    return [round(a + (b - a) * (i + 1) / n, 2) for i in range(n)]


def test_a_setup_is_not_bought_at_the_signal_price_it_goes_on_watch():
    book, marks, now, p0 = signal()
    assert book["trades"] == [] and book["watch"]["AAA"]["kind"] == "bounce"
    feed(book, marks, [p0 + 0.05] * 6, now)                     # still near the signal, no pullback: nothing is bought
    assert book["trades"] == []


def test_it_buys_after_a_pullback_once_the_price_turns_up_with_the_stop_under_the_pullback_low():
    book, marks, now, p0 = signal()
    low = round(p0 * 0.985, 2)
    path = ramp(p0, low, 30) + [low] * 6 + ramp(low, low * 1.006, 12) + [round(low * 1.0065, 2)] * 3
    feed(book, marks, path, now)
    assert len(book["trades"]) == 1
    t = book["trades"][0]
    assert t["signal"] == p0 and t["pullback_low"] <= low and t["entry"] < p0
    assert t["stop0"] == pytest.approx(t["pullback_low"] * 0.998, abs=0.02) and t["entry"] - t["stop0"] <= t["entry"] * 0.015 + 0.02
    assert "bought the pullback" in t["reason"]


def test_a_falling_price_is_not_bought_and_a_stock_that_runs_away_is_dropped():
    book, marks, now, p0 = signal()
    feed(book, marks, ramp(p0, p0 * 0.97, 60), now)             # falls and keeps falling
    assert book["trades"] == [] and "AAA" in book["watch"]
    book, marks, now, p0 = signal()
    feed(book, marks, ramp(p0, p0 * 1.03, 30), now)
    assert book["trades"] == [] and not book.get("watch")
    assert "ran away without a pullback" in book["skipped"][-1]["reason"]


def test_no_bounce_within_twenty_minutes_drops_the_watch():
    book, marks, now, p0 = signal()
    low = round(p0 * 0.985, 2)
    feed(book, marks, ramp(p0, low, 20) + [low] * 80, now)      # a flat low for more than 20 minutes
    assert book["trades"] == [] and not book.get("watch")
    assert "no bounce confirmed" in book["skipped"][-1]["reason"]


def test_a_stop_further_than_the_hard_limit_from_the_entry_is_not_bought():
    book, marks, now, p0 = signal()
    low = round(p0 * 0.985, 2)
    feed(book, marks, ramp(p0, low, 30) + [low] * 6 + [round(low * 1.02, 2)] * 6, now)       # it jumps 2% off the low: the stop would be too far away
    assert book["trades"] == [] and "stop too far" in book["skipped"][-1]["reason"]


def test_the_stop_is_never_more_than_one_and_a_half_percent_under_the_entry():
    book = quick.new_book()
    t = quick._enter(book, "AAA", "breakout", "t", 100.0, 99.5, 5.0, T0)
    assert t["stop0"] >= 98.5
    t = quick._enter(book, "BBB", "breakout", "t", 100.0, 99.5, 5.0, T0, stop=95.0)
    assert t["stop0"] == 98.5


def opened(entry=100.0):
    book = quick.new_book()
    quick._enter(book, "AAA", "breakout", "t", entry, entry, 3.0, T0)
    return book, {}


def bars(book, marks, prices, start=T0 + timedelta(minutes=1), every=60):
    done = []
    for i, px in enumerate(prices):
        done += quick.step(book, marks, {"AAA": snap(atr=3.0)}, {"AAA": px}, start + timedelta(seconds=every * i))
    return done


def test_it_takes_the_profit_at_one_percent_when_the_stock_is_not_riding():
    book, marks = opened()
    bars(book, marks, [100.2, 100.5, 101.0, 100.7, 100.6])        # reached +1%, fell back inside the same 5-minute bar
    t = book["trades"][0]
    assert t["status"] == "CLOSED" and "took the profit" in t["exit_reason"] and 0.5 < t["pct"] < 1.1


def test_it_rides_when_the_bar_that_reached_one_percent_closes_near_its_high_then_trails():
    book, marks = opened()
    start = datetime(2026, 10, 26, 10, 0, tzinfo=NY)
    bars(book, marks, [100.3, 100.6, 100.9, 101.2, 101.35, 101.4, 101.5, 101.8, 102.0], start=start, every=40)
    pos = book["positions"].get("AAA")
    assert pos and pos.get("riding") and pos["stop"] >= 100.5
    bars(book, marks, [102.6, 103.0, 103.3], start=start + timedelta(minutes=10), every=60)
    assert book["positions"]["AAA"]["stop"] == pytest.approx(103.3 * 0.993, abs=0.02)
    bars(book, marks, [102.4], start=start + timedelta(minutes=14))
    t = book["trades"][0]
    assert t["status"] == "CLOSED" and "trailing stop" in t["exit_reason"] and t["pct"] > 1.5


def test_at_most_three_entries_in_the_first_fifteen_minutes_then_the_pace_limit(monkeypatch):
    monkeypatch.setattr(quick, "PULLBACK_GATE", False)
    monkeypatch.setattr(quick, "OPEN_CAP_MIN", 25)               # the test path confirms a bounce about 18 minutes in
    start = datetime(2026, 10, 26, 9, 30, tzinfo=NY)
    book = multi(ENTRY, ["A", "B", "C", "D"], lambda t: snap(), start=start)
    assert len(book["trades"]) == 3
    assert any("opening limit" in x["reason"] for x in book["skipped"])


def test_a_trade_saves_its_price_path_one_point_a_minute_from_entry_to_exit():
    book = quick.new_book()
    t0 = datetime(2026, 10, 26, 10, 0, 40, tzinfo=NY)
    quick._enter(book, "AAA", "breakout", "t", 100.0, 100.0, 3.0, t0)
    path = book["trades"][0]["path"]
    assert path == [[datetime(2026, 10, 26, 10, 0, 0, tzinfo=NY).timestamp(), 100.0]]            # the entry, stamped with its minute
    for i in range(1, 400):                                                                         # 20-second prices for over two hours
        quick.step(book, {}, {"AAA": snap(atr=3.0)}, {"AAA": 100.0 + (i % 7) * 0.02}, t0 + timedelta(seconds=20 * i))
        if book["trades"][0]["status"] == "CLOSED":
            break
    t = book["trades"][0]
    p = t["path"]
    assert all(b[0] > a[0] for a, b in zip(p, p[1:])) and all(len(x) == 2 for x in p)
    assert len(p) <= quick.PATH_MAX and p[0][1] == 100.0
    if t["status"] == "CLOSED":
        assert p[-1][1] == t["exit"]


def test_the_path_is_capped_and_thinned_and_dropped_for_old_closed_trades():
    t = {"status": "OPEN"}
    base = datetime(2026, 10, 26, 10, 0, tzinfo=NY)
    for i in range(200):
        quick._trace(t, 100 + i * 0.01, base + timedelta(minutes=i))
    assert len(t["path"]) <= quick.PATH_MAX and t["path"][0][1] == 100.0 and t["path"][-1][1] == pytest.approx(101.99)
    book = quick.new_book()
    book["trades"] = [{"status": "CLOSED", "closed": "2026-10-20 15:00", "path": [[1, 2]]}, {"status": "CLOSED", "closed": "2026-10-26 15:00", "path": [[1, 2]]}]
    quick._prune_paths(book, base)
    assert "path" not in book["trades"][0] and book["trades"][1]["path"]
