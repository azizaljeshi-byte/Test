"""Scheduled scan of every tracked stock: python -m stockwatch.ci_scan --mode MODE

The scan runs whether or not Telegram is set up, and the run reports what actually happened: where the
holdings came from, how many tickers were analysed, how fresh the prices are, and which decision changes
were confirmed and delivered. Telegram gets a message when a stock's call moves between classes (WAIT ->
BUY, HOLD -> TRIM...), held or watchlist (`transitions.py`). The repository is public, so the log and the
run summary carry counts and statuses only: no tickers, share counts, costs, bot token or chat ID. The
alert memory between runs is encrypted (`alert_state.py`); the scan's own database is thrown away.

Modes:
  holdings-scan       scan, send confirmed decision changes, save the alert memory (the schedule uses this)
  holdings-dry-run    scan and count what would be sent; nothing is sent or saved; demo data allowed
  telegram-check      are both Telegram secrets present and well formed? (no network call)
  telegram-test-send  send one fixed test message with no holdings in it (needs --confirm SEND)

Exit status 1 means something needs the owner: no real portfolio, demo data in a live scan, the scanner
failed, nothing could be analysed, Telegram half configured, the alert key missing, a send failed, or a
change had no channel to go to.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import logging
import os
import re
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import alert_state, notify, transitions
from .config import load_portfolio
from .data import get_provider, selected_provider
from .store import Store

MODES = ("holdings-scan", "holdings-dry-run", "telegram-check", "telegram-test-send")
NY, RIYADH = ZoneInfo("America/New_York"), ZoneInfo("Asia/Riyadh")


class Report:
    def __init__(self, mode: str, now: datetime):
        self.mode, self.now = mode, now
        self.rows: list[tuple[str, str]] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def add(self, label: str, value) -> None:
        self.rows.append((label, str(value)))

    def markdown(self) -> str:
        verdict = ("❌ NEEDS ATTENTION" if self.errors else "⚠️ RAN WITH WARNINGS" if self.warnings else "✅ OK")
        lines = [f"## StockWatch {self.mode}: {verdict}", "",
                 f"Run at {self.now:%Y-%m-%d %H:%M} UTC · {self.now.astimezone(NY):%a %H:%M} New York · "
                 f"{self.now.astimezone(RIYADH):%a %H:%M} Riyadh", "", "| | |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in self.rows]
        lines += [""] + [f"- ❌ {e}" for e in self.errors] + [f"- ⚠️ {w}" for w in self.warnings]
        lines += ["", "_A green run means the checks above passed. Data freshness and delivery are only what "
                      "this table says; counts only, no tickers or positions (public log)._"]
        return "\n".join(lines) + "\n"

    def publish(self) -> int:
        text = self.markdown()
        print(text, flush=True)
        for e in self.errors:
            print(f"::error title=StockWatch {self.mode}::{e}", flush=True)
        for w in self.warnings:
            print(f"::warning title=StockWatch {self.mode}::{w}", flush=True)
        if os.getenv("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write(text)
        return 1 if self.errors else 0


def portfolio_source(portfolio) -> str:
    if portfolio.sheet_url:
        return "Google Sheet"
    if portfolio.source is None:
        return "STOCKWATCH_PORTFOLIO secret"
    return "example file" if Path(portfolio.source).name == "portfolio.example.yaml" else "portfolio.yaml file"


def _sheet_problem(message: str) -> str:
    """The sheet's address is private: drop it, and any other link, from an error message."""
    sheet = (os.getenv("STOCKWATCH_SHEET_URL") or "").strip()
    message = message.replace(sheet, "<sheet>") if sheet else message
    return re.sub(r"https?://\S+", "<link>", message)


def last_session(now: datetime) -> date:
    """The latest weekday whose regular session has closed or is under way in New York (holidays ignored)."""
    ny = now.astimezone(NY)
    day = ny.date()
    if (ny.hour, ny.minute) < (9, 30):        # before the 09:30 open, today's bar doesn't exist yet
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def freshness(evals, provider, now: datetime) -> tuple[date | None, int]:
    """Latest daily bar across the analysed tickers, and how many are older than the last session."""
    expected, latest, stale = last_session(now), None, 0
    for e in evals:
        hist = provider.peek_history(e.ticker) if hasattr(provider, "peek_history") else None
        if hist is None or hist.empty:
            stale += 1
            continue
        bar = hist.index[-1].date()
        latest = max(latest, bar) if latest else bar
        stale += bar < expected
    return latest, stale


