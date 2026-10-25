"""The price status in the app: the forced exit call, Telegram, the dashboard and the engine. Synthetic data only."""
import pytest

from stockwatch import status, tradeplan, transitions, ui
from stockwatch.config import Holding
from stockwatch.data import DemoProvider
from stockwatch.engine import evaluate

from test_ci_scan import NOW, PLANS, ev
from test_stockwatch import make_portfolio

LEVELS = {"high": 120.0, "drawdown": -0.2, "sma50": 110.0, "sma200": 100.0, "as_of": "2026-10-22", "close": 96.0,
          "years_of_data": 5.0, "support_low": 98.0, "support_high": 101.0, "exit_below": 98.0, "failure": 94.0,
          "deep_below": 90.0}


@pytest.fixture
def exit_on(monkeypatch):
    """Turn the forced exit on (it is off by default); fixtures run before the test body builds its statuses."""
    monkeypatch.setattr(status, "EXIT_ON_BREAKDOWN", True)


def ps(code, owned=True, floor=True, **kw):
    lv = dict(LEVELS) if floor else {k: v for k, v in LEVELS.items() if k in ("high", "close", "as_of", "years_of_data")}
    action = status._action(code, lv, owned) if floor and code != "unknown" else "No data."
    return {"code": code, "label": status.LABEL[code], "action": action, "why": "The close is below the support zone.",
            "floor_known": floor, "provisional": None, "levels": lv, **kw}


def held(call="HOLD", code=None, **kw):
    e = ev("A", call, **kw)
    if code:
        e.technical = {"price_status": ps(code)}
    return e


def snap_of(e):
    return {"ticker": e.ticker, "tier": e.tier, "verdict": e.verdict, "price": e.price,
            "technical_score": 60, "fundamental_score": 60, "composite": 60,
            "payload": {"plan": e.plan, "watchlist": e.watchlist, "signals": [], "technical": e.technical, "quote": {},
                        "position": {}, "events": {}, "fundamental": {}, "error": None}}


# ---- the rule

@pytest.mark.parametrize("code,watchlist,expected", [
    ("breakdown", False, True), ("deep_breakdown", False, True),
    ("testing_support", False, False), ("weakening", False, False), ("record_high", False, False),
    ("unknown", False, False), ("breakdown", True, False), ("deep_breakdown", True, False)])
def test_only_a_confirmed_breakdown_on_a_held_stock_forces_an_exit(exit_on, code, watchlist, expected):
    assert status.forces_exit(ps(code), watchlist) is expected


def test_no_status_forces_nothing():
    for missing in (None, {}, "breakdown", {"label": "BREAKDOWN"}):
        assert status.forces_exit(missing, False) is False


def test_by_default_a_breakdown_changes_no_call_and_never_says_exit():
    assert status.EXIT_ON_BREAKDOWN is False
    broken = ps("deep_breakdown")
    assert status.forces_exit(broken, False) is False
    assert transitions.effective_stance("HOLD", PLANS["HOLD"], False, broken) == "HOLD"
    state, why = transitions.reading(held("HOLD", "deep_breakdown"), False)
    assert why == "" and state["state"] == "HOLD"
    snap = snap_of(held("HOLD", "breakdown"))
    html = ui.row(snap)
    assert "HOLD" in html and "BREAKDOWN" in html and "SELL" not in html and "Exit" not in html
    assert ui.ring(snap)[0] == 3 and "Exit" not in ui.status_note(snap)
    assert "not reviewed" in ui.status_note(snap)


def test_by_default_the_telegram_message_names_the_status_but_the_call_is_unchanged():
    e = held("HOLD", "breakdown")
    t = {"ticker": "A", "held": True, "from": "TRIM", "from_stance": "TRIM", "from_verdict": "TRIM / REVIEW",
         "to": "HOLD", "to_stance": "HOLD", "to_verdict": "HOLD"}
    msg = transitions.message(t, e, "2026-10-22", NOW)
    assert "Price status: BREAKDOWN (daily close 96.00, 2026-10-22)." in msg and "Exit" not in msg


