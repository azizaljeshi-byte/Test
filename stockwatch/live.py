"""Background tracker for the dashboard: while the market is trading, re-run the full analysis
every couple of minutes and refresh prices every minute, writing results to the store. The page
only reads the store, so taps never wait on a sweep."""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

from . import market
from .config import load_portfolio
from .data import us_session
from .scanner import refresh_quotes, run_once
from .store import Store

log = logging.getLogger("stockwatch.live")

# full analysis (technicals with today's live bar, verdicts, plans, alerts) and price-only refreshes
SWEEP_SECONDS = int(os.getenv("STOCKWATCH_SWEEP_SECONDS", "120"))
QUOTE_SECONDS = int(os.getenv("STOCKWATCH_QUOTE_SECONDS", "60"))
MARKET_SECONDS = int(os.getenv("STOCKWATCH_MARKET_SECONDS", "1800"))   # S&P 500 opportunity scan

MARKET_LOCK = threading.Lock()   # one S&P scan at a time (tracker or the button)

# one sweep at a time, whether it comes from the tracker or the Sweep now button
SWEEP_LOCK = threading.Lock()


def current_portfolio(store: Store):
    base = load_portfolio()
    return base if base.sheet_url else store.apply_overrides(base)


def market_scan(provider, store: Store | None = None, progress=None) -> list[dict]:
    """Run the S&P 500 scan, save it, and log buy setups that are new since the last scan."""
    store = store or Store()
    with MARKET_LOCK:
        portfolio = current_portfolio(store)
        before = store.latest_market_scan() or {}
        was = {r["ticker"] for r in before.get("results", []) if r["verdict"] == "BUY SETUP"}
        result = market.run(provider, progress=progress, exclude={h.ticker for h in portfolio.holdings})
        store.save_market_scan(result)
        new = [r for r in result["results"] if r["verdict"] == "BUY SETUP" and r["ticker"] not in was]
        return store.record_market_alerts(new)


def sweep(provider, store: Store | None = None):
    store = store or Store()
    with SWEEP_LOCK:
        return run_once(current_portfolio(store), provider, store)


class Tracker:
    def __init__(self, provider, store_path=None, start: bool = True):
        self.provider = provider
        self.store_path = store_path
        self.last_sweep = 0.0
        self.last_quotes = 0.0
        self.last_error: str | None = None
        self.last_market: float | None = None   # read from the store on first use, so restarts don't rescan
        self.market_running = False
        self.market_error: str | None = None
        self.running = True
        self._thread = threading.Thread(target=self._loop, name="stockwatch-tracker", daemon=True)
        if start:
            self._thread.start()

    def status(self) -> dict:
        now = time.time()
        return {"alive": self._thread.is_alive(), "session": us_session(),
                "market_running": self.market_running, "market_error": self.market_error,
                "next_market_in": (max(0, int(self.last_market + MARKET_SECONDS - now))
                                   if self.last_market else None),
                "next_sweep_in": max(0, int(self.last_sweep + SWEEP_SECONDS - now)) if self.last_sweep else 0,
                "last_sweep": datetime.fromtimestamp(self.last_sweep, tz=timezone.utc) if self.last_sweep else None,
                "error": self.last_error}

    def step(self, store: Store, now: float | None = None) -> str:
        """One tracker cycle; returns what it did (for tests and logs)."""
        now = now or time.time()
        if us_session() == "CLOSED":
            return "closed"
        if now - self.last_sweep >= SWEEP_SECONDS:
            sweep(self.provider, store)
            self.last_sweep = self.last_quotes = time.time()
            return "sweep"
        if now - self.last_quotes >= QUOTE_SECONDS:
            refresh_quotes(current_portfolio(store), self.provider, store)
            self.last_quotes = time.time()
            return "quotes"
        return "idle"

    def maybe_market_scan(self, store: Store, now: float | None = None, background: bool = True) -> bool:
        """Start the S&P scan when it's due. It runs on its own thread so the 2-minute tracking
        isn't held up by a scan that can take a minute or two."""
        now = now or time.time()
        if self.last_market is None:
            last = store.latest_market_scan()
            self.last_market = datetime.fromisoformat(last["scanned_at"]).timestamp() if last else 0.0
        if us_session() == "CLOSED" or self.market_running or now - self.last_market < MARKET_SECONDS:
            return False
        self.market_running = True
        self.last_market = now

        def run():
            try:
                market_scan(self.provider, Store(self.store_path) if self.store_path else Store())
                self.market_error = None
            except Exception as e:
                self.market_error = str(e)
                log.exception("S&P scan failed")
            finally:
                self.last_market = time.time()
                self.market_running = False

        if background:
            threading.Thread(target=run, name="stockwatch-sp500", daemon=True).start()
        else:
            run()
        return True

    def _loop(self):
        store = Store(self.store_path) if self.store_path else Store()   # its own connection for this thread
        while self.running:
            try:
                self.step(store)
                self.maybe_market_scan(store)
                self.last_error = None
            except Exception as e:   # keep tracking through a bad sweep
                self.last_error = str(e)
                log.exception("live tracker iteration failed")
            time.sleep(5)
