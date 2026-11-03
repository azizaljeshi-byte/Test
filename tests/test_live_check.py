"""ui.live_check: the New call (last completed daily bar) against the live tape, display only."""
from stockwatch import ui


def snap(call, price, state="REGULAR", line=100.0, band=98.0, known=True):
    oc = {"known": known, "call": call, "why": "daily reason", "exit_line": line, "band_line": band}
    return {"ticker": "AAA", "price": 101.0, "payload": {"technical": {"one_call": oc, "day_change": 0.0},
                                                          "quote": {"market_state": state, "live_price": price, "live_change": 0.0}}}


def test_a_buy_that_has_fallen_through_its_line_or_band_today_says_so_and_never_shows_a_clean_buy():
    s = snap("BUY", 99.0)
    assert ui.live_check(s)["word"] == "under the line now"
    assert "under the line now" in ui.call_chips(s) and "Live 99.00 is under the exit line 100.00" in ui.call_why(s)
    assert ui.live_check(snap("ADD", 97.0))["word"] == "under the band now"
    assert "daily reason" in ui.call_why(snap("WAIT FOR TURN", 99.0))                   # the original reason is kept after the live line


def test_no_conflict_means_no_change_and_an_exit_that_has_recovered_is_flagged():
    assert ui.live_check(snap("BUY", 103.0)) is None and "now" not in ui.call_chips(snap("BUY", 103.0))
    assert ui.live_check(snap("AVOID", 97.0)) is None and ui.live_check(snap("EXIT", 97.0)) is None      # already consistent
    assert ui.live_check(snap("ON THE LINE", 99.0)) is None
    assert ui.live_check(snap("AVOID", 101.0))["word"] == "back above the line now"


def test_unknown_data_or_a_closed_market_never_overrides():
    assert ui.live_check(snap("BUY", 99.0, state="CLOSED")) is None
    assert ui.live_check(snap("BUY", 99.0, known=False)) is None
    s = snap("BUY", float("nan"))
    assert ui.live_check(s) is None
