"""Telegram messages when a stock's price status changes. Offline, synthetic data, fake Telegram."""
import re

import pytest

from stockwatch import alert_state, notify, status, transitions

from test_ci_scan import (CHAT, NOW, TOKEN, FakeTelegram, Fleet, clean_env, configure, ev, http_error)
from test_status_wiring import ps


_AUTOUSE = clean_env      # imported so its autouse fixture also applies to this file


def sev(ticker, code, held=True, **kw):
    """A scripted evaluation carrying a price status (no status when code is None)."""
    e = ev(ticker, "HOLD" if held else "WAIT", held=held, **kw)
    e.technical = {"price_status": ps(code, owned=held)} if code else {}
    return e


def cur(code, held=True):
    return {"code": code, "held": held}


# ---- the change rules

def test_first_sight_is_a_baseline_a_change_needs_two_runs_and_flipping_back_cancels():
    st, ready, c = transitions.step_status({}, {"A": cur("record_high")}, "t0")
    assert not ready and c["baseline"] == 1 and st["A"]["code"] == "record_high"
    st, ready, c = transitions.step_status(st, {"A": cur("breakdown")}, "t1")
    assert not ready and c["pending"] == 1 and st["A"]["code"] == "record_high"      # seen once: nothing yet
    st, ready, _ = transitions.step_status(st, {"A": cur("record_high")}, "t2")
    assert not ready and st["A"]["pending"] is None                                  # flipped back: cancelled
    for _ in range(3):                                                               # alternating never confirms
        st, ready, _ = transitions.step_status(st, {"A": cur("breakdown")}, "t")
        assert not ready
        st, ready, _ = transitions.step_status(st, {"A": cur("record_high")}, "t")
    st, _, _ = transitions.step_status(st, {"A": cur("breakdown")}, "t3")
    st, ready, _ = transitions.step_status(st, {"A": cur("breakdown")}, "t4")
    assert ready == [{"ticker": "A", "held": True, "from": "record_high", "to": "breakdown", "first_seen": "t3"}]


def test_every_move_counts_up_down_and_sideways():
    for a, b in [("record_high", "strong_uptrend"), ("pullback", "weakening"), ("weakening", "testing_support"),
                 ("testing_support", "breakdown"), ("breakdown", "deep_breakdown"), ("deep_breakdown", "weakening"),
                 ("breakdown", "record_high")]:
        st, _, _ = transitions.step_status({}, {"A": cur(a)}, "t0")
        st, _, _ = transitions.step_status(st, {"A": cur(b)}, "t1")
        st, ready, _ = transitions.step_status(st, {"A": cur(b)}, "t2")
        assert [(t["from"], t["to"]) for t in ready] == [(a, b)]


def test_no_reading_neither_confirms_nor_cancels_and_a_failed_send_is_offered_again():
    st, _, _ = transitions.step_status({}, {"A": cur("pullback")}, "t0")
    st, _, _ = transitions.step_status(st, {"A": cur("weakening")}, "t1")
    st, ready, c = transitions.step_status(st, {"A": None}, "t2")                    # an outage in between
    assert not ready and c["skipped"] == 1 and st["A"]["pending"]["count"] == 1
    st, ready, _ = transitions.step_status(st, {"A": cur("weakening")}, "t3")
    assert len(ready) == 1                                                           # the send fails: not recorded...
    st, ready, _ = transitions.step_status(st, {"A": cur("weakening")}, "t4")
    assert len(ready) == 1 and ready[0]["first_seen"] == "t1"                        # ...so it is offered again
    transitions.status_delivered(st, ready[0], "t5")
    st, ready, c = transitions.step_status(st, {"A": cur("weakening")}, "t6")
    assert not ready and c["unchanged"] == 1 and st["A"]["code"] == "weakening"


def test_a_stock_that_leaves_the_list_is_forgotten_and_comes_back_as_a_baseline():
    st, _, _ = transitions.step_status({}, {"A": cur("pullback"), "B": cur("pullback")}, "t0")
    st, _, c = transitions.step_status(st, {"B": cur("pullback")}, "t1")
    assert c["removed"] == 1 and "A" not in st
    st, ready, c = transitions.step_status(st, {"A": cur("breakdown"), "B": cur("pullback")}, "t2")
    assert not ready and c["baseline"] == 1


