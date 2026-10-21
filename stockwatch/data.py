"""Market data providers.

Every provider returns:
  * history(ticker)      -> DataFrame indexed by date with Open/High/Low/Close/Volume
  * fundamentals(ticker) -> dict with the normalized keys listed in FUNDAMENTAL_KEYS
                            (missing values are None)
"""
from __future__ import annotations

import functools
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
    "target_low_price", "target_high_price", "analyst_count",
    "eps_trailing", "eps_forward", "price_to_sales", "industry", "industry_key",
    "short_pct_float", "short_ratio", "shares_short", "shares_short_prior",  # short_ratio = days to cover
    "insider_pct", "institution_pct",
]


# Sector ETF used to tell stock-specific weakness from sector-wide moves.
SECTOR_ETFS = {
    "Technology": "XLK", "Communication Services": "XLC", "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP", "Healthcare": "XLV", "Financial Services": "XLF",
    "Industrials": "XLI", "Energy": "XLE", "Utilities": "XLU", "Real Estate": "XLRE",
    "Basic Materials": "XLB",
}


class DataProvider(Protocol):
    def history(self, ticker: str, period: str = "5y") -> pd.DataFrame: ...
    def fundamentals(self, ticker: str) -> dict: ...

    def events(self, ticker: str) -> dict:
        """{"earnings_date": date | None,
            "news": [{"title", "publisher", "url", "published": datetime}],
            "rating_changes": [{"date": datetime, "firm", "action", "from_grade", "to_grade"}]}
        action is one of up / down / init / main / reit."""
        ...

    def research(self, ticker: str) -> dict:
        """Slow-moving deep data, every key optional:
            "earnings": [{"quarter": date, "eps_actual", "eps_estimate", "surprise_pct"}]  newest first
            "quarterly": [{"period": date, "revenue", "gross_profit", "operating_income", "net_income"}]  newest first
            "annual": [{"period": date, "revenue", "eps"}]  newest first
            "insiders": [{"date": datetime, "insider", "position", "text", "shares", "value"}]
            "peers": [ticker, ...]"""
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
        "target_low_price": "targetLowPrice", "target_high_price": "targetHighPrice",
        "analyst_count": "numberOfAnalystOpinions", "eps_trailing": "trailingEps", "eps_forward": "forwardEps",
        "price_to_sales": "priceToSalesTrailing12Months", "industry": "industry", "industry_key": "industryKey",
        "short_pct_float": "shortPercentOfFloat", "short_ratio": "shortRatio", "shares_short": "sharesShort",
        "shares_short_prior": "sharesShortPriorMonth", "insider_pct": "heldPercentInsiders",
        "institution_pct": "heldPercentInstitutions",
    }

    def __init__(self):
        import yfinance  # imported lazily so the demo provider works without it
        self._yf = yfinance

    def history(self, ticker: str, period: str = "5y") -> pd.DataFrame:
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

    def research(self, ticker: str) -> dict:
        return _yahoo_research(self._yf, ticker)


def _yahoo_research(yf, ticker: str) -> dict:
    t = yf.Ticker(ticker)
    out: dict = {"earnings": [], "quarterly": [], "annual": [], "insiders": [], "peers": []}

    def attempt(name, fn):
        try:
            fn()
        except Exception as e:
            log.info("%s failed for %s: %s", name, ticker, e)

    def earnings():
        eh = t.earnings_history
        if eh is not None and not eh.empty:
            for q, r in eh.sort_index(ascending=False).iterrows():
                out["earnings"].append({"quarter": pd.Timestamp(q).date(), "eps_actual": _f(r.get("epsActual")),
                                        "eps_estimate": _f(r.get("epsEstimate")),
                                        "surprise_pct": _f(r.get("surprisePercent"))})

    def statements(freq, key, rows):
        df = t.get_income_stmt(pretty=False, freq=freq)
        if df is None or df.empty:
            return
        for col in sorted(df.columns, reverse=True):
            out[key].append({"period": pd.Timestamp(col).date(),
                             **{name: _f(df.at[row, col]) if row in df.index else None for name, row in rows.items()}})

    def insiders():
        it = t.insider_transactions
        if it is not None and not it.empty:
            for _, r in it.head(40).iterrows():
                out["insiders"].append({"date": pd.Timestamp(r.get("Start Date")).to_pydatetime(),
                                        "insider": r.get("Insider"), "position": r.get("Position"),
                                        "text": str(r.get("Text") or ""), "shares": _f(r.get("Shares")),
                                        "value": _f(r.get("Value"))})

    def peers():
        key = (t.info or {}).get("industryKey")
        if key:
            out["peers"] = [p for p in _industry_leaders(yf, key) if p.upper() != ticker.upper()][:6]

    attempt("earnings history", earnings)
    attempt("quarterly statements", lambda: statements("quarterly", "quarterly", {
        "revenue": "TotalRevenue", "gross_profit": "GrossProfit",
        "operating_income": "OperatingIncome", "net_income": "NetIncome"}))
    attempt("annual statements", lambda: statements("yearly", "annual", {"revenue": "TotalRevenue", "eps": "DilutedEPS"}))
    attempt("insider transactions", insiders)
    attempt("peers", peers)
    return out


