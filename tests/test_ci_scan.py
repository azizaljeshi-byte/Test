"""Scheduled scan, decision-change alerts and Telegram delivery: offline, synthetic data, fake Telegram."""
import io
import json
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml

from stockwatch import alert_state, ci_scan, notify, transitions, ui
from stockwatch.engine import Evaluation
from stockwatch.signals import Signal

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "123456789:" + "A" * 35
CHAT = "987654321"
STATE_KEY = "synthetic-state-key-" + "x" * 30
SECRET_TICKER, SECRET_SHARES, SECRET_COST = "QWXYZ", "4321.5", "876.54"
PORTFOLIO = (f"holdings:\n  - {{ticker: {SECRET_TICKER}, tier: 1, shares: {SECRET_SHARES}, cost_basis: {SECRET_COST}}}\n"
             "  - {ticker: BBB, tier: 2}\n")
NOW = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)      # Fri 11:00 New York, 18:00 Riyadh


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("STOCKWATCH_PORTFOLIO", "STOCKWATCH_SHEET_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                "NTFY_TOPIC", "SMTP_HOST", "ALERT_EMAIL_TO", "STOCKWATCH_DEMO", "GITHUB_STEP_SUMMARY",
                "STOCKWATCH_STATE_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(ci_scan.time, "sleep", lambda s: None)


class FakeTelegram:
    """Stands in for api.telegram.org: records each request, answers with the queued responses."""
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, req, timeout=None):
        self.requests.append(json.loads(req.data))
        r = self.responses.pop(0) if self.responses else {"ok": True}
        if isinstance(r, Exception):
            raise r
        return io.BytesIO(json.dumps(r).encode())


def http_error(code, body):
    return urllib.error.HTTPError(f"https://api.telegram.org/bot{TOKEN}/sendMessage", code, "x", {},
                                  io.BytesIO(json.dumps(body).encode()))


def alert(i=0, severity=3):
    return (f"T{i}", 10.0 + i, "RISK - REVIEW", Signal("risk", "p", f"c{i}", "Hit stop " + "x" * 300, severity))


PLANS = {   # synthetic plans in the trade-plan shape
    "HOLD": {"stance": "HOLD", "entry_low": 95.0, "entry_high": 97.0, "stop": 90.0, "stop_basis": "below support at 91.00",
             "targets": [{"price": 115.0, "label": "resistance"}], "trigger": None},
    "TRIM": {"stance": "TRIM", "entry_low": 95.0, "entry_high": 97.0, "stop": 92.0, "stop_basis": "3x ATR below the current price",
             "targets": [{"price": 110.0, "label": "52-week high"}], "trigger": None},
    "BUY": {"stance": "BUY ON PULLBACK", "entry_low": 96.5, "entry_high": 98.0, "stop": 93.0, "stop_basis": "below support at 94.00",
            "targets": [{"price": 108.0, "label": "resistance"}], "trigger": "limit order in the zone, -2.0% below the current price"},
    "NOW": {"stance": "BUY NOW", "entry_low": 99.0, "entry_high": 100.0, "stop": 95.0, "stop_basis": "below support at 96.00",
            "targets": [{"price": 108.0, "label": "resistance"}], "trigger": None},
    "WAIT": {"stance": "WAIT FOR CONFIRMATION", "entry_low": 99.0, "entry_high": 100.0, "stop": 95.0, "stop_basis": "2x ATR below entry",
             "targets": [{"price": 108.0, "label": "resistance"}], "trigger": "a daily close back above 100.50 (+0.5%)"},
}
VERDICT = {"HOLD": "HOLD", "TRIM": "TRIM / REVIEW", "BUY": "WATCH", "NOW": "BUY SETUP", "WAIT": "WATCH"}


def ev(ticker, call, held=True, price=100.0, plan="same", error=None, verdict=None):
    plan = PLANS[call] if plan == "same" else plan
    e = Evaluation(ticker, 1 if held else 2, not held, price, 60, 60, 60, verdict or VERDICT[call],
                   [Signal("risk" if call == "TRIM" else "opportunity", "t", "x", f"synthetic reason for {call}", 2)],
                   {}, {}, plan=plan, quote={"live_price": price, "fetched_at": "2026-10-23T14:55:00+00:00"},
                   error=error)
    return e


