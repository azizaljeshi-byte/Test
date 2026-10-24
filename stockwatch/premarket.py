"""The US pre-market briefing inside the app: indexes and futures, macro, the 11 sectors, your biggest movers, your
exposure by industry (percent only, never amounts) and the news. Display only; nothing here changes a score or call.

Built from what the app already holds (the scan snapshots) plus one bulk price download for ~30 market symbols and,
when FINNHUB_API_KEY is set, Finnhub's market headlines. It runs on its own thread (`request`), never inside the page.

Honest limits: movers come from your tracked names, not the whole market; there is no economic calendar and no written
"why" per sector (those need research the app can't do by itself); anything that can't be priced shows as n/a.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import data, finnhub

log = logging.getLogger(__name__)

INDEXES = [("S&P 500", "SPY", "ES=F"), ("Nasdaq 100", "QQQ", "NQ=F"), ("Dow", "DIA", "YM=F"), ("Russell 2000", "IWM", "RTY=F")]
MACRO = [("VIX", "^VIX", "level"), ("US 10Y yield", "^TNX", "yield"), ("Dollar (DXY)", "DX-Y.NYB", "level"),
         ("Oil (WTI)", "CL=F", "level"), ("Gold", "GC=F", "level"), ("Bitcoin", "BTC-USD", "level")]
SECTORS = [("Technology", "XLK"), ("Communication", "XLC"), ("Consumer cyclical", "XLY"), ("Consumer defensive", "XLP"),
           ("Health care", "XLV"), ("Financials", "XLF"), ("Industrials", "XLI"), ("Energy", "XLE"),
           ("Utilities", "XLU"), ("Real estate", "XLRE"), ("Materials", "XLB")]
SECTOR_OF = {"Technology": "Technology", "Communication Services": "Communication", "Consumer Cyclical": "Consumer cyclical",
             "Consumer Defensive": "Consumer defensive", "Healthcare": "Health care", "Financial Services": "Financials",
             "Industrials": "Industrials", "Energy": "Energy", "Utilities": "Utilities", "Real Estate": "Real estate",
             "Basic Materials": "Materials"}
ALWAYS_PARTIAL_TODAY = ("=F", "-USD")      # futures and crypto trade through the day: a bar dated today is never complete
MOVER_MIN = 0.03                           # "major moves only"
MOVERS_MAX = 5
NEWS_HOURS = 36
TTL = 300                                  # seconds a built briefing stays fresh


def all_symbols() -> tuple[str, ...]:
    out = []
    for _, etf, fut in INDEXES:
        out += [etf, fut]
    out += [s for _, s, _ in MACRO] + [s for _, s in SECTORS]
    return tuple(dict.fromkeys(out))


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def prior_session(df, symbol: str, now: datetime) -> tuple[float | None, float | None, str | None]:
    """(last completed close, its % change from the close before, its date) from daily bars. A bar dated today in New
    York is dropped while it can still be incomplete (before the close, and always for futures and crypto)."""
    if df is None or len(df) < 3 or "Close" not in df:
        return None, None, None
    close = df["Close"].astype(float).dropna()
    close = close[close > 0]
    if len(close) < 3:
        return None, None, None
    today = now.astimezone(data.NY).date()
    idx = pd.to_datetime(close.index)
    idx = idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx
    if idx[-1].date() == today and (symbol.endswith(ALWAYS_PARTIAL_TODAY) or data.us_session(now) in ("PRE", "REGULAR")):
        close, idx = close.iloc[:-1], idx[:-1]
    if len(close) < 2:
        return None, None, None
    return float(close.iloc[-1]), float(close.iloc[-1] / close.iloc[-2] - 1), idx[-1].date().isoformat()


def live_change(q: dict | None) -> float | None:
    """Today's move: the live change in the regular session, else the pre-market / after-hours change from the last
    regular close. None when there is no trade to measure."""
    q = q or {}
    return _num(q.get("live_change")) if _num(q.get("live_change")) is not None else _num(q.get("ext_change"))


def row(label: str, symbol: str, hist: dict, quotes: dict, now: datetime, kind: str = "level", future: str | None = None) -> dict:
    last, prior, as_of = prior_session(hist.get(symbol), symbol, now)
    out = {"label": label, "symbol": symbol, "last": last, "prior": prior, "as_of": as_of,
           "now": live_change(quotes.get(symbol)), "kind": kind, "future": None}
    if future:
        out["future"] = {"symbol": future, "now": live_change(quotes.get(future))}
    out["known"] = last is not None
    return out


def exposure(snaps: list[dict]) -> list[dict]:
    """Owned positions grouped by sector as a share of the owned total: percent only, never amounts."""
    groups: dict[str, dict] = {}
    total = 0.0
    for s in snaps:
        p = s.get("payload") or {}
        value = _num((p.get("position") or {}).get("value"))
        if p.get("watchlist") or not value or value <= 0:
            continue
        sector = SECTOR_OF.get((p.get("profile") or {}).get("sector") or "", (p.get("profile") or {}).get("sector") or "Other")
        g = groups.setdefault(sector, {"sector": sector, "value": 0.0, "names": []})
        g["value"] += value
        g["names"].append(s["ticker"])
        total += value
    out = [{"sector": g["sector"], "pct": g["value"] / total, "names": sorted(g["names"])} for g in groups.values()] if total else []
    return sorted(out, key=lambda g: -g["pct"])


def movers(snaps: list[dict]) -> dict:
    """The biggest moves among tracked names (owned and watchlist): last session, and extended hours / live."""
    prior, now = [], []
    for s in snaps:
        p = s.get("payload") or {}
        d = _num((p.get("technical") or {}).get("day_change"))
        q = p.get("quote") or {}
        n = live_change(q) if q.get("market_state") else None
        held = not p.get("watchlist")
        if d is not None and abs(d) >= MOVER_MIN:
            prior.append({"ticker": s["ticker"], "pct": d, "held": held})
        if n is not None and abs(n) >= MOVER_MIN:
            now.append({"ticker": s["ticker"], "pct": n, "held": held, "session": q.get("ext_session") or q.get("market_state")})
    key = lambda m: -abs(m["pct"])
    return {"prior": sorted(prior, key=key)[:MOVERS_MAX * 2], "now": sorted(now, key=key)[:MOVERS_MAX * 2]}


def holdings_news(snaps: list[dict], now: datetime) -> list[dict]:
    seen, out = set(), []
    for s in snaps:
        p = s.get("payload") or {}
        for n in (p.get("events") or {}).get("news") or []:
            try:
                when = datetime.fromisoformat(str(n["published"]))
            except (KeyError, ValueError):
                continue
            when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
            title = (n.get("title") or "").strip()
            if not title or title.lower() in seen or now - when > timedelta(hours=NEWS_HOURS):
                continue
            seen.add(title.lower())
            out.append({"ticker": s["ticker"], "title": title, "publisher": n.get("publisher"), "url": n.get("url"),
                        "tone": n.get("tone"), "published": when.isoformat(timespec="minutes"), "held": not p.get("watchlist")})
    held = sorted((n for n in out if n["held"]), key=lambda n: n["published"], reverse=True)
    rest = sorted((n for n in out if not n["held"]), key=lambda n: n["published"], reverse=True)
    return (held + rest)[:10]


def takeaway(indexes: list[dict], macro: list[dict]) -> str:
    def move(r):
        c = r["future"]["now"] if r.get("future") and r["future"]["now"] is not None else r["now"]
        return c
    spx = next((r for r in indexes if r["symbol"] == "SPY"), None)
    ndx = next((r for r in indexes if r["symbol"] == "QQQ"), None)
    bits = []
    for name, r in (("S&P 500", spx), ("Nasdaq 100", ndx)):
        c = move(r) if r else None
        if c is not None:
            bits.append(f"{name} {c:+.1%}")
    vix = next((r for r in macro if r["symbol"] == "^VIX"), None)
    if vix and vix["last"] is not None:
        bits.append(f"VIX {vix['last']:.1f}")
    return " · ".join(bits) if bits else "No market prices yet."


def build(provider, snaps: list[dict], now: datetime | None = None, news_fn=None) -> dict:
    """The whole briefing as plain data. Every part fails alone: a part that can't be built is listed in `missing`."""
    now = now or datetime.now(timezone.utc)
    missing: list[str] = []
    hist: dict = {}
    quotes: dict = {}
    syms = all_symbols()
    try:
        hist = provider.bulk_history(syms, "3mo") or {}
    except Exception as e:
        log.info("briefing history failed: %s", e)
        missing.append("market prices (history download failed)")
    try:
        quotes = provider.bulk_quotes(list(syms)) or {}
    except Exception as e:
        log.info("briefing quotes failed: %s", e)
        missing.append("live and pre-market prices")
    indexes = [row(n, etf, hist, quotes, now, future=fut) for n, etf, fut in INDEXES]
    macro = [row(n, s, hist, quotes, now, kind=k) for n, s, k in MACRO]
    sectors = [row(n, s, hist, quotes, now) for n, s in SECTORS]
    for r in sectors:       # the tracked names in each sector, so a sector move says which of yours it touches
        r["names"] = sorted(s["ticker"] for s in snaps
                            if SECTOR_OF.get(((s.get("payload") or {}).get("profile") or {}).get("sector") or "") == r["label"])[:6]
    if not any(r["known"] for r in indexes + macro + sectors) and not any("history" in m for m in missing):
        missing.append("market prices (nothing could be priced)")
    market_news, news_why = [], None
    fetch = news_fn if news_fn is not None else (finnhub.market_news if finnhub.enabled() else None)
    if fetch is None:
        news_why = "no FINNHUB_API_KEY is set, so there are no market headlines"
    else:
        try:
            market_news = [{**n, "published": n["published"].isoformat(timespec="minutes")} for n in fetch()]
        except Exception as e:
            log.info("briefing market news failed: %s", e)
            news_why = "Finnhub didn't return market headlines"
    return {"as_of": now.isoformat(timespec="minutes"), "session": data.us_session(now), "takeaway": takeaway(indexes, macro),
            "indexes": indexes, "macro": macro, "sectors": sectors, "exposure": exposure(snaps), "movers": movers(snaps),
            "holdings_news": holdings_news(snaps, now), "market_news": market_news, "market_news_why": news_why,
            "missing": missing,
            "limits": ["Movers cover your tracked names, not the whole market.",
                       "No economic calendar and no written reason per sector: the app can't research those by itself."]}


# ---- background cache: the page asks, a thread builds, the page shows the last good one
_lock = threading.Lock()
_state: dict = {"data": None, "built": 0.0, "running": False, "error": None}


def request(provider, snaps: list[dict], force: bool = False) -> None:
    """Start a build on its own thread unless a fresh one exists or one is running."""
    with _lock:
        fresh = _state["data"] is not None and time.monotonic() - _state["built"] < TTL
        if _state["running"] or (fresh and not force):
            return
        _state["running"] = True

    def run():
        try:
            result = build(provider, snaps)
            with _lock:
                _state.update(data=result, built=time.monotonic(), error=None)
        except Exception as e:
            log.exception("briefing build failed")
            with _lock:
                _state["error"] = str(e)[:160]
        finally:
            with _lock:
                _state["running"] = False
    threading.Thread(target=run, name="stockwatch-briefing", daemon=True).start()


def current() -> dict:
    """{'data': last good briefing or None, 'running': bool, 'error': str | None, 'age': seconds | None}"""
    with _lock:
        return {"data": _state["data"], "running": _state["running"], "error": _state["error"],
                "age": None if _state["data"] is None else int(time.monotonic() - _state["built"])}