def check_telegram(report: Report) -> bool:
    """Decision-change alerts go to Telegram only. True when it can deliver; a half-set Telegram is an error."""
    tg = notify.telegram_config()
    report.add("Telegram", tg)
    if tg not in ("configured", "not configured"):
        report.errors.append(f"Telegram is {tg}. Fix the repository secrets; nothing can be sent to Telegram.")
    unused = [name for name, var in (("ntfy", "NTFY_TOPIC"), ("email", "SMTP_HOST")) if os.getenv(var)]
    if unused:
        report.add("Other channels", f"{', '.join(unused)}: not used by the scheduled scan (Telegram only)")
    return tg == "configured"


def stale_tickers(evals, provider, now: datetime) -> set[str]:
    expected = last_session(now)
    out = set()
    for e in evals:
        hist = provider.peek_history(e.ticker) if hasattr(provider, "peek_history") else None
        if hist is None or hist.empty or hist.index[-1].date() < expected:
            out.add(e.ticker)
    return out


def holdings(mode: str, now: datetime, state_path: Path | None = None) -> Report:
    report = Report(mode, now)
    state_path = state_path or alert_state.PATH
    dry = mode == "holdings-dry-run"
    try:
        portfolio = load_portfolio()
    except Exception as e:
        report.errors.append(f"Portfolio couldn't be loaded ({type(e).__name__}). Check the STOCKWATCH_PORTFOLIO secret's YAML.")
        return report
    source = portfolio_source(portfolio)
    report.add("Holdings source", source)
    if portfolio.sheet_error:
        report.errors.append("Google Sheet unreadable, so the backup list was used: "
                             + _sheet_problem(portfolio.sheet_error)[:200])
    if source == "example file":
        report.errors.append("Only the example list was found, which isn't your portfolio, so nothing was scanned. "
                             "Add your holdings as the STOCKWATCH_PORTFOLIO repository secret (or STOCKWATCH_SHEET_URL).")
        check_telegram(report)
        return report
    held = sum(not h.is_watchlist for h in portfolio.holdings)
    report.add("Tracked stocks", f"{len(portfolio.holdings)} ({held} held, {len(portfolio.holdings) - held} watchlist)")
    if not portfolio.holdings:
        report.errors.append(f"The {source} has no holdings, so nothing was scanned.")
        check_telegram(report)
        return report
    provider_name = selected_provider(portfolio.settings.data_provider)
    synthetic = provider_name == "demo"
    report.add("Market data", "SYNTHETIC demo prices (not market data)" if synthetic else "Yahoo")
    if synthetic and not dry:
        report.errors.append("The demo data provider is selected (STOCKWATCH_DEMO or data_provider: demo). "
                             "A live scan never runs or alerts on synthetic prices; use holdings-dry-run to try it.")
        check_telegram(report)
        return report
    can_deliver = check_telegram(report)
    report.add("Alert state key", alert_state.key_status())
    if alert_state.key_status() != "configured" and not dry:
        report.errors.append(f"{alert_state.KEY_ENV} is {alert_state.key_status()}: without it the alert memory can't be "
                             "stored privately, so decision-change alerts are off. Add a random 32+ character "
                             "repository secret.")

    with tempfile.TemporaryDirectory() as tmp:
        try:
            from .scanner import analyse
            provider = get_provider(provider_name)
            # a throwaway database: snapshots hold share counts and costs, so nothing of it is kept or cached
            store = Store(Path(tmp) / "scan.db")
            sink = io.StringIO()       # library output names tickers; keep it out of the public log
            logging.disable(logging.CRITICAL)
            try:
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    evals, _ = analyse(portfolio, provider, store, quiet=True)
            finally:
                logging.disable(logging.NOTSET)
        except Exception as e:
            report.errors.append(f"The scanner failed ({type(e).__name__}); no analysis completed.")
            return report

    ok = [e for e in evals if not e.error]
    report.add("Analysed", f"{len(ok)} of {len(evals)}")
    if not ok:
        report.errors.append("No ticker could be analysed (market data unavailable?), so no decision was checked.")
    elif len(ok) < len(evals):
        report.warnings.append(f"{len(evals) - len(ok)} of {len(evals)} tickers couldn't be analysed this run.")
    latest, stale_count = freshness(ok, provider, now)
    stale = stale_tickers(ok, provider, now)
    report.add("Latest daily bar", f"{latest} (expected {last_session(now)})" if latest else "none")
    if ok and stale_count:
        report.warnings.append(f"{stale_count} of {len(ok)} analysed tickers have prices older than the last session "
                               "(a market holiday can cause this); their calls aren't compared this run.")
    quotes = sum(transitions.current_quote(e.quote, now) is not None for e in ok)
    report.add("Live quotes", f"{quotes} of {len(ok)} traded in their session within the last hour"
               + (" (synthetic)" if synthetic else ""))

    readings = {e.ticker: transitions.reading(e, e.ticker in stale)[0] for e in evals}
    bar_dates = {}
    for e in ok:
        hist = provider.peek_history(e.ticker) if hasattr(provider, "peek_history") else None
        if hist is not None and not hist.empty:
            bar_dates[e.ticker] = str(hist.index[-1].date())
    if alert_state.key_status() != "configured":
        report.add("Decision changes", "not checked (no alert state key)")
        return report
    try:
        entries, restored = alert_state.load(state_path)
    except alert_state.StateError as e:
        report.errors.append(f"Alert memory unreadable: {e}. Starting a new baseline; no changes can be alerted this run.")
        entries, restored = {}, "unreadable"
    if restored == "none":
        report.warnings.append("No saved alert memory (first run, or the cache expired after 7 days unused): "
                               "this run records each stock's current call as the baseline and alerts nothing.")
    report.add("Alert memory", f"{restored} ({len(entries)} stocks)" if restored == "restored" else restored)
    stamp = now.isoformat(timespec="seconds")
    entries, ready, counts = transitions.step(entries, readings, stamp)
    report.add("Decision changes", f"{len(ready)} confirmed · {counts['pending']} awaiting confirmation · "
                                   f"{counts['baseline']} new baselines · {counts['skipped']} without valid data")
    if dry:
        report.add("Delivery", f"dry run: {len(ready)} message(s) would be sent; nothing sent or saved")
        if not can_deliver:
            report.warnings.append("Telegram isn't configured: a live run would have nowhere to send changes.")
        return report

    sent = failed = 0
    by_ticker = {e.ticker: e for e in evals}
    if ready and not can_deliver:
        report.errors.append(f"{len(ready)} decision change(s) confirmed but Telegram isn't configured. "
                             "They stay pending and are sent once it is.")
    elif ready:
        for i, t in enumerate(ready):
            if i:
                time.sleep(1.1)        # Telegram allows about one message a second per chat
            try:
                notify.telegram_send(transitions.message(t, by_ticker[t["ticker"]], bar_dates.get(t["ticker"]), now))
                transitions.delivered(entries, t, stamp)
                sent += 1
            except (notify.DeliveryError, ValueError) as e:
                failed += 1
                last_error = str(e)
        if failed:
            report.errors.append(f"{failed} of {len(ready)} Telegram message(s) failed ({last_error}). "
                                 "They stay pending and are retried next run.")
    elif not can_deliver:
        report.warnings.append("Telegram isn't configured, so future decision changes won't reach you. "
                               "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
    report.add("Delivery", f"telegram: {sent} sent, {failed} failed" if ready else "nothing to send")
    try:
        alert_state.save(entries, state_path)
    except Exception as e:
        report.errors.append(f"Alert memory couldn't be saved ({type(e).__name__}); confirmed changes may repeat.")
    return report


def telegram(mode: str, now: datetime, confirm: str | None) -> Report:
    report = Report(mode, now)
    status = notify.telegram_config()
    report.add("Telegram", status)
    if status != "configured":
        report.errors.append(f"Telegram is {status}. Set both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as repository secrets.")
        return report
    if mode == "telegram-check":
        report.add("Delivery", "not attempted (check only)")
        return report
    if confirm != "SEND":
        report.errors.append("Test message not sent: type SEND in the confirm box to send it.")
        return report
    try:
        report.add("Delivery", notify.telegram_test(f"{now:%Y-%m-%d %H:%M} UTC"))
    except notify.DeliveryError as e:
        report.add("Delivery", "failed")
        report.errors.append(str(e))
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=MODES, default="holdings-dry-run")
    p.add_argument("--confirm", help="SEND, to allow telegram-test-send")
    args = p.parse_args(argv)
    now = datetime.now(timezone.utc)
    report = holdings(args.mode, now) if args.mode.startswith("holdings") else telegram(args.mode, now, args.confirm)
    return report.publish()


if __name__ == "__main__":
    raise SystemExit(main())
