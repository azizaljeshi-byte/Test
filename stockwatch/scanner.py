"""Continuous scanner: python -m stockwatch.scanner [--once] [--demo]"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone

from . import notify
from .config import load_portfolio
from .data import get_provider
from .engine import Evaluation, scan
from .store import Store

log = logging.getLogger("stockwatch")


def run_once(portfolio, provider, store: Store) -> list[Evaluation]:
    evals = scan(portfolio, provider)
    alerts = []
    for e in evals:
        store.save_snapshot(e)
        if e.error:
            log.warning("%s: %s", e.ticker, e.error)
            continue
        alerts += [(e.ticker, e.price, e.verdict, s)
                   for s in store.record_alerts(e, portfolio.settings.alert_cooldown_hours)]
    notify.send(alerts)
    log.info("scanned %d tickers, %d new alerts", len(evals), len(alerts))
    return evals


def refresh_quotes(portfolio, provider, store: Store) -> int:
    """Fast path between sweeps: refresh only the live / extended-hours quotes, in one bulk request
    when the provider supports it."""
    tickers = [h.ticker for h in portfolio.holdings]
    try:
        if hasattr(provider, "bulk_quotes"):
            quotes = provider.bulk_quotes(tickers)
        else:
            quotes = {t: provider.quote(t) for t in tickers}
    except Exception as e:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        quotes = {t: {"error": str(e), "fetched_at": stamp} for t in tickers}
    for ticker, q in quotes.items():
        store.update_quote(ticker, q)
    return sum(1 for q in quotes.values() if q.get("ext_price") is not None or q.get("live_price") is not None)


def main(argv=None):
    p = argparse.ArgumentParser(description="Continuously scan your portfolio")
    p.add_argument("--portfolio", help="path to portfolio.yaml")
    p.add_argument("--once", action="store_true", help="run a single scan and exit")
    p.add_argument("--demo", action="store_true", help="use synthetic offline data")
    p.add_argument("--interval", type=int, help="minutes between scans (overrides config)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    first = load_portfolio(args.portfolio)
    provider = get_provider("demo" if args.demo else first.settings.data_provider)
    store = Store()
    interval = args.interval or first.settings.scan_interval_minutes

    while True:
        try:
            # re-read each loop so edits to the Google Sheet (or dashboard additions) are picked up
            portfolio = load_portfolio(args.portfolio)
            if portfolio.sheet_error:
                log.warning("Google Sheet unavailable, using the YAML list: %s", portfolio.sheet_error)
            if not portfolio.sheet_url:
                portfolio = store.apply_overrides(portfolio)
            run_once(portfolio, provider, store)
        except Exception:
            log.exception("scan failed")
        if args.once:
            return
        time.sleep(interval * 60)


if __name__ == "__main__":
    main()