def test_effective_stance_turns_hold_into_exit_under_a_broken_support(exit_on):
    assert transitions.effective_stance("HOLD", PLANS["HOLD"], False) == "HOLD"                       # unchanged without it
    assert transitions.effective_stance("HOLD", PLANS["HOLD"], False, ps("breakdown")) == "REDUCE / EXIT"
    assert transitions.effective_stance("STRONG HOLD", None, False, ps("deep_breakdown")) == "REDUCE / EXIT"
    assert transitions.effective_stance("OPPORTUNITY - ADD", {"stance": "ADD"}, False, ps("breakdown")) == "REDUCE / EXIT"
    assert transitions.effective_stance("HOLD", PLANS["HOLD"], False, ps("testing_support")) == "HOLD"   # a heads-up only


def test_a_watchlist_name_is_never_told_to_sell(exit_on):
    assert transitions.effective_stance("WATCH", PLANS["WAIT"], True, ps("breakdown", owned=False)) == "WAIT FOR CONFIRMATION"
    assert transitions.effective_stance("AVOID", {"stance": "NO TRADE"}, True, ps("deep_breakdown", owned=False)) == "NO TRADE"


# ---- Telegram

def test_a_broken_support_is_a_valid_sell_reading_not_a_disagreement(exit_on):
    assert transitions.reading(held("HOLD"), False)[0]["state"] == "HOLD"
    state, why = transitions.reading(held("HOLD", "breakdown"), False)
    assert why == "" and state["state"] == "SELL" and state["stance"] == "REDUCE / EXIT"
    state, why = transitions.reading(held("HOLD", "deep_breakdown", verdict="STRONG HOLD"), False)
    assert why == "" and state["state"] == "SELL"


def test_the_old_guard_still_blocks_a_sell_that_nothing_justifies(exit_on):
    e = held("TRIM", verdict="STRONG HOLD")                                         # a trim plan on a strong hold: still refused
    assert transitions.reading(e, False) == (None, "verdict and plan disagree")
    e = held("TRIM", "testing_support", verdict="STRONG HOLD")                      # a heads-up is not a forced exit
    assert transitions.reading(e, False) == (None, "verdict and plan disagree")


def test_hold_to_exit_is_sent_after_two_runs_with_the_status_and_the_exit_line(exit_on):
    entries, _, _ = transitions.step({}, {"A": transitions.reading(held("HOLD"), False)[0]}, "t0")
    broken = held("HOLD", "breakdown")
    for _ in range(2):
        entries, ready, _ = transitions.step(entries, {"A": transitions.reading(broken, False)[0]}, "t1")
    assert [(t["from"], t["to"]) for t in ready] == [("HOLD", "SELL")]
    msg = transitions.message(ready[0], broken, "2026-10-22", NOW)
    assert msg.startswith("🔴 A (held): HOLD → SELL")
    assert "Exit the trade: closed below support (98.00)." in msg
    assert "Price status: BREAKDOWN (daily close 96.00, 2026-10-22)." in msg
    assert "If you keep part" not in msg


def test_a_heads_up_message_names_the_status_without_changing_the_call():
    e = held("HOLD", "testing_support")
    t = {"ticker": "A", "held": True, "from": "TRIM", "from_stance": "TRIM", "from_verdict": "TRIM / REVIEW",
         "to": "HOLD", "to_stance": "HOLD", "to_verdict": "HOLD"}
    msg = transitions.message(t, e, "2026-10-22", NOW)
    assert msg.split("\n")[0].endswith("SELL SOME → HOLD")                       # the call is still the plan's
    assert "Price status: TESTING SUPPORT (daily close 96.00, 2026-10-22)." in msg
    assert "Exit the trade" not in msg and "Exit now" not in msg


def test_no_status_line_for_healthy_or_unknown_statuses():
    for code in ("record_high", "pullback", "unknown"):
        e = held("HOLD", code)
        t = {"ticker": "A", "held": True, "from": "TRIM", "from_stance": "TRIM", "from_verdict": "TRIM / REVIEW",
             "to": "HOLD", "to_stance": "HOLD", "to_verdict": "HOLD"}
        assert "Price status" not in transitions.message(t, e, "2026-10-22", NOW)


# ---- the dashboard

def test_the_dashboard_call_matches_telegram_under_a_broken_support(exit_on):
    e = held("HOLD", "breakdown")
    assert ui._action(snap_of(e))[0] == ui.ACTIONS[transitions.effective_stance(
        e.verdict, e.plan, e.watchlist, e.technical["price_status"])][0] == "SELL"
    assert ui.action(snap_of(e))[0] in ("SELL", "REASSESS")                          # REASSESS only on a hard rebound


