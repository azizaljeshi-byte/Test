"""Market data providers.

Every provider returns:
  * history(ticker)      -> DataFrame indexed by date with Open/High/Low/Close/Volume
  * fundamentals(ticker) -> dict with the normalized keys listed in FUNDAMENTAL_KEYS
                            (missing values are None)
"""
from __future__ import annotations

import functools
import logging
import os
import threading
import time
import zlib
from concurrent.futures import Future
from datetime import date, datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

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
    "summary", "website", "employees", "country",           # company profile
]


# Sector ETF used to tell stock-specific weakness from sector-wide moves.
SECTOR_ETFS = {
    "Technology": "XLK", "Communication Services": "XLC", "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP", "Healthcare": "XLV", "Financial Services": "XLF",
    "Industrials": "XLI", "Energy": "XLE", "Utilities": "XLU", "Real Estate": "XLRE",
    "Basic Materials": "XLB",
}


NY = ZoneInfo("America/New_York")


def us_session(now: datetime | None = None) -> str:
    """US equity session by the clock (exchange holidays aren't modeled): PRE, REGULAR, POST or CLOSED."""
    t = (now or datetime.now(timezone.utc)).astimezone(NY)
    if t.weekday() >= 5:
        return "CLOSED"
    minutes = t.hour * 60 + t.minute
    if 4 * 60 <= minutes < 9 * 60 + 30:
        return "PRE"
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return "REGULAR"
    if 16 * 60 <= minutes < 20 * 60:
        return "POST"
    return "CLOSED"


class DataProvider(Protocol):
    def history(self, ticker: str, period: str = "5y") -> pd.DataFrame: ...
    def fundamentals(self, ticker: str) -> dict: ...

    def events(self, ticker: str) -> dict:
        """{"earnings_date": date | None,
            "news": [{"title", "publisher", "url", "published": datetime}],
            "rating_changes": [{"date": datetime, "firm", "action", "from_grade", "to_grade"}]}
        action is one of up / down / init / main / reit."""
        ...

    def quote(self, ticker: str) -> dict:
        """Latest price including extended hours:
            {"market_state": PRE | REGULAR | POST | CLOSED, "regular_price": float,
             "ext_session": "pre" | "post" | None, "ext_price": float | None,
             "ext_change": float | None (fraction vs regular_price), "ext_time": datetime | None}"""
        ...

    def filings(self, ticker: str) -> dict:
        """SEC EDGAR data, see sec.fetch."""
        ...

    def street(self, ticker: str) -> dict:
        """Analyst view and options market, see street.analyze for the keys."""
        ...

    def research(self, ticker: str) -> dict:
        """Slow-moving deep data, every key optional:
            "earnings": [{"quarter": date, "eps_actual", "eps_estimate", "surprise_pct"}]  newest first
            "quarterly": [{"period": date, "revenue", "gross_profit", "operating_income", "net_income"}]  newest first
            "annual": [{"period": date, "revenue", "eps"}]  newest first
            "insiders": [{"date": datetime, "insider", "position", "text", "shares", "value"}]
            "peers": [ticker, ...]"""
        ...


# Yahoo rate-limits its token ("crumb") when many requests arrive at once, after which quote,
# fundamentals and analyst requests fail with 401s. Keep only a few requests in flight.
_YAHOO_SLOTS = threading.BoundedSemaphore(3)


