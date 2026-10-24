"""The Day Board Radar (stockwatch/dayboard.py): one word per stock, a gauge that never contradicts the call, and a count of
agreeing checks. Synthetic snapshots only."""

from stockwatch import dayboard, status

from test_ci_scan import ev
from test_status_wiring import ps, snap_of


def make(call, code=None, held=True, mom=None, second=None, pricecheck=None, rs=None, zones=None, **kw):
    e = ev("A", call, held=held, **kw)
    tech = {}
    if code:
        p = ps(code)
        if second is not None:
            p["second"] = second
        if pricecheck is not None:
            p["pricecheck"] = pricecheck
        tech["price_status"] = p
    if mom:
        tech["momentum"] = {"known": True, "momentum": mom, "momentum_label": mom.upper(), "cause": "drift",
                            "cause_label": "stock-specific drift", "also": [], "facts": {}}
    if rs is not None:
        tech["rs_spy_3m"] = rs
    if zones is not None:
        tech["zones"] = zones
    e.technical = tech
    s = snap_of(e)
    return s


def test_a_sell_call_with_a_risk_signal_is_act_and_a_calm_hold_is_calm():
    assert dayboard.word(make("TRIM", "breakdown")) == "ACT"
    assert dayboard.word(make("HOLD", "strong_uptrend")) == "CALM"


def test_a_buy_now_in_the_entry_zone_is_buy_and_an_error_is_unclear():
    assert dayboard.word(make("NOW", "pullback")) == "BUY"
    broken = make("HOLD")
    broken["payload"]["error"] = "boom"
    assert dayboard.word(broken) == "UNCLEAR"
    assert "boom" in dayboard.assess(broken)["why"] and dayboard.assess(broken)["gauge"] is None


def test_checks_agreeing_with_a_sell_give_a_bad_gauge_and_a_count():
    s = make("TRIM", "breakdown", mom="falling", second={"source": "TradingView", "signal": "sell"},
             pricecheck={"source": "Stooq", "agrees": True, "verdict": "matches", "note": "ok"}, rs=-0.15)
    a = dayboard.assess(s)
    assert a["word"] == "ACT" and a["gauge"] in (0, 1) and a["gauge_label"] in ("BAD", "WEAK")
    agree, known = a["sure"]
    assert known == 6 and agree >= 5 and a["grade"] == "HIGH"
    assert "closes back above 101.00" in a["change"]


def test_unknown_is_not_counted_as_a_no():
    s = make("TRIM", "breakdown", mom="falling")        # no second opinion, no price check, no market read
    a = dayboard.assess(s)
    assert a["sure"] == (2, 3)                        # structure and momentum agree; signals are neutral; the unread ones are left out
    assert any(c["state"] is None for c in a["checks"])


def test_too_few_readable_checks_shows_no_gauge_and_says_why():
    e = ev("HOLD", "HOLD")
    e.technical = {}
    a = dayboard.assess(snap_of(e))
    assert a["gauge"] is None and "checks could be read" in a["why"]


def test_a_gauge_pointing_the_other_way_from_the_call_shows_unclear_not_two_answers():
    s = make("NOW", "strong_uptrend", mom="strong", second={"source": "TradingView", "signal": "buy"}, rs=0.2)
    assert dayboard.assess(s)["gauge"] in (3, 4)
    bad = make("NOW", "pullback", mom="falling", second={"source": "TradingView", "signal": "sell"}, rs=-0.2)
    a = dayboard.assess(bad)
    assert a["word"] == "BUY" and a["gauge"] is None and "other way" in a["why"]
    assert dayboard.word(make("NOW", "breakdown")) != "BUY"        # a confirmed breakdown already stops a buy call


def test_a_price_feed_mismatch_counts_against_the_call():
    s = make("TRIM", "breakdown", mom="falling", second={"source": "TradingView", "signal": "sell"},
             pricecheck={"source": "Stooq", "agrees": False, "verdict": "differs", "note": "x"}, rs=-0.1)
    a = dayboard.assess(s)
    assert a["sure"][0] < a["sure"][1]


def test_render_groups_stocks_and_escapes_text():
    risky = make("TRIM", "breakdown", mom="falling")
    calm = make("HOLD", "strong_uptrend")
    html = dayboard.render([risky, calm])
    assert "Needs you today" in html or "Getting close" in html
    assert "All calm" in html and "Quick key" in html and "<details" in html
    assert "?view=target&t=A" in html


def test_zones_are_shown_with_grades_and_reasons_and_say_why_when_unknown():
    z = {"known": True, "close": 100.0, "as_of": "2026-10-22",
         "support": [{"low": 90.0, "high": 91.0, "grade": "HIGH", "touches": 4, "age_days": 10, "points": 5,
                      "reasons": ["4 touches", "200-day average"]}],
         "resistance": [{"low": 110.0, "high": 111.0, "grade": "LOW", "touches": 1, "age_days": 500, "points": 0,
                         "reasons": ["1 touch", "17 months old"]}]}
    html = dayboard.zones_html(make("HOLD", "pullback", zones=z), 100.0)
    assert "HIGH" in html and "200-day average" in html and "LOW" in html and "17 months old" in html
    unk = dayboard.zones_html(make("HOLD", "pullback", zones={"known": False, "why": "Only 50 daily bars", "support": [], "resistance": []}), 100.0)
    assert "No read" in unk and "Only 50 daily bars" in unk