class FreshProvider:
    """Every ticker has today's daily bar; `stale` ones a week-old bar."""
    def __init__(self, stale=()):
        self.stale = set(stale)

    def peek_history(self, ticker, period="5y"):
        day = "2026-10-16" if ticker in self.stale else "2026-10-23"
        return pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime([day]))


class Fleet:
    """Drives the scan with scripted evaluations instead of market data."""
    def __init__(self, monkeypatch, tmp_path, stale=()):
        self.calls, self.state = {}, tmp_path / "alert_state.bin"
        monkeypatch.setenv("STOCKWATCH_PORTFOLIO", "holdings:\n" + "".join(
            f"  - {{ticker: {t}, tier: 1, shares: {s}}}\n" for t, s in (("HELD", 10), ("WATCH", 0))))
        monkeypatch.setattr(ci_scan, "get_provider", lambda name: FreshProvider(stale))
        monkeypatch.setattr("stockwatch.scanner.analyse", lambda pf, provider, store, quiet=False: (self.evals, []))
        self.evals = []

    def run(self, *evals, mode="holdings-scan", now=NOW):
        self.evals = list(evals)
        return ci_scan.holdings(mode, now, self.state)


def configure(monkeypatch, telegram=True, key=True):
    if telegram:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
        monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    if key:
        monkeypatch.setenv("STOCKWATCH_STATE_KEY", STATE_KEY)


# ---- Telegram configuration and delivery

@pytest.mark.parametrize("token,chat,expected", [
    (None, None, "not configured"),
    (TOKEN, None, "incomplete: TELEGRAM_BOT_TOKEN set but TELEGRAM_CHAT_ID missing"),
    (None, CHAT, "incomplete: TELEGRAM_CHAT_ID set but TELEGRAM_BOT_TOKEN missing"),
    ("not-a-token", CHAT, "invalid: TELEGRAM_BOT_TOKEN"),
    (TOKEN, "my chat", "invalid: TELEGRAM_CHAT_ID"),
    (TOKEN, "-1001234567890", "configured"),
    (TOKEN, "@my_channel", "configured"),
])
def test_telegram_config_names_the_problem_without_the_values(monkeypatch, token, chat, expected):
    for var, value in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat)):
        if value:
            monkeypatch.setenv(var, value)
    status = notify.telegram_config()
    assert status.startswith(expected)
    assert TOKEN not in status and CHAT not in status


def test_telegram_message_is_capped_and_failures_never_echo_the_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    assert notify.send([alert(i) for i in range(40)], quiet=True)["telegram"] == "sent"
    text = fake.requests[0]["text"]
    lines = text.splitlines()
    assert len(text) <= notify.TELEGRAM_LIMIT and lines[0] == "StockWatch: 40 alerts"
    assert lines[-1] == f"+{40 - (len(lines) - 2)} more in the dashboard log" and len(lines) - 2 <= notify.MAX_PUSH_LINES
    assert all(len(line) > 300 for line in lines[1:-1])          # whole alerts only, never cut mid-line
    assert fake.requests[0]["chat_id"] == CHAT

    fake = FakeTelegram(http_error(401, {"ok": False, "description": f"Unauthorized {TOKEN}"}))
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    out = notify.send([alert()], quiet=True)["telegram"]
    assert out.startswith("failed: Telegram HTTP 401") and TOKEN not in out and "<TELEGRAM_BOT_TOKEN>" in out

    fake = FakeTelegram(urllib.error.URLError(f"cannot reach api.telegram.org/bot{TOKEN}"))
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    out = notify.send([alert()], quiet=True)["telegram"]
    assert out.startswith("failed: Telegram unreachable") and TOKEN not in out


