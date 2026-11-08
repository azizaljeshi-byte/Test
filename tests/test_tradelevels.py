import numpy as np
import pandas as pd

from stockwatch import technical_view, tradelevels as tl, design

ZONES = {"known": True, "support": [{"low": 95.0, "high": 97.0, "grade": "MEDIUM", "reasons": []}],
         "resistance": [{"low": 106.0, "high": 107.0, "grade": "LOW", "reasons": []}, {"low": 111.0, "high": 113.0, "grade": "HIGH", "reasons": []},
                        {"low": 120.0, "high": 121.0, "grade": "LOW", "reasons": []}]}


def oc(call="BUY", line=96.2, close=100.0, dist=1.9):
    return {"known": True, "call": call, "exit_line": line, "close": close, "distance_swings": dist, "why": "x"}


def test_buy_plan_uses_exit_line_and_nearest_two_resistances():
    p = tl.build(oc(), ZONES, 100.0)
    assert p["mode"] == "buy" and p["entry"] == 100.0 and p["stop"] == 96.2
    assert p["targets"] == [106.0, 111.0]                      # the third ceiling is not used
    assert abs(p["risk"] - 3.8) < 1e-9 and abs(p["ratios"][0] - 6 / 3.8) < 1e-9


def test_under_line_and_wait_draw_no_entry():
    u = tl.build(oc("AVOID", line=39.91, close=37.15), ZONES, 37.15)
    assert u["mode"] == "under" and u["entry"] is None and u["targets"] == []
    w = tl.build(oc("WAIT", line=80.0, close=100.0, dist=5), ZONES, 100.0)
    assert w["mode"] == "wait" and w["stop"] is None
    assert "NO ENTRY NOW" in tl.html(u) and "NO ENTRY YET" in tl.html(w)


def test_unknown_gives_nothing():
    assert tl.build(None, {"known": False}, 10) is None and tl.build({"known": False}, {"known": False}, 10) is None
    assert tl.build(None, ZONES, 10)["mode"] == "noline"            # levels without an exit line are still drawn, with the reason
    assert tl.build(oc(), ZONES, None) is None and tl.html(None) == ""


def test_html_shows_labels_and_warns_when_profit_1_is_closer_than_risk():
    p = tl.build(oc(line=90.0, dist=5), {"known": True, "support": [], "resistance": [{"low": 102.0, "high": 103.0, "grade": "LOW", "reasons": []}]}, 100.0)
    h = tl.html(p)
    assert "Stop loss" in h and "Profit 1" in h and "Profit 2" not in h and "closer than the risk" in h


def test_swings_and_atr_fallback():
    assert abs(tl.atr_of({"close": 100, "exit_line": 96, "distance_swings": 2.0}) - 2.0) < 1e-9
    assert tl.atr_of({"atr": 1.5}) == 1.5 and tl.atr_of({}) is None
    assert abs(tl.swings_away(100, 106, 2.0) - 3.0) < 1e-9 and tl.swings_away(100, 106, None) is None


def test_zone_row_shows_distance():
    assert "1.8 swings away" in design.zone_row("resistance", 42.0, 42.44, "LOW", ["2 touches"], "1.8 swings away")
    assert "swings away" not in design.zone_row("support", 142.6, None, "MEDIUM")


def test_macd_histogram_row_is_context_not_a_vote():
    r = np.random.default_rng(2)
    c = 100 * np.exp(np.cumsum(r.normal(0, 0.015, 200)))
    h = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=pd.bdate_range(end="2026-10-30", periods=200))
    rows = technical_view.indicators(h)
    row = [x for x in rows if x["name"] == "MACD histogram"]
    assert len(row) == 1 and row[0]["read"] in ("Rising", "Falling", "Flat")
    ev = technical_view.evidence(h)
    n_votes = sum(ev["ind_summary"][k] for k in ("buy", "sell", "neutral"))
    assert n_votes == len([x for x in rows if x["name"] not in technical_view.CONTEXT_ONLY])


def test_zone_rows_show_a_grade_badge():
    oc = {"known": True, "exit_line": 240.12, "close": 171.97, "call": "AVOID", "atr": 6.3}
    z = {"known": True, "resistance": [{"low": 177.91, "high": 177.91, "grade": "LOW", "reasons": []}, {"low": 200.58, "high": 200.58, "grade": "MEDIUM", "reasons": []}],
         "support": [{"low": 170.76, "high": 170.76, "grade": "HIGH", "reasons": []}]}
    h = tl.html(tl.build(oc, z, 171.97))
    assert "tl-g-weak" in h and "tl-g-medium" in h and "tl-g-strong" in h and ">WEAK<" in h
    assert h.index("Exit line") < h.index("Resistance 2") < h.index("Resistance 1") < h.index("Price now") < h.index("Support 1")


def test_no_exit_line_still_draws_the_levels_and_says_why():
    z = {"known": True, "resistance": [{"low": 110.0, "high": 111.0, "grade": "LOW", "reasons": []}],
         "support": [{"low": 90.0, "high": 91.0, "grade": "HIGH", "reasons": []}]}
    h = tl.html(tl.build({"known": False, "why": "Only 150 daily bars"}, z, 100.0))
    assert "NO EXIT LINE" in h and "Only 150 daily bars" in h and "Resistance 1" in h and "Support 1" in h
    assert tl.build(None, {"known": False}, 100.0) is None      # nothing to draw at all
