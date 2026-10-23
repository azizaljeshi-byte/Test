"""Finnhub (free plan) as a second source for what Yahoo blocks on shared cloud servers:
analyst ratings, price targets, earnings history and calendar, insider trades, key ratios, news.

Set FINNHUB_API_KEY (free at finnhub.io). The free plan allows 60 requests a minute, so calls
are spaced out here and results are cached by the provider for hours.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger(__name__)

BASE = "https://finnhub.io/api/v1"
MIN_INTERVAL = 1.05            # seconds between requests: stays under 60 a minute
_lock = threading.Lock()
_last_call = [0.0]


def enabled() -> bool:
    return bool(os.getenv("FINNHUB_API_KEY"))


def _get(path: str, **params):
    key = os.getenv("FINNHUB_API_KEY")
    if not key:
        raise RuntimeError("FINNHUB_API_KEY not set")
    with _lock:   # pace requests across threads
        wait = _last_call[0] + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
    url = f"{BASE}{path}?{urllib.parse.urlencode({**params, 'token': key})}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=15) as r:
        return json.loads(r.read().decode())


def _pct(v):
    return v / 100 if isinstance(v, (int, float)) else None


def _try(name, fn, default):
    try:
        return fn()
    except Exception as e:   # one endpoint failing (e.g. premium-only) shouldn't drop the rest
        log.info("finnhub %s failed: %s", name, e)
        return default


# ------------------------------------------------------------------ mapped to the app's formats

def fundamentals(ticker: str) -> dict:
    m = (_get("/stock/metric", symbol=ticker, metric="all") or {}).get("metric") or {}
    prof = _try("profile", lambda: _get("/stock/profile2", symbol=ticker), {}) or {}
    cap = m.get("marketCapitalization") or prof.get("marketCapitalization")
    out = {
        "name": prof.get("name"), "industry": prof.get("finnhubIndustry"), "country": prof.get("country"),
        "website": prof.get("weburl"), "market_cap": cap * 1e6 if cap else None,   # Finnhub reports millions
        "pe_trailing": m.get("peTTM") or m.get("peBasicExclExtraTTM"), "price_to_sales": m.get("psTTM"),
        "revenue_growth": _pct(m.get("revenueGrowthTTMYoy")), "earnings_growth": _pct(m.get("epsGrowthTTMYoy")),
        "gross_margin": _pct(m.get("grossMarginTTM")), "operating_margin": _pct(m.get("operatingMarginTTM")),
        "profit_margin": _pct(m.get("netProfitMarginTTM")), "roe": _pct(m.get("roeTTM")),
        "current_ratio": m.get("currentRatioQuarterly"),
        "debt_to_equity": m.get("totalDebt/totalEquityQuarterly"),
        "source": "Finnhub",
    }
    return {k: v for k, v in out.items() if v is not None}


def street(ticker: str) -> dict:
    """Recommendation trend and price targets in the shape street.analyze expects."""
    recs = _try("recommendation", lambda: _get("/stock/recommendation", symbol=ticker), []) or []
    recs = sorted(recs, key=lambda r: r.get("period", ""), reverse=True)
    out = {"recs": [{"period": r.get("period"), "strongBuy": int(r.get("strongBuy") or 0), "buy": int(r.get("buy") or 0),
                     "hold": int(r.get("hold") or 0), "sell": int(r.get("sell") or 0),
                     "strongSell": int(r.get("strongSell") or 0)} for r in recs[:4]],
           "targets": {}}
    pt = _try("price target", lambda: _get("/stock/price-target", symbol=ticker), {}) or {}
    for key, src in (("low", "targetLow"), ("mean", "targetMean"), ("median", "targetMedian"), ("high", "targetHigh")):
        if pt.get(src):
            out["targets"][key] = float(pt[src])
    return out


def earnings(ticker: str) -> list[dict]:
    rows = _get("/stock/earnings", symbol=ticker) or []
    rows = sorted(rows, key=lambda r: r.get("period", ""), reverse=True)
    return [{"quarter": date.fromisoformat(r["period"]), "eps_actual": r.get("actual"), "eps_estimate": r.get("estimate"),
             "surprise_pct": _pct(r.get("surprisePercent"))} for r in rows[:4] if r.get("period")]


def next_earnings(ticker: str) -> date | None:
    today = date.today()
    cal = (_get("/calendar/earnings", symbol=ticker, **{"from": today.isoformat(),
                                                       "to": (today + timedelta(days=120)).isoformat()}) or {})
    dates = sorted(date.fromisoformat(e["date"]) for e in cal.get("earningsCalendar") or [] if e.get("date"))
    return next((d for d in dates if d >= today), None)


def insiders(ticker: str) -> list[dict]:
    rows = (_get("/stock/insider-transactions", symbol=ticker) or {}).get("data") or []
    out = []
    for r in rows[:40]:
        code = r.get("transactionCode")
        text = {"P": "Purchase", "S": "Sale"}.get(code, f"Code {code}")   # only open-market P/S count as signals
        when = r.get("transactionDate") or r.get("filingDate")
        price, change = r.get("transactionPrice") or 0, r.get("change") or 0
        out.append({"date": datetime.fromisoformat(when) if when else None, "insider": r.get("name"), "position": None,
                    "text": text, "shares": abs(change), "value": abs(change) * price if price else None})
    return out


def news(ticker: str, days: int = 4) -> list[dict]:
    today = date.today()
    rows = _get("/company-news", symbol=ticker, **{"from": (today - timedelta(days=days)).isoformat(),
                                                    "to": today.isoformat()}) or []
    return [{"title": r["headline"], "publisher": r.get("source"), "url": r.get("url"),
             "published": datetime.fromtimestamp(r["datetime"], tz=timezone.utc)}
            for r in sorted(rows, key=lambda r: r.get("datetime", 0), reverse=True)[:10] if r.get("headline")]


def quote(ticker: str) -> dict:
    """Finnhub's latest quote: price, today's high/low/open, previous close and the trade time (Unix seconds).
    A second source for the CIS shadow only; nothing in scoring or alerts reads it."""
    q = _get("/quote", symbol=ticker) or {}
    return {"price": q.get("c"), "high": q.get("h"), "low": q.get("l"), "open": q.get("o"),
            "prev_close": q.get("pc"), "time": q.get("t"), "source": "Finnhub"}