@pytest.mark.parametrize("make,expected", [
    (lambda: sev("A", "breakdown"), {"code": "breakdown", "held": True}),
    (lambda: sev("A", "pullback", held=False), {"code": "pullback", "held": False}),
    (lambda: sev("A", "unknown"), None),                         # could not be read: not a status
    (lambda: sev("A", None), None),                              # an older evaluation with no status
    (lambda: sev("A", "breakdown", error="no data"), None),
])
def test_only_a_real_status_is_a_reading(make, expected):
    assert transitions.status_reading(make(), False) == expected


def test_stale_prices_and_the_switch_give_no_reading(monkeypatch):
    assert transitions.status_reading(sev("A", "breakdown"), True) is None
    monkeypatch.setattr(status, "ALERT_ON_CHANGE", False)
    assert transitions.status_reading(sev("A", "breakdown"), False) is None


def test_the_status_memory_rides_in_the_call_memory_without_being_swept_away():
    calls = {"A": {"held": True, "state": "HOLD", "stance": "HOLD", "verdict": "HOLD", "since": "t", "pending": None}}
    memory = transitions.join_state(calls, {"A": {"code": "pullback", "since": "t", "pending": None}})
    c, s = transitions.split_state(memory)
    assert set(c) == {"A"} and s["A"]["code"] == "pullback"
    c, _, counts = transitions.step(c, {"A": None}, "t2")                            # the call step must not touch it
    assert transitions.join_state(c, s)[transitions.STATUS_KEY]["A"]["code"] == "pullback"
    assert transitions.split_state(calls) == (calls, {})                             # a memory from before this existed


# ---- the message

def test_a_worsening_message_has_the_move_the_price_the_meaning_and_the_levels():
    e = sev("A", "breakdown")
    t = {"ticker": "A", "held": True, "from": "testing_support", "to": "breakdown"}
    msg = transitions.status_message(t, e, "2026-10-22", NOW)
    lines = msg.split("\n")
    assert lines[0] == "🔴 A (held): TESTING SUPPORT → BREAKDOWN"
    assert lines[1].startswith("Price 100.00 (Yahoo, regular session, last trade Fri 23 Oct 10:55 New York)")
    assert "Why: The close is below the support zone." in msg
    assert "Closed below support (98.00). Automatic level, not reviewed: check the chart before acting." in msg
    assert "Support 98.00 to 101.00 · exit below 98.00 · deeper level 90.00 · high 120.00 (daily close 96.00, 2026-10-22)." in msg
    assert msg.endswith("Automatic levels, not reviewed. Model levels from StockWatch's rules, not orders or predictions.")
    assert len(msg) < transitions.LIMIT


def test_an_improving_message_and_a_watchlist_message():
    t = {"ticker": "W", "held": False, "from": "weakening", "to": "pullback"}
    msg = transitions.status_message(t, sev("W", "pullback", held=False), "2026-10-22", NOW)
    assert msg.startswith("🔵 W (watchlist): WEAKENING → PULLBACK") and "Not owned: nothing to exit." in msg
    t = {"ticker": "W", "held": False, "from": "pullback", "to": "breakdown"}
    msg = transitions.status_message(t, sev("W", "breakdown", held=False), "2026-10-22", NOW)
    assert "Support is broken. Not a buy until it recovers." in msg and "Exit" not in msg


def test_a_provisional_note_and_a_missing_floor_are_said_plainly():
    e = sev("A", "testing_support")
    e.technical["price_status"]["provisional"] = {"code": "breakdown", "label": "BREAKDOWN", "price": 97.0,
                                                  "note": "The live price 97.00 reads BREAKDOWN. It is confirmed only if a session closes there."}
    t = {"ticker": "A", "held": True, "from": "weakening", "to": "testing_support"}
    assert "confirmed only if a session closes there" in transitions.status_message(t, e, "2026-10-22", NOW)
    e = sev("A", None)
    e.technical = {"price_status": ps("weakening", floor=False)}
    t = {"ticker": "A", "held": True, "from": "pullback", "to": "weakening"}
    msg = transitions.status_message(t, e, "2026-10-22", NOW)
    assert "Support 98.00" not in msg and "Daily close 96.00 (2026-10-22); the high is 120.00." in msg


