"""S&P 500 opportunity scan: python -m stockwatch.market [--demo] [--notify]

Stage 1 screens every constituent on price action from one bulk download.
Stage 2 runs the full fundamental + technical evaluation on the best setups only,
which keeps the scan to a few hundred requests instead of several thousand.
"""
from __future__ import annotations

import argparse
import logging
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

from . import relative, technical, tradeplan
from .config import Holding, load_portfolio
from .data import get_provider
from .engine import evaluate
from .signals import OPPORTUNITY

log = logging.getLogger("stockwatch.market")

BUNDLED = Path(__file__).parent / "universe" / "sp500.csv"
LIVE_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
# triggers strong enough to put a stock on the shortlist by themselves
ENTRY_CODES = {"golden_cross", "reclaimed_200d", "bb_pullback", "volume_surge_up", "technical_turn"}
# supporting evidence: adds to the setup score, but not enough alone
SUPPORT_CODES = {"macd_bull", "leading_market", "rsi_oversold"}
_universe_cache: tuple[float, pd.DataFrame] | None = None


def load_universe(refresh_hours: float = 24) -> pd.DataFrame:
    """Current S&P 500 members (refreshed daily from a maintained list; bundled copy as fallback)."""
    global _universe_cache
    if _universe_cache and time.time() - _universe_cache[0] < refresh_hours * 3600:
        return _universe_cache[1]
    try:
        with urllib.request.urlopen(LIVE_URL, timeout=10) as r:
            raw = pd.read_csv(StringIO(r.read().decode()))
        df = pd.DataFrame({"ticker": raw["Symbol"].str.replace(".", "-", regex=False), "name": raw["Security"],
                           "sector": raw["GICS Sector"], "industry": raw["GICS Sub-Industry"], "cik": raw["CIK"]})
        if len(df) < 400:
            raise ValueError("list looks incomplete")
    except Exception as e:
        log.info("live S&P list unavailable (%s), using bundled copy", e)
        df = pd.read_csv(BUNDLED)
    _universe_cache = (time.time(), df)
    return df


def screen(histories: dict[str, pd.DataFrame], market: pd.DataFrame | None) -> pd.DataFrame:
    """Stage 1: technical setup score for every ticker."""
    rows = []
    for t, hist in histories.items():
        if len(hist) < 220:
            continue
        try:
            ts, m, sig = technical.analyze(hist, 3.0, owned=False)
            _, rs, rs_sig = relative.analyze(hist, market, None, None, tier=2)
        except Exception:
            continue
        opp = [s for s in sig + rs_sig if s.kind == OPPORTUNITY]
        entries = [s for s in opp if s.code in ENTRY_CODES
                   or (s.code == "new_52w_high" and m["trend"] == "up")]
        support = [s for s in opp if s.code in SUPPORT_CODES]
        pullback = m["trend"] == "up" and m["rsi"] < 45
        if not entries and not pullback:
            continue
        entries += support
        setup = ts + 6 * len(entries) + (8 if pullback else 0) + float(np.clip((rs["rs_spy_3m"] or 0) * 40, -8, 8))
        rows.append({"ticker": t, "setup": setup, "tech": ts, "trend": m["trend"], "rsi": m["rsi"],
                     "rs_spy_3m": rs["rs_spy_3m"], "triggers": [s.message for s in entries]
                     + (["Pullback within an uptrend"] if pullback else [])})
    return pd.DataFrame(rows).sort_values("setup", ascending=False) if rows else pd.DataFrame()


def run(provider, top: int = 25, progress=None, exclude: set[str] = frozenset()) -> dict:
    """Full scan. progress(fraction, text) is called as stages complete."""
    def step(frac, text):
        if progress:
            progress(frac, text)
        log.info(text)

    portfolio = load_portfolio()
    universe = load_universe()
    tickers = tuple(t for t in universe["ticker"] if t not in exclude)
    step(0.05, f"Downloading prices for {len(tickers)} S&P 500 stocks...")
    histories = provider.bulk_history(tickers)
    try:
        market = provider.history(portfolio.settings.benchmark)
    except Exception:
        market = None
    step(0.45, f"Screening {len(histories)} price histories for setups...")
    shortlist = screen(histories, market)
    picks = shortlist.head(top)
    step(0.55, f"{len(shortlist)} setups found; evaluating the top {len(picks)} in depth...")

    names = universe.set_index("ticker")
    evaluated = []
    # progress is reported from this thread only: UI callbacks (Streamlit) can't run in workers
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(evaluate, Holding(row.ticker, 2, 0), portfolio, provider, light=True,
                               hist=histories[row.ticker]): row for row in picks.itertuples()}
        for fut in as_completed(futures):
            row = futures[fut]
            evaluated.append((fut.result(), row))
            step(0.55 + 0.4 * len(evaluated) / max(len(picks), 1),
                 f"Evaluated {row.ticker} ({len(evaluated)}/{len(picks)})")

    results = []
    for e, row in evaluated:
        if e.error:
            continue
        rank = {"BUY SETUP": 0, "WATCH": 1, "AVOID": 2}.get(e.verdict, 1)
        results.append({
            "ticker": e.ticker, "name": names.at[e.ticker, "name"] if e.ticker in names.index else e.name,
            "sector": names.at[e.ticker, "sector"] if e.ticker in names.index else None,
            "verdict": e.verdict, "composite": e.composite, "fundamental": e.fundamental_score,
            "technical": e.technical_score, "price": e.price, "rank": rank,
            "triggers": row.triggers, "rs_spy_3m": row.rs_spy_3m,
            "earnings_days": (e.events or {}).get("days_to_earnings"),
            "top_signals": [s.message for s in e.signals if s.kind == OPPORTUNITY][:3],
            "top_risks": [s.message for s in e.signals if s.kind != OPPORTUNITY and s.severity >= 2][:2],
            "plan": e.plan,
        })
    results.sort(key=lambda r: (r["rank"], -r["composite"]))
    step(1.0, f"Done: {sum(r['verdict'] == 'BUY SETUP' for r in results)} buy setups among {len(results)} finalists")
    return {"universe": len(tickers), "priced": len(histories), "setups": len(shortlist),
            "results": results, "evaluations": [e for e, _ in evaluated if not e.error]}


def main(argv=None):
    from . import notify
    from .signals import Signal
    from .store import Store

    p = argparse.ArgumentParser(description="Scan the S&P 500 for opportunities")
    p.add_argument("--demo", action="store_true")
    p.add_argument("--notify", action="store_true", help="push the top buy setups")
    p.add_argument("--top", type=int, default=25)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    portfolio = load_portfolio()
    provider = get_provider("demo" if args.demo else portfolio.settings.data_provider)
    scan = run(provider, args.top, exclude={h.ticker for h in portfolio.holdings})
    store = Store()
    store.save_market_scan(scan)
    buys = [r for r in scan["results"] if r["verdict"] == "BUY SETUP"][:5]
    for r in scan["results"][:10]:
        print(f"{r['ticker']:6} {r['verdict']:10} {r['composite']:5.1f}  {'; '.join(r['triggers'][:2])}")
    if args.notify and buys:
        notify.send([(r["ticker"], r["price"], "S&P SCAN", Signal(OPPORTUNITY, "market", "market_scan",
                      f"{r['name']}: {'; '.join(r['triggers'][:1])}. Plan: {tradeplan.summary(r.get('plan'))}", 2))
                     for r in buys])


if __name__ == "__main__":
    main()
