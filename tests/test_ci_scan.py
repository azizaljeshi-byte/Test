"""Scheduled holdings scan and Telegram delivery: offline, synthetic data, fake Telegram."""
import io
import json
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml

from stockwatch import ci_scan, notify
from stockwatch.signals import Signal

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "123456789:" + "A" * 35
CHAT = "987654321"
SECRET_TICKER, SECRET_SHARES, SECRET_COST = "QWXYZ", "4321.5", "876.54"
PORTFOLIO = (f"holdings:\n  - {{ticker: {SECRET_TICKER}, tier: 1, shares: {SECRET_SHARES}, cost_basis: {SECRET_COST}}}\n"
             "  - {ticker: BBB, tier: 2}\nsettings: {data_provider: demo}\n")
NOW = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)      # Fri 11:00 New York, 18:00 Riyadh


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for var in ("STOCKWATCH_PORTFOLIO", "STOCKWATCH_SHEET_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                "NTFY_TOPIC", "SMTP_HOST", "STOCKWATCH_DEMO", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(ci_scan, "DEFAULT_DB", tmp_path / "alerts.db")


class FakeTelegram:
    """Stands in for api.telegram.org: records each request, answers with the queued responses."""
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, req, timeout=None):
        self.requests.append(json.loads(req.data))
        self.urls = getattr(self, "urls", []) + [req.full_url]
        r = self.responses.pop(0) if self.responses else {"ok": True}
        if isinstance(r, Exception):
            raise r
        return io.BytesIO(json.dumps(r).encode())


def http_error(code, body):
    return urllib.error.HTTPError(f"https://api.telegram.org/bot{TOKEN}/sendMessage", code, "x", {},
                                  io.BytesIO(json.dumps(body).encode()))


def alert(i=0, severity=3):
    return (f"T{i}", 10.0 + i, "RISK - REVIEW", Signal("risk", "p", f"c{i}", "Hit stop " + "x" * 300, severity))


def run(monkeypatch, mode="holdings-scan", portfolio=PORTFOLIO, db=None):
    if portfolio is not None:
        monkeypatch.setenv("STOCKWATCH_PORTFOLIO", portfolio)
    return ci_scan.holdings(mode, NOW, db or ci_scan.DEFAULT_DB)


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


# ---- the holdings scan always runs and reports honestly

def test_example_list_is_never_scanned_as_a_portfolio(monkeypatch):
    monkeypatch.setattr("stockwatch.scanner.analyse", lambda *a, **k: pytest.fail("example list was scanned"))
    report = run(monkeypatch, portfolio=None)
    assert dict(report.rows)["Holdings source"] == "example file"
    assert report.errors and "isn't your portfolio" in report.errors[0]
    assert report.publish() == 1


def test_empty_or_broken_portfolio_fails(monkeypatch):
    assert "no holdings" in run(monkeypatch, portfolio="holdings: []\n").errors[0]
    assert "couldn't be loaded" in run(monkeypatch, portfolio="holdings:\n  - {tier: 1}\n").errors[0]


def test_unreadable_sheet_is_an_error_but_the_backup_list_is_still_scanned(monkeypatch):
    sheet = "https://docs.google.com/spreadsheets/d/PRIVATE_SHEET_ID_1234567890/edit"
    monkeypatch.setenv("STOCKWATCH_SHEET_URL", sheet)
    monkeypatch.setattr("stockwatch.config.fetch_sheet_csv", lambda url: (_ for _ in ()).throw(
        PermissionError(f"sign-in page at {sheet}")))
    report = run(monkeypatch, mode="holdings-dry-run")
    rows = dict(report.rows)
    assert rows["Holdings source"] == "STOCKWATCH_PORTFOLIO secret" and rows["Analysed"] == "2 of 2"
    assert any("Google Sheet unreadable" in e for e in report.errors)
    assert sheet not in report.markdown() and "PRIVATE_SHEET_ID" not in report.markdown()


def test_scan_runs_without_any_channel_and_undelivered_alerts_fail_the_run(monkeypatch):
    report = run(monkeypatch)
    rows = dict(report.rows)
    assert rows["Analysed"] == "2 of 2" and rows["Tickers"] == "2 (1 with shares, 1 watchlist)"
    assert int(rows["New alerts"]) > 0 and rows["Delivery"] == "not sent: no channel configured"
    assert any("no notification channel" in e for e in report.errors)
    # the next run finds no *new* alerts in this run's history: green, but warns there's no channel
    again = run(monkeypatch)
    assert dict(again.rows)["New alerts"] == "0" and not again.errors
    assert any("No notification channel" in w for w in again.warnings)