@functools.lru_cache(maxsize=256)
def _industry_leaders(yf, key: str) -> tuple[str, ...]:
    """Industry membership barely changes, so one lookup per industry per process is plenty."""
    top = yf.Industry(key).top_companies
    return tuple(p for p in top.index.tolist() if p) if top is not None else ()


def _f(v) -> float | None:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else v


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

    def history(self, ticker: str, period: str = "5y") -> pd.DataFrame:
        rng = self._rng(ticker)
        n = 1260
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
        pe_t, pe_f = float(rng.uniform(8, 60)), float(rng.uniform(7, 45))
        return {
            "name": f"{ticker} (demo)", "sector": str(rng.choice(["Technology", "Healthcare", "Energy"])),
            "market_cap": float(rng.uniform(2e10, 3e12)),
            "pe_trailing": pe_t, "pe_forward": pe_f,
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
            "target_low_price": price * float(rng.uniform(0.6, 0.9)),
            "target_high_price": price * float(rng.uniform(1.2, 1.9)), "analyst_count": int(rng.integers(3, 40)),
            "eps_trailing": price / pe_t, "eps_forward": price / pe_f,
            "price_to_sales": float(rng.uniform(1, 20)), "industry": "Demo Industry", "industry_key": "demo",
            "short_pct_float": float(rng.uniform(0.01, 0.3)), "short_ratio": float(rng.uniform(0.5, 8)),
            "shares_short": 1e7, "shares_short_prior": 1e7 * float(rng.uniform(0.6, 1.3)),
            "insider_pct": float(rng.uniform(0.0, 0.3)), "institution_pct": float(rng.uniform(0.1, 0.9)),
        }

    def research(self, ticker: str) -> dict:
        rng = self._rng(ticker + ":r")
        q_end = (pd.Timestamp.today() - pd.offsets.QuarterEnd(1)).normalize()
        quarters = [(q_end - pd.offsets.QuarterEnd(i)).date() for i in range(8)]
        rev0 = float(rng.uniform(5e8, 2e10))
        growth = float(rng.uniform(-0.03, 0.08))
        quarterly = []
        for i, q in enumerate(quarters[:5]):
            rev = rev0 / (1 + growth) ** i
            om = float(rng.uniform(0.05, 0.3))
            quarterly.append({"period": q, "revenue": rev, "gross_profit": rev * 0.55,
                              "operating_income": rev * om, "net_income": rev * om * 0.8})
        earnings = []
        for q in quarters[:4]:
            est = float(rng.uniform(0.2, 2.0))
            act = est * float(rng.uniform(0.85, 1.2))
            earnings.append({"quarter": q, "eps_actual": act, "eps_estimate": est, "surprise_pct": act / est - 1})
        hist = self.history(ticker)["Close"]
        annual = []
        for i in range(4):
            fy = date(date.today().year - 1 - i, 12, 31)
            px = float(hist.loc[:pd.Timestamp(fy)].iloc[-1])
            annual.append({"period": fy, "revenue": rev0 * 4 / (1.15 ** i), "eps": px / float(rng.uniform(15, 40))})
        now = datetime.now()
        insiders = [{"date": now - timedelta(days=float(rng.uniform(1, 150))), "insider": f"Insider {i}",
                     "position": str(rng.choice(["CEO", "CFO", "Director"])),
                     "text": str(rng.choice(["Sale at price 50.00 per share.", "Purchase at price 48.00 per share.",
                                             "Stock Award(Grant) at price 0.00 per share."])),
                     "shares": float(rng.integers(1000, 50000)), "value": float(rng.uniform(5e4, 3e6))}
                    for i in range(5)]
        return {"earnings": earnings, "quarterly": quarterly, "annual": annual, "insiders": insiders,
                "peers": [p for p in ["AAPL", "MSFT", "NVDA", "GOOGL", "AMD"] if p != ticker][:4]}

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

    TTL = {"history": 300, "fundamentals": 6 * 3600, "events": 3600, "research": 12 * 3600}

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

    def history(self, ticker: str, period: str = "5y") -> pd.DataFrame:
        return self._get("history", ticker, period)

    def fundamentals(self, ticker: str) -> dict:
        return self._get("fundamentals", ticker)

    def events(self, ticker: str) -> dict:
        return self._get("events", ticker)

    def research(self, ticker: str) -> dict:
        return self._get("research", ticker)


def get_provider(name: str) -> DataProvider:
    if name == "demo":
        return CachedProvider(DemoProvider())
    if name == "yahoo":
        return CachedProvider(YahooProvider())
    raise ValueError(f"Unknown data provider: {name}")
