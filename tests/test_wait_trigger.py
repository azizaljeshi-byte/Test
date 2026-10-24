"""A wait trigger far above the price is shown as recovery steps, not one distant number."""
import numpy as np

from stockwatch import tradeplan

from test_stockwatch import _plan

FALLING = np.r_[np.geomspace(300, 100, 280), np.linspace(100, 98, 20)]        # far under all its averages
NEAR = np.r_[np.geomspace(100, 150, 280), np.linspace(150, 146, 20)]


def test_a_far_trigger_becomes_steps_nearest_first():
    p = _plan(FALLING, "WATCH")
    assert p["stance"] == "WAIT FOR CONFIRMATION"
    t = p["trigger"]
    assert t.startswith("recovery steps: 20-day ") and "50-day" in t and "200-day" in t
    assert t.index("20-day") < t.index("50-day") < t.index("200-day")
    assert t.count("%)") == 3 and "(+" in t
    assert tradeplan.summary(p) == f"wait: {t}"


def test_the_steps_match_the_real_averages_and_percentages():
    p = _plan(FALLING, "WATCH")
    price = float(FALLING[-1])
    sma20 = float(np.mean(FALLING[-20:]))
    assert f"20-day {sma20:.2f} ({(sma20 / price - 1) * 100:+.1f}%)" in p["trigger"]


def test_a_near_trigger_keeps_the_single_level_wording():
    p = _plan(np.r_[np.geomspace(100, 150, 280), np.linspace(150, 138, 20)], "WATCH")
    if p["stance"] == "WAIT FOR CONFIRMATION" and p["trigger"].startswith("a daily close back above"):
        assert "recovery steps" not in p["trigger"]


def test_only_averages_above_the_price_are_listed():
    assert tradeplan.recovery_steps(100.0, 90.0, 120.0, 150.0) == "recovery steps: 50-day 120.00 (+20.0%), 200-day 150.00 (+50.0%)"
    assert tradeplan.recovery_steps(100.0, 90.0, 95.0, 99.0) is None
    assert tradeplan.recovery_steps(100.0, float("nan"), None, 130.0) == "recovery steps: 200-day 130.00 (+30.0%)"


def test_the_telegram_wait_line_reads_naturally():
    p = _plan(FALLING, "WATCH")
    assert p["trigger"].startswith("recovery steps")
    assert len("Not a buy yet. Wait for " + p["trigger"] + ".") < 300


def test_a_downtrend_without_steps_falls_back_to_the_old_text(monkeypatch):
    monkeypatch.setattr(tradeplan, "recovery_steps", lambda *a: None)
    assert _plan(FALLING, "WATCH")["trigger"].startswith("a daily close back above")
