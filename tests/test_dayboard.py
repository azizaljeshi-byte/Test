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


def test_zones_show_reasons_and_say_why_when_unknown():
    z = {"known": True, "close": 100.0, "as_of": "2026-10-22",
         "support": [{"low": 90.0, "high": 91.0, "grade": "HIGH", "touches": 4, "age_days": 10, "points": 5,
                      "reasons": ["4 touches", "200-day average"]}],
         "resistance": [{"low": 110.0, "high": 111.0, "grade": "LOW", "touches": 1, "age_days": 500, "points": 0,
                         "reasons": ["1 touch", "17 months old"]}]}
    html = dayboard.zones_html(make("HOLD", "pullback", zones=z), 100.0)
    assert "200-day average" in html and "17 months old" in html and "Weak: the price may pass through" in html
    unk = dayboard.zones_html(make("HOLD", "pullback", zones={"known": False, "why": "Only 50 daily bars", "support": [], "resistance": []}), 100.0)
    assert "No read" in unk and "Only 50 daily bars" in unk


def test_old_names_are_not_replaced_underneath():
    assert status.EXIT_ON_BREAKDOWN is False       # the board only re-presents; the ladder and calls are untouched


# ---- the card list and the map

def board_set():
    bad = make("TRIM", "breakdown", mom="falling", second={"source": "TradingView", "signal": "sell"}, rs=-0.15)
    good = make("HOLD", "strong_uptrend", mom="strong", rs=0.2)
    bad["ticker"], good["ticker"] = "BADX", "GOODX"
    return [bad, good]


def test_every_stock_has_a_tinted_row_and_a_dot_that_jumps_to_it():
    html = dayboard.render(board_set())
    assert html.count('class="rd-row') == 2
    assert 'id="c-BADX"' in html and 'href="#c-GOODX"' in html and 'href="?view=target&t=BADX"' in html
    assert "dz-act" in html and "dz-calm" in html


def test_the_map_places_a_stock_by_its_gauge_and_counts_the_ones_it_cannot_place():
    broken = make("HOLD")
    broken["payload"]["error"] = "boom"
    html = dayboard.dot_map([broken] + board_set())
    assert html.count('class="rd-dot') == 2 and "1 not placed" in html


def test_the_map_names_are_off_until_a_filter_is_picked():
    css = dayboard.CSS
    assert "#rdf-act:checked~.rd-scroll .rd-dot.dz-act span{display:block}" in css or "#rdf-act:checked~.rd-scroll .rd-dot.dz-act span" in css
    assert ".rd-dot span{display:none" in css and "prefers-reduced-motion" in css


def test_the_card_shows_ratings_and_plain_english_zones_without_the_old_grades():
    z = {"known": True, "close": 100.0, "as_of": "2026-10-22",
         "support": [{"low": 90.0, "high": 91.0, "grade": "HIGH", "touches": 4, "age_days": 10, "points": 5, "reasons": ["4 touches"]}],
         "resistance": []}
    html = dayboard.card(make("HOLD", "pullback", zones=z))
    assert "Fundamentals" in html and "Technical" in html and "Likely to hold: a good place to buy" in html
    assert ">HIGH<" not in html and ">LOW<" not in html


def test_last_quarter_is_beat_miss_or_in_line_and_unknown_says_nothing():
    s = make("HOLD", "pullback")
    def q(act, est):
        s["payload"]["research"] = {"earnings": {"quarters": [{"quarter": "2026-09-30", "eps_actual": act, "eps_estimate": est}]}}
        return dayboard.last_quarter(s)
    assert "BEAT" in q(1.10, 1.00) and "MISS" in q(0.90, 1.00) and "IN LINE" in q(1.01, 1.00)
    assert q(None, 1.0) == "" and q(1.0, 0) == ""


def test_the_next_report_line_says_when_the_date_is_an_estimate():
    s = make("HOLD", "pullback")
    s["payload"]["events"] = {"days_to_earnings": 9, "earnings_estimated": True}
    assert "in 9 days" in dayboard.next_report(s) and "estimated" in dayboard.next_report(s)
    s["payload"]["events"] = {}
    assert dayboard.next_report(s) == ""


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


def test_two_stocks_reporting_the_same_day_do_not_break_the_coming_up_list():
    a, b = make("HOLD", "pullback"), make("HOLD", "pullback")
    a["ticker"], b["ticker"] = "AAA", "BBB"
    for s in (a, b):
        s["payload"]["events"] = {"days_to_earnings": 4}
    html = dayboard.events_calendar([a, b])
    assert "AAA" in html and "BBB" in html


def test_the_bell_shows_only_when_earnings_are_within_a_week():
    s = make("HOLD", "pullback")
    s["payload"]["events"] = {"days_to_earnings": 5}
    assert "dz-bell" in dayboard.card(s)
    s["payload"]["events"] = {"days_to_earnings": 12}
    assert "dz-bell" not in dayboard.card(s)
    s["payload"]["events"] = {}
    assert "dz-bell" not in dayboard.card(s)


def test_the_card_shows_the_after_hours_price_or_that_there_were_no_trades():
    s = make("HOLD", "pullback")
    s["payload"]["quote"] = {"market_state": "POST", "ext_price": 101.5, "ext_change": 0.015, "ext_session": "post"}
    html = dayboard.card(s)
    assert "AH" in html and "101.50" in html
    s["payload"]["quote"] = {"market_state": "POST", "ext_price": float("nan")}
    assert "AH no trades yet" in dayboard.card(s)


def test_today_card_rows_and_chips():
    lines = ["Market backdrop is supportive (risk-on).", "Needs attention now: DIS, GLW.", "In a buy zone: AAPL.",
             "Reporting this week: GLW (3d), NVDA (5d).", "Big out-of-hours moves: TSLA -4.2% AH, AMD +3.1% pre.",
             "Strongest: AAPL, MSFT. Weakest: DIS, GLW.", "Something new."]
    html = dayboard.today_card(lines, ["DIS"], "Friday 23 Oct")
    assert 'class="rd-today"' in html and "Friday 23 Oct" in html
    assert html.count('class="rd-bc act"') == 2 and html.count('class="rd-bc buy"') == 3
    assert "view=target&t=GLW" in html and "<small>3d</small>" in html
    assert 'class="rd-bc dn"' in html and "-4.2% AH" in html and "Note" in html
    assert dayboard.today_card([], [], "") == ""