def _yahoo(fn):
    """Throttle a Yahoo call and retry yfinance's 'database is locked' cache error, which
    happens when several threads open its timezone cache at once."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        for attempt in range(4):
            with _YAHOO_SLOTS:
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    if "database is locked" not in str(e) or attempt == 3:
                        raise
            time.sleep(0.4 * (attempt + 1))
    return wrapper


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
        "institution_pct": "heldPercentInstitutions", "summary": "longBusinessSummary", "website": "website",
        "employees": "fullTimeEmployees", "country": "country",
    }

    def __init__(self):
        import yfinance  # imported lazily so the demo provider works without it
        self._yf = yfinance
        self._industry: dict[str, str] = {}   # filled by fundamentals(), saves research() an extra lookup

    @_yahoo
    def history(self, ticker: str, period: str = "5y") -> pd.DataFrame:
        df = self._yf.Ticker(ticker).history(period=period, auto_adjust=True)
        if df.empty:
            raise ValueError(f"No price history for {ticker}")
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df[["Open", "High", "Low", "Close", "Volume"]]

    @_yahoo
    def fundamentals(self, ticker: str) -> dict:
        info = self._yf.Ticker(ticker).info or {}
        out = {k: info.get(src) for k, src in self._MAP.items()}
        if sum(v is not None for v in out.values()) < 4:
            # a blocked request comes back nearly empty: try Finnhub, otherwise raise so it isn't cached
            fh = _fallback("fundamentals", ticker)
            if fh and len(fh) >= 5:
                return fh
            raise RuntimeError(f"Yahoo returned no fundamentals for {ticker} (likely rate-limited)")
        if out.get("industry_key"):
            self._industry[ticker.upper()] = out["industry_key"]
        if out["peg"] is None:
            out["peg"] = info.get("pegRatio")
        if out["debt_to_equity"] is not None:
            out["debt_to_equity"] = out["debt_to_equity"] / 100.0  # Yahoo reports percent
        return out

    @_yahoo
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
        if not out["earnings_date"]:
            out["earnings_date"] = _fallback("next_earnings", ticker)
        if not out["news"]:
            out["news"] = _fallback("news", ticker) or []
        return out

    @_yahoo
    def research(self, ticker: str) -> dict:
        out = _yahoo_research(self._yf, ticker, self._industry.get(ticker.upper()))
        if not out.get("earnings"):
            out["earnings"] = _fallback("earnings", ticker) or []
        if not out.get("insiders"):
            out["insiders"] = _fallback("insiders", ticker) or []
        return out

    @_yahoo
    def quote(self, ticker: str) -> dict:
        """Live price from minute bars that include pre/post-market trading.

        During regular hours: the latest trade and today's change. Outside them: the latest
        pre-market or after-hours trade against the last regular close. Uses Yahoo's chart
        data, which works without the token that Yahoo rate-limits. The session comes from
        the New York clock."""
        t = self._yf.Ticker(ticker)
        errors = []
        for interval in ("1m", "5m"):
            try:
                bars = t.history(period="5d", interval=interval, prepost=True)
                if bars.empty:
                    raise ValueError("no bars returned")
                return _quote_from_bars(bars, f"{interval} bars", errors)
            except Exception as e:
                errors.append(f"{interval} bars: {e}")
        return _quote_from_bars(None, None, errors)

    @_yahoo
    def intraday(self, ticker: str) -> pd.DataFrame:
        """Today's (and yesterday's) 1-minute bars including pre/post-market, for momentum readouts."""
        bars = self._yf.Ticker(ticker).history(period="2d", interval="1m", prepost=True)
        if bars.empty:
            raise ValueError(f"No intraday bars for {ticker}")
        return bars

    @_yahoo
    def bulk_quotes(self, tickers: list[str]) -> dict[str, dict]:
        """Quotes for many tickers from one download, so a refresh takes seconds, not minutes."""
        df = self._yf.download(list(tickers), period="5d", interval="1m", prepost=True, group_by="ticker",
                               threads=True, progress=False, auto_adjust=False)
        out = {}
        for t in tickers:
            try:
                sub = df[t] if len(tickers) > 1 else df
                out[t] = _quote_from_bars(sub if not sub.dropna(how="all").empty else None, "1m bars",
                                          [] if not sub.dropna(how="all").empty else ["no bars returned"])
            except KeyError:
                out[t] = _quote_from_bars(None, None, ["not in the bulk download"])
        return out

    def filings(self, ticker: str) -> dict:
        from . import sec
        return sec.fetch(ticker)

    @_yahoo
    def street(self, ticker: str) -> dict:
        out = _yahoo_street(self._yf, ticker)
        if not out.get("recs") or not any((out.get("targets") or {}).get(k) for k in ("mean", "median")):
            fh = _fallback("street", ticker) or {}
            out["recs"] = out.get("recs") or fh.get("recs") or []
            if not any((out.get("targets") or {}).get(k) for k in ("mean", "median")):
                out["targets"] = {**(out.get("targets") or {}), **(fh.get("targets") or {})}
        return out

    def bulk_history(self, tickers: tuple[str, ...], period: str = "2y") -> dict[str, pd.DataFrame]:
        """Daily bars for many tickers in a few requests (used by the market scan)."""
        out: dict[str, pd.DataFrame] = {}
        for i in range(0, len(tickers), 100):
            chunk = list(tickers[i:i + 100])
            df = self._yf.download(chunk, period=period, group_by="ticker", auto_adjust=True,
                                   threads=True, progress=False)
            for t in chunk:
                try:
                    sub = df[t] if len(chunk) > 1 else df
                    sub = sub[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
                    if len(sub) > 30:
                        sub.index = pd.to_datetime(sub.index).tz_localize(None)
                        out[t] = sub
                except KeyError:
                    continue
        return out

    def sec_facts(self, ticker: str) -> dict:
        from . import sec
        return sec.fetch_facts(ticker)

    @_yahoo
    def raw_quote(self, ticker: str) -> dict:
        """Uncached raw quote fields, for the dashboard's diagnostics panel."""
        info = self._yf.Ticker(ticker).info or {}
        keys = ("marketState", "regularMarketPrice", "regularMarketTime", "preMarketPrice", "preMarketTime",
                "postMarketPrice", "postMarketTime", "exchangeTimezoneName")
        return {k: info.get(k) for k in keys}