@pytest.mark.parametrize("token,chat", [(TOKEN, None), (None, CHAT), ("bad", CHAT)])
def test_half_configured_telegram_fails_even_with_no_alerts(monkeypatch, token, chat):
    for var, value in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat)):
        if value:
            monkeypatch.setenv(var, value)
    report = run(monkeypatch, mode="holdings-dry-run")
    assert any(e.startswith("Telegram is ") for e in report.errors)
    assert dict(report.rows)["Analysed"] == "2 of 2"          # the scan still ran


def test_live_scan_delivers_by_telegram_and_a_failed_send_fails_the_run(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    report = run(monkeypatch)
    assert dict(report.rows)["Delivery"] == "telegram: sent" and not report.errors and len(fake.requests) == 1
    monkeypatch.setattr(notify.urllib.request, "urlopen", FakeTelegram(http_error(403, {"description": "Forbidden: bot was blocked by the user"})))
    monkeypatch.setattr(ci_scan, "DEFAULT_DB", ci_scan.DEFAULT_DB.with_name("fresh.db"))
    report = run(monkeypatch)
    assert any("telegram failed: Telegram HTTP 403" in e for e in report.errors) and report.publish() == 1


def test_dry_run_sends_nothing_and_leaves_the_alert_history_alone(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.setattr(notify.urllib.request, "urlopen", lambda *a, **k: pytest.fail("dry run sent a message"))
    db = tmp_path / "history.db"
    first = run(monkeypatch, mode="holdings-dry-run", db=db)
    assert int(dict(first.rows)["New alerts"]) > 0 and "dry run" in dict(first.rows)["Delivery"]
    assert not db.exists()                                      # nothing written to the real history
    second = run(monkeypatch, mode="holdings-dry-run", db=db)
    assert dict(second.rows)["New alerts"] == dict(first.rows)["New alerts"]


def test_failed_analysis_and_scanner_crash_are_reported(monkeypatch):
    from stockwatch.data import DemoProvider
    monkeypatch.setattr(DemoProvider, "history", lambda self, t, period="5y": (_ for _ in ()).throw(RuntimeError("no data")))
    report = run(monkeypatch, mode="holdings-dry-run")
    assert dict(report.rows)["Analysed"] == "0 of 2" and any("No ticker could be analysed" in e for e in report.errors)
    monkeypatch.setattr("stockwatch.scanner.analyse", lambda *a, **k: 1 / 0)
    assert "scanner failed (ZeroDivisionError)" in run(monkeypatch).errors[0]


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


def test_public_output_has_no_holdings_or_credentials(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    monkeypatch.setattr(notify.urllib.request, "urlopen", FakeTelegram())
    monkeypatch.setenv("STOCKWATCH_PORTFOLIO", PORTFOLIO)
    assert ci_scan.main(["--mode", "holdings-scan"]) == 0
    public = capsys.readouterr().out + capsys.readouterr().err + (tmp_path / "summary.md").read_text()
    for private in (SECRET_TICKER, SECRET_SHARES, SECRET_COST, "4321", "876.54", TOKEN, CHAT):
        assert private not in public, private
    assert "Analysed | 2 of 2" in public


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


def test_workflow_always_scans_and_manual_runs_are_dry_by_default():
    wf = yaml.safe_load((ROOT / ".github/workflows/scan.yml").read_text())
    text = (ROOT / ".github/workflows/scan.yml").read_text()
    dispatch = wf[True]["workflow_dispatch"]["inputs"]
    assert dispatch["mode"]["default"] == "holdings-dry-run"
    assert set(dispatch["mode"]["options"]) == {*ci_scan.MODES, "market-scan"}
    scan, market = wf["jobs"]["scan"], wf["jobs"]["market"]
    assert "skipping scan" not in text and not any("cfg.outputs" in str(s.get("if", "")) for s in scan["steps"])
    assert "inputs.mode != 'market-scan'" in scan["if"] and "inputs.mode == 'market-scan'" in market["if"]
    assert "'holdings-scan'" in scan["env"]["MODE"]                         # the schedule is the live scan
    assert any("stockwatch.ci_scan" in str(s.get("run", "")) for s in scan["steps"])
