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


WIDE_MAX = int(os.getenv("STOCKWATCH_WIDE_MAX", "30"))     # market stocks added to the live sweep (0 switches it off)


def wide_extras(store: Store, held: set[str], limit: int | None = None) -> list[str]:
    """Stocks outside the watchlist that Quick and the New call account may also trade (owner, 30 Oct: open both to the
    whole market). First any stock with an open trade (its stop must always be watched), then the best setups of the last
    S&P 500 scan, up to `limit`. They get the same live prices and the same one-call as tracked stocks, but no alerts and
    no card on the Radar."""
    limit = WIDE_MAX if limit is None else limit
    if limit <= 0:
        return []
    import json
    out: list[str] = []
    try:
        for key in ("quick_book", "paper_newcall_book"):
            raw = store.get_setting(key)
            for t in ((json.loads(raw) if raw else {}).get("positions") or {}):
                if t not in held and t not in out:
                    out.append(t)                      # an open trade is always tracked, whatever the limit
    except Exception:
        log.exception("open-trade tickers could not be read")
    try:
        room = limit
        for r in (store.latest_market_scan() or {}).get("results", []):
            t = r.get("ticker")
            if room <= 0:
                break
            if t and t not in held and t not in out and r.get("verdict") != "AVOID":
                out.append(t)
                room -= 1
    except Exception:
        log.exception("market scan list could not be read")
    return out


def current_portfolio(store: Store, wide: bool = False):
    base = load_portfolio()
    base = base if base.sheet_url else store.apply_overrides(base)
    if not wide:
        return base
    from dataclasses import replace
    from .config import Holding
    extras = wide_extras(store, {h.ticker for h in base.holdings})
    if not extras:
        return base
    return replace(base, holdings=list(base.holdings) + [Holding(t, 2, 0) for t in extras], extras=frozenset(extras))


def market_scan(provider, store: Store | None = None, progress=None) -> list[dict]:
    """Run the S&P 500 scan, save it, and log buy setups that are new since the last scan."""
    store = store or Store()
    with MARKET_LOCK:
        portfolio = current_portfolio(store)
        before = store.latest_market_scan() or {}
        was = {r["ticker"] for r in before.get("results", []) if r["verdict"] == "BUY SETUP"}
        result = market.run(provider, progress=progress, exclude={h.ticker for h in portfolio.holdings})
        stats = result.pop("stats", None)
        if stats:
            import json
            store.set_setting("universe_stats", json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "stats": stats}))
        store.save_market_scan(result)
        new = [r for r in result["results"] if r["verdict"] == "BUY SETUP" and r["ticker"] not in was]
        return store.record_market_alerts(new)


def sweep(provider, store: Store | None = None):
    store = store or Store()
    with SWEEP_LOCK:
        return run_once(current_portfolio(store, wide=True), provider, store)


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
            refresh_quotes(current_portfolio(store, wide=True), self.provider, store)
            self.last_quotes = time.time()
            return "quotes"
        return "idle"

    def maybe_market_scan(self, store: Store, now: float | None = None, background: bool = True,
                          force: bool = False) -> bool:
        """Start the S&P scan when it's due. It runs on its own thread so the 2-minute tracking
        isn't held up by a scan that can take a minute or two."""
        now = now or time.time()
        if self.last_market is None:
            last = store.latest_market_scan()
            self.last_market = datetime.fromisoformat(last["scanned_at"]).timestamp() if last else 0.0
        # the S&P scan waits for the first portfolio sweep, which needs the same slow data sources more
        if self.market_running or (not force and (us_session() == "CLOSED" or not self.last_sweep
                                                   or now - self.last_market < MARKET_SECONDS)):
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
                if time.time() - getattr(self, "_paper_at", 0.0) >= 20:
                    self._paper_at = time.time()
                    # the main Paper account and the whole-watchlist account are switched off (owner, 30 Oct); their history stays stored
                    try:
                        from . import events, paper_newcall
                        nc = paper_newcall.tick(store)  # the technical-first one-call traded on paper, in its own account
                        if nc.get("did"):
                            events.trades("New call", nc["did"], paper_newcall.load_book(store), store)
                    except Exception:
                        log.exception("new-call paper step failed")
                    try:
                        from . import events, quick
                        qd = quick.tick(store).get("did")                      # the Quick tab's own fake account, separate from Paper
                        if qd:
                            events.trades("Quick", qd, quick.load_book(store, migrate=False), store)
                    except Exception:
                        log.exception("quick trading step failed")
                    try:
                        from . import candidates
                        candidates.tick(store)                                 # the shared list of stocks worth watching, and what each account did with them
                    except Exception:
                        log.exception("candidates step failed")
                    try:
                        from . import jobs
                        jobs.tick()                                            # run-once study jobs, only when data/run_job.txt exists
                    except Exception:
                        log.exception("job runner step failed")
                    try:
                        from . import testlist
                        testlist.tick(store)                                   # the manual test list: breakouts with entry, stop and target, log only
                    except Exception:
                        log.exception("test list step failed")
                    try:
                        from . import agent
                        agent.tick(self.store_path)                            # the AI agent: its own thread, so a slow answer never delays a stop
                    except Exception:
                        log.exception("agent step failed")
                    try:
                        from . import ask_ai
                        ask_ai.tick(self.store_path)                           # "Ask the AI" requests from the page, own thread
                    except Exception:
                        log.exception("ask_ai step failed")
                    try:
                        from . import funnel
                        funnel.run_async(self.store_path)                      # whole-S&P sector/industry read every 5 minutes, own thread, log only
                    except Exception:
                        log.exception("funnel step failed")
                    try:
                        from . import extended
                        extended.run_async(self.store_path)                    # pre-market / after-hours monitor, own thread, log only
                    except Exception:
                        log.exception("extended hours step failed")
                    try:
                        from . import dbtrim, store as store_module
                        dbtrim.run_async(self.store_path or store_module.DEFAULT_DB)   # hourly, own thread: keeps the database from growing
                    except Exception:
                        log.exception("database clean-up step failed")
                    try:
                        from . import backup
                        backup.run_async()         # once a day after the US session closes, on its own thread: never blocks the tracker
                    except Exception:
                        log.exception("backup step failed")
                if self.last_sweep and self.last_sweep != getattr(self, "_flip_at", None):
                    self._flip_at = self.last_sweep               # once per finished sweep: owned stocks turning EXIT, new buy signals
                    try:
                        from . import events
                        pf = current_portfolio(store, wide=True)
                        snaps_now = store.latest_snapshots()
                        events.call_flips(store, snaps_now, pf.holdings, pf.extras)
                        events.moves(store, snaps_now, pf.holdings, pf.extras)
                        events.signals(store, snaps_now, pf.holdings, pf.extras)
                    except Exception:
                        log.exception("push step failed")
                self.maybe_market_scan(store)
                self.last_error = None
            except Exception as e:   # keep tracking through a bad sweep
                self.last_error = str(e)
                log.exception("live tracker iteration failed")
            time.sleep(5)
