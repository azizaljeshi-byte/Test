"""TradingView's technical rating as a second, independent opinion on a stock's structure. Display only.

Uses TradingView's public screener endpoint (no key): one request returns, for the tickers asked, its overall rating
(-1 strong sell to +1 strong buy, blended from ~26 moving-average and oscillator checks), the moving-average and
oscillator halves, RSI, ADX and the monthly classic pivot levels (support S1-S3, resistance R1-R3).

Unofficial and unsupported: it can change, rate-limit or block a cloud server at any time. Whatever fails returns None
and the screen says there was no read; nothing in scoring, status or alerts depends on it.
"""
from __future__ import annotations

import json
import logging
import math
import urllib.request

log = logging.getLogger(__name__)

URL = "https://scanner.tradingview.com/america/scan"
COLUMNS = ["name", "close", "Recommend.All", "Recommend.MA", "Recommend.Other", "RSI", "ADX",
           "Pivot.M.Classic.S3", "Pivot.M.Classic.S2", "Pivot.M.Classic.S1", "Pivot.M.Classic.Middle",
           "Pivot.M.Classic.R1", "Pivot.M.Classic.R2", "Pivot.M.Classic.R3"]
EXCHANGES = ("NASDAQ", "NYSE", "AMEX", "NYSEARCA", "BATS", "CBOE")       # real US listings first, OTC and others last
BUY, STRONG = 0.1, 0.5


def _post(payload: dict) -> dict:
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          "User-Agent": "Mozilla/5.0 (compatible; StockWatch)"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode())


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def signal(rating: float | None) -> tuple[str | None, bool]:
    """('buy' | 'sell' | 'neutral' | None, strong?) from the -1..+1 rating."""
    if rating is None:
        return None, False
    if rating >= BUY:
        return "buy", rating >= STRONG
    if rating <= -BUY:
        return "sell", rating <= -STRONG
    return "neutral", False


def _rank(symbol: str) -> int:
    ex = symbol.split(":")[0]
    return EXCHANGES.index(ex) if ex in EXCHANGES else len(EXCHANGES)


def read(tickers: list[str]) -> dict[str, dict]:
    """{ticker: opinion} for the tickers TradingView knows; tickers it doesn't know are simply absent."""
    want = [t.upper() for t in tickers if t]
    if not want:
        return {}
    payload = {"filter": [{"left": "name", "operation": "in_range", "right": want}], "options": {"lang": "en"},
               "markets": ["america"], "symbols": {"query": {"types": []}, "tickers": []}, "columns": COLUMNS,
               "range": [0, max(10, len(want) * 6)]}
    rows = (_post(payload) or {}).get("data") or []
    best: dict[str, tuple[int, dict]] = {}
    for row in rows:
        d = row.get("d") or []
        if len(d) != len(COLUMNS) or not isinstance(d[0], str):
            continue
        name = d[0].upper()
        rank = _rank(str(row.get("s") or ""))
        if name in best and best[name][0] <= rank:
            continue
        v = dict(zip(COLUMNS, d))
        rating = _num(v["Recommend.All"])
        sig, strong = signal(rating)
        levels = [x for x in (_num(v[c]) for c in COLUMNS[7:]) if x is not None and x > 0]
        if sig is None and not levels:
            continue
        best[name] = (rank, {"source": "TradingView", "signal": sig, "strength": "strong" if strong else None,
                             "rating": None if rating is None else round(rating, 2),
                             "ma": None if _num(v["Recommend.MA"]) is None else round(v["Recommend.MA"], 2),
                             "osc": None if _num(v["Recommend.Other"]) is None else round(v["Recommend.Other"], 2),
                             "rsi": _num(v["RSI"]), "adx": _num(v["ADX"]), "trending": None if _num(v["ADX"]) is None else v["ADX"] >= 25,
                             "levels": levels, "buy": None, "neutral": None, "sell": None})
    return {k: v[1] for k, v in best.items() if k in want}


def second_opinion(ticker: str) -> dict | None:
    """One ticker's read, or None when TradingView doesn't answer or doesn't know it."""
    try:
        return read([ticker]).get(ticker.upper())
    except Exception as e:      # unofficial endpoint: any failure is 'no read', never an error on screen
        log.info("tradingview %s failed: %s", ticker, e)
        return None