def test_telegram_rate_limit_waits_once_when_short_and_reports_when_long(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    slept = []
    monkeypatch.setattr(notify.time, "sleep", slept.append)
    fake = FakeTelegram(http_error(429, {"ok": False, "parameters": {"retry_after": 3}}), {"ok": True})
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    assert notify.send([alert()], quiet=True)["telegram"] == "sent" and slept == [3] and len(fake.requests) == 2
    fake = FakeTelegram(http_error(429, {"ok": False, "parameters": {"retry_after": 60}}))
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    assert notify.send([alert()], quiet=True)["telegram"] == "failed: Telegram rate limit: retry after 60 s"
    assert len(fake.requests) == 1
    fake = FakeTelegram({"ok": False, "description": "Bad Request: chat not found"})
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    assert "chat not found" in notify.send([alert()], quiet=True)["telegram"]



# ---- the decision a message is about: the dashboard's reconciled call

def test_effective_stance_is_the_dashboards_call():
    for verdict, stance, watchlist in [("HOLD", "TRIM", True), ("WATCH", "HOLD", True), ("HOLD", "HOLD", False),
                                       ("RISK - REVIEW", "REDUCE / EXIT", False), ("BUY SETUP", None, True)]:
        plan = {"stance": stance} if stance else None
        snap = {"verdict": verdict, "payload": {"plan": plan, "watchlist": watchlist}}
        assert ui.ACTIONS[transitions.effective_stance(verdict, plan, watchlist)][0] == ui._action(snap)[0]
    assert transitions.effective_stance("WATCH", {"stance": "REDUCE / EXIT"}, True) == "NO TRADE"   # never 'sell' unowned


@pytest.mark.parametrize("e,stale,why", [
    (ev("A", "HOLD", error="no data"), False, "analysis failed"),
    (ev("A", "HOLD", price=float("nan")), False, "no price"),
    (ev("A", "HOLD"), True, "stale prices"),
    (ev("A", "HOLD", plan=None), False, "no trade plan"),
    (ev("A", "NOW", held=False, verdict="WATCH"), False, "verdict and plan disagree"),   # never BUY NOW while WATCH
    (ev("A", "TRIM", verdict="STRONG HOLD"), False, "verdict and plan disagree"),
])
def test_no_valid_reading_means_no_call(e, stale, why):
    assert transitions.reading(e, stale) == (None, why)


def test_engine_plan_buy_on_dip_for_a_watch_verdict_is_tracked_like_the_dashboard_shows_it():
    """tradeplan.build gives a watchlist uptrend above its pullback zone BUY ON PULLBACK even with a WATCH
    verdict; the dashboard says BUY ON DIP, so the tracker must accept it, as a conditional entry."""
    from stockwatch import tradeplan
    close = pd.Series([100 + i * 0.05 for i in range(240)] + [104.0] * 20)
    hist = pd.DataFrame({"Close": close})
    tech = {"price": 110.0, "atr": 2.0, "sma50": 104.0, "sma200": 100.0, "trend": "up", "high_52w": 130.0}
    plan = tradeplan.build(hist, tech, {}, 60.0, "WATCH", 2, True, levels={"support": 100.0, "resistance": 120.0})
    assert plan["stance"] == "BUY ON PULLBACK" and plan["entry_high"] < 110.0      # the zone sits below the price
    e = ev("W", "WAIT", held=False, price=110.0, plan=plan, verdict="WATCH")
    snap = {"verdict": "WATCH", "payload": {"plan": plan, "watchlist": True}}
    assert ui._action(snap)[0] == "BUY ON DIP"
    state, why = transitions.reading(e, False)
    assert why == "" and state["state"] == "DIP"
    entries, ready, c = transitions.step({}, {"W": state}, "t1")
    assert c["baseline"] == 1 and not ready                                   # a baseline, not a BUY alert
    entries, _, _ = step({}, ev("W", "WAIT", held=False))
    for _ in range(2):
        entries, ready, _ = transitions.step(entries, {"W": state}, "t")
    msg = transitions.message(ready[0], e)
    assert "WAIT → BUY ON DIP" in msg and "not a buy at the current price" in msg
    assert f"Entry zone: {plan['entry_low']:.2f}–{plan['entry_high']:.2f}" in msg and "BUY NOW" not in msg


def step(entries, *evals, now="t"):
    return transitions.step(entries, {e.ticker: transitions.reading(e, False)[0] for e in evals}, now)


def test_baseline_confirmation_flip_back_outage_and_ownership():
    entries, ready, c = step({}, ev("A", "HOLD"), ev("W", "WAIT", held=False))
    assert not ready and c["baseline"] == 2                                   # first sight: baseline, no "BUY" spam
    entries, ready, c = step(entries, ev("A", "TRIM"), ev("W", "WAIT", held=False))
    assert not ready and c["pending"] == 1 and entries["A"]["state"] == "HOLD"  # one run isn't enough
    entries, ready, _ = step(entries, ev("A", "HOLD"), ev("W", "WAIT", held=False))
    assert not ready and entries["A"]["pending"] is None                      # flipped back: cancelled
    for _ in range(3):                                                        # alternating never confirms
        entries, ready, _ = step(entries, ev("A", "TRIM"))
        assert not ready
        entries, ready, _ = step(entries, ev("A", "HOLD"))
    entries, _, _ = step(entries, ev("A", "TRIM"))
    entries, ready, c = step(entries, ev("A", "HOLD", error="outage"))       # outage: nothing changes
    assert not ready and c["skipped"] == 1 and entries["A"]["state"] == "HOLD" and entries["A"]["pending"]["count"] == 1
    entries, ready, _ = step(entries, ev("A", "TRIM"))
    assert [(t["from"], t["to"]) for t in ready] == [("HOLD", "TRIM")]
    entries, ready, c = step(entries, ev("A", "WAIT", held=False))           # sold out: re-baseline, no SELL
    assert not ready and c["baseline"] == 1 and entries["A"]["held"] is False
    entries, _, c = step(entries)                                             # left the fleet
    assert c["removed"] == 1 and not entries


def test_undelivered_transition_is_offered_again_once_delivered_never_repeats():
    entries, _, _ = step({}, ev("W", "WAIT", held=False))
    for _ in range(2):
        entries, ready, _ = step(entries, ev("W", "BUY", held=False))
    assert len(ready) == 1                                                    # failed send: still ready
    entries, ready, _ = step(entries, ev("W", "BUY", held=False))
    assert len(ready) == 1 and ready[0]["first_seen"] == "t"
    transitions.delivered(entries, ready[0], "t2")
    entries, ready, c = step(entries, ev("W", "BUY", held=False))
    assert not ready and c["unchanged"] == 1 and entries["W"]["state"] == "DIP"


def text(call_from, call_to, held=True, **kw):
    t = {"ticker": "A", "held": held, "from": transitions.STANCE_CLASS[PLANS[call_from]["stance"]],
         "from_stance": PLANS[call_from]["stance"], "from_verdict": VERDICT[call_from],
         "to": transitions.STANCE_CLASS[PLANS[call_to]["stance"]], "to_stance": PLANS[call_to]["stance"],
         "to_verdict": VERDICT[call_to]}
    return transitions.message(t, ev("A", call_to, held=held, **kw))


def test_messages_carry_the_plans_levels_and_never_invent_them():
    trim = text("HOLD", "TRIM")
    assert trim.startswith("🟠 A (held): HOLD → SELL SOME") and "HOLD → TRIM / REVIEW" in trim
    assert ("Trim: take some profit at the current price (the plan has no separate trim zone), keep the rest above 92.00."
            in trim) and "Target: 110.00 (52-week high)" in trim
    assert "Price 100.00 (Yahoo, 2026-10-23 14:55 UTC)" in trim and "not orders or predictions" in trim
    buy = text("WAIT", "BUY", held=False)
    assert "WAIT → BUY ON DIP" in buy and "Entry zone: 96.50–98.00" in buy and "Trigger: limit order" in buy
    assert "Conditional entry: a limit order inside the zone, not a buy at the current price." in buy
    now = text("BUY", "NOW", held=False)
    assert "BUY ON DIP → BUY NOW" in now and "Conditional entry" not in now and "Entry zone: 99.00–100.00" in now
    assert "Stop: 93.00 (below support at 94.00)" in buy and "Target: 108.00 (resistance)" in buy
    wait = text("BUY", "WAIT", held=False)
    assert "Not a buy yet. Wait for a daily close back above 100.50" in wait and "Entry zone" not in wait
    assert "Watch zone: 99.00–100.00 (not an active buy)" in wait
    bare = text("WAIT", "NOW", held=False, plan={"stance": "BUY NOW", "targets": []})
    assert "Entry zone: unavailable" in bare and "Stop: unavailable" in bare and "Target: unavailable" in bare


# ---- the encrypted alert memory

def test_alert_memory_is_encrypted_and_refuses_the_wrong_key(monkeypatch, tmp_path):
    path = tmp_path / "state.bin"
    assert alert_state.key_status() == "missing"
    monkeypatch.setenv("STOCKWATCH_STATE_KEY", "short")
    assert alert_state.key_status().startswith("too short")
    monkeypatch.setenv("STOCKWATCH_STATE_KEY", STATE_KEY)
    assert alert_state.load(path) == ({}, "none")
    alert_state.save({SECRET_TICKER: {"held": True, "state": "HOLD", "stance": "HOLD", "verdict": "HOLD"}}, path)
    raw = path.read_bytes()
    assert SECRET_TICKER.encode() not in raw and b"HOLD" not in raw and STATE_KEY.encode() not in raw
    assert alert_state.load(path)[0][SECRET_TICKER]["state"] == "HOLD"
    monkeypatch.setenv("STOCKWATCH_STATE_KEY", "another-key-" + "y" * 30)
    with pytest.raises(alert_state.StateError, match="can't be decrypted"):
        alert_state.load(path)
    monkeypatch.setenv("STOCKWATCH_STATE_KEY", STATE_KEY)
    path.write_bytes(raw[:-3] + b"xyz")
    with pytest.raises(alert_state.StateError):
        alert_state.load(path)


# ---- the scheduled scan, end to end with scripted decisions

def test_end_to_end_baseline_confirm_send_then_silence(monkeypatch, tmp_path):
    configure(monkeypatch)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    fleet = Fleet(monkeypatch, tmp_path)
    first = fleet.run(ev("HELD", "HOLD"), ev("WATCH", "WAIT", held=False))
    assert not first.errors and "2 new baselines" in dict(first.rows)["Decision changes"] and not fake.requests
    fleet.run(ev("HELD", "TRIM"), ev("WATCH", "BUY", held=False))             # seen once
    assert not fake.requests
    third = fleet.run(ev("HELD", "TRIM"), ev("WATCH", "BUY", held=False))     # confirmed: sent
    assert dict(third.rows)["Delivery"] == "telegram: 2 sent, 0 failed" and not third.errors
    texts = [r["text"] for r in fake.requests]
    assert any(t.startswith("🟠 HELD (held): HOLD → SELL SOME") for t in texts)
    assert any(t.startswith("🟢 WATCH (watchlist): WAIT → BUY ON DIP") and "Entry zone: 96.50–98.00" in t for t in texts)
    fourth = fleet.run(ev("HELD", "TRIM"), ev("WATCH", "BUY", held=False))    # unchanged: silence
    assert len(fake.requests) == 2 and dict(fourth.rows)["Delivery"] == "nothing to send"


def test_failed_send_stays_pending_and_is_sent_exactly_once_later(monkeypatch, tmp_path):
    configure(monkeypatch)
    fleet = Fleet(monkeypatch, tmp_path)
    fleet.run(ev("HELD", "HOLD"), ev("WATCH", "WAIT", held=False))
    fleet.run(ev("HELD", "TRIM"), ev("WATCH", "WAIT", held=False))
    monkeypatch.setattr(notify.urllib.request, "urlopen", FakeTelegram(http_error(500, {"description": "Internal"})))
    failed = fleet.run(ev("HELD", "TRIM"), ev("WATCH", "WAIT", held=False))
    assert any("1 of 1 Telegram message(s) failed" in e for e in failed.errors) and failed.publish() == 1
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    retried = fleet.run(ev("HELD", "TRIM"), ev("WATCH", "WAIT", held=False))   # a fresh process: state from disk
    assert len(fake.requests) == 1 and not retried.errors
    fleet.run(ev("HELD", "TRIM"), ev("WATCH", "WAIT", held=False))
    assert len(fake.requests) == 1


def test_no_telegram_or_only_partial_email_never_counts_as_delivered(monkeypatch, tmp_path):
    configure(monkeypatch, telegram=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")                    # host without a recipient
    fleet = Fleet(monkeypatch, tmp_path)
    fleet.run(ev("HELD", "HOLD"), ev("WATCH", "WAIT", held=False))
    fleet.run(ev("HELD", "TRIM"), ev("WATCH", "WAIT", held=False))
    report = fleet.run(ev("HELD", "TRIM"), ev("WATCH", "WAIT", held=False))
    assert any("Telegram isn't configured" in e for e in report.errors)
    assert "not used by the scheduled scan" in dict(report.rows)["Other channels"]
    entries, _ = alert_state.load(fleet.state)
    assert entries["HELD"]["state"] == "HOLD" and entries["HELD"]["pending"]["state"] == "TRIM"   # still pending


def test_outage_or_stale_prices_never_send_a_phantom_change(monkeypatch, tmp_path):
    configure(monkeypatch)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    fleet = Fleet(monkeypatch, tmp_path, stale={"WATCH"})
    fleet.run(ev("HELD", "HOLD"), ev("WATCH", "WAIT", held=False))
    for _ in range(3):
        report = fleet.run(ev("HELD", "HOLD", error="Yahoo refused"), ev("WATCH", "BUY", held=False))
    assert not fake.requests and "2 without valid data" in dict(report.rows)["Decision changes"]
    assert alert_state.load(fleet.state)[0]["HELD"]["state"] == "HOLD"


def test_missing_key_blocks_alerts_and_stores_nothing(monkeypatch, tmp_path):
    configure(monkeypatch, key=False)
    monkeypatch.setattr(notify.urllib.request, "urlopen", lambda *a, **k: pytest.fail("sent without a state key"))
    fleet = Fleet(monkeypatch, tmp_path)
    report = fleet.run(ev("HELD", "TRIM"), ev("WATCH", "BUY", held=False))
    assert any("STOCKWATCH_STATE_KEY is missing" in e for e in report.errors) and not fleet.state.exists()
    assert dict(report.rows)["Analysed"] == "2 of 2"                         # the scan itself still ran


def test_unreadable_memory_rebaselines_loudly(monkeypatch, tmp_path):
    configure(monkeypatch)
    fleet = Fleet(monkeypatch, tmp_path)
    fleet.state.write_bytes(b"garbage")
    report = fleet.run(ev("HELD", "HOLD"), ev("WATCH", "WAIT", held=False))
    assert any("Alert memory unreadable" in e for e in report.errors)
    assert alert_state.load(fleet.state)[1] == "restored"                    # a fresh baseline was written


def test_dry_run_counts_but_never_sends_or_saves(monkeypatch, tmp_path):
    configure(monkeypatch)
    monkeypatch.setattr(notify.urllib.request, "urlopen", lambda *a, **k: pytest.fail("dry run sent"))
    fleet = Fleet(monkeypatch, tmp_path)
    fleet.run(ev("HELD", "HOLD"), ev("WATCH", "WAIT", held=False))
    fleet.run(ev("HELD", "TRIM"), ev("WATCH", "WAIT", held=False))
    before = fleet.state.read_bytes()
    dry = fleet.run(ev("HELD", "TRIM"), ev("WATCH", "WAIT", held=False), mode="holdings-dry-run")
    assert dict(dry.rows)["Delivery"] == "dry run: 1 message(s) would be sent; nothing sent or saved"
    assert fleet.state.read_bytes() == before


def test_demo_data_never_drives_a_live_scan(monkeypatch, tmp_path):
    configure(monkeypatch)
    monkeypatch.setattr(notify.urllib.request, "urlopen", lambda *a, **k: pytest.fail("demo data sent a message"))
    for how in ("env", "settings"):
        if how == "env":
            monkeypatch.setenv("STOCKWATCH_DEMO", "1")
            monkeypatch.setenv("STOCKWATCH_PORTFOLIO", PORTFOLIO)
        else:
            monkeypatch.delenv("STOCKWATCH_DEMO")
            monkeypatch.setenv("STOCKWATCH_PORTFOLIO", PORTFOLIO + "settings: {data_provider: demo}\n")
        monkeypatch.setattr("stockwatch.scanner.analyse", lambda *a, **k: pytest.fail("analysed demo data live"))
        live = ci_scan.holdings("holdings-scan", NOW, tmp_path / "s.bin")
        assert any("never runs or alerts on synthetic prices" in e for e in live.errors)
    monkeypatch.undo()
    configure(monkeypatch)
    monkeypatch.setenv("STOCKWATCH_DEMO", "1")
    monkeypatch.setenv("STOCKWATCH_PORTFOLIO", PORTFOLIO)
    dry = ci_scan.holdings("holdings-dry-run", NOW, tmp_path / "s.bin")
    assert dict(dry.rows)["Market data"].startswith("SYNTHETIC") and "(synthetic)" in dict(dry.rows)["Live quotes"]
    assert dict(dry.rows)["Analysed"] == "2 of 2"


# ---- holdings source, failures and privacy

def test_example_list_is_never_scanned_as_a_portfolio(monkeypatch, tmp_path):
    monkeypatch.setattr("stockwatch.scanner.analyse", lambda *a, **k: pytest.fail("example list was scanned"))
    report = ci_scan.holdings("holdings-scan", NOW, tmp_path / "s.bin")
    assert dict(report.rows)["Holdings source"] == "example file"
    assert "isn't your portfolio" in report.errors[0] and report.publish() == 1


def test_empty_or_broken_portfolio_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCKWATCH_PORTFOLIO", "holdings: []\n")
    assert "no holdings" in ci_scan.holdings("holdings-scan", NOW, tmp_path / "s.bin").errors[0]
    monkeypatch.setenv("STOCKWATCH_PORTFOLIO", "holdings:\n  - {tier: 1}\n")
    assert "couldn't be loaded" in ci_scan.holdings("holdings-scan", NOW, tmp_path / "s.bin").errors[0]


def test_unreadable_sheet_is_an_error_but_the_backup_list_is_still_scanned(monkeypatch, tmp_path):
    sheet = "https://docs.google.com/spreadsheets/d/PRIVATE_SHEET_ID_1234567890/edit"
    monkeypatch.setenv("STOCKWATCH_SHEET_URL", sheet)
    monkeypatch.setenv("STOCKWATCH_DEMO", "1")
    monkeypatch.setenv("STOCKWATCH_PORTFOLIO", PORTFOLIO)
    monkeypatch.setattr("stockwatch.config.fetch_sheet_csv", lambda url: (_ for _ in ()).throw(
        PermissionError(f"sign-in page at {sheet}")))
    report = ci_scan.holdings("holdings-dry-run", NOW, tmp_path / "s.bin")
    rows = dict(report.rows)
    assert rows["Holdings source"] == "STOCKWATCH_PORTFOLIO secret" and rows["Analysed"] == "2 of 2"
    assert any("Google Sheet unreadable" in e for e in report.errors)
    assert sheet not in report.markdown() and "PRIVATE_SHEET_ID" not in report.markdown()


@pytest.mark.parametrize("token,chat", [(TOKEN, None), (None, CHAT), ("bad", CHAT)])
def test_half_configured_telegram_fails(monkeypatch, tmp_path, token, chat):
    for var, value in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat)):
        if value:
            monkeypatch.setenv(var, value)
    fleet = Fleet(monkeypatch, tmp_path)
    report = fleet.run(ev("HELD", "HOLD"), ev("WATCH", "WAIT", held=False), mode="holdings-dry-run")
    assert any(e.startswith("Telegram is ") for e in report.errors) and dict(report.rows)["Analysed"] == "2 of 2"


