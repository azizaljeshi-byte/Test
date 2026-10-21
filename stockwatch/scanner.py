"""Continuous scanner: python -m stockwatch.scanner [--once] [--demo]"""
from __future__ import annotations

import argparse
import logging
import time

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


def main(argv=None):
    p = argparse.ArgumentParser(description="Continuously scan your portfolio")
    p.add_argument("--portfolio", help="path to portfolio.yaml")
    p.add_argument("--once", action="store_true", help="run a single scan and exit")
    p.add_argument("--demo", action="store_true", help="use synthetic offline data")
    p.add_argument("--interval", type=int, help="minutes between scans (overrides config)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    base = load_portfolio(args.portfolio)
    provider = get_provider("demo" if args.demo else base.settings.data_provider)
    store = Store()
    interval = args.interval or base.settings.scan_interval_minutes

    while True:
        try:
            # re-read each loop so tickers added from the dashboard are picked up
            run_once(store.apply_overrides(base), provider, store)
        except Exception:
            log.exception("scan failed")
        if args.once:
            return
        time.sleep(interval * 60)


if __name__ == "__main__":
    main()