def test_a_message_never_states_a_status_this_run_did_not_read():
    e = sev("A", "pullback")                                    # the run now reads pullback...
    t = {"ticker": "A", "held": True, "from": "weakening", "to": "breakdown"}   # ...so a breakdown claim has no backing
    msg = transitions.status_message(t, e, "2026-10-22", NOW)
    assert "Closed below support" not in msg and "Why:" not in msg and "Support 98.00" not in msg
    assert msg.startswith("🔴 A (held): WEAKENING → BREAKDOWN")


# ---- whole scan runs

def run_history(fleet, *codes):
    return [fleet.run(sev("HELD", c), sev("WATCH", "pullback", held=False)) for c in codes]


def test_end_to_end_baseline_confirm_send_then_silence(monkeypatch, tmp_path):
    configure(monkeypatch)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    fleet = Fleet(monkeypatch, tmp_path)
    first = fleet.run(sev("HELD", "record_high"), sev("WATCH", "pullback", held=False))
    assert not first.errors and not fake.requests
    assert "2 new baselines" in dict(first.rows)["Status changes"]
    fleet.run(sev("HELD", "breakdown"), sev("WATCH", "pullback", held=False))        # seen once
    assert not fake.requests
    third = fleet.run(sev("HELD", "breakdown"), sev("WATCH", "pullback", held=False))   # confirmed: sent
    assert not third.errors and dict(third.rows)["Delivery"] == "telegram: 1 sent, 0 failed"
    assert dict(third.rows)["Status changes"].startswith("1 confirmed")
    assert [r["text"].split("\n")[0] for r in fake.requests] == ["🔴 HELD (held): RECORD HIGH → BREAKDOWN"]
    fourth = fleet.run(sev("HELD", "breakdown"), sev("WATCH", "pullback", held=False))  # unchanged: silence
    assert len(fake.requests) == 1 and dict(fourth.rows)["Delivery"] == "nothing to send"


def test_improving_alerts_too_and_each_change_is_sent_once(monkeypatch, tmp_path):
    configure(monkeypatch)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    fleet = Fleet(monkeypatch, tmp_path)
    for code in ("breakdown", "breakdown", "breakdown", "weakening", "weakening", "weakening", "weakening"):
        fleet.run(sev("HELD", code), sev("WATCH", "pullback", held=False))
    assert [r["text"].split("\n")[0] for r in fake.requests] == ["🟠 HELD (held): BREAKDOWN → WEAKENING"]


def test_a_failed_send_stays_pending_and_arrives_exactly_once_later(monkeypatch, tmp_path):
    configure(monkeypatch)
    fleet = Fleet(monkeypatch, tmp_path)
    run_history(fleet, "pullback", "weakening")
    monkeypatch.setattr(notify.urllib.request, "urlopen", FakeTelegram(http_error(500, {"description": "Internal"})))
    failed = fleet.run(sev("HELD", "weakening"), sev("WATCH", "pullback", held=False))
    assert any("1 of 1 Telegram message(s) failed" in e for e in failed.errors)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    retried = fleet.run(sev("HELD", "weakening"), sev("WATCH", "pullback", held=False))   # a fresh process: state from disk
    assert len(fake.requests) == 1 and not retried.errors
    fleet.run(sev("HELD", "weakening"), sev("WATCH", "pullback", held=False))
    assert len(fake.requests) == 1


def test_an_outage_or_stale_prices_or_no_status_never_send_a_phantom_change(monkeypatch, tmp_path):
    configure(monkeypatch)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    fleet = Fleet(monkeypatch, tmp_path, stale={"WATCH"})
    fleet.run(sev("HELD", "pullback"), sev("WATCH", "pullback", held=False))
    for _ in range(3):
        report = fleet.run(sev("HELD", "breakdown", error="Yahoo refused"), sev("WATCH", "breakdown", held=False))
    assert not fake.requests and "2 without a status" in dict(report.rows)["Status changes"]
    for _ in range(3):                                          # the status could not be read at all
        fleet.run(sev("HELD", "unknown"), sev("WATCH", None, held=False))
    assert not fake.requests
    assert transitions.split_state(alert_state.load(fleet.state)[0])[1]["HELD"]["code"] == "pullback"


