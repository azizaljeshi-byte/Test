"""Market data providers.

Every provider returns:
  * history(ticker)      -> DataFrame indexed by date with Open/High/Low/Close/Volume
  * fundamentals(ticker) -> dict with the normalized keys listed in FUNDAMENTAL_KEYS
                            (missing values are None)
"""
from __future__ import annotations

import logging
import threading
import time
import zlib
from concurrent.futures import Future
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

FUNDAMENTAL_KEYS = [
    "name", "sector", "market_cap",
    "pe_trailing", "pe_forward", "peg",
    "revenue_growth", "earnings_growth",          # fractions, 0.12 = 12%
    "gross_margin", "operating_margin", "profit_margin", "roe",
    "debt_to_equity",                             # ratio, 1.5 = 150%
    "current_ratio", "free_cash_flow",
    "target_mean_price", "recommendation_mean",   # 1 = strong buy ... 5 = sell
]


# Sector ETF used to tell stock-specific weakness from sector-wide moves.
SECTOR_ETFS = {
    "Technology": "XLK", "Communication Services": "XLC", "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP", "Healthcare": "XLV", "Financial Services": "XLF",
    "Industrials": "XLI", "Energy": "XLE", "Utilities": "XLU", "Real Estate": "XLRE",
    "Basic Materials": "XLB",
}


class DataProvider(Protocol):
    def history(self, ticker: str, period: str = "2y") -> pd.DataFrame: ...
    def fundamentals(self, ticker: str) -> dict: ...

    def events(self, ticker: str) -> dict:
        """{"earnings_date": date | None,
            "news": [{"title", "publisher", "url", "published": datetime}],
            "rating_changes": [{"date": datetime, "firm", "action", "from_grade", "to_grade"}]}
        action is one of up / down / init / main / reit."""
        ...