def test_failed_analysis_and_scanner_crash_are_reported(monkeypatch, tmp_path):
    configure(monkeypatch)
    fleet = Fleet(monkeypatch, tmp_path)
    report = fleet.run(ev("HELD", "HOLD", error="x"), ev("WATCH", "WAIT", held=False, error="y"))
    assert dict(report.rows)["Analysed"] == "0 of 2" and any("No ticker could be analysed" in e for e in report.errors)
    monkeypatch.setattr("stockwatch.scanner.analyse", lambda *a, **k: 1 / 0)
    assert any("scanner failed (ZeroDivisionError)" in e for e in fleet.run().errors)


def test_stale_and_missing_prices_are_counted(monkeypatch):
    class Peek:
        def __init__(self, bars):
            self.bars = bars

        def peek_history(self, t):
            return self.bars.get(t)
    old = pd.DataFrame({"Close": [1.0]}, index=pd.to_datetime(["2026-10-15"]))
    fresh = pd.DataFrame({"Close": [1.0]}, index=pd.to_datetime(["2026-10-22"]))
    evals = [type("E", (), {"ticker": t})() for t in ("A", "B", "C")]
    before_open = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)   # Fri 08:00 New York
    latest, stale = ci_scan.freshness(evals, Peek({"A": fresh, "B": old}), before_open)
    assert str(latest) == "2026-10-22" and stale == 2          # B is a week old, C has no prices