def test_a_broken_support_is_act_now_on_the_radar(exit_on):
    r, why = ui.ring(snap_of(held("HOLD", "deep_breakdown")))
    assert r == 1 and "support broke" in why
    assert ui.ring(snap_of(held("HOLD", "testing_support")))[0] == 3                  # a heads-up isn't act-now


def test_the_list_row_shows_the_status_chip_and_the_exit_call(exit_on):
    html = ui.row(snap_of(held("HOLD", "breakdown")))
    assert "BREAKDOWN" in html and "SELL" in html and "✕" in html
    assert "RECORD HIGH" in ui.row(snap_of(held("HOLD", "record_high")))


def test_unknown_stays_off_the_list_but_details_says_why():
    e = held("HOLD")
    e.technical = {"price_status": status._unknown("Only 120 daily bars; the 200-day average needs 200.")}
    s = snap_of(e)
    assert ui.status_chip(s) == "" and "NO READ" not in ui.row(s)
    note = ui.status_note(s)
    assert "NO READ" in note and "Only 120 daily bars" in note and "Exit" not in note


def test_details_statement_has_the_action_the_levels_and_the_provisional_note(exit_on):
    e = held("HOLD", "breakdown")
    e.technical["price_status"]["provisional"] = {"code": "deep_breakdown", "label": "DEEP BREAKDOWN", "price": 88.0,
                                                  "note": "The live price 88.00 reads DEEP BREAKDOWN. It is confirmed only if a session closes there."}
    note = ui.status_note(snap_of(e))
    assert "BREAKDOWN" in note and "Exit the trade" in note
    assert "Support 98.00 to 101.00" in note and "exit below 98.00" in note and "deeper level 90.00" in note
    assert "only if a session closes there" in note and "Automatic levels, not reviewed" in note


def test_a_snapshot_saved_before_the_status_existed_renders_without_it():
    e = held("HOLD")
    s = snap_of(e)
    assert ui.price_status(s) is None and ui.status_chip(s) == "" and ui.status_note(s) == ""
    assert ui._action(s)[0] == "HOLD" and "SELL" not in ui.row(s)
    s["payload"].pop("technical")
    assert ui.status_note(s) == "" and ui.row(s)


def test_a_watchlist_name_under_a_broken_support_shows_no_exit():
    e = ev("W", "WAIT", held=False)
    e.technical = {"price_status": ps("breakdown", owned=False)}
    s = snap_of(e)
    assert ui._action(s)[0] != "SELL"
    note = ui.status_note(s)
    assert "Not a buy until it recovers" in note and "Exit the trade" not in note
    assert "support broke" not in ui.ring(s)[1]


# ---- the engine

def test_the_engine_stores_the_status_with_the_technical_data():
    e = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    p = e.technical["price_status"]
    assert isinstance(p, dict) and p["code"] in status.ORDER + ("unknown",) and p["label"]
    assert e.error is None


def test_a_watchlist_name_is_assessed_with_watchlist_wording():
    e = evaluate(Holding("AAA", 2, 0.0), make_portfolio(), DemoProvider())
    p = e.technical["price_status"]
    assert "Exit the trade" not in p["action"] and "Exit now" not in p["action"]