def _yahoo_street(yf, ticker: str) -> dict:
    t = yf.Ticker(ticker)
    out: dict = {"eps": {}, "revenue": {}, "eps_trend": {}, "revisions": {}, "recs": [], "targets": {}, "options": []}

    def attempt(name, fn):
        try:
            fn()
        except Exception as e:
            log.info("%s failed for %s: %s", name, ticker, e)

    def periodic(key, df, cols):
        if df is not None and not df.empty:
            for period, r in df.iterrows():
                out[key][str(period)] = {k: _f(r.get(src)) for k, src in cols.items()}

    attempt("earnings estimate", lambda: periodic("eps", t.earnings_estimate, {
        "avg": "avg", "low": "low", "high": "high", "year_ago": "yearAgoEps", "analysts": "numberOfAnalysts",
        "growth": "growth"}))
    attempt("revenue estimate", lambda: periodic("revenue", t.revenue_estimate, {
        "avg": "avg", "low": "low", "high": "high", "year_ago": "yearAgoRevenue", "analysts": "numberOfAnalysts",
        "growth": "growth"}))
    attempt("eps trend", lambda: periodic("eps_trend", t.eps_trend, {
        "current": "current", "7d": "7daysAgo", "30d": "30daysAgo", "60d": "60daysAgo", "90d": "90daysAgo"}))
    attempt("eps revisions", lambda: periodic("revisions", t.eps_revisions, {
        "up7": "upLast7days", "up30": "upLast30days", "down7": "downLast7Days", "down30": "downLast30days"}))

    def recs():
        df = t.recommendations
        if df is not None and not df.empty:
            out["recs"] = [{k: (str(r[k]) if k == "period" else int(r.get(k) or 0))
                            for k in ("period", "strongBuy", "buy", "hold", "sell", "strongSell")}
                           for _, r in df.iterrows()]
    attempt("recommendations", recs)
    attempt("price targets", lambda: out["targets"].update(
        {k: _f(v) for k, v in (t.analyst_price_targets or {}).items()}))

    def options():
        expiries = list(t.options or ())
        spot = out["targets"].get("current")
        if not expiries or not spot:
            return
        today = date.today()
        dated = [(date.fromisoformat(e), e) for e in expiries]
        cal = (t.calendar or {}).get("Earnings Date") or []
        wanted = {"1 month": min(dated, key=lambda d: abs((d[0] - today).days - 30))}
        upcoming = sorted(d for d in cal if d >= today)
        if upcoming:
            after = [d for d in dated if d[0] >= upcoming[0]]
            if after:
                wanted["earnings"] = after[0]
        for label, (exp_date, exp) in wanted.items():
            chain = t.option_chain(exp)
            row = {"label": label, "expiry": exp, "days": (exp_date - today).days}
            for side, df in (("call", chain.calls), ("put", chain.puts)):
                if df is None or df.empty:
                    continue
                atm = df.iloc[(df["strike"] - spot).abs().argsort()[:1]].iloc[0]
                mid = (atm["bid"] + atm["ask"]) / 2 if atm["bid"] > 0 and atm["ask"] > 0 else atm["lastPrice"]
                row[f"{side}_mid"], row[f"{side}_iv"], row["strike"] = _f(mid), _f(atm["impliedVolatility"]), _f(atm["strike"])
            if row.get("call_mid") and row.get("put_mid"):
                row["implied_move"] = (row["call_mid"] + row["put_mid"]) / spot
            out["options"].append(row)
    attempt("options", options)
    return out