def test_last_session_follows_the_new_york_clock():
    assert str(ci_scan.last_session(datetime(2026, 10, 23, 12, tzinfo=timezone.utc))) == "2026-10-22"  # Fri 08:00 NY
    assert str(ci_scan.last_session(NOW)) == "2026-10-23"                       # Fri 11:00 NY: today's bar exists
    assert str(ci_scan.last_session(datetime(2026, 10, 23, 21, tzinfo=timezone.utc))) == "2026-10-23"
    assert str(ci_scan.last_session(datetime(2026, 10, 25, 12, tzinfo=timezone.utc))) == "2026-10-23"  # Sunday


def test_public_output_and_cached_state_have_no_holdings_or_credentials(monkeypatch, tmp_path, capsys):
    configure(monkeypatch)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    fleet = Fleet(monkeypatch, tmp_path)
    monkeypatch.setenv("STOCKWATCH_PORTFOLIO", PORTFOLIO)
    secret = lambda call: ev(SECRET_TICKER, call, price=876.54)
    for call in ("HOLD", "TRIM", "TRIM"):
        fleet.run(secret(call), ev("BBB", "WAIT", held=False))
    fleet.evals = [secret("TRIM"), ev("BBB", "WAIT", held=False)]
    monkeypatch.setattr(alert_state, "PATH", fleet.state)
    assert ci_scan.main(["--mode", "holdings-scan"]) == 0
    public = capsys.readouterr().out + capsys.readouterr().err + (tmp_path / "summary.md").read_text()
    cached = fleet.state.read_bytes()
    for private in (SECRET_TICKER, SECRET_SHARES, SECRET_COST, "876.54", TOKEN, CHAT, STATE_KEY):
        assert private not in public, private
        assert private.encode() not in cached, private
    assert SECRET_TICKER in fake.requests[0]["text"]                       # it reaches Telegram, and only Telegram


