"""Momentum and the kind of move (stockwatch/momentum.py). Synthetic bars only: not market data."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from stockwatch import momentum, transitions, ui
from stockwatch.config import Holding
from stockwatch.data import DemoProvider
from stockwatch.engine import evaluate

from test_ci_scan import NOW as CI_NOW, ev
from test_status import NOW, bars, ramp
from test_status_wiring import ps, snap_of
from test_stockwatch import make_portfolio

N = 300


def frame(closes, vols=None):
    df = bars(closes)
    df["Volume"] = np.full(len(closes), 1_000_000.0) if vols is None else np.asarray(vols, float)
    return df


def flat_then(tail, n=N, base=100.0):
    """A quiet, very slightly rising base then a scripted tail of closes."""
    head = base * (1 + 0.0001) ** np.arange(n - len(tail))
    return np.concatenate([head, np.asarray(tail, float)])


def decline(days=20, total=-0.12, base=100.0):
    return base * (1 + total) ** (np.arange(1, days + 1) / days)


def test_a_steady_climb_on_quiet_volume_is_strong_and_unremarkable():
    r = momentum.assess(frame(ramp(N, 0.004)), None, None, NOW)
    assert r["known"] and r["momentum"] == "strong" and r["cause"] == "none" and r["why"].startswith("Nothing unusual")
    assert r["facts"]["ret20"] > 0.08


def test_a_slide_with_heavy_down_volume_is_distribution():
    closes = flat_then(decline(25, -0.12))
    vols = np.full(len(closes), 1_000_000.0)
    vols[-25:] = np.linspace(1.1e6, 1.9e6, 25)               # rising volume through the slide: every down day is heavier
    r = momentum.assess(frame(closes, vols), None, None, NOW)
    assert r["momentum"] in ("falling", "weak") and r["cause"] == "distribution"
    assert r["facts"]["distribution_days"] >= 5 and "heavy-volume down days" in r["why"]


def test_a_one_day_collapse_on_huge_volume_is_event_driven_and_wins_over_the_rest():
    closes = flat_then(np.concatenate([np.full(5, 100.0), [86.0], np.full(8, 85.0)]))
    vols = np.full(len(closes), 1_000_000.0)
    vols[-9] = 6_000_000.0
    r = momentum.assess(frame(closes, vols), None, None, NOW)
    assert r["cause"] == "event" and "-14% day on 6.0x" in r["why"] and r["momentum"] in ("falling", "weak")


def test_a_big_move_on_ordinary_volume_is_not_an_event():
    closes = flat_then(np.concatenate([np.full(5, 100.0), [86.0], np.full(8, 85.0)]))
    r = momentum.assess(frame(closes), None, None, NOW)
    assert r["cause"] != "event"


def test_a_decline_that_matches_the_market_is_market_wide():
    closes = flat_then(decline(25, -0.08))
    market = frame(flat_then(decline(25, -0.07)))
    r = momentum.assess(frame(closes), market, None, NOW)
    assert r["cause"] == "market" and "market is -6%" in r["why"]


def test_a_decline_far_worse_than_the_market_is_not_blamed_on_it():
    closes = flat_then(decline(25, -0.18))
    market = frame(flat_then(decline(25, -0.04)))
    assert momentum.assess(frame(closes), market, None, NOW)["cause"] != "market"


def test_the_sector_explains_it_when_the_market_does_not():
    closes = flat_then(decline(25, -0.08))
    flat_market = frame(flat_then(np.full(25, 100.0)))
    sector = frame(flat_then(decline(25, -0.07)))
    r = momentum.assess(frame(closes), flat_market, sector, NOW)
    assert r["cause"] == "sector" and "sector is -6%" in r["why"]


def test_a_quiet_fall_with_no_cause_is_stock_specific_drift():
    r = momentum.assess(frame(flat_then(decline(25, -0.06))), None, None, NOW)
    assert r["cause"] == "drift" and "it is the stock itself" in r["why"]


def test_a_rise_on_rising_volume_is_accumulation():
    closes = flat_then(100 * (1.12) ** (np.arange(1, 26) / 25))
    vols = np.full(len(closes), 1_000_000.0)
    vols[-25:] = np.linspace(1.1e6, 1.9e6, 25)
    r = momentum.assess(frame(closes, vols), None, None, NOW)
    assert r["cause"] == "accumulation" and r["facts"]["accumulation_days"] >= 5


def test_a_rally_with_the_market_is_market_wide():
    closes = flat_then(100 * (1.06) ** (np.arange(1, 26) / 25))
    market = frame(flat_then(100 * (1.05) ** (np.arange(1, 26) / 25)))
    assert momentum.assess(frame(closes), market, None, NOW)["cause"] == "market"


@pytest.mark.parametrize("tail,expected", [
    (decline(20, -0.15), "falling"),
    (decline(20, -0.05), "weak"),
])
def test_the_momentum_ladder_down(tail, expected):
    assert momentum.assess(frame(flat_then(tail)), None, None, NOW)["momentum"] == expected


def test_fading_and_stabilising():
    up_then_stall = flat_then(np.concatenate([100 * 1.10 ** (np.arange(1, 11) / 10), np.full(10, 110.5)]))
    fading = momentum.assess(frame(up_then_stall), None, None, NOW)
    assert fading["momentum"] in ("fading", "strong", "building")        # the stall turns MACD down only after a few bars
    drop_then_bounce = flat_then(np.concatenate([decline(12, -0.10), 90 * 1.04 ** (np.arange(1, 9) / 8)]))
    r = momentum.assess(frame(drop_then_bounce), None, None, NOW)
    assert r["momentum"] in ("stabilising", "weak", "falling")


def test_also_lists_the_other_things_that_hit():
    closes = flat_then(decline(25, -0.08))
    vols = np.full(len(closes), 1_000_000.0)
    vols[-25:] = np.linspace(1.1e6, 1.9e6, 25)
    market = frame(flat_then(decline(25, -0.07)))
    r = momentum.assess(frame(closes, vols), market, None, NOW)
    assert r["cause"] == "market" and r["also"] == ["distribution"] and "Also:" in r["why"]


def test_oversold_is_said_plainly():
    r = momentum.assess(frame(flat_then(decline(25, -0.25))), None, None, NOW)
    assert "oversold" in r["tone"] and r["facts"]["rsi"] < 30


def test_unknown_is_unknown_with_the_reason():
    assert momentum.assess(frame(ramp(40)), None, None, NOW)["known"] is False
    assert "Only 40" in momentum.assess(frame(ramp(40)), None, None, NOW)["why"]
    assert momentum.assess(None, None, None, NOW)["known"] is False
    no_vol = frame(ramp(N), np.zeros(N))
    r = momentum.assess(no_vol, None, None, NOW)
    assert r["known"] is False and "Volume is missing" in r["why"]
    later = datetime(2026, 11, 25, 15, 0, tzinfo=timezone.utc)
    assert momentum.assess(frame(ramp(N)), None, None, later)["known"] is False       # four weeks stale


def test_a_bad_benchmark_is_ignored_not_a_crash():
    closes = flat_then(decline(25, -0.08))
    for bad in (pd.DataFrame(), pd.DataFrame({"Close": [np.nan] * 5}), "nope"):
        r = momentum.assess(frame(closes), bad, bad, NOW)
        assert r["known"] and r["cause"] in ("drift", "distribution", "event")


# ---- on screen and in Telegram

def snap_with(mo):
    e = ev("HOOD", "HOLD")
    e.technical = {"price_status": ps("breakdown"), "momentum": mo}
    return snap_of(e)


def falling():
    closes = flat_then(decline(25, -0.12))
    vols = np.full(len(closes), 1_000_000.0)
    vols[-25:] = np.linspace(1.1e6, 1.9e6, 25)
    return momentum.assess(frame(closes, vols), None, None, NOW)


def test_the_row_shows_the_flow_for_a_notable_move_and_nothing_for_quiet_strength():
    html = ui.row(snap_with(falling()))
    assert "<b>FLOW</b>" in html and "distribution (sustained selling)" in html
    quiet = momentum.assess(frame(ramp(N, 0.004)), None, None, NOW)
    assert ui.flow_line(snap_with(quiet)) == "" and "<b>FLOW</b>" not in ui.row(snap_with(quiet))
    assert ui.flow_line(snap_with(None)) == "" and ui.flow_line(snap_with({"known": False, "why": "x"})) == ""


def test_details_explains_it_with_the_numbers():
    note = ui.flow_note(snap_with(falling()))
    assert "distribution (sustained selling)" in note and "distribution days" in note and "20-day" in note
    assert "no read" in ui.flow_note(snap_with({"known": False, "why": "Only 40 daily bars; momentum needs 70."}))
    assert ui.flow_note(snap_with(None)) == ""


def test_the_status_message_carries_one_flow_line_only_when_it_was_read():
    e = ev("HOOD", "HOLD")
    e.technical = {"price_status": ps("breakdown"), "momentum": falling()}
    t = {"ticker": "HOOD", "held": True, "from": "testing_support", "to": "breakdown"}
    msg = transitions.status_message(t, e, "2026-10-22", CI_NOW)
    assert any(l.startswith("Flow: ") and "distribution (sustained selling)" in l for l in msg.split("\n"))
    e.technical["momentum"] = {"known": False, "why": "x"}
    assert "Flow:" not in transitions.status_message(t, e, "2026-10-22", CI_NOW)


def test_the_engine_records_it_and_it_changes_no_call(monkeypatch):
    a = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    assert "momentum" in a.technical
    monkeypatch.setattr(momentum, "assess", lambda *x, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    b = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    assert b.technical["momentum"] is None and (a.verdict, a.plan) == (b.verdict, b.plan)