def _yahoo_research(yf, ticker: str, industry_key: str | None = None) -> dict:
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
        key = industry_key or (t.info or {}).get("industryKey")
        if key:
            out["peers"] = [p for p in _industry_leaders(yf, key) if p.upper() != ticker.upper()][:4]

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


def _fallback(kind: str, ticker: str):
    """Ask Finnhub for something Yahoo didn't return, when a FINNHUB_API_KEY is configured."""
    from . import finnhub
    if not finnhub.enabled():
        return None
    try:
        return getattr(finnhub, kind)(ticker)
    except Exception as e:
        log.info("finnhub %s failed for %s: %s", kind, ticker, e)
        return None


_SECOND: dict[str, tuple[float, dict | None]] = {}
SECOND_TTL = 6 * 3600       # technical reads move slowly; this keeps the Finnhub requests few


def second_opinion(ticker: str) -> dict | None:
    """Finnhub's technical read for one ticker, cached for hours. None when Finnhub isn't configured or answers nothing."""
    hit = _SECOND.get(ticker)
    if hit and time.monotonic() - hit[0] < SECOND_TTL:
        return hit[1]
    out = _fallback("second_opinion", ticker)
    if out is not None or hit is None:       # a failed refresh keeps the older read rather than blanking it
        _SECOND[ticker] = (time.monotonic(), out)
    return _SECOND[ticker][1]


def _bar_summary(bars: pd.DataFrame) -> dict:
    """Latest bar and its session, the latest regular-session close, and the regular close
    of the trading day before it (for today's change)."""
    bars = bars.dropna(subset=["Close"])
    if bars.empty:
        raise ValueError("no bars returned")
    idx = bars.index if bars.index.tz is not None else bars.index.tz_localize("UTC")
    sessions = [us_session(ts.to_pydatetime()) for ts in idx]
    regular = [i for i, sess in enumerate(sessions) if sess == "REGULAR"]
    last_regular = prev_regular = None
    if regular:
        last_i = regular[-1]
        last_regular = float(bars["Close"].iloc[last_i])
        day = idx[last_i].tz_convert(NY).date()
        earlier = [i for i in regular if idx[i].tz_convert(NY).date() < day]
        prev_regular = float(bars["Close"].iloc[earlier[-1]]) if earlier else None
    return {"last_close": float(bars["Close"].iloc[-1]), "last_session": sessions[-1],
            "last_time": idx[-1].to_pydatetime().astimezone(timezone.utc),
            "last_regular": last_regular, "prev_regular": prev_regular}