class YahooProvider:
    """Free data via yfinance. Fine for personal use; not an official feed."""

    _MAP = {
        "name": "shortName", "sector": "sector", "market_cap": "marketCap",
        "pe_trailing": "trailingPE", "pe_forward": "forwardPE",
        "peg": "trailingPegRatio", "revenue_growth": "revenueGrowth",
        "earnings_growth": "earningsGrowth", "gross_margin": "grossMargins",
        "operating_margin": "operatingMargins", "profit_margin": "profitMargins",
        "roe": "returnOnEquity", "debt_to_equity": "debtToEquity",
        "current_ratio": "currentRatio", "free_cash_flow": "freeCashflow",
        "target_mean_price": "targetMeanPrice",
        "recommendation_mean": "recommendationMean",
    }

    def __init__(self):
        import yfinance  # imported lazily so the demo provider works without it
        self._yf = yfinance

    def history(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        df = self._yf.Ticker(ticker).history(period=period, auto_adjust=True)
        if df.empty:
            raise ValueError(f"No price history for {ticker}")
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df[["Open", "High", "Low", "Close", "Volume"]]

    def fundamentals(self, ticker: str) -> dict:
        info = self._yf.Ticker(ticker).info or {}
        out = {k: info.get(src) for k, src in self._MAP.items()}
        if out["peg"] is None:
            out["peg"] = info.get("pegRatio")
        if out["debt_to_equity"] is not None:
            out["debt_to_equity"] = out["debt_to_equity"] / 100.0  # Yahoo reports percent
        return out

    def events(self, ticker: str) -> dict:
        t = self._yf.Ticker(ticker)
        out = {"earnings_date": None, "news": [], "rating_changes": []}
        # each feed fails independently on Yahoo, so one missing piece doesn't drop the rest
        try:
            dates = (t.calendar or {}).get("Earnings Date") or []
            upcoming = sorted(d for d in dates if d >= date.today())
            out["earnings_date"] = upcoming[0] if upcoming else None
        except Exception as e:
            log.info("calendar failed for %s: %s", ticker, e)
        try:
            out["news"] = [n for n in (_parse_news(a) for a in (t.news or [])) if n]
        except Exception as e:
            log.info("news failed for %s: %s", ticker, e)
        try:
            ud = t.upgrades_downgrades
            if ud is not None and not ud.empty:
                for when, row in ud.sort_index(ascending=False).head(15).iterrows():
                    out["rating_changes"].append({
                        "date": pd.Timestamp(when).to_pydatetime(), "firm": row.get("Firm"),
                        "action": row.get("Action"), "from_grade": row.get("FromGrade"),
                        "to_grade": row.get("ToGrade")})
        except Exception as e:
            log.info("rating changes failed for %s: %s", ticker, e)
        return out


def _parse_news(a: dict) -> dict | None:
    """Yahoo has shipped two news formats; accept both."""
    c = a.get("content") or a
    title = c.get("title")
    if not title:
        return None
    if c.get("pubDate"):
        published = datetime.fromisoformat(c["pubDate"].replace("Z", "+00:00"))
    elif a.get("providerPublishTime"):
        published = datetime.fromtimestamp(a["providerPublishTime"], tz=timezone.utc)
    else:
        return None
    provider = c.get("provider")
    url = (c.get("canonicalUrl") or c.get("clickThroughUrl") or {}).get("url") or a.get("link")
    return {"title": title, "url": url, "published": published,
            "publisher": provider.get("displayName") if isinstance(provider, dict) else a.get("publisher")}


class DemoProvider:
    """Deterministic synthetic data so the app can run offline / in tests."""

    def _rng(self, ticker: str) -> np.random.Generator:
        return np.random.default_rng(zlib.crc32(ticker.encode()))

    def history(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        rng = self._rng(ticker)
        n = 504
        drift = rng.uniform(-0.0006, 0.0012)
        vol = rng.uniform(0.012, 0.03)
        rets = rng.normal(drift, vol, n)
        # inject a regime change in the last ~60 bars so signals vary by ticker
        rets[-60:] += rng.choice([-0.004, -0.002, 0.0, 0.002, 0.004])
        close = rng.uniform(40, 400) * np.exp(np.cumsum(rets))
        spread = np.abs(rng.normal(0, vol, n)) * close
        high = close + spread
        low = close - spread
        open_ = np.r_[close[0], close[:-1]]
        volume = rng.lognormal(15, 0.35, n)
        volume[-1] *= rng.choice([1.0, 1.0, 2.8])
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
        return pd.DataFrame({"Open": open_, "High": high, "Low": low,
                             "Close": close, "Volume": volume}, index=idx)

    def fundamentals(self, ticker: str) -> dict:
        rng = self._rng(ticker + ":f")
        price = float(self.history(ticker)["Close"].iloc[-1])
        return {
            "name": f"{ticker} (demo)", "sector": str(rng.choice(["Technology", "Healthcare", "Energy"])),
            "market_cap": float(rng.uniform(2e10, 3e12)),
            "pe_trailing": float(rng.uniform(8, 60)), "pe_forward": float(rng.uniform(7, 45)),
            "peg": float(rng.uniform(0.6, 3.5)),
            "revenue_growth": float(rng.uniform(-0.1, 0.4)),
            "earnings_growth": float(rng.uniform(-0.3, 0.6)),
            "gross_margin": float(rng.uniform(0.2, 0.75)),
            "operating_margin": float(rng.uniform(-0.05, 0.45)),
            "profit_margin": float(rng.uniform(-0.05, 0.35)),
            "roe": float(rng.uniform(-0.05, 0.5)),
            "debt_to_equity": float(rng.uniform(0.0, 2.8)),
            "current_ratio": float(rng.uniform(0.7, 3.0)),
            "free_cash_flow": float(rng.uniform(-2e9, 5e10)),
            "target_mean_price": price * float(rng.uniform(0.85, 1.4)),
            "recommendation_mean": float(rng.uniform(1.4, 3.6)),
        }

    _HEADLINES = [
        ("{t} beats estimates and raises full-year guidance", 1),
        ("{t} wins multi-year government contract", 1),
        ("{t} announces $500M stock offering", -1),
        ("{t} faces SEC probe over accounting", -1),
        ("{t} shares steady ahead of investor day", 0),
        ("Analysts weigh {t} valuation after rally", 0),
    ]

    def events(self, ticker: str) -> dict:
        rng = self._rng(ticker + ":e")
        now = datetime.now(timezone.utc)
        picks = rng.choice(len(self._HEADLINES), size=3, replace=False)
        news = [{"title": self._HEADLINES[i][0].format(t=ticker), "publisher": "Demo Wire", "url": None,
                 "published": now - timedelta(hours=float(rng.uniform(1, 120)))} for i in picks]
        changes = []
        if rng.random() < 0.5:
            up = rng.random() < 0.5
            changes.append({"date": now - timedelta(days=float(rng.uniform(0, 20))), "firm": "Demo Securities",
                            "action": "up" if up else "down",
                            "from_grade": "Hold" if up else "Buy", "to_grade": "Buy" if up else "Hold"})
        return {"earnings_date": date.today() + timedelta(days=int(rng.integers(1, 70))),
                "news": sorted(news, key=lambda n: n["published"], reverse=True), "rating_changes": changes}


class CachedProvider:
    """Shares fetches across threads and scans. Fundamentals and events change slowly,
    so they're kept longer, which also keeps the Yahoo request count down."""

    TTL = {"history": 300, "fundamentals": 6 * 3600, "events": 3600}

    def __init__(self, inner: DataProvider):
        self.inner = inner
        self._lock = threading.Lock()
        self._cache: dict[tuple, tuple[float, Future]] = {}

    def _get(self, kind: str, *args):
        key = (kind, *args)
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < self.TTL[kind]:
                fut, owner = hit[1], False
            else:
                fut, owner = Future(), True
                self._cache[key] = (time.monotonic(), fut)
        if owner:
            try:
                fut.set_result(getattr(self.inner, kind)(*args))
            except Exception as e:
                with self._lock:  # don't remember failures
                    self._cache.pop(key, None)
                fut.set_exception(e)
        return fut.result()

    def history(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        return self._get("history", ticker, period)

    def fundamentals(self, ticker: str) -> dict:
        return self._get("fundamentals", ticker)

    def events(self, ticker: str) -> dict:
        return self._get("events", ticker)


def get_provider(name: str) -> DataProvider:
    if name == "demo":
        return CachedProvider(DemoProvider())
    if name == "yahoo":
        return CachedProvider(YahooProvider())
    raise ValueError(f"Unknown data provider: {name}")
