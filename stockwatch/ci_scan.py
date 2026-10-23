"""Holdings scan for the scheduled GitHub Actions job: python -m stockwatch.ci_scan --mode MODE

The scan runs whether or not a notification channel is set, and the run reports what actually
happened: where the holdings came from, how many tickers were analysed, how fresh the prices are and
whether each alert was delivered. The repository is public, so the log and the run summary carry
counts and statuses only: no tickers, share counts, costs, bot token or chat ID.

Modes:
  holdings-scan       scan and deliver new alerts (the schedule uses this)
  holdings-dry-run    scan against a throwaway copy of the alert history; nothing is sent or saved
  telegram-check      are both Telegram secrets present and well formed? (no network call)
  telegram-test-send  send one fixed test message with no holdings in it (needs --confirm SEND)

Exit status 1 means something needs the owner: no real portfolio, the scanner failed, nothing could
be analysed, Telegram half configured, a send failed, or alerts had no channel to go to.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import logging
import os
import re
import shutil
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import notify
from .config import load_portfolio
from .data import get_provider, selected_provider
from .store import DEFAULT_DB, Store

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
    day = now.astimezone(NY).date()
    if now.astimezone(NY).hour < 10:          # before the open, today's bar doesn't exist yet
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


def check_channels(report: Report) -> bool:
    """Report each channel; True when at least one can deliver. A half-set Telegram is an error."""
    tg = notify.telegram_config()
    report.add("Telegram", tg)
    if tg not in ("configured", "not configured"):
        report.errors.append(f"Telegram is {tg}. Fix the repository secrets; nothing can be sent to Telegram.")
    others = [name for name, var in (("ntfy", "NTFY_TOPIC"), ("email", "SMTP_HOST")) if os.getenv(var)]
    if others:
        report.add("Other channels", ", ".join(others))
    return tg == "configured" or bool(others)


def holdings(mode: str, now: datetime, db: Path = DEFAULT_DB) -> Report:
    report = Report(mode, now)
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
        check_channels(report)
        return report
    held = sum(not h.is_watchlist for h in portfolio.holdings)
    report.add("Tickers", f"{len(portfolio.holdings)} ({held} with shares, {len(portfolio.holdings) - held} watchlist)")
    if not portfolio.holdings:
        report.errors.append(f"The {source} has no holdings, so nothing was scanned.")
        check_channels(report)
        return report
    if not held:
        report.warnings.append("No holding has a share count, so everything is treated as watchlist "
                               "(no stop-loss or position alerts).")

    can_deliver = check_channels(report)
    dry = mode == "holdings-dry-run"
    with contextlib.ExitStack() as stack:
        if dry:   # a throwaway copy: alerts found here are neither sent nor remembered
            tmp = Path(stack.enter_context(tempfile.TemporaryDirectory())) / "dry-run.db"
            if Path(db).exists():
                shutil.copy(db, tmp)
            db = tmp
        try:
            from .scanner import analyse
            provider = get_provider(selected_provider(portfolio.settings.data_provider))
            store = Store(db)
            # library output names tickers; keep it out of the public log
            sink = io.StringIO()
            logging.disable(logging.CRITICAL)
            try:
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    evals, alerts = analyse(portfolio, provider, store, quiet=True)
            finally:
                logging.disable(logging.NOTSET)
        except Exception as e:
            report.errors.append(f"The scanner failed ({type(e).__name__}); no analysis completed.")
            return report

    ok = [e for e in evals if not e.error]
    report.add("Analysed", f"{len(ok)} of {len(evals)}")
    if not ok:
        report.errors.append("No ticker could be analysed (market data unavailable?), so nothing was checked for alerts.")
    elif len(ok) < len(evals):
        report.warnings.append(f"{len(evals) - len(ok)} of {len(evals)} tickers couldn't be analysed this run.")
    latest, stale = freshness(ok, provider, now)
    report.add("Latest daily bar", f"{latest} (expected {last_session(now)})" if latest else "none")
    if ok and stale:
        report.warnings.append(f"{stale} of {len(ok)} analysed tickers have prices older than the last session "
                               "(a market holiday can cause this).")
    quotes = sum(bool(e.quote.get("fetched_at")) and not e.quote.get("error") for e in ok)
    report.add("Live quotes", f"{quotes} of {len(ok)}")
    report.add("New alerts", len(alerts))

    if dry:
        report.add("Delivery", f"dry run: {len(alerts)} alert(s) would be sent; nothing sent, alert history unchanged")
        if not can_deliver:
            report.warnings.append("No notification channel is configured: a live run would have nowhere to send alerts.")
        return report
    if not alerts:
        report.add("Delivery", "nothing new to send")
        if not can_deliver:
            report.warnings.append("No notification channel is configured, so future alerts won't reach you. "
                                   "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        return report
    if not can_deliver:
        report.add("Delivery", "not sent: no channel configured")
        report.errors.append(f"{len(alerts)} new alert(s) found but no notification channel is configured. "
                             "The alert history isn't saved on a failed run, so they're retried once a channel works.")
        return report
    results = notify.send(alerts, quiet=True)
    report.add("Delivery", "; ".join(f"{k}: {v}" for k, v in results.items() if v != "not configured"))
    for name, outcome in results.items():
        if outcome.startswith("failed"):
            report.errors.append(f"{name} {outcome}. The alert history isn't saved on a failed run, so they're retried.")
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