def test_a_memory_saved_before_status_alerts_starts_with_a_silent_baseline(monkeypatch, tmp_path):
    configure(monkeypatch)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    fleet = Fleet(monkeypatch, tmp_path)
    fleet.run(sev("HELD", "breakdown"), sev("WATCH", "breakdown", held=False))
    calls, _ = transitions.split_state(alert_state.load(fleet.state)[0])
    alert_state.save(calls, fleet.state)                                          # the old file shape: no status entry
    report = fleet.run(sev("HELD", "breakdown"), sev("WATCH", "breakdown", held=False))
    assert not fake.requests and "2 new baselines" in dict(report.rows)["Status changes"]


def test_a_call_change_and_a_status_change_in_one_run_send_both_in_order(monkeypatch, tmp_path):
    configure(monkeypatch)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    fleet = Fleet(monkeypatch, tmp_path)
    fleet.run(ev("HELD", "HOLD"), sev("WATCH", "pullback", held=False))
    held_trim = lambda code: (lambda e: (setattr(e, "technical", {"price_status": ps(code)}), e)[1])(ev("HELD", "TRIM"))
    fleet.run(held_trim("pullback"), sev("WATCH", "weakening", held=False))
    report = fleet.run(held_trim("pullback"), sev("WATCH", "weakening", held=False))
    texts = [r["text"].split("\n")[0] for r in fake.requests]
    assert texts == ["🟠 HELD (held): HOLD → SELL SOME", "🟠 WATCH (watchlist): PULLBACK → WEAKENING"]
    assert dict(report.rows)["Delivery"] == "telegram: 2 sent, 0 failed"


def test_the_switch_stops_status_messages_without_touching_call_alerts(monkeypatch, tmp_path):
    monkeypatch.setattr(status, "ALERT_ON_CHANGE", False)
    configure(monkeypatch)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    fleet = Fleet(monkeypatch, tmp_path)
    reports = [fleet.run(sev("HELD", c), sev("WATCH", "pullback", held=False)) for c in ("pullback", "breakdown", "breakdown", "breakdown")]
    assert not fake.requests and "Status changes" not in dict(reports[-1].rows)
    fleet.run(ev("HELD", "HOLD"), ev("WATCH", "WAIT", held=False))
    fleet.run(ev("HELD", "TRIM"), ev("WATCH", "WAIT", held=False))
    fleet.run(ev("HELD", "TRIM"), ev("WATCH", "WAIT", held=False))
    assert [r["text"].split("\n")[0] for r in fake.requests] == ["🟠 HELD (held): HOLD → SELL SOME"]


def test_a_dry_run_counts_status_changes_but_never_sends_or_saves(monkeypatch, tmp_path):
    configure(monkeypatch)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    fleet = Fleet(monkeypatch, tmp_path)
    run_history(fleet, "pullback", "breakdown")
    before = fleet.state.read_bytes()
    dry = fleet.run(sev("HELD", "breakdown"), sev("WATCH", "pullback", held=False), mode="holdings-dry-run")
    assert "1 message(s) would be sent" in dict(dry.rows)["Delivery"] and not fake.requests
    assert fleet.state.read_bytes() == before


def test_status_alerts_without_telegram_stay_pending_and_say_so(monkeypatch, tmp_path):
    configure(monkeypatch, telegram=False)
    fleet = Fleet(monkeypatch, tmp_path)
    run_history(fleet, "pullback", "breakdown")
    report = fleet.run(sev("HELD", "breakdown"), sev("WATCH", "pullback", held=False))
    assert any("Telegram isn't configured" in e for e in report.errors)
    st = transitions.split_state(alert_state.load(fleet.state)[0])[1]
    assert st["HELD"]["code"] == "pullback" and st["HELD"]["pending"]["code"] == "breakdown"


def test_the_public_log_and_the_cached_memory_reveal_no_tickers_or_statuses(monkeypatch, tmp_path):
    configure(monkeypatch)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    fleet = Fleet(monkeypatch, tmp_path)
    reports = run_history(fleet, "record_high", "breakdown", "breakdown")
    public = reports[-1].markdown()
    cached = fleet.state.read_bytes()
    for ticker in ("HELD", "WATCH"):                              # whole words: "STOCKWATCH" is the app's own name
        assert not re.search(rf"\b{ticker}\b", public), ticker
        assert ticker.encode() not in cached, ticker
    for private in ("BREAKDOWN", "RECORD HIGH", "breakdown", "record_high", TOKEN, CHAT):
        assert private not in public, private
        assert private.encode() not in cached, private
    assert "RECORD HIGH → BREAKDOWN" in fake.requests[0]["text"]                  # it reaches Telegram, and only Telegram