def test_telegram_check_and_test_send(monkeypatch):
    assert ci_scan.telegram("telegram-check", NOW, None).errors          # nothing configured
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.setattr(notify.urllib.request, "urlopen", lambda *a, **k: pytest.fail("check mode sent a message"))
    check = ci_scan.telegram("telegram-check", NOW, None)
    assert not check.errors and dict(check.rows)["Delivery"] == "not attempted (check only)"
    assert "type SEND" in ci_scan.telegram("telegram-test-send", NOW, "").errors[0]
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    sent = ci_scan.telegram("telegram-test-send", NOW, "SEND")
    assert dict(sent.rows)["Delivery"] == "sent" and "No holdings are included" in fake.requests[0]["text"]
    monkeypatch.setattr(notify.urllib.request, "urlopen", FakeTelegram(http_error(400, {"description": "Bad Request: chat not found"})))
    assert "chat not found" in ci_scan.telegram("telegram-test-send", NOW, "SEND").errors[0]


def test_workflow_always_scans_caches_only_the_encrypted_memory_and_is_dry_by_default():
    wf = yaml.safe_load((ROOT / ".github/workflows/scan.yml").read_text())
    text = (ROOT / ".github/workflows/scan.yml").read_text()
    dispatch = wf[True]["workflow_dispatch"]["inputs"]
    assert dispatch["mode"]["default"] == "holdings-dry-run"
    assert set(dispatch["mode"]["options"]) == {*ci_scan.MODES, "market-scan"}
    scan, market = wf["jobs"]["scan"], wf["jobs"]["market"]
    assert "skipping scan" not in text and not any("cfg.outputs" in str(s.get("if", "")) for s in scan["steps"])
    assert "inputs.mode != 'market-scan'" in scan["if"] and "inputs.mode == 'market-scan'" in market["if"]
    assert "'holdings-scan'" in scan["env"]["MODE"] and "STOCKWATCH_STATE_KEY" in scan["env"]
    cached = [s["with"]["path"] for s in scan["steps"] if "actions/cache" in str(s.get("uses", ""))]
    assert cached == ["data/alert_state.bin", "data/alert_state.bin"] and "stockwatch.db" not in text
    save = next(s for s in scan["steps"] if str(s.get("uses", "")).startswith("actions/cache/save"))
    assert "always()" in save["if"] and "holdings-scan" in save["if"]