def test_a_failing_status_never_fails_the_evaluation(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("status exploded")
    monkeypatch.setattr(status, "assess", boom)
    e = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    assert e.error is None and e.technical["price_status"] is None and e.verdict != "ERROR"


# ---- the plan follows the call (only when the switch is on)

def plan_of(call="HOLD"):
    return dict(PLANS[call], bias="bullish", sma20=98.0, rr=2.0, outlook="Steady.", exits=["Stop: sell if it closes below 90.00."],
                notes=[], horizon="x", entry=96.0, risk_per_share=6.0, price=100.0)


def test_the_plan_is_untouched_while_the_switch_is_off():
    plan = plan_of()
    assert tradeplan.exit_on_breakdown(plan, ps("breakdown"), False) is plan


def test_a_broken_support_turns_the_plan_into_the_exit_plan(exit_on):
    plan = plan_of("TRIM")
    out = tradeplan.exit_on_breakdown(plan, ps("breakdown"), False)
    assert out is not plan and plan["stance"] == "TRIM"                         # the original is not mutated
    assert out["stance"] == "REDUCE / EXIT" and out["bias"] == "bearish"
    assert tradeplan.summary(out) == "exit · closed below support 98.00"
    assert out["exits"][0] == "Exit the trade: closed below support (98.00)."
    assert "deeper level, 90.00" in out["exits"][1] and "101.00" in out["exits"][2]
    assert out["notes"][-1].startswith("Automatic support levels, not reviewed")
    assert "Support broke" in out["outlook"]
    deep = tradeplan.exit_on_breakdown(plan, ps("deep_breakdown"), False)
    assert tradeplan.summary(deep) == "exit now · below the deeper level 90.00"
    assert deep["exits"][0].startswith("Exit now") and "already broken" in deep["exits"][1]


def test_the_exit_plan_leaves_other_plans_and_cases_alone(exit_on):
    plan = plan_of()
    assert tradeplan.exit_on_breakdown(plan, ps("breakdown"), True) is plan             # a watchlist name
    assert tradeplan.exit_on_breakdown(plan, ps("testing_support"), False) is plan      # a heads-up only
    assert tradeplan.exit_on_breakdown(plan, None, False) is plan
    assert tradeplan.exit_on_breakdown(None, ps("breakdown"), False) is None
    already = plan_of("HOLD")
    already["stance"] = "REDUCE / EXIT"
    assert tradeplan.exit_on_breakdown(already, ps("deep_breakdown"), False) is already  # its own exit plan stands


def test_call_plan_and_chip_agree_on_the_row_when_the_switch_is_on(exit_on):
    e = held("TRIM", "breakdown")
    e.plan = tradeplan.exit_on_breakdown(e.plan, e.technical["price_status"], False)
    html = ui.row(snap_of(e))
    assert "SELL" in html and "BREAKDOWN" in html
    assert "exit · closed below support 98.00" in html and "trim" not in html.split('class="pl"')[1].lower()


def test_the_engine_makes_a_broken_support_an_exit_plan_when_the_switch_is_on(exit_on, monkeypatch):
    monkeypatch.setattr(status, "assess", lambda *a, **k: ps("breakdown"))
    e = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    assert e.technical["price_status"]["code"] == "breakdown" and e.plan["stance"] == "REDUCE / EXIT"
    assert e.plan["status_exit"] and transitions.effective_stance(e.verdict, e.plan, e.watchlist,
                                                                  e.technical["price_status"]) == "REDUCE / EXIT"


def test_the_engine_leaves_the_plan_alone_while_the_switch_is_off(monkeypatch):
    monkeypatch.setattr(status, "assess", lambda *a, **k: ps("breakdown"))
    e = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    assert e.plan.get("status_exit") is None                                   # no exit plan was built from the status
    assert e.technical["price_status"]["code"] == "breakdown"                  # but the status is still recorded


# ---- a confirmed breakdown never sits under "buy more" (always on, independent of the exit switch)

ADD_PLAN = dict(plan_of("NOW"), stance="ADD")


@pytest.mark.parametrize("code,blocks", [("breakdown", True), ("deep_breakdown", True), ("testing_support", True),
                                         ("weakening", True), ("record_high", False), ("unknown", False)])
def test_a_breakdown_or_a_bad_chart_blocks_buying(code, blocks):
    assert status.blocks_buy(ps(code)) is blocks
    assert status.blocks_buy(None) is False and status.blocks_buy({}) is False


@pytest.mark.parametrize("stance", ["ADD", "BUY NOW", "BUY ON PULLBACK", "BUY THE BREAKOUT"])
def test_a_buy_over_a_breakdown_becomes_hold_or_wait(stance):
    plan = dict(ADD_PLAN, stance=stance)
    held_out = tradeplan.hold_off_buying(plan, ps("breakdown"), False)
    assert plan["stance"] == stance and held_out["stance"] == "HOLD"           # the original is not mutated
    assert tradeplan.summary(held_out) == "don't add yet · closed below support 98.00"
    assert "101.00" in held_out["trigger"] and "adding is on hold" in held_out["notes"][-1]
    assert tradeplan.hold_off_buying(plan, ps("deep_breakdown"), True)["stance"] == "WAIT FOR CONFIRMATION"


def test_testing_support_no_longer_keeps_the_buy_entry_gates_owner_2026_10_25():
    held = tradeplan.hold_off_buying(ADD_PLAN, ps("testing_support"), False)
    assert held["stance"] == "HOLD" and "testing support" in held["status_exit"] and "Buy held back" in held["notes"][-1]
    assert transitions.effective_stance("OPPORTUNITY - ADD", ADD_PLAN, False, ps("testing_support")) == "HOLD"
    assert tradeplan.hold_off_buying(ADD_PLAN, ps("testing_support"), True)["stance"] == "WAIT FOR CONFIRMATION"


def test_each_entry_gate_blocks_and_a_missing_read_never_does():
    good = ps("strong_uptrend")
    assert status.entry_blockers(good, {"momentum": {"known": True, "momentum": "strong"}}) == []
    assert status.entry_blockers(good, {"momentum": {"known": True, "momentum": "falling"}}) == ["momentum is falling"]
    assert status.entry_blockers(good, {"momentum": {"known": False}}) == []                  # not read: unknown, not a no
    assert status.entry_blockers(good, None) == []
    assert status.entry_blockers({**good, "second": {"source": "TradingView", "signal": "sell"}}) == ["TradingView says SELL"]
    assert status.entry_blockers({**good, "second": {"source": "TradingView", "unavailable": "x"}}) == []
    assert status.entry_blockers({**good, "pricecheck": {"agrees": False}}) == ["the price data from another source disagrees"]
    assert status.entry_blockers({**good, "pricecheck": {"unavailable": "x", "agrees": False}}) == []
    assert status.entry_blockers(None) == []
    mom = {"momentum": {"known": True, "momentum": "falling"}}
    assert tradeplan.hold_off_buying(ADD_PLAN, good, False, mom)["stance"] == "HOLD"
    assert transitions.effective_stance("OPPORTUNITY - ADD", ADD_PLAN, False, good, mom) == "HOLD"
    assert transitions.effective_stance("OPPORTUNITY - ADD", ADD_PLAN, False, good, {}) == "ADD"


def test_other_plans_are_left_alone():
    for plan in (plan_of("HOLD"), plan_of("TRIM"), None):
        assert tradeplan.hold_off_buying(plan, ps("breakdown"), False) is plan
    assert tradeplan.hold_off_buying(ADD_PLAN, None, False) is ADD_PLAN


def test_effective_stance_never_says_buy_over_a_breakdown():
    for stance in ("ADD", "BUY NOW", "BUY ON PULLBACK", "BUY THE BREAKOUT"):
        plan = dict(ADD_PLAN, stance=stance)
        assert transitions.effective_stance("OPPORTUNITY - ADD", plan, False, ps("breakdown")) == "HOLD"
        assert transitions.effective_stance("BUY SETUP", plan, True, ps("breakdown")) == "WAIT FOR CONFIRMATION"


def test_the_row_shows_hold_and_breakdown_not_buy_more_and_breakdown():
    e = ev("HOOD", "NOW")
    e.technical = {"price_status": ps("breakdown")}
    e.plan = tradeplan.hold_off_buying(dict(ADD_PLAN), e.technical["price_status"], False)
    html = ui.row(snap_of(e))
    assert "BREAKDOWN" in html and "BUY MORE" not in html and "in the entry zone now" not in html
    assert "add yet" in html and "closed below support 98.00" in html
    plain = ev("HOOD", "NOW")
    plain.technical = {"price_status": ps("testing_support")}
    plain.plan = dict(ADD_PLAN)
    assert "BUY MORE" not in ui.row(snap_of(plain)) and "TESTING SUPPORT" in ui.row(snap_of(plain))


def test_telegram_sees_hold_not_buy_when_support_has_broken():
    e = ev("HOOD", "NOW")
    e.verdict, e.plan = "OPPORTUNITY - ADD", dict(ADD_PLAN)
    e.technical = {"price_status": ps("breakdown")}
    state, why = transitions.reading(e, False)
    assert state["state"] == "HOLD" and state["stance"] == "HOLD", why


def test_the_engine_holds_off_buying_over_a_breakdown(monkeypatch):
    monkeypatch.setattr(status, "assess", lambda *a, **k: ps("breakdown"))
    e = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    stance = transitions.effective_stance(e.verdict, e.plan, e.watchlist, e.technical["price_status"])
    assert stance not in status.BUY_STANCES