def test_old_names_are_not_replaced_underneath():
    assert status.EXIT_ON_BREAKDOWN is False       # the board only re-presents; the ladder and calls are untouched


# ---- the gauge board

def board_set():
    bad = make("TRIM", "breakdown", mom="falling", second={"source": "TradingView", "signal": "sell"}, rs=-0.15)
    good = make("HOLD", "strong_uptrend", mom="strong", rs=0.2)
    bad["ticker"], good["ticker"] = "BADX", "GOODX"
    return [bad, good]


def test_every_stock_sits_under_one_step_and_is_tappable():
    html = dayboard.board(board_set())
    assert html.count('class="gchip') == 2
    assert "BADX" in html and "GOODX" in html and 'for="dbp-BADX"' in html and 'id="dbp-GOODX"' in html
    assert 'href="?view=target&t=BADX"' in html and "checked" not in html.replace(":checked", "")


def test_the_dial_reads_the_owned_holdings():
    third = make("HOLD", "pullback", mom="building", rs=0.0)
    third["ticker"] = "MIDX"
    watch = make("HOLD", "strong_uptrend", mom="strong", rs=0.3, held=False)
    watch["ticker"] = "WATCHX"
    items = [(s, dayboard.assess(s)) for s in board_set() + [third, watch]]
    mean, read = dayboard.portfolio_read(items)
    assert mean is not None and read in dayboard.STEPS
    own_only = [(s, a) for s, a in items if not s["payload"]["watchlist"]]
    assert dayboard.portfolio_read(own_only) == (mean, read)           # a watchlist name never moves the needle


def test_too_few_readable_stocks_says_unclear_and_draws_no_needle():
    e = ev("HOLD", "HOLD")
    e.technical = {}
    html = dayboard.board([snap_of(e)])
    assert "UNCLEAR" in html and "gneedle" not in html


def test_the_unclear_row_lists_stocks_with_no_gauge():
    broken = make("HOLD")
    broken["payload"]["error"] = "boom"
    html = dayboard.board([broken] + board_set())
    assert "UNCLEAR · 1" in html


def test_motion_respects_reduced_motion():
    assert "prefers-reduced-motion" in dayboard.CSS


def test_headline_counts_and_plurals():
    assert "1 needs you" in dayboard.headline(1, 1, 1) and "1 is close" in dayboard.headline(1, 1, 1)
    assert "3 need you" in dayboard.headline(3, 2, 0) and "0 are calm" in dayboard.headline(3, 2, 0)


# ---- stage 1 fixes: say why a check was skipped, and a held sell reads as one answer

def test_a_skipped_check_says_why(monkeypatch):
    s = make("TRIM", "breakdown", pricecheck={"source": "Stooq", "unavailable": "Stooq could not be reached"},
             second={"source": "TradingView", "unavailable": "TradingView could not be reached"})
    texts = {c["text"] for c in dayboard.assess(s)["checks"]}
    assert "Price data skipped: Stooq could not be reached" in texts
    assert "TradingView: no read (TradingView could not be reached)" in texts
    quiet = make("TRIM", "breakdown")                    # no price check was asked for
    assert any("only asked for stocks that are falling" in c["text"] for c in dayboard.assess(quiet)["checks"])


def _held(monkeypatch, trail=0.33):
    s = make("TRIM", "breakdown", mom="falling", second={"source": "TradingView", "signal": "sell"},
             pricecheck={"source": "Stooq", "agrees": True, "verdict": "matches", "note": "ok"}, rs=-0.15)
    s["payload"]["technical"]["trailing_stop"] = trail
    s["payload"]["signals"] = [{"kind": "risk", "severity": 3, "code": "atr_trailing_stop", "message": "below the stop"}]
    monkeypatch.setattr(dayboard.ui, "reassess", lambda snap: "Up 3.2% in the last session. Re-check at the next close.")
    return s


def test_a_sell_waiting_for_the_close_is_scored_as_a_sell_and_names_its_level(monkeypatch):
    s = _held(monkeypatch)
    a = dayboard.assess(s)
    assert a["word"] == "WATCH" and a["sell_side"] is True
    assert dayboard.held_sell(s) == 0.33
    assert a["sure"] is not None and a["sure"][0] >= 5          # the checks that point to selling now count as agreeing
    assert "WATCH · SELL BELOW 0.33" in dayboard.card(s)


def test_a_watch_that_is_not_a_held_sell_is_unchanged(monkeypatch):
    s = make("HOLD", "testing_support", mom="falling")
    assert dayboard.held_sell(s) is False
    a = dayboard.assess(s)
    assert a["sell_side"] is False and a["sure"] is None