def _quote_from_bars(bars: pd.DataFrame | None, source: str | None, errors: list[str]) -> dict:
    clock = us_session()
    out = {"market_state": clock, "ext_session": None, "ext_price": None, "ext_change": None, "ext_time": None,
           "ext_stale": False, "live_price": None, "live_change": None, "live_time": None,
           "regular_price": None, "source": None,
           "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    summary = None
    if bars is not None:
        try:
            summary = _bar_summary(bars)
            out["source"] = source
        except Exception as e:
            errors = errors + [f"{source}: {e}"]
    if summary:
        out["regular_price"] = summary["last_regular"]
        if clock == "REGULAR" and summary["last_session"] == "REGULAR":
            out["live_price"], out["live_time"] = summary["last_close"], summary["last_time"]
            if summary["prev_regular"]:
                out["live_change"] = summary["last_close"] / summary["prev_regular"] - 1
        elif clock != "REGULAR" and summary["last_session"] in ("PRE", "POST"):
            sess = summary["last_session"].lower()
            out.update(ext_session=sess, ext_price=summary["last_close"], ext_time=summary["last_time"],
                       ext_stale=sess == "post" and clock == "PRE")
            if summary["last_regular"]:
                out["ext_change"] = summary["last_close"] / summary["last_regular"] - 1
        elif clock != "REGULAR":
            errors = errors + ["no extended-hours trades since the last close"]
    out["error"] = "; ".join(errors) or None
    return out


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
            "summary": (f"{ticker} Inc. (demo) designs and sells products for enterprise and consumer markets. "
                        "The company operates through hardware, software and services segments, and sells "
                        "directly and through partners worldwide. It was founded in 1998 and is headquartered "
                        "in Austin, Texas."),
            "website": "https://example.com", "employees": int(rng.integers(50, 200_000)), "country": "United States",
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

    def quote(self, ticker: str) -> dict:
        rng = self._rng(ticker + ":q")
        regular = float(self.history(ticker)["Close"].iloc[-1])
        state = us_session()
        session = {"PRE": "pre", "POST": "post", "CLOSED": "post"}.get(state)
        move = float(rng.choice([rng.normal(0, 0.01), rng.normal(0, 0.01), rng.choice([-0.08, 0.07])]))
        price = regular * (1 + move) if session else None
        live = state == "REGULAR"
        drift = float(np.random.default_rng().normal(0, 0.004))   # a little movement between refreshes
        return {"market_state": state, "regular_price": regular, "ext_session": session, "ext_price": price,
                "ext_change": move if session else None, "ext_time": datetime.now(timezone.utc) if session else None,
                "ext_stale": False, "live_price": regular * (1 + drift) if live else None,
                "live_change": drift if live else None, "live_time": datetime.now(timezone.utc) if live else None,
                "source": "demo", "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def filings(self, ticker: str) -> dict:
        from . import sec
        return sec.demo(ticker)

    def bulk_quotes(self, tickers: list[str]) -> dict[str, dict]:
        return {t: self.quote(t) for t in tickers}

    def intraday(self, ticker: str) -> pd.DataFrame:
        rng = self._rng(ticker + ":i")
        last = float(self.history(ticker)["Close"].iloc[-1])
        start = pd.Timestamp.now(tz="America/New_York").normalize() + pd.Timedelta(hours=4)
        idx = pd.date_range(start, periods=16 * 60, freq="1min")
        so_far = idx[idx <= pd.Timestamp.now(tz="America/New_York")]
        idx = so_far if len(so_far) > 30 else idx[:300]   # before 4:30am, pretend a few hours have traded
        path = last * np.exp(np.cumsum(rng.normal(float(rng.uniform(-0.0003, 0.0004)), 0.0015, len(idx))))
        vol = rng.lognormal(9, 0.6, len(idx))
        return pd.DataFrame({"Open": path, "High": path * 1.001, "Low": path * 0.999, "Close": path, "Volume": vol},
                            index=idx)

    def bulk_history(self, tickers: tuple[str, ...], period: str = "2y") -> dict[str, pd.DataFrame]:
        return {t: self.history(t).iloc[-504:] for t in tickers}

    def street(self, ticker: str) -> dict:
        rng = self._rng(ticker + ":s")
        price = float(self.history(ticker)["Close"].iloc[-1])
        eps0, g0, g1 = float(rng.uniform(1, 8)), float(rng.uniform(-0.1, 0.35)), float(rng.uniform(-0.05, 0.4))
        drift30, drift90 = float(rng.normal(0, 0.03)), float(rng.normal(0, 0.06))
        up, down = int(rng.integers(0, 8)), int(rng.integers(0, 6))
        recs = []
        for i, period in enumerate(["0m", "-1m", "-2m", "-3m"]):
            sb, b = int(rng.integers(2, 12)), int(rng.integers(3, 15))
            recs.append({"period": period, "strongBuy": sb, "buy": b, "hold": int(rng.integers(2, 12)),
                         "sell": int(rng.integers(0, 3)), "strongSell": int(rng.integers(0, 2))})
        iv = float(rng.uniform(0.25, 0.9))
        return {
            "eps": {"0q": {"avg": eps0 / 4, "growth": g0, "analysts": 20},
                    "0y": {"avg": eps0, "growth": g0, "analysts": 25, "year_ago": eps0 / (1 + g0)},
                    "+1y": {"avg": eps0 * (1 + g1), "growth": g1, "analysts": 22}},
            "revenue": {"0y": {"growth": g0 * 0.8}, "+1y": {"growth": g1 * 0.7}},
            "eps_trend": {"0y": {"current": eps0, "30d": eps0 / (1 + drift30), "90d": eps0 / (1 + drift90)},
                          "+1y": {"current": eps0 * (1 + g1), "30d": eps0 * (1 + g1) / (1 + drift30),
                                  "90d": eps0 * (1 + g1) / (1 + drift90)}},
            "revisions": {"0y": {"up30": up, "down30": down, "up7": min(up, 2), "down7": min(down, 1)}},
            "recs": recs,
            "targets": {"current": price, "low": price * float(rng.uniform(0.6, 0.9)),
                        "mean": price * float(rng.uniform(0.95, 1.35)), "median": price * float(rng.uniform(0.95, 1.3)),
                        "high": price * float(rng.uniform(1.3, 1.9))},
            "options": [{"label": "1 month", "days": 30, "implied_move": iv * (30 / 365) ** 0.5 * 0.8, "call_iv": iv},
                        {"label": "earnings", "days": int(rng.integers(5, 60)),
                         "implied_move": float(rng.uniform(0.04, 0.14)), "call_iv": iv * 1.2}],
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

    # history stays under the tracker's 2-minute sweep so today's bar carries the live price
    TTL = {"history": 100, "fundamentals": 6 * 3600, "events": 3600, "research": 12 * 3600, "quote": 60,
           "filings": 3 * 3600, "bulk_history": 900, "street": 3 * 3600,
           "sec_facts": 24 * 3600, "intraday": 45}

    def __init__(self, inner: DataProvider):
        self.inner = inner
        self._lock = threading.Lock()
        self._cache: dict[tuple, tuple[float, Future]] = {}
        self._last: dict[tuple, pd.DataFrame] = {}   # last good price history, for pages that mustn't wait

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
                value = getattr(self.inner, kind)(*args)
                if kind == "history":
                    with self._lock:
                        self._last[key] = value
                fut.set_result(value)
            except Exception as e:
                with self._lock:  # don't remember failures
                    self._cache.pop(key, None)
                fut.set_exception(e)
        return fut.result()

    def history(self, ticker: str, period: str = "5y") -> pd.DataFrame:
        return self._get("history", ticker, period)

    def peek_history(self, ticker: str, period: str = "5y") -> pd.DataFrame | None:
        """The last good history however old, without fetching or waiting: the page must never queue
        behind the tracker's Yahoo calls. None until something has fetched it."""
        with self._lock:
            return self._last.get(("history", ticker, period))

    def fundamentals(self, ticker: str) -> dict:
        return self._get("fundamentals", ticker)

    def events(self, ticker: str) -> dict:
        return self._get("events", ticker)

    def research(self, ticker: str) -> dict:
        return self._get("research", ticker)

    def quote(self, ticker: str) -> dict:
        return self._get("quote", ticker)

    def intraday(self, ticker: str) -> pd.DataFrame:
        return self._get("intraday", ticker)

    def bulk_quotes(self, tickers: list[str]) -> dict[str, dict]:
        """Not cached: it's the explicit 'refresh prices now' path."""
        if hasattr(self.inner, "bulk_quotes"):
            return self.inner.bulk_quotes(list(tickers))
        return {t: self.quote(t) for t in tickers}

    def filings(self, ticker: str) -> dict:
        return self._get("filings", ticker)

    def bulk_history(self, tickers: tuple[str, ...], period: str = "2y") -> dict[str, pd.DataFrame]:
        return self._get("bulk_history", tuple(tickers), period)

    def street(self, ticker: str) -> dict:
        return self._get("street", ticker)

    def sec_facts(self, ticker: str) -> dict:
        if not hasattr(self.inner, "sec_facts"):
            raise NotImplementedError
        return self._get("sec_facts", ticker)


def selected_provider(setting: str) -> str:
    """The provider the app runs on: demo when STOCKWATCH_DEMO is set, otherwise the portfolio's setting."""
    return "demo" if os.getenv("STOCKWATCH_DEMO") else setting


def get_provider(name: str) -> DataProvider:
    if name == "demo":
        return CachedProvider(DemoProvider())
    if name == "yahoo":
        return CachedProvider(YahooProvider())
    raise ValueError(f"Unknown data provider: {name}")
