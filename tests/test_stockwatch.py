import io
import time

import numpy as np
import pandas as pd
import pytest

from stockwatch import fundamental, technical
from stockwatch.config import Holding, Portfolio, Settings, TierRules, load_portfolio
from stockwatch.data import DemoProvider, get_provider
from stockwatch.engine import evaluate, scan
from stockwatch.store import Store

T1 = TierRules(0.65, 0.35, 25, 4.0, 15)
T2 = TierRules(0.40, 0.60, 12, 2.5, 7)


def make_portfolio(*holdings):
    return Portfolio(list(holdings), {1: T1, 2: T2}, Settings(data_provider="demo"))


def frame(close):
    close = pd.Series(close, dtype=float)
    idx = pd.bdate_range("2024-01-01", periods=len(close))
    return pd.DataFrame({"Open": close.values, "High": close.values * 1.01, "Low": close.values * 0.99,
                         "Close": close.values, "Volume": np.full(len(close), 1e6)}, index=idx)


class FixedProvider:
    def __init__(self, df, fundamentals):
        self.df, self.f = df, fundamentals

    def history(self, ticker, period="5y"):
        return self.df

    def fundamentals(self, ticker):
        return self.f

    def events(self, ticker):
        return {}

    def research(self, ticker):
        return {}

    def quote(self, ticker):
        return {}

    def filings(self, ticker):
        return {}

    def street(self, ticker):
        return {}


STRONG_FUNDAMENTALS = dict(pe_forward=15, peg=0.9, revenue_growth=0.25, earnings_growth=0.3,
                           operating_margin=0.3, roe=0.3, free_cash_flow=1e9, debt_to_equity=0.2,
                           current_ratio=2.0, recommendation_mean=1.7)
WEAK_FUNDAMENTALS = dict(pe_forward=80, peg=4, revenue_growth=-0.1, earnings_growth=-0.4,
                         operating_margin=-0.05, roe=-0.1, free_cash_flow=-1e9, debt_to_equity=3.0,
                         current_ratio=0.7, recommendation_mean=3.8)


def test_rsi_bounds_and_extremes():
    up = technical.rsi(pd.Series(np.arange(1, 100, dtype=float)))
    down = technical.rsi(pd.Series(np.arange(100, 1, -1, dtype=float)))
    assert up.iloc[-1] > 95 and down.iloc[-1] < 5


def test_crossed_above_requires_still_above():
    a = pd.Series([1, 1, 3, 1], dtype=float)
    b = pd.Series([2, 2, 2, 2], dtype=float)
    assert not technical.crossed_above(a, b, 3)  # crossed up then back down = whipsaw
    assert technical.crossed_above(a.iloc[:3], b.iloc[:3], 3)


def test_uptrend_scores_higher_than_downtrend():
    up, _, _ = technical.analyze(frame(np.linspace(50, 150, 300)))
    down, m, sigs = technical.analyze(frame(np.linspace(150, 50, 300)))
    assert up > 70 > 30 > down
    assert m["trend"] == "down"


def test_fundamental_score_ordering_and_missing_data():
    good, _, good_sig = fundamental.analyze(STRONG_FUNDAMENTALS, 100)
    bad, _, bad_sig = fundamental.analyze(WEAK_FUNDAMENTALS, 100)
    assert good > 80 and bad < 20
    assert all(s.kind == "opportunity" for s in good_sig)
    assert {"revenue_declining", "negative_fcf", "high_leverage"} <= {s.code for s in bad_sig}
    assert fundamental.analyze({}, 100)[0] == 50.0


def test_quality_pullback_is_an_opportunity():
    # long uptrend then a sharp short pullback: RSI drops while still above the 200-day
    close = np.r_[np.linspace(50, 150, 280), np.linspace(150, 135, 8)]
    ev = evaluate(Holding("X", 1, 10, 100), make_portfolio(), FixedProvider(frame(close), STRONG_FUNDAMENTALS))
    assert "quality_entry" in {s.code for s in ev.signals}
    assert ev.verdict == "OPPORTUNITY - ADD"


def test_weak_fundamentals_plus_downtrend_is_thesis_break_and_stop():
    close = np.linspace(150, 60, 300)
    ev = evaluate(Holding("X", 2, 10, 150), make_portfolio(), FixedProvider(frame(close), WEAK_FUNDAMENTALS))
    codes = {s.code for s in ev.signals}
    assert {"thesis_breakdown", "stop_loss"} <= codes
    assert ev.verdict == "RISK - REVIEW"


def test_watchlist_has_no_position_signals():
    close = np.linspace(150, 60, 300)
    ev = evaluate(Holding("X", 2, 0), make_portfolio(), FixedProvider(frame(close), WEAK_FUNDAMENTALS))
    assert not any(s.source == "position" for s in ev.signals)
    assert "atr_trailing_stop" not in {s.code for s in ev.signals}
    assert ev.verdict == "AVOID"


def test_scan_concentration_and_errors():
    class Broken(DemoProvider):
        def history(self, ticker, period="5y"):
            if ticker == "BAD":
                raise ValueError("no data")
            return super().history(ticker, period)

    p = make_portfolio(Holding("AAA", 2, 1000, 1), Holding("BBB", 2, 1, 1), Holding("BAD", 1, 1, 1))
    evals = {e.ticker: e for e in scan(p, Broken())}
    assert evals["BAD"].verdict == "ERROR"
    assert "concentration" in {s.code for s in evals["AAA"].signals}


def test_store_dedupes_alerts(tmp_path):
    store = Store(tmp_path / "t.db")
    ev = evaluate(Holding("X", 2, 10, 150), make_portfolio(),
                  FixedProvider(frame(np.linspace(150, 60, 300)), WEAK_FUNDAMENTALS))
    first = store.record_alerts(ev, cooldown_hours=24)
    assert first and store.record_alerts(ev, cooldown_hours=24) == []
    store.save_snapshot(ev)
    assert store.latest_snapshots()[0]["ticker"] == "X"


def test_example_portfolio_loads():
    p = load_portfolio("portfolio.example.yaml")
    assert {h.tier for h in p.holdings} == {1, 2}
    assert any(h.is_watchlist for h in p.holdings)


def test_invalid_tier_rejected(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text("holdings:\n  - {ticker: X, tier: 3}\n")
    with pytest.raises(ValueError):
        load_portfolio(f)


def test_portfolio_from_env(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_PORTFOLIO", "holdings:\n  - {ticker: tsla, tier: 2, shares: 5}\n")
    p = load_portfolio()
    assert p.source is None and p.holdings[0].ticker == "TSLA"


def test_recent_listing_not_penalized_for_missing_averages():
    score, m, _ = technical.analyze(frame(np.linspace(20, 30, 60)))
    assert np.isnan(m["sma200"]) and score > 50  # was 40 when missing averages counted as bearish


# ---- relative strength, catalysts, caching, fleet overrides

from datetime import date, datetime, timedelta, timezone

from stockwatch import catalysts, relative
from stockwatch.config import to_yaml
from stockwatch.data import CachedProvider


def test_relative_strength_leading_and_lagging():
    market = frame(np.linspace(100, 110, 300))
    _, m, sig = relative.analyze(frame(np.geomspace(100, 400, 300)), market, None, None, tier=1)
    assert m["rs_spy_3m"] > 0.10 and "leading_market" in {s.code for s in sig}
    adj, m, sig = relative.analyze(frame(np.linspace(200, 100, 300)), market, market, "XLK", tier=1)
    codes = {s.code: s for s in sig}
    assert adj < 0 and codes["lagging_market"].severity == 2 and "lagging_sector" in codes


def test_market_regime():
    assert relative.market_regime(frame(np.linspace(100, 150, 300)))["state"] == "RISK-ON"
    assert relative.market_regime(frame(np.linspace(150, 100, 300)))["state"] == "RISK-OFF"


def test_catalysts_earnings_ratings_news():
    now = datetime.now(timezone.utc)
    events = {
        "earnings_date": date(2026, 1, 8),
        "rating_changes": [
            {"date": now - timedelta(days=2), "firm": "MS", "action": "down", "from_grade": "Buy", "to_grade": "Hold"},
            {"date": now - timedelta(days=60), "firm": "GS", "action": "up", "from_grade": "Hold", "to_grade": "Buy"},
        ],
        "news": [
            {"title": "Company announces stock offering", "published": now - timedelta(hours=5)},
            {"title": "Company beats estimates", "published": now - timedelta(hours=6)},
            {"title": "Company faces lawsuit", "published": now - timedelta(days=10)},
        ],
    }
    m, sig = catalysts.analyze(events, owned=True, tier=2, today=date(2026, 1, 5))
    codes = {s.code: s for s in sig}
    assert m["days_to_earnings"] == 3 and codes["earnings_soon"].severity == 2
    assert "downgrade" in codes and "upgrade" not in codes        # old upgrade is outside the window
    assert codes["news_negative"].severity == 2 and "offering" in codes["news_negative"].message
    assert "news_positive" in codes


def test_catalysts_handles_naive_dates_and_empty():
    m, sig = catalysts.analyze({}, owned=False, tier=1)
    assert sig == [] and m["earnings_date"] is None
    naive = {"rating_changes": [{"date": datetime.now() - timedelta(days=1), "firm": "X", "action": "up"}]}
    assert catalysts.analyze(naive, owned=True, tier=1)[1][0].code == "upgrade"


def test_cached_provider_dedupes_and_does_not_cache_errors():
    calls = []

    class Inner(DemoProvider):
        def history(self, ticker, period="5y"):
            calls.append(ticker)
            if ticker == "BAD":
                raise ValueError("boom")
            return super().history(ticker, period)

    cp = CachedProvider(Inner())
    cp.history("SPY"), cp.history("SPY")
    assert calls.count("SPY") == 1
    for _ in range(2):
        with pytest.raises(ValueError):
            cp.history("BAD")
    assert calls.count("BAD") == 2


def test_fleet_overrides_layer_over_config(tmp_path):
    store = Store(tmp_path / "t.db")
    base = make_portfolio(Holding("AAA", 1, 10, 50.0), Holding("BBB", 2, 5))
    store.upsert_ticker("ccc", 2, 0)
    store.upsert_ticker("AAA", 2, 20)
    store.remove_ticker("BBB")
    p = store.apply_overrides(base)
    by = {h.ticker: h for h in p.holdings}
    assert set(by) == {"AAA", "CCC"}
    assert by["AAA"].tier == 2 and by["AAA"].shares == 20 and by["AAA"].cost_basis == 50.0
    store.upsert_ticker("BBB", 1, 0)  # re-adding a removed ticker brings it back
    assert "BBB" in {h.ticker for h in store.apply_overrides(base).holdings}


def test_to_yaml_round_trips(tmp_path, monkeypatch):
    p = make_portfolio(Holding("AAA", 1, 10, 50.0), Holding("WWW", 2, 0))
    monkeypatch.setenv("STOCKWATCH_PORTFOLIO", to_yaml(p))
    back = {h.ticker: h for h in load_portfolio().holdings}
    assert back["AAA"].cost_basis == 50.0 and back["WWW"].is_watchlist


# ---- deep research and briefings

from stockwatch import briefing, deepdive


def test_earnings_track_streaks_trends_and_reaction():
    idx = pd.bdate_range("2025-01-01", periods=400)
    vol = np.full(400, 1e6)
    close = np.linspace(100, 120, 400)
    spike = idx.get_loc(idx[idx >= pd.Timestamp("2025-10-28")][0])
    vol[spike] = 9e6
    close[spike:] *= 1.08
    hist = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": vol}, index=idx)
    q = [date(2025, 9, 30), date(2025, 6, 30), date(2025, 3, 31), date(2024, 12, 31)]
    research = {
        "earnings": [{"quarter": d, "eps_actual": 1.1, "eps_estimate": 1.0, "surprise_pct": 0.1} for d in q],
        "quarterly": [{"period": d, "revenue": r, "gross_profit": r * 0.5, "operating_income": r * om, "net_income": 0}
                      for d, r, om in zip(q + [date(2024, 9, 30)], [140, 130, 120, 110, 100], [0.3, 0.25, 0.2, 0.2, 0.2])],
    }
    m, sig = deepdive.earnings_track(research, hist)
    codes = {s.code for s in sig}
    assert m["beat_streak"] == 4 and {"beat_streak", "revenue_rising", "margin_expanding"} <= codes
    assert m["quarters"][0]["report_day"] == "2025-10-28" and abs(m["quarters"][0]["reaction"] - 0.08) < 0.01
    assert abs(m["revenue_yoy_latest"] - 0.4) < 1e-9


def test_smart_money_insiders_and_shorts():
    now = datetime.now()
    research = {"insiders": [
        {"date": now - timedelta(days=5), "insider": "A", "text": "Purchase at price 10", "value": 200_000},
        {"date": now - timedelta(days=9), "insider": "B", "text": "Purchase at price 11", "value": 100_000},
        {"date": now - timedelta(days=3), "insider": "C", "text": "Stock Award(Grant)", "value": 9e9},
        {"date": now - timedelta(days=200), "insider": "D", "text": "Sale at price 30", "value": 9e9},
    ]}
    f = {"short_pct_float": 0.25, "short_ratio": 4.0, "shares_short": 13e6, "shares_short_prior": 10e6}
    m, sig = deepdive.smart_money(f, research)
    codes = {s.code: s for s in sig}
    assert m["insider_buy_90d"] == 300_000 and m["buyers_90d"] == 2 and m["insider_sell_90d"] == 0
    assert codes["insider_buying"].severity == 2 and codes["heavily_shorted"].severity == 2 and "shorts_adding" in codes
    assert m["insider_tx"][0]["insider"] == "C"  # newest first


def test_valuation_context_guards_and_fair_value():
    hist = frame(np.full(800, 100.0))
    hist.index = pd.bdate_range("2022-06-01", periods=800)
    annual = [{"period": date(2024, 12, 31), "eps": 5.0}, {"period": date(2023, 12, 31), "eps": 4.0}]
    f = {"pe_trailing": 15.0, "pe_forward": 12.0, "eps_forward": 8.0, "revenue_growth": 0.2,
         "target_mean_price": 130.0, "target_low_price": 90.0, "target_high_price": 400.0}
    peers = {"P1": {"pe_forward": 20.0, "revenue_growth": 0.1}, "P2": {"pe_forward": 24.0, "revenue_growth": 0.1}}
    m, sig = deepdive.valuation_context(f, {"annual": annual}, hist, peers, 100.0)
    assert m["pe_hist_median"] == 22.5 and m["peer_median_pe"] == 22.0
    assert {"cheap_vs_history", "cheap_vs_peers"} <= {s.code for s in sig}
    fv = m["fair_value"]
    assert set(fv["methods"]) == {"analysts", "own history", "peer multiple"}
    assert fv["high"] < 200  # spans method midpoints, not the most bullish single target
    # a split-distorted EPS history (P/E 100x off) is discarded rather than trusted
    m2, _ = deepdive.valuation_context(f, {"annual": [{"period": date(2024, 12, 31), "eps": 0.05}]}, hist, {}, 100.0)
    assert m2["pe_hist_median"] is None and "own history" not in m2.get("fair_value", {}).get("methods", {})


def test_levels_find_nearest_support_and_resistance():
    wave = 100 + 10 * np.sin(np.linspace(0, 12 * np.pi, 300))
    lv = deepdive.levels(frame(wave), 100.0)
    assert lv["support"] < 100 < lv["resistance"]


def test_briefing_reports_changes_and_watch_items():
    store_snap = lambda verdict, composite, price, codes: {  # noqa: E731
        "ticker": "X", "tier": 1, "verdict": verdict, "composite": composite, "price": price,
        "fundamental_score": 72, "technical_score": 40,
        "payload": {"watchlist": False, "error": None, "position": {},
                    "signals": [{"kind": "risk", "code": c, "message": c.upper(), "severity": 2, "source": "t"} for c in codes],
                    "technical": {"trend": "down", "rsi": 25.0, "sma200": 110.0, "trailing_stop": 95.0,
                                  "rs_spy_3m": -0.2},
                    "fundamental": {"pillar_growth": 90, "pillar_quality": 30},
                    "events": {"earnings_date": "2026-11-01", "days_to_earnings": 5},
                    "research": {"earnings": {"avg_move": 0.07, "beats": 3, "reported": 4}}}}
    prev, now = store_snap("HOLD", 60, 100.0, ["old"]), store_snap("RISK - REVIEW", 45, 90.0, ["new"])
    b = briefing.stock(now, prev)
    text = " ".join(b["changed"] + b["watch"] + b["why"])
    assert "HOLD to RISK - REVIEW" in text and "fell 15 points" in text and "New: NEW" in text and "Cleared: OLD" in text
    assert "moved about 7%" in text and "stop has been hit" in text and "would turn the trend up" in text
    assert "underperformed the market by 20%" in text and "best on growth (90)" in text
    assert briefing.stock(now)["changed"][0].startswith("First scan")
    lines = briefing.portfolio([now], {"X": prev}, {"state": "RISK-OFF", "day_change": -0.01})
    assert any("hostile" in l for l in lines) and any("HOLD -> RISK - REVIEW" in l for l in lines)


def test_company_overview_report_card():
    snap = {"ticker": "X", "verdict": "HOLD", "technical_score": 30.0, "payload": {
        "profile": {"name": "Xco", "industry": "Semiconductors", "country": "Taiwan", "market_cap": 5e11,
                    "employees": 70000, "summary": "Makes chips."},
        "fundamental": {"pillar_valuation": 85, "pillar_growth": 70, "pillar_quality": 90, "pillar_balance": 20,
                        "pe": 18.0, "revenue_growth": 0.3, "operating_margin": 0.4, "debt_to_equity": 3.0},
        "technical": {"trend": "down", "rs_spy_3m": -0.1},
        "research": {"earnings": {"beats": 4, "reported": 4, "avg_move": 0.05},
                     "smart_money": {"buyers_90d": 2, "short_pct_float": 0.02, "institution_pct": 0.6}}}}
    o = briefing.overview(snap)
    assert o["intro"].startswith("Xco is a mega-cap semiconductors company based in Taiwan")
    grades = {g["area"]: g["grade"] for g in o["grades"]}
    assert grades == {"Valuation": "A", "Growth": "B", "Profitability": "A", "Balance sheet": "F",
                      "Momentum": "F", "Earnings delivery": "A", "Smart money": "A"}
    assert o["strengths"][0].startswith(("Profitability", "Earnings delivery", "Smart money"))
    assert any(c.startswith("Balance sheet: debt/equity 3.0") for c in o["concerns"])
    # missing data degrades to fewer grades, not errors
    bare = briefing.overview({"ticker": "Y", "verdict": "WATCH", "technical_score": 50.0, "payload": {}})
    assert bare["name"] == "Y" and {g["area"] for g in bare["grades"] if g["grade"] != "?"} == {"Momentum"}


# ---- extended hours

from stockwatch.data import YahooProvider, us_session
from stockwatch.engine import _extended_hours


def test_us_session_by_new_york_clock():
    utc = timezone.utc
    assert us_session(datetime(2026, 10, 21, 12, 0, tzinfo=utc)) == "PRE"       # 08:00 ET Wed
    assert us_session(datetime(2026, 10, 21, 15, 0, tzinfo=utc)) == "REGULAR"   # 11:00 ET
    assert us_session(datetime(2026, 10, 21, 21, 30, tzinfo=utc)) == "POST"     # 17:30 ET
    assert us_session(datetime(2026, 10, 22, 2, 0, tzinfo=utc)) == "CLOSED"     # 22:00 ET
    assert us_session(datetime(2026, 10, 24, 15, 0, tzinfo=utc)) == "CLOSED"    # Saturday


def _fake_yahoo(info, bars=None):
    """bars: a DataFrame for every history() call, or a dict of interval -> DataFrame."""
    class T:
        def __init__(self, sym):
            self.info = info

        def history(self, **kw):
            b = bars.get(kw.get("interval")) if isinstance(bars, dict) else bars
            return b if b is not None else pd.DataFrame()

    yp = YahooProvider.__new__(YahooProvider)
    yp._yf = type("yf", (), {"Ticker": T})
    yp._industry = {}
    return yp


ORIGINAL_SESSION = us_session


def _clock(monkeypatch, session):
    """Pin 'now' to a session while bar timestamps are still classified by the real clock."""
    import stockwatch.data as data_mod
    monkeypatch.setattr(data_mod, "us_session", lambda now=None: session if now is None else ORIGINAL_SESSION(now))


def _bars(*points):
    idx = pd.DatetimeIndex([pd.Timestamp(t, tz="America/New_York") for t, _ in points])
    return pd.DataFrame({"Close": [c for _, c in points]}, index=idx)


def test_quote_reads_premarket_from_minute_bars(monkeypatch):
    _clock(monkeypatch, "PRE")
    bars = _bars(("2026-10-21 15:59", 50.0), ("2026-10-21 19:00", 49.0), ("2026-10-22 06:05", 52.0))
    q = _fake_yahoo({}, bars).quote("X")   # no quote fields at all, like when Yahoo blocks the token
    assert q["ext_session"] == "pre" and q["ext_price"] == 52.0 and q["source"] == "1m bars"
    assert abs(q["ext_change"] - 0.04) < 1e-9 and not q["ext_stale"] and q["market_state"] == "PRE"


def test_quote_flags_last_nights_after_hours_and_quiet_mornings(monkeypatch):
    _clock(monkeypatch, "PRE")
    q = _fake_yahoo({}, _bars(("2026-10-21 15:59", 50.0), ("2026-10-21 19:00", 49.0))).quote("X")
    assert q["ext_session"] == "post" and q["ext_stale"]
    quiet = _fake_yahoo({}, _bars(("2026-10-21 15:59", 50.0))).quote("X")
    assert quiet["ext_price"] is None and "no extended-hours trades" in quiet["error"]


def test_quote_falls_back_to_5m_bars_and_reports_failures(monkeypatch):
    _clock(monkeypatch, "POST")
    q = _fake_yahoo({}, {"1m": None, "5m": _bars(("2026-10-21 15:55", 100.0), ("2026-10-21 19:55", 105.0))}).quote("X")
    assert q["ext_session"] == "post" and q["source"] == "5m bars" and abs(q["ext_change"] - 0.05) < 1e-9
    assert "1m bars: no bars returned" in q["error"]
    broken = _fake_yahoo({}, None).quote("X")
    assert broken["ext_price"] is None and "5m bars: no bars returned" in broken["error"]
    _clock(monkeypatch, "REGULAR")
    live = _fake_yahoo({}, _bars(("2026-10-21 10:00", 100.0))).quote("X")
    assert live["ext_price"] is None and live["error"] is None


def test_quote_gives_live_price_and_day_change_in_regular_hours(monkeypatch):
    _clock(monkeypatch, "REGULAR")
    bars = _bars(("2026-10-20 15:59", 100.0), ("2026-10-20 18:00", 99.0),   # yesterday's close, then after hours
                 ("2026-10-21 08:00", 101.0), ("2026-10-21 11:42", 103.0))  # this morning's pre-market, then live
    q = _fake_yahoo({}, bars).quote("X")
    assert q["live_price"] == 103.0 and abs(q["live_change"] - 0.03) < 1e-9   # vs yesterday's regular close
    assert q["ext_price"] is None and q["live_time"].tzinfo is not None


def test_yahoo_fundamentals_refuse_empty_responses():
    with pytest.raises(RuntimeError, match="rate-limited"):
        _fake_yahoo({"shortName": "X"}).fundamentals("X")
    yp = _fake_yahoo({"shortName": "X", "marketCap": 1e9, "trailingPE": 20, "revenueGrowth": 0.1,
                      "industryKey": "semis"})
    assert yp.fundamentals("X")["pe_trailing"] == 20 and yp._industry["X"] == "semis"


def test_extended_hours_signal_thresholds():
    assert _extended_hours({"ext_change": 0.02, "ext_price": 1, "ext_session": "post"}, False) == []
    s = _extended_hours({"ext_change": -0.07, "ext_price": 93.0, "ext_session": "post"}, False)[0]
    assert s.kind == "risk" and s.severity == 2 and s.message.startswith("After hours: -7.0%")
    s = _extended_hours({"ext_change": 0.06, "ext_price": 10.6, "ext_session": "pre"}, True)[0]
    assert s.kind == "opportunity" and s.severity == 1 and "Pre-market" in s.message


# ---- push notifications

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from stockwatch import notify
from stockwatch.signals import Signal


def test_ntfy_sends_one_grouped_push(monkeypatch):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, dict(self.headers), self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    monkeypatch.setenv("NTFY_SERVER", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("NTFY_TOPIC", "sw-test")
    monkeypatch.setenv("DASHBOARD_URL", "https://example.streamlit.app")
    for var in ("TELEGRAM_BOT_TOKEN", "SMTP_HOST"):
        monkeypatch.delenv(var, raising=False)
    alerts = [("AAA", 10.0, "HOLD", Signal("opportunity", "t", "x", "Golden cross", 2))]
    alerts += [(f"T{i}", 5.0, "RISK - REVIEW", Signal("risk", "p", "stop_loss", "Hit stop", 3)) for i in range(20)]
    notify.send(alerts)
    srv.server_close()

    path, headers, body = received[0]
    lines = body.decode().splitlines()
    assert len(received) == 1 and path == "/sw-test"
    assert headers["Priority"] == "5" and headers["Tags"] == "rotating_light"
    assert headers["Title"].startswith("StockWatch: 21 alerts - T0") and headers["Click"].endswith("streamlit.app")
    assert lines[0].startswith("🔴 T0") and lines[-1] == "+6 more in the dashboard log"   # urgent first, capped


def test_send_survives_channel_failure(monkeypatch, capsys):
    monkeypatch.setenv("NTFY_SERVER", "http://127.0.0.1:9")  # nothing listens here
    monkeypatch.setenv("NTFY_TOPIC", "sw-test")
    notify.send([("AAA", 1.0, "HOLD", Signal("risk", "t", "x", "msg", 2))])
    assert "AAA" in capsys.readouterr().out


# ---- Google Sheet ticker list

from stockwatch import config as cfg

SHEET = "https://docs.google.com/spreadsheets/d/1SQ8UHD2HYSTPFex7VV8fUQ3KRWQ087SqdFNS7lXPEzA/edit#gid=0"


def test_sheet_urls():
    assert cfg.sheet_csv_url(SHEET).endswith("/1SQ8UHD2HYSTPFex7VV8fUQ3KRWQ087SqdFNS7lXPEzA/export?format=csv&gid=0")
    assert cfg.sheet_csv_url(SHEET.replace("gid=0", "gid=77")).endswith("gid=77")
    pub = "https://docs.google.com/spreadsheets/d/e/2PACX-abc/pub?gid=0&single=true&output=csv"
    assert cfg.sheet_csv_url(pub) == pub
    assert cfg.sheet_edit_url(SHEET) == SHEET.split("#")[0]


def test_parse_holdings_csv_is_forgiving():
    text = ("Ticker,Tier,Shares,Avg cost,Target price,Notes\n"
            "googl,1,1.5,\"$1,150.50\",,core idea\n"
            " NVDA ,x,3,,,\n"
            ",,,,,\n"
            "RR,2,,,,\n"
            "NVDA,1,4,,,\n")
    hs = {h.ticker: h for h in cfg.parse_holdings_csv(text)}
    assert list(hs) == ["GOOGL", "NVDA", "RR"]
    assert hs["GOOGL"].cost_basis == 1150.5 and hs["GOOGL"].notes == "core idea"
    assert hs["NVDA"].tier == 1 and hs["NVDA"].shares == 4    # duplicate row: last one wins
    assert hs["RR"].is_watchlist and hs["RR"].tier == 2
    with pytest.raises(ValueError):
        cfg.parse_holdings_csv("Symbol-ish,Tier\nX,1\n")


def test_load_portfolio_prefers_sheet_and_falls_back(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_PORTFOLIO", "holdings:\n  - {ticker: OLD, tier: 1}\n")
    monkeypatch.setenv("STOCKWATCH_SHEET_URL", SHEET)
    monkeypatch.setattr(cfg, "fetch_sheet_csv", lambda url: "Ticker,Tier,Shares\nNEW,2,5\n")
    p = cfg.load_portfolio()
    assert [h.ticker for h in p.holdings] == ["NEW"] and p.sheet_url == SHEET and p.sheet_error is None

    def boom(url):
        raise PermissionError("not shared")
    monkeypatch.setattr(cfg, "fetch_sheet_csv", boom)
    p = cfg.load_portfolio()
    assert [h.ticker for h in p.holdings] == ["OLD"] and p.sheet_url is None and "not shared" in p.sheet_error


def test_fetch_sheet_csv_detects_unshared_sheet(monkeypatch):
    class Resp(io.BytesIO):
        def __init__(self, body, ctype):
            super().__init__(body)
            self.headers = {"Content-Type": ctype}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(cfg.urllib.request, "urlopen",
                        lambda url, timeout: Resp(b"<!DOCTYPE html><title>Sign in</title>", "text/html"))
    with pytest.raises(PermissionError, match="Anyone with the link"):
        cfg.fetch_sheet_csv(SHEET)
    monkeypatch.setattr(cfg.urllib.request, "urlopen",
                        lambda url, timeout: Resp("﻿Ticker,Tier\nAAA,1\n".encode(), "text/csv"))
    assert cfg.fetch_sheet_csv(SHEET).startswith("Ticker")


# ---- technical shift, SEC filings, S&P scan, links

from stockwatch import market, sec, ui
from stockwatch.engine import _technical_shift


def test_technical_shift_flags_breakdown_independent_of_fundamentals():
    up = np.geomspace(50, 150, 300)
    crash = np.r_[up, up[-1] * np.geomspace(1, 0.78, 6)[1:]]
    hist = frame(crash)
    ts, _, _ = technical.analyze(hist, 2.5)
    sig = _technical_shift(hist, ts, fs=75, atr_mult=2.5, owned=True)
    assert sig and sig[0].code == "technical_breakdown" and sig[0].severity == 2
    assert "fundamentals unchanged and still solid (75)" in sig[0].message
    steady = frame(up)
    assert _technical_shift(steady, technical.analyze(steady)[0], 75, 2.5, True) == []


def test_sec_analysis_events_offerings_and_dilution():
    today = date(2026, 10, 21)
    data = {"filings": [
        {"form": "8-K", "date": "2026-10-19", "items": "4.02,9.01", "url": "u"},
        {"form": "8-K", "date": "2026-10-18", "items": "1.01", "url": "u"},
        {"form": "424B5", "date": "2026-10-10", "items": "", "url": "u"},
        {"form": "NT 10-Q", "date": "2026-09-30", "items": "", "url": "u"},
        {"form": "8-K", "date": "2026-08-01", "items": "1.03", "url": "u"},   # too old to alert
        {"form": "4", "date": "2026-10-01", "items": "", "url": "u"},
    ], "shares": [{"end": "2026-09-30", "value": 120e6}, {"end": "2026-06-30", "value": 110e6},
                  {"end": "2025-09-30", "value": 100e6}]}
    m, sig = sec.analyze(data, market_cap=5e8, today=today)
    codes = {s.code: s for s in sig}
    assert codes["8k_4.02"].severity == 3 and codes["8k_1.01"].kind == "opportunity"
    assert codes["sec_offering"].severity == 2 and "sec_late_filing" in codes and "8k_1.03" not in codes
    assert codes["dilution"].severity == 2 and abs(m["shares_change_1y"] - 0.2) < 1e-9
    assert m["form4_90d"] == 1 and all(f["form"] != "4" for f in m["filings"])
    assert m["filings"][0]["label"] == "8-K: past financial statements can no longer be relied on"
    _, sig_big = sec.analyze(data, market_cap=5e11, today=today)
    assert {s.code: s for s in sig_big}["sec_offering"].severity == 1   # shelf filings are routine for large caps


def _fresh_ticker_list(monkeypatch):
    monkeypatch.setattr(sec, "_ticker_list", {"tickers": None, "fetched": 0.0, "failed": 0.0, "error": None})


def test_sec_ticker_lookup_uses_bundled_ciks(monkeypatch):
    _fresh_ticker_list(monkeypatch)
    monkeypatch.setattr(sec, "_get", lambda url: (_ for _ in ()).throw(OSError("offline")))
    assert sec.cik_for("AAPL") == 320193 and sec.cik_for("brk.b") == 1067983
    assert sec.cik_for(" BRK/B ") == 1067983                            # spellings of a share class


def test_sec_ticker_list_failure_is_reported_and_retried_not_remembered(monkeypatch):
    """Non-S&P tickers (RIVN) need SEC's ticker list. A failed download used to be cached for the life of
    the process and reported as "no SEC CIK"; now the reason is kept and the download is retried."""
    _fresh_ticker_list(monkeypatch)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    calls, fail = [], [True]

    def get(url):
        calls.append(url)
        if fail[0]:
            raise OSError("HTTP Error 403: Forbidden")
        return {"0": {"cik_str": 1874178, "ticker": "RIVN", "title": "Rivian Automotive, Inc."}}
    monkeypatch.setattr(sec, "_get", get)
    t0 = 1_000_000.0
    cik, why = sec.cik_lookup("RIVN", now=t0)
    assert cik is None and "SEC ticker list unavailable" in why and "403" in why
    assert "SEC_USER_AGENT is missing" in why                         # the likely cause is named
    assert sec.cik_lookup("MSFT", now=t0) == (789019, None)            # S&P names don't need the list
    sec.cik_lookup("RIVN", now=t0 + 60)
    assert len(calls) == 1                                              # no hammering inside the retry window
    fail[0] = False
    assert sec.cik_lookup("rivn ", now=t0 + sec.TICKER_LIST_RETRY + 1) == (1874178, None)   # retried, found
    assert sec.cik_lookup("ZZZZ", now=t0 + sec.TICKER_LIST_RETRY + 2) == (None, "not in SEC's ticker list")
    fail[0] = True                                                      # a later failure keeps the last good list
    later = t0 + sec.TICKER_LIST_RETRY + sec.TICKER_LIST_TTL + 10
    assert sec.cik_lookup("RIVN", now=later) == (1874178, None) and len(calls) == 3
    cik, why = sec.cik_lookup("NEWCO", now=later)                     # absence from a stale list isn't verified
    assert cik is None and "as last downloaded (refresh failing" in why and "recent listing" in why


def test_every_workflow_job_that_runs_stockwatch_identifies_itself_to_sec():
    """Any job running StockWatch code may reach SEC (filings, or the fundamentals fallback when Yahoo
    refuses), so each must pass the SEC_USER_AGENT secret. The S&P market job once didn't."""
    import yaml
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    checked = []
    for wf in sorted((root / ".github" / "workflows").glob("*.yml")):
        jobs = (yaml.safe_load(wf.read_text()) or {}).get("jobs") or {}
        for name, job in jobs.items():
            runs = " ".join(str(step.get("run", "")) for step in job.get("steps") or [])
            if "stockwatch" not in runs:
                continue
            checked.append(f"{wf.name}:{name}")
            env = {**(job.get("env") or {})}
            assert env.get("SEC_USER_AGENT") == "${{ secrets.SEC_USER_AGENT }}", f"{wf.name}:{name}"
            assert "SEC_USER_AGENT not set" in runs, f"{wf.name}:{name} doesn't warn when it's missing"
    assert {"scan.yml:scan", "scan.yml:market", "sec-audit.yml:audit"} <= set(checked)


def test_sec_user_agent_status_and_fallback_never_expose_the_value(monkeypatch):
    sent = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        sent.append(req.get_header("User-agent"))
        return Resp(b"{}")
    monkeypatch.setattr(sec.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sec, "_warned_user_agent", False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    assert sec.user_agent_status() == "missing"
    sec._get("https://data.sec.gov/x.json")
    sec._get("https://data.sec.gov/y.json")
    assert sent == [sec.DEFAULT_USER_AGENT] * 2 and sec._warned_user_agent  # still works, warned once
    monkeypatch.setenv("SEC_USER_AGENT", "just-a-name")
    assert sec.user_agent_status() == "invalid"
    monkeypatch.setenv("SEC_USER_AGENT", "Jane Doe jane.doe@example.com")
    assert sec.user_agent_status() == "configured"
    sec._get("https://data.sec.gov/z.json")
    assert sent[-1] == "Jane Doe jane.doe@example.com"
    md = sec_audit.markdown([], today=date(2026, 10, 22))
    assert "SEC identification (SEC_USER_AGENT): configured." in md and "jane" not in md.lower()
    monkeypatch.delenv("SEC_USER_AGENT")
    assert "**not configured** (missing)" in sec_audit.markdown([], today=date(2026, 10, 22))


def test_sec_user_agent_pasted_over_two_lines_is_sent_as_one_valid_header(monkeypatch):
    import http.client
    sent = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        sent.append(req.get_header("User-agent"))
        return Resp(b"{}")
    monkeypatch.setattr(sec.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("SEC_USER_AGENT", "Jane Doe\r\n  jane.doe@example.com\n")
    assert sec.user_agent_status() == "configured"
    sec._get("https://data.sec.gov/z.json")
    assert sent[-1] == "Jane Doe jane.doe@example.com"
    assert not http.client._is_illegal_header_value(sent[-1].encode())   # what urllib checks before sending
    monkeypatch.setenv("SEC_USER_AGENT", "Jane Doe jane.doe@example.com\x07")
    assert sec.user_agent_status() == "invalid"


def test_market_screen_and_run_on_demo():
    universe = market.load_universe()
    assert len(universe) > 450 and {"ticker", "name", "sector", "cik"} <= set(universe.columns)
    hists = {"UP": frame(np.r_[np.geomspace(50, 150, 280), np.linspace(150, 140, 8)]),
             "DOWN": frame(np.geomspace(150, 50, 288))}
    shortlist = market.screen(hists, frame(np.linspace(100, 110, 288)))
    assert list(shortlist["ticker"]) == ["UP"]
    small = universe.head(30)
    monkey = market._universe_cache
    market._universe_cache = (time.time(), small)
    try:
        scan = market.run(get_provider("demo"), top=5)
    finally:
        market._universe_cache = monkey
    assert scan["universe"] == 30 and len(scan["results"]) <= 5
    assert all({"ticker", "verdict", "composite", "triggers"} <= set(r) for r in scan["results"])


def test_link_tickers_only_links_whole_symbols():
    html = ui.link_tickers("Needs attention: RR, RRX & <b>", {"RR", "RRX"})
    assert '<a href="?view=target&t=RR" target="_self">RR</a>,' in html
    assert '<a href="?view=target&t=RRX" target="_self">RRX</a>' in html and "&lt;b&gt;" in html


# ---- trade plan

from stockwatch import tradeplan


def _plan(close, verdict, tier=2, watchlist=True, fs=70.0, **kw):
    hist = frame(close)
    _, tech, _ = technical.analyze(hist, 2.5, owned=not watchlist)
    return tradeplan.build(hist, tech, {"analyst_upside": kw.get("upside")}, fs, verdict, tier, watchlist,
                           events=kw.get("events"), quote=kw.get("quote"))


UPTREND_DIP = np.r_[np.geomspace(50, 150, 280), np.linspace(150, 141, 8)]


def test_plan_buy_setup_has_ordered_levels():
    p = _plan(UPTREND_DIP, "BUY SETUP")
    assert p["stance"] in ("BUY NOW", "BUY ON PULLBACK") and p["bias"] == "bullish"
    t1, t2 = (t["price"] for t in p["targets"])
    assert p["stop"] < p["entry_low"] <= p["entry_high"] < t1 < t2
    assert t1 >= p["entry"] + 1.5 * p["risk_per_share"] - 1e-9
    assert any("Stop: sell if it closes below" in e for e in p["exits"])


def test_plan_never_says_buy_when_verdict_says_watch():
    p = _plan(UPTREND_DIP, "WATCH")
    assert p["stance"] in ("WAIT FOR CONFIRMATION", "BUY ON PULLBACK")
    assert p["stance"] != "BUY NOW" and p["trigger"]


def test_plan_breakout_and_no_trade():
    breakout = _plan(np.geomspace(50, 150, 300), "BUY SETUP")
    assert breakout["stance"] == "BUY THE BREAKOUT" and "close above" in breakout["trigger"]
    no_trade = _plan(np.geomspace(150, 60, 300), "AVOID", fs=30)
    assert no_trade["stance"] == "NO TRADE" and no_trade["bias"] == "bearish"
    assert len(no_trade["exits"]) == 2 and "revisit" in no_trade["trigger"]


def test_plan_for_held_positions_and_warnings():
    exit_plan = _plan(np.geomspace(150, 60, 300), "RISK - REVIEW", watchlist=False, fs=30)
    assert exit_plan["stance"] == "REDUCE / EXIT" and exit_plan["exits"][0].startswith("Reduce or exit now")
    assert not any("Take a third" in e for e in exit_plan["exits"]) and "current price" in exit_plan["stop_basis"]
    hold = _plan(UPTREND_DIP, "STRONG HOLD", tier=1, watchlist=False,
                 events={"days_to_earnings": 3}, quote={"ext_change": -0.06, "ext_session": "post"})
    assert hold["stance"] == "HOLD" and hold["horizon"].startswith("Position trade")
    assert any("Earnings in 3 days" in n for n in hold["notes"]) and any("After hours" in n for n in hold["notes"])


def test_position_sizing_risk_budget_and_cap():
    plan = {"risk_per_share": 5.0, "entry": 100.0}
    s = tradeplan.size(plan, 100_000, 1.0, 50)
    assert s["budget"] == 1000 and s["shares"] == 200 and not s["capped"]
    capped = tradeplan.size(plan, 100_000, 1.0, 7)
    assert capped["capped"] and capped["value"] == pytest.approx(7000)
    assert tradeplan.size(plan, 0, 1.0, 7) is None


# ---- street view, scenarios, earnings setup, older scenarios, plan refinement

from stockwatch import analogs, street


def test_consensus_and_scenarios():
    c = street.consensus([{"period": "0m", "strongBuy": 5, "buy": 10, "hold": 4, "sell": 1, "strongSell": 0},
                          {"period": "-1m"}, {"period": "-2m"},
                          {"period": "-3m", "strongBuy": 1, "buy": 5, "hold": 10, "sell": 3, "strongSell": 1}])
    assert c["label"] == "Buy" and c["buy"] == 15 and c["sell"] == 1 and c["change_3m"] < -0.5
    sc = street.scenarios(100.0, 0.30, 130.0)
    assert [x["months"] for x in sc] == [3, 6, 12]
    year = sc[-1]
    assert year["bear"] < 100 < year["base"] < year["bull"] and 0.5 < year["p_up"] < 0.8
    assert abs(year["base"] - 100 * (1 + 0.5 * 0.30 + 0.5 * street.MARKET_RETURN)) < 1e-9   # blended, not the raw target


def test_street_signals_revisions_and_growth():
    raw = {"recs": [], "targets": {"median": 120.0, "low": 80.0},
           "eps": {"0y": {"growth": 0.05}, "+1y": {"growth": 0.25}},
           "eps_trend": {"0y": {"current": 2.06, "30d": 2.0, "90d": 1.9}},
           "revisions": {"0y": {"up30": 6, "down30": 1}}, "options": []}
    m, sig = street.analyze(raw, 100.0, frame(np.linspace(90, 100, 300)), None, {}, {}, None, owned=True)
    codes = {s.code for s in sig}
    assert {"estimates_rising", "growth_accelerating"} <= codes
    assert abs(m["revisions"]["eps_30d"] - 0.03) < 1e-9 and m["upside_median"] == pytest.approx(0.2)
    assert m["sigma_source"] == "price history" and len(m["scenarios"]) == 3


def test_earnings_setup_verdicts():
    earn = {"reported": 4, "beats": 4, "quarters": [{"reaction": 0.05}, {"reaction": 0.03}]}
    good = street.earnings_setup(5, earn, {"eps_30d": 0.04}, frame(np.linspace(100, 98, 300)),
                                 frame(np.linspace(100, 110, 300)), 0.06, {})
    assert good["verdict"] == "favourable" and len(good["for"]) >= 3
    bad_earn = {"reported": 4, "beats": 1, "quarters": [{"reaction": -0.06}]}
    runup = frame(np.r_[np.full(279, 100.0), np.linspace(100, 125, 21)])
    bad = street.earnings_setup(5, bad_earn, {"eps_30d": -0.05}, runup, frame(np.full(300, 100.0)), 0.15,
                                {"pe_vs_peers": 0.8})
    assert bad["verdict"] == "unfavourable" and "unusually large" in bad["note"]
    assert street.earnings_setup(None, earn, {}, runup, None, None, {}) is None


def test_analog_replay_counts_outcomes():
    rng = np.random.default_rng(3)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0008, 0.015, 1200)))
    h = analogs.replay(frame(close), stop_pct=0.05, target_pct=0.08, tier=2)
    assert h and h["n"] >= 6 and h["horizon_days"] == 30
    assert abs(h["win_rate"] + h["loss_rate"] + h["neither_rate"] - 1) < 1e-9
    assert analogs.replay(frame(close[:200]), 0.05, 0.08, 2) is None


def test_refine_uses_history_earnings_and_forward_view():
    base = _plan(UPTREND_DIP, "BUY SETUP")
    tech = {"trend": "up", "atr": 2.0}
    weak_history = {"n": 20, "win_rate": 0.3, "loss_rate": 0.6, "neither_rate": 0.1, "median_days_to_target": 12}
    r = tradeplan.refine(base, weak_history, {}, {}, 2, False, tech, 70)
    assert r["stance"] == "WAIT FOR CONFIRMATION" and "only 30% of 20" in r["notes"][-1]
    assert "12 trading days" in r["timeframe"] and any("about 18 trading days" in e for e in r["exits"])
    st = {"earnings_setup": {"days": 3, "verdict": "unfavourable", "for": [], "against": ["x"]},
          "consensus": {"score": 2.0, "label": "Buy", "buy": 10, "hold": 3, "sell": 0},
          "targets": {"median": 200.0}, "upside_median": 0.3, "growth": {"+1y": {"eps": 0.2}},
          "revisions": {"eps_30d": 0.05}, "scenarios": [{"months": 12, "bear": 1, "base": 2, "bull": 3, "p_up": 0.7}]}
    held = tradeplan.refine({**base, "stance": "HOLD"}, None, st, {}, 2, True, tech, 70)
    assert any("consider trimming before the report" in n for n in held["notes"])
    assert held["bias"] == "bullish" and any("rates it Buy" in f for f in held["forward"])
    entry = tradeplan.refine(base, None, st, {}, 2, False, tech, 70)
    assert entry["stance"] == "WAIT FOR CONFIRMATION" and "earnings report" in entry["trigger"]


def test_refresh_quotes_patches_latest_snapshot(tmp_path):
    from stockwatch.scanner import refresh_quotes
    store = Store(tmp_path / "q.db")
    p = make_portfolio(Holding("AAA", 2, 1))
    store.save_snapshot(evaluate(p.holdings[0], p, FixedProvider(frame(np.linspace(10, 20, 300)), {})))

    class Q:
        def quote(self, t):
            return {"market_state": "PRE", "ext_price": 21.0, "ext_change": 0.05, "ext_session": "pre"}
    assert refresh_quotes(p, Q(), store) == 1
    assert store.snapshot("AAA")["payload"]["quote"]["ext_price"] == 21.0


def test_news_tone_and_today_count():
    now = datetime.now(timezone.utc)
    m, _ = catalysts.analyze({"news": [{"title": "X beats estimates", "published": now - timedelta(hours=3)},
                                       {"title": "X faces lawsuit", "published": now - timedelta(hours=50)},
                                       {"title": "X holds annual meeting", "published": now - timedelta(hours=1)}]},
                             owned=True, tier=1)
    assert [n["tone"] for n in m["news"]] == ["positive", "negative", "neutral"] and m["news_today"] == 2


def test_sec_dilution_ignores_stock_splits():
    today = date(2026, 10, 21)
    split = {"filings": [], "shares": [{"end": "2026-09-30", "value": 4.3e9}, {"end": "2025-09-30", "value": 4.4e8}]}
    m, sig = sec.analyze(split, today=today)
    assert m["split"] == 10 and "dilution" not in {s.code for s in sig} and abs(m["shares_change_1y"] + 0.0227) < 1e-3
    diluted = {"filings": [], "shares": [{"end": "2026-09-30", "value": 2.6e8}, {"end": "2025-09-30", "value": 1e8}]}
    m, sig = sec.analyze(diluted, today=today)
    assert "split" not in m and {s.code: s for s in sig}["dilution"].severity == 2


def test_unavailable_fundamentals_are_unknown_not_bad():
    close = np.geomspace(150, 60, 300)
    ev = evaluate(Holding("X", 1, 10), make_portfolio(), FixedProvider(frame(close), {"debt_to_equity": 5.0}))
    codes = {s.code for s in ev.signals}
    assert ev.fundamental["available"] is False and ev.composite == ev.technical_score
    assert "fundamentals_unavailable" in codes
    assert not {"thesis_breakdown", "core_fundamentals_weak"} & codes


# ---- fundamentals from SEC filings (fallback when Yahoo refuses)

def _fact(start, end, val, form="10-Q", filed=None):
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed or end}


SEC_COMPANY = {"entityName": "Example Corp", "facts": {
    "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2026-07-25", "val": 100e6, "form": "10-Q", "filed": "2026-08-01"}]}}},
    "us-gaap": {
        # fiscal year = calendar year; latest filing is the Q2 10-Q (6-month YTD and 3-month figures)
        "Revenues": {"units": {"USD": [
            _fact("2024-01-01", "2024-12-31", 800e6, "10-K"), _fact("2025-01-01", "2025-12-31", 1000e6, "10-K"),
            _fact("2025-01-01", "2025-06-30", 450e6), _fact("2025-04-01", "2025-06-30", 230e6),
            _fact("2026-01-01", "2026-06-30", 600e6), _fact("2026-04-01", "2026-06-30", 310e6)]}},
        "NetIncomeLoss": {"units": {"USD": [
            _fact("2025-01-01", "2025-12-31", 100e6, "10-K"), _fact("2025-01-01", "2025-06-30", 40e6),
            _fact("2026-01-01", "2026-06-30", 60e6)]}},
        "OperatingIncomeLoss": {"units": {"USD": [
            _fact("2025-01-01", "2025-12-31", 150e6, "10-K"), _fact("2025-01-01", "2025-06-30", 60e6),
            _fact("2026-01-01", "2026-06-30", 90e6)]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
            _fact("2025-01-01", "2025-12-31", 200e6, "10-K"), _fact("2025-01-01", "2025-06-30", 90e6),
            _fact("2026-01-01", "2026-06-30", 110e6)]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
            _fact("2025-01-01", "2025-12-31", 50e6, "10-K"), _fact("2025-01-01", "2025-06-30", 20e6),
            _fact("2026-01-01", "2026-06-30", 30e6)]}},
        "StockholdersEquity": {"units": {"USD": [{"end": "2026-06-30", "val": 500e6, "form": "10-Q", "filed": "2026-08-01"}]}},
        "AssetsCurrent": {"units": {"USD": [{"end": "2026-06-30", "val": 300e6, "form": "10-Q"}]}},
        "LiabilitiesCurrent": {"units": {"USD": [{"end": "2026-06-30", "val": 150e6, "form": "10-Q"}]}},
        "LongTermDebtNoncurrent": {"units": {"USD": [{"end": "2026-06-30", "val": 200e6, "form": "10-Q"}]}},
    }}}


def test_sec_facts_trailing_twelve_months_and_growth(monkeypatch):
    monkeypatch.setattr(sec, "cik_for", lambda t: 123)
    monkeypatch.setattr(sec, "_get", lambda url: SEC_COMPANY)
    f = sec.fetch_facts("EXM")
    assert f["revenue"] == pytest.approx(1150e6)               # 600 YTD + 1000 FY - 450 prior YTD
    assert f["revenue_growth"] == pytest.approx(600 / 450 - 1)
    assert f["net_income"] == pytest.approx(120e6) and f["net_income_growth"] == pytest.approx(0.5)
    assert f["operating_cash_flow"] == pytest.approx(220e6) and f["capex"] == pytest.approx(60e6)
    assert f["shares"] == 100e6 and f["equity"] == 500e6
    d = sec.derive(f, price=24.0)
    assert d["market_cap"] == pytest.approx(2.4e9) and d["pe_trailing"] == pytest.approx(20.0)
    assert d["operating_margin"] == pytest.approx(180e6 / 1150e6)   # 90 YTD + 150 FY - 60 prior YTD and d["free_cash_flow"] == pytest.approx(160e6)
    assert d["debt_to_equity"] == pytest.approx(0.4) and d["current_ratio"] == pytest.approx(2.0)
    assert d["roe"] == pytest.approx(0.24) and d["source"] == "SEC filings"


def test_engine_falls_back_to_sec_fundamentals_when_yahoo_refuses(monkeypatch):
    monkeypatch.setattr(sec, "cik_for", lambda t: 123)
    monkeypatch.setattr(sec, "_get", lambda url: SEC_COMPANY)

    class Blocked(FixedProvider):
        def fundamentals(self, ticker):
            raise RuntimeError("Yahoo returned no fundamentals (likely rate-limited)")

        def sec_facts(self, ticker):
            return sec.fetch_facts(ticker)

    ev = evaluate(Holding("EXM", 1, 10), make_portfolio(), Blocked(frame(np.linspace(20, 24, 300)), {}))
    assert ev.fundamental["available"] and ev.fundamental["source"] == "SEC filings"
    assert ev.composite != ev.technical_score and "fundamentals_unavailable" not in {s.code for s in ev.signals}


def test_estimate_next_earnings_from_results_filings():
    filings = [{"form": "8-K", "date": "2025-10-28", "items": "2.02,9.01"},
               {"form": "8-K", "date": "2026-07-29", "items": "2.02"},
               {"form": "8-K", "date": "2026-08-05", "items": "5.02"}]
    assert sec.estimate_next_earnings(filings, today=date(2026, 10, 21)) == date(2026, 10, 27)
    assert sec.estimate_next_earnings([], today=date(2026, 10, 21)) is None


def test_technical_score_curve_and_breakdown():
    falling = frame(np.geomspace(150, 40, 300))
    ts, m, _ = technical.analyze(falling)
    assert 3 < ts < 25                                   # mostly negative factors: low, but not a flat 0
    assert m["raw_points"] == pytest.approx(sum(p for _, p in m["score_parts"]))
    assert any("below the 200-day" in name for name, _ in m["score_parts"])
    worse = frame(np.r_[np.geomspace(150, 40, 290), np.geomspace(40, 25, 10)])
    assert technical.analyze(worse)[0] < ts               # still ranked, not tied at 0
    assert technical.to_score(0) == 50 and abs(technical.to_score(10) - 60) < 1.5   # ~1:1 near the middle


def test_card_shows_live_price_during_regular_hours():
    snap = {"ticker": "X", "tier": 1, "verdict": "HOLD", "price": 100.0, "fundamental_score": 60,
            "technical_score": 55, "composite": 58,
            "payload": {"watchlist": False, "signals": [], "position": {}, "fundamental": {"available": True},
                        "technical": {"day_change": 0.01, "trend": "up"},
                        "quote": {"market_state": "REGULAR", "live_price": 104.5, "live_change": 0.045,
                                  "fetched_at": "2026-10-21T15:42:10+00:00"}}}
    html = ui.card(snap)
    assert "104.50" in html and "+4.5%" in html and "LIVE 15:42" in html and ">100.00" not in html
    snap["payload"]["quote"] = {"market_state": "CLOSED"}
    assert "100.00" in ui.card(snap) and "LIVE" not in ui.card(snap)


def test_bulk_quotes_split_one_download_per_ticker(monkeypatch):
    _clock(monkeypatch, "PRE")
    one = _bars(("2026-10-21 15:59", 50.0), ("2026-10-22 06:05", 52.0))
    two = _bars(("2026-10-21 15:59", 10.0))
    df = pd.concat({"AAA": one, "BBB": two}, axis=1)
    calls = []

    class YF:
        @staticmethod
        def download(tickers, **kw):
            calls.append((tuple(tickers), kw["interval"], kw["prepost"]))
            return df

    yp = YahooProvider.__new__(YahooProvider)
    yp._yf, yp._industry = YF, {}
    q = yp.bulk_quotes(["AAA", "BBB", "CCC"])
    assert calls == [(("AAA", "BBB", "CCC"), "1m", True)]                       # one request for all
    assert q["AAA"]["ext_session"] == "pre" and abs(q["AAA"]["ext_change"] - 0.04) < 1e-9
    assert q["BBB"]["ext_price"] is None and "no extended-hours trades" in q["BBB"]["error"]
    assert q["CCC"]["error"] == "not in the bulk download"


def test_live_tracker_sweeps_then_refreshes_prices(monkeypatch, tmp_path):
    from stockwatch import live
    import stockwatch.live as live_mod
    monkeypatch.setenv("STOCKWATCH_PORTFOLIO", "holdings:\n  - {ticker: AAA, tier: 2, shares: 5}\n")
    monkeypatch.delenv("STOCKWATCH_SHEET_URL", raising=False)
    store = Store(tmp_path / "live.db")
    t = live.Tracker(get_provider("demo"), store_path=tmp_path / "live.db", start=False)
    monkeypatch.setattr(live_mod, "us_session", lambda now=None: "CLOSED")
    assert t.step(store) == "closed"
    monkeypatch.setattr(live_mod, "us_session", lambda now=None: "REGULAR")
    assert t.step(store) == "sweep" and store.snapshot("AAA") is not None
    mark = store.watermark()
    assert t.step(store) == "idle"
    assert t.step(store, now=time.time() + live.QUOTE_SECONDS + 1) == "quotes"
    assert t.step(store, now=time.time() + live.SWEEP_SECONDS + 1) == "sweep"
    assert store.watermark() != mark and t.status()["session"] in ("PRE", "REGULAR", "POST", "CLOSED")


def test_card_marks_changed_verdicts():
    snap = {"ticker": "X", "tier": 1, "verdict": "BUY SETUP", "price": 10.0, "fundamental_score": 70,
            "technical_score": 60, "composite": 66,
            "payload": {"watchlist": True, "signals": [], "position": {}, "fundamental": {"available": True},
                        "technical": {}, "quote": {}}}
    assert "NEW</b> was WATCH" in ui.cards([snap], changed={"X": "WATCH"})
    assert "NEW" not in ui.cards([snap])


def test_tracker_runs_the_sp500_scan_on_schedule(monkeypatch, tmp_path):
    from stockwatch import live
    import stockwatch.live as live_mod
    monkeypatch.setenv("STOCKWATCH_PORTFOLIO", "holdings:\n  - {ticker: AAA, tier: 2, shares: 5}\n")
    monkeypatch.delenv("STOCKWATCH_SHEET_URL", raising=False)
    saved = market._universe_cache
    market._universe_cache = (time.time(), market.load_universe().head(40))
    try:
        store = Store(tmp_path / "m.db")
        t = live.Tracker(get_provider("demo"), store_path=tmp_path / "m.db", start=False)
        monkeypatch.setattr(live_mod, "us_session", lambda now=None: "CLOSED")
        assert not t.maybe_market_scan(store, background=False)
        monkeypatch.setattr(live_mod, "us_session", lambda now=None: "REGULAR")
        assert not t.maybe_market_scan(store, background=False)      # waits for the first portfolio sweep
        t.last_sweep = time.time()
        assert t.maybe_market_scan(store, background=False)          # nothing on record: scan now
        first = store.latest_market_scan()
        assert first and first["universe"] == 40
        assert not t.maybe_market_scan(store, background=False)      # just ran
        restarted = live.Tracker(get_provider("demo"), store_path=tmp_path / "m.db", start=False)
        restarted.last_sweep = time.time()
        assert not restarted.maybe_market_scan(store, background=False)   # a restart doesn't rescan
        assert t.maybe_market_scan(store, now=time.time() + live.MARKET_SECONDS + 1, background=False)
        logged = [a for a in store.recent_alerts() if a["code"] == "sp500_buy_setup"]
        buys = {r["ticker"] for r in first["results"] if r["verdict"] == "BUY SETUP"}
        assert {a["ticker"] for a in logged} == buys              # logged once, not again on the rescan
    finally:
        market._universe_cache = saved


# ---- turbo

from stockwatch import turbo
from stockwatch.engine import Evaluation


def _ev(stance="BUY NOW", verdict="BUY SETUP", composite=70.0, **plan):
    p = {"stance": stance, "entry_low": 98.0, "entry_high": 100.0, "stop": 94.0, "rr": 2.0, "trigger": "a close above 101",
         "targets": [{"price": 112.0}], "history": {"n": 20, "win_rate": 0.6}, **plan}
    return Evaluation("X", 2, True, 100.0, 60, 70, composite, verdict, [], {"atr": 2.0}, {}, plan=p, name="X Corp")


def test_turbo_buy_when_price_is_in_the_zone():
    d = turbo.decide(_ev(), {"price": 99.5, "day_change": 0.01, "extension_atr": 0.5, "sma20": 97.0})
    assert d["decision"] == "BUY" and d["confidence"] == "High" and "entry 98.00-100.00" in d["line"]


def test_turbo_does_not_chase_a_runner():
    d = turbo.decide(_ev(), {"price": 112.0, "day_change": 0.09, "extension_atr": 3.5, "sma20": 100.0})
    assert d["decision"] == "WAIT FOR PULLBACK" and d["chasing"] and "chasing here" in d["notes"][0]
    zone_low = float(d["line"].split("buy zone ")[1].split("-")[0])
    stop = float(d["line"].split("stop ")[1])
    assert stop < zone_low                                      # stop moved below the new zone


def test_turbo_ran_past_zone_and_broken_stop():
    ran = turbo.decide(_ev(), {"price": 104.0, "day_change": 0.02, "extension_atr": 1.0, "sma20": 99.0})
    assert ran["decision"] == "WAIT FOR PULLBACK" and "already above the entry zone" in ran["notes"][0]
    broke = turbo.decide(_ev(), {"price": 92.0, "day_change": -0.06, "extension_atr": -1.0, "sma20": 99.0})
    assert broke["decision"] == "PASS" and "below the stop" in broke["line"]
    avoid = turbo.decide(_ev(stance="NO TRADE", verdict="AVOID", composite=30), {"price": 99.0})
    assert avoid["decision"] == "PASS" and avoid["confidence"] == "High"


def test_turbo_momentum_vwap_and_relative_volume():
    idx = pd.date_range("2026-10-21 09:30", "2026-10-21 12:45", freq="1min", tz="America/New_York")
    intraday = pd.DataFrame({"Close": np.linspace(100, 104, len(idx)), "High": np.linspace(100, 104, len(idx)),
                             "Low": np.linspace(100, 104, len(idx)), "Volume": np.full(len(idx), 1000.0)}, index=idx)
    hist = frame(np.linspace(80, 100, 300))
    hist["Volume"] = 390_000.0     # 1,000 a minute over a full day
    m = turbo.momentum(intraday, hist, atr=2.0, prev_close=100.0)
    assert m["price"] == 104.0 and m["day_change"] == pytest.approx(0.04)
    assert 101.9 < m["vwap"] < 102.1 and m["vs_vwap"] > 0
    assert m["rel_volume"] == pytest.approx(1.0, rel=0.02)


def test_reconcile_trailing_stop_on_a_bullish_stock_means_trim_not_exit():
    plan = _plan(UPTREND_DIP, "RISK - REVIEW", watchlist=False)
    plan = {**plan, "bias": "bullish"}
    assert plan["stance"] == "REDUCE / EXIT"
    stop_hit = [Signal("risk", "technical", "atr_trailing_stop", "Below ATR trailing stop 109", 3)]
    r = tradeplan.reconcile(plan, stop_hit)
    assert r["stance"] == "TRIM / PROTECT" and r["bias"] == "mixed"
    assert r["exits"][0].startswith("Trim a third to a half") and "Short term and long term disagree" in r["outlook"]
    assert tradeplan.summary(r).startswith("trim / protect")
    thesis = [Signal("risk", "combined", "thesis_breakdown", "Weak fundamentals confirmed by breakdown", 3)]
    r2 = tradeplan.reconcile(plan, stop_hit + thesis)
    assert r2["stance"] == "REDUCE / EXIT" and r2["bias"] == "mixed" and "risk-control exit" in r2["outlook"]
    assert tradeplan.reconcile({**plan, "bias": "bearish"}, stop_hit)["stance"] == "REDUCE / EXIT"


# ---- Finnhub fallback

from stockwatch import finnhub

FH = {
    "/stock/metric": {"metric": {"peTTM": 22.5, "psTTM": 4.1, "revenueGrowthTTMYoy": 12.0, "epsGrowthTTMYoy": -5.0,
                                 "grossMarginTTM": 55.0, "operatingMarginTTM": 20.0, "netProfitMarginTTM": 15.0,
                                 "roeTTM": 18.0, "currentRatioQuarterly": 1.6, "totalDebt/totalEquityQuarterly": 0.7,
                                 "marketCapitalization": 25000.0}},
    "/stock/profile2": {"name": "Example Inc", "finnhubIndustry": "Semiconductors", "country": "US"},
    "/stock/recommendation": [{"period": "2026-09-01", "strongBuy": 2, "buy": 5, "hold": 6, "sell": 1, "strongSell": 0},
                              {"period": "2026-10-01", "strongBuy": 4, "buy": 8, "hold": 4, "sell": 0, "strongSell": 0}],
    "/stock/price-target": {"targetLow": 80, "targetMean": 120, "targetMedian": 118, "targetHigh": 160},
    "/stock/earnings": [{"period": "2026-06-30", "actual": 1.1, "estimate": 1.0, "surprisePercent": 10.0},
                        {"period": "2026-09-30", "actual": 1.3, "estimate": 1.2, "surprisePercent": 8.3}],
    "/calendar/earnings": {"earningsCalendar": [{"date": (date.today() + timedelta(days=9)).isoformat()}]},
    "/stock/insider-transactions": {"data": [
        {"name": "CEO", "change": 5000, "transactionPrice": 100.0, "transactionCode": "P", "transactionDate": "2026-10-01"},
        {"name": "CFO", "change": -2000, "transactionPrice": 110.0, "transactionCode": "S", "transactionDate": "2026-09-20"}]},
    "/company-news": [{"headline": "Example wins contract", "source": "Reuters", "url": "u", "datetime": 1761040000}],
}


def test_finnhub_maps_to_app_formats(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "x")
    monkeypatch.setattr(finnhub, "_get", lambda path, **kw: FH[path])
    f = finnhub.fundamentals("EXM")
    assert f["market_cap"] == 25e9 and f["revenue_growth"] == pytest.approx(0.12) and f["operating_margin"] == 0.2
    assert f["debt_to_equity"] == 0.7 and f["source"] == "Finnhub" and f["name"] == "Example Inc"
    s = finnhub.street("EXM")
    assert s["recs"][0]["period"] == "2026-10-01" and s["targets"]["median"] == 118.0   # newest first
    assert street.consensus(s["recs"])["label"] in ("Buy", "Strong Buy")
    e = finnhub.earnings("EXM")
    assert e[0]["quarter"] == date(2026, 9, 30) and e[0]["surprise_pct"] == pytest.approx(0.083)
    assert finnhub.next_earnings("EXM") == date.today() + timedelta(days=9)
    ins = finnhub.insiders("EXM")
    assert ins[0]["text"] == "Purchase" and ins[0]["value"] == 500_000 and ins[1]["text"] == "Sale"
    assert deepdive.smart_money({}, {"insiders": ins})[0]["buyers_90d"] <= 1
    assert finnhub.news("EXM")[0]["title"] == "Example wins contract"


def test_finnhub_paces_requests(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "x")
    calls = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(finnhub.urllib.request, "urlopen", lambda req, timeout: calls.append(time.monotonic()) or Resp(b"{}"))
    monkeypatch.setattr(finnhub, "MIN_INTERVAL", 0.05)
    for _ in range(3):
        finnhub._get("/stock/metric", symbol="X")
    assert calls[2] - calls[0] >= 0.09


def test_yahoo_falls_back_to_finnhub_when_blocked(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "x")
    monkeypatch.setattr(finnhub, "_get", lambda path, **kw: FH[path])
    yp = _fake_yahoo({"shortName": "X"})              # Yahoo returns next to nothing
    f = yp.fundamentals("EXM")
    assert f["source"] == "Finnhub" and f["pe_trailing"] == 22.5
    monkeypatch.delenv("FINNHUB_API_KEY")
    with pytest.raises(RuntimeError):
        yp.fundamentals("EXM")


def test_revision_direction_never_contradicts_its_evidence():
    d = street.revision_direction
    assert d({"eps_30d": 0.125, "up30": 28, "down30": 2}) == "up"
    assert d({"eps_30d": 0.002, "up30": 2, "down30": 4}) == "down"
    assert d({"eps_30d": 0.05, "up30": 1, "down30": 6}) is None          # counts and consensus disagree
    assert d({"eps_30d": 0.048, "up30": 0, "down30": 1}) is None         # the one revision was a cut
    assert d({"eps_30d": -0.52, "up30": 0, "down30": 1}) == "down"
    assert d({"eps_30d": None, "up30": 1, "down30": 0}) is None          # too little evidence
    raw = {"recs": [], "targets": {}, "eps_trend": {"0y": {"current": 0.08, "30d": 0.02}},
           "revisions": {"0y": {"up30": 1.0, "down30": 1.0}}, "options": []}
    m, sig = street.analyze(raw, 10.0, frame(np.linspace(9, 10, 300)), None, {}, {}, None, owned=True)
    assert m["revisions"]["eps_30d"] is None and m["revisions"]["up30"] == 1   # tiny base ignored, counts are ints
    assert not [s for s in sig if s.code.startswith("estimates_")]


def test_product_offerings_are_not_share_sales():
    now = datetime.now(timezone.utc)
    m, sig = catalysts.analyze({"news": [{"title": "Can WDAY's New AI Offerings Drive Growth?", "published": now}]},
                               owned=True, tier=1)
    assert m["news"][0]["tone"] != "negative" and not sig
    m, sig = catalysts.analyze({"news": [{"title": "ONDS announces $50M registered direct offering", "published": now}]},
                               owned=True, tier=1)
    assert m["news"][0]["tone"] == "negative" and sig[0].code == "news_negative" and sig[0].severity == 2


# ---- radar scope


def _rsnap(ticker="X", verdict="HOLD", price=100.0, watch=False, plan=None, signals=None, days=None):
    return {"ticker": ticker, "tier": 1, "verdict": verdict, "price": price, "fundamental_score": 60,
            "technical_score": 55, "composite": 58,
            "payload": {"watchlist": watch, "signals": signals or [], "position": {}, "fundamental": {"available": True},
                        "technical": {}, "quote": {}, "plan": plan or {},
                        "events": {"days_to_earnings": days} if days is not None else {}}}


def test_radar_ring_follows_how_soon_a_stock_needs_you():
    buy = {"stance": "BUY ON PULLBACK", "entry_low": 95.0, "entry_high": 99.0, "stop": 90.0}
    assert ui.ring(_rsnap(verdict="BUY SETUP", price=97, plan=buy)) == (1, "in the entry zone now")
    assert ui.ring(_rsnap(verdict="BUY SETUP", price=101, plan=buy))[0] == 2              # 2% above the zone
    assert ui.ring(_rsnap(verdict="BUY SETUP", price=110, plan=buy))[0] == 3
    # the plan's zone never pulls a stock with a non-buy verdict into "act now": no conflicting answers
    assert ui.ring(_rsnap(verdict="WATCH", price=97, plan=buy))[0] == 3
    urgent = [{"kind": "risk", "severity": 3, "message": "trailing stop hit"}]
    assert ui.ring(_rsnap(verdict="RISK - REVIEW", signals=urgent)) == (1, "trailing stop hit")
    exit_plan = {"stance": "REDUCE / EXIT", "stop": 80.0}
    assert ui.ring(_rsnap(verdict="RISK - REVIEW", plan=exit_plan))[0] == 1
    near_stop = {"stance": "HOLD", "stop": 98.0}
    assert ui.ring(_rsnap(plan=near_stop))[1] == "2.0% above the stop"
    assert ui.ring(_rsnap(plan=near_stop, watch=True))[0] == 3                          # no stop on a watchlist name
    assert ui.ring(_rsnap(days=2)) == (1, "earnings in 2 days")
    assert ui.ring(_rsnap(days=6))[0] == 2
    assert ui.ring(_rsnap(price=float("nan"), plan=buy, verdict="BUY SETUP"))[0] == 3   # unknown price: no claim


def test_radar_draws_every_stock_and_links_to_details():
    plan = {"stance": "BUY NOW", "entry_low": 95.0, "entry_high": 99.0, "stop": 90.0, "rr": 2.0,
            "targets": [{"price": 111.0}, {"price": 120.0}]}
    snaps = [_rsnap("AAA", "BUY SETUP", 97, plan=plan),
             _rsnap("BBB", "RISK - REVIEW", watch=True), _rsnap("CCC")]
    html = ui.radar(snaps, shown={"AAA"})
    assert html.count('class="blip') == 3 and "?view=target&t=BBB" in html
    assert 'class="blip own urgent"' in html                       # owned, act-now buy pulses
    assert html.count(" dim") == 2                                 # filtered out: faded, not removed
    listed = ui.rows(snaps, changed={"CCC": "WATCH"})
    assert listed.index(">AAA<") < listed.index(">CCC<")          # act now first
    assert "ACT NOW</b> in the entry zone now" in listed and "NEW <small>was WATCH" in listed
    assert "▲ BUY NOW</span>" in listed and "OWNED · T1" in listed
    assert "buy now 95.00-99.00 · stop 90.00" in listed


def test_list_call_is_plain_buy_or_sell_and_never_sells_a_watchlist_name():
    assert ui.action(_rsnap(verdict="OPPORTUNITY - ADD", plan={"stance": "ADD"}))[0] == "BUY MORE"
    assert ui.action(_rsnap(verdict="BUY SETUP", watch=True, plan={"stance": "BUY ON PULLBACK"}))[0] == "BUY ON DIP"
    assert ui.action(_rsnap(verdict="RISK - REVIEW", plan={"stance": "REDUCE / EXIT"}))[0] == "SELL"
    assert ui.action(_rsnap(verdict="TRIM / REVIEW", plan={"stance": "TRIM / PROTECT"}))[0] == "SELL SOME"
    assert ui.action(_rsnap(verdict="RISK - REVIEW", watch=True, plan={"stance": "REDUCE / EXIT"}))[0] == "PASS"
    assert ui.action(_rsnap(verdict="WATCH", watch=True))[0] == "WAIT"                 # no plan: from the verdict
    assert ui.action(_rsnap(verdict="HOLD"))[0] == "HOLD"
    err = _rsnap(verdict="ERROR")
    assert ui.action(err)[0] == "NO SIGNAL"


def test_tapping_a_dot_previews_it_without_a_reload():
    snaps = [_rsnap("BRK.B", "HOLD"), _rsnap("AAA", "BUY SETUP", watch=True)]
    html = ui.radar(snaps)
    assert '<label class="blip own far" for="pv-BRK_B"' in html            # the dot toggles a hidden radio
    assert 'id="pv-BRK_B"' in html and 'id="pvc-BRK_B"' in html            # tickers become safe ids
    assert "#pv-BRK_B:checked~.mc-pvs #pvc-BRK_B{display:block}" in html    # CSS shows the matching preview
    assert "checked>" not in html and 'checked="' not in html              # React would lock a pre-checked radio
    assert html.count('class="mc-pv"') == 2 and "Open full details" in html and 'for="pv-none"' in html


def test_peek_history_never_waits_and_keeps_the_last_good_copy():
    calls = []

    class Inner:
        def history(self, ticker, period="5y"):
            calls.append(ticker)
            if len(calls) > 1:
                raise RuntimeError("401 Invalid Crumb")
            return pd.DataFrame({"Close": [1.0, 2.0]})

    cp = CachedProvider(Inner())
    assert cp.peek_history("SPY") is None and calls == []          # nothing fetched yet: no claim, no fetch
    cp.history("SPY")
    cp._cache.clear()                                               # TTL ran out
    with pytest.raises(RuntimeError):
        cp.history("SPY")                                           # Yahoo now refuses
    assert list(cp.peek_history("SPY")["Close"]) == [1.0, 2.0]      # the page still has the last good copy


def _sell(price=1.00, live=None, live_change=None, trail=None, tripped=False, stance="REDUCE / EXIT", watch=False):
    sigs = [{"kind": "risk", "severity": 3, "code": "atr_trailing_stop", "message": "Below ATR trailing stop"}] if tripped else \
           [{"kind": "risk", "severity": 3, "code": "cash_burn", "message": "Burning cash"}]
    s = _rsnap("SPAI", "RISK - REVIEW", price, watch=watch, signals=sigs,
               plan={"stance": stance, "stop": 0.80, "targets": [{"price": 1.2}, {"price": 1.4}]})
    s["payload"]["technical"] = {"trailing_stop": trail, "day_change": 0.0}
    if live is not None:
        s["payload"]["quote"] = {"market_state": "REGULAR", "live_price": live, "live_change": live_change}
    return s


def test_a_sell_into_a_bounce_waits_for_the_close():
    calm = _sell(live=0.99, live_change=-0.01, trail=1.05, tripped=True)
    assert ui.action(calm)[0] == "SELL" and ui.reassess(calm) is None
    bounce = _sell(live=1.03, live_change=0.05, trail=1.05, tripped=True)         # SPAI +5%, still under the stop
    assert ui.action(bounce)[0] == "REASSESS"
    assert "Up 5.0% today" in ui.reassess(bounce) and "closes below the trailing stop (1.05)" in ui.reassess(bounce)
    retaken = _sell(live=1.07, live_change=0.02, trail=1.05, tripped=True)        # back above the stop that fired
    assert ui.reassess(retaken).startswith("Back above its trailing stop (1.05) at 1.07")
    thesis = _sell(live=1.06, live_change=0.06)                                    # sell for business reasons
    assert ui.action(thesis)[0] == "REASSESS" and "before acting" in ui.reassess(thesis)
    assert ui.reassess(_sell(live=1.06, live_change=0.06, stance="TRIM")) is not None   # SELL SOME too
    assert ui.reassess(_sell(live=1.06, live_change=0.06, watch=True)) is None    # PASS on a watchlist name: nothing to sell
    assert ui.reassess(_sell(live=float("nan"), live_change=0.06)) is None        # no price: no claim
    closed = _sell(price=1.04, trail=1.05, tripped=True)
    closed["payload"]["technical"]["day_change"] = 0.04
    assert "in the last session" in ui.reassess(closed) and "next close" in ui.reassess(closed)
    row = ui.row(bounce)
    assert "↻ REASSESS" in row and "DON'T RUSH" in row and "IF IT FAILS" in row
    assert "Reassess before selling" in ui.reassess_note(bounce) and ui.reassess_note(calm) == ""


def test_first_sweep_shows_each_stock_as_it_lands_without_doubling_snapshots(monkeypatch, tmp_path):
    from stockwatch.scanner import run_once
    monkeypatch.setenv("STOCKWATCH_PORTFOLIO", "holdings:\n  - {ticker: AAA, tier: 1, shares: 5}\n  - {ticker: BBB, tier: 2, shares: 0}\n")
    monkeypatch.delenv("STOCKWATCH_SHEET_URL", raising=False)
    pf, store = load_portfolio(), Store(tmp_path / "s.db")
    seen_mid_sweep = []
    real_save = store.save_snapshot

    def spy(e):
        real_save(e)
        seen_mid_sweep.append(len(store.latest_snapshots()))
    monkeypatch.setattr(store, "save_snapshot", spy)
    run_once(pf, get_provider("demo"), store)
    assert seen_mid_sweep[:2] == [1, 2]                       # on screen one by one, before the sweep ends
    assert all(len(store.history(t)) == 1 for t in ("AAA", "BBB"))     # the final save replaced the early copy
    assert store.snapshot("AAA")["payload"]["position"].get("weight_pct") == 100   # portfolio checks kept
    run_once(pf, get_provider("demo"), store)
    assert all(len(store.history(t)) == 2 for t in ("AAA", "BBB"))     # later sweeps: one snapshot each
    assert store.previous_snapshot("AAA") is not None


# ---- SEC data audit (read-only; Phase 1 of the valuation work)

from stockwatch import sec_audit


def _fy(year, val, form="10-K", filed=None, start=None):
    return {"start": start or f"{year}-01-01", "end": f"{year}-12-31", "val": val, "form": form,
            "filed": filed or f"{year + 1}-02-15"}


def _inst(day, val, form="10-K", filed="2026-02-15"):
    return {"end": day, "val": val, "form": form, "filed": filed}


AUDIT_COMPANY = {"entityName": "Audit Example Corp", "cik": 999, "facts": {
    "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        # two classes reported for the same date; the app keeps one of them
        _inst("2026-07-20", 300e6, "10-Q", "2026-07-30"), _inst("2026-07-20", 600e6, "10-Q", "2026-07-30")]}}},
    "us-gaap": {
        # revenue tag switch: SalesRevenueNet until FY2021, the newer tag from FY2022 (plus 10-Q YTD for TTM)
        "SalesRevenueNet": {"units": {"USD": [_fy(2020, 700e6), _fy(2021, 800e6)]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _fy(2022, 900e6), _fy(2023, 1000e6), _fy(2024, 1100e6), _fy(2025, 1200e6),
            {"start": "2025-01-01", "end": "2025-06-30", "val": 560e6, "form": "10-Q", "filed": "2025-07-30"},
            {"start": "2026-01-01", "end": "2026-06-30", "val": 640e6, "form": "10-Q", "filed": "2026-07-30"}]}},
        # FY2023 operating cash flow first filed at 100, re-filed at 110 a year later; FY2024 amended (10-K/A)
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
            _fy(2023, 100e6), _fy(2023, 110e6, filed="2025-02-15"), _fy(2024, 120e6),
            _fy(2024, 120e6, form="10-K/A", filed="2025-05-01")]}},
        # a 10:1 split: FY2024 shares re-filed x10 and EPS /10 in the FY2025 10-K (confirmed)
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
            _fy(2024, 100e6), _fy(2024, 1000e6, filed="2026-02-15"), _fy(2025, 1000e6),
            {"start": "2026-01-01", "end": "2026-06-30", "val": 1000e6, "form": "10-Q", "filed": "2026-07-30"}]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": [
            _fy(2024, 5.0), _fy(2024, 0.5, filed="2026-02-15"), _fy(2025, 0.6)]}},
        "WeightedAverageNumberOfSharesOutstandingBasic": {"units": {"shares": [
            {"start": "2026-01-01", "end": "2026-06-30", "val": 950e6, "form": "10-Q", "filed": "2026-07-30"}]}},
        # only reported in euros
        "ShareBasedCompensation": {"units": {"EUR": [_fy(2025, 50e6)]}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
            _inst("2024-12-31", 300e6, filed="2025-02-15"), _inst("2025-12-31", 350e6),
            _inst("2026-06-30", 400e6, "10-Q", "2026-07-30")]}},
        "PropertyPlantAndEquipmentNet": {"units": {"USD": [_inst("2025-12-31", 2e9)]}},
    }}}
AUDIT_SUBMISSIONS = {"name": "Audit Example Corp", "sic": "6021", "sicDescription": "National Commercial Banks",
                     "fiscalYearEnd": "1231", "tickers": ["AEX", "AEX.B"]}


def test_sec_audit_finds_history_restatements_splits_and_units():
    r = sec_audit.audit_company("aex", AUDIT_COMPANY, AUDIT_SUBMISSIONS, today=date(2026, 10, 22))
    f = r["fields"]
    rev = f["revenue"]
    assert rev["years"] == 6 and rev["status"] == "covered" and rev["used_by_app"]
    assert "reporting tag changed" in rev["issues"][0] and "SalesRevenueNet (2020-2021)" in rev["issues"][0]
    assert rev["ttm"] == {"value": pytest.approx(1280e6), "end": "2026-06-30"}     # 640 + 1200 - 560
    ocf = f["operating_cash_flow"]
    fy23 = next(y for y in ocf["annual"] if y["end"] == "2023-12-31")
    assert fy23["restated"] and fy23["first"] == 100e6 and fy23["latest"] == 110e6
    assert any("restated" in i and "2023" in i for i in ocf["issues"])
    assert any("amended" in i and "2024" in i for i in ocf["issues"])
    shares = f["diluted_shares"]
    fy24 = next(y for y in shares["annual"] if y["end"] == "2024-12-31")
    assert fy24["split"] == "10:1" and not fy24["restated"]             # shares x10 and EPS /10: a real split
    assert any("confirmed by shares and EPS" in i for i in shares["issues"] + f["eps_diluted"]["issues"])
    assert shares["ttm"] is None                                        # share counts are not summed
    assert f["sbc"]["status"] == "other units only" and "EUR" in f["sbc"]["issues"][0]
    assert f["dna"]["status"] == "missing" and not f["dna"]["used_by_app"]
    assert f["cash"]["years"] == 2 and f["cash"]["latest"]["end"] == "2026-06-30"
    assert f["ppe_net"]["latest"]["value"] == 2e9 and f["ppe_gross"]["status"] == "missing"   # observed only
    findings = " ".join(r["findings"])
    assert "2 different cover-page share counts" in findings            # two classes, app keeps one
    # compared with basic weighted shares, with the date gap stated, and no claim the market cap is wrong
    assert "-68% away from basic weighted-average shares" in findings and "20 days apart" in findings
    assert "would be off" not in findings
    assert "financial company (SIC 6021)" in findings
    assert "Stock-based compensation" in findings and "Depreciation" in findings
    assert r["app_extraction"]["shares"] in (300e6, 600e6)


def test_sec_audit_does_not_call_an_unconfirmed_multiple_a_split():
    company = {"facts": {"us-gaap": {
        # EPS re-filed at 2x with no matching move in shares: possibly a split, but kept as a restatement
        "EarningsPerShareDiluted": {"units": {"USD/shares": [_fy(2024, 1.0), _fy(2024, 2.0, filed="2026-02-15")]}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [_fy(2024, 100e6)]}},
        # a fiscal-year change: two annual periods ending 3 months apart are not two fiscal years
        "Revenues": {"units": {"USD": [_fy(2024, 900e6), _fy(2025, 1000e6, start="2024-04-01",
                                                              filed="2025-05-15") | {"end": "2025-03-31"}]}}}}}
    r = sec_audit.audit_company("XYZ", company, None, today=date(2026, 10, 22))
    eps = r["fields"]["eps_diluted"]["annual"][0]
    assert eps["rescale"] == pytest.approx(2.0) and eps["split"] is None and eps["restated"]
    assert any("possibly a split but not confirmed" in i for i in r["fields"]["eps_diluted"]["issues"])
    rev = r["fields"]["revenue"]
    assert rev["years"] == 1 and any("overlapping" in i for i in rev["issues"])


def test_sec_audit_keeps_the_direction_of_a_reverse_split():
    company = {"facts": {"us-gaap": {
        # 1-for-10 reverse split: shares re-filed down /10, EPS up x10
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
            _fy(2024, 1000e6), _fy(2024, 100e6, filed="2026-02-15")]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": [_fy(2024, 0.5), _fy(2024, 5.0, filed="2026-02-15")]}}}}}
    f = sec_audit.audit_company("REV", company, None, today=date(2026, 10, 22))["fields"]
    row = f["diluted_shares"]["annual"][0]
    assert row["split"] == "1-for-10 reverse" and not row["restated"]
    assert any("1-for-10 reverse (FY 2024)" in i for i in f["diluted_shares"]["issues"])
    assert not any("10:1" in i for i in f["diluted_shares"]["issues"] + f["eps_diluted"]["issues"])


def test_sec_audit_report_status_and_unavailable_tickers(monkeypatch):
    def get(url):
        if "companyfacts" in url:
            return AUDIT_COMPANY
        raise OSError("submissions down")
    ok = sec_audit.audit_ticker("AEX", today=date(2026, 10, 22), get=get, lookup=lambda t: (999, None))
    assert ok["status"] == "ok" and ok["sic"] is None                   # submissions missing: unknown, not invented
    gone = sec_audit.audit_ticker("ZZZZ", get=get, lookup=lambda t: (None, "not in SEC's ticker list"))
    assert gone == {"ticker": "ZZZZ", "status": "unavailable", "reason": "not in SEC's ticker list"}
    listless = sec_audit.audit_ticker("RIVN", get=get, lookup=lambda t: (None, "SEC ticker list unavailable (403)"))
    assert listless["reason"] == "SEC ticker list unavailable (403)"   # the real reason, not "no CIK"
    down = sec_audit.audit_ticker("AEX", get=lambda url: (_ for _ in ()).throw(OSError("403")), lookup=lambda t: (1, None))
    assert down["status"] == "unavailable" and "403" in down["reason"]
    assert sec_audit.summary([ok])["status"] == "COMPLETE"
    assert sec_audit.summary([ok, gone]) | {} == {"status": "PARTIAL", "total": 2, "available": 1, "unavailable": 1,
                                                  "exit_code": 1}
    assert sec_audit.summary([gone, down])["status"] == "NO DATA"
    md = sec_audit.markdown([ok, gone], today=date(2026, 10, 22))
    assert "**Status: PARTIAL**: 1 of 2 companies retrieved" in md and "ZZZZ (not in SEC's ticker list)" in md
    assert "| Revenue | yes | ✓ 6y ⚠ |" in md and "Unavailable: not in SEC's ticker list" in md and "coverage only" in md
    import re
    assert not re.search(r"\bnan\b", md.lower())                       # no missing number shown as nan
    # the command's exit code tells the workflow whether any data was retrieved
    for results, code in (([ok], 0), ([ok, gone], 1), ([down], 2)):
        it = iter(results)
        monkeypatch.setattr(sec_audit, "audit_ticker", lambda t: next(it))
        assert sec_audit.main(["T"] * len(results) + ["--markdown", "/dev/null"]) == code


def test_sec_audit_and_quality_are_not_wired_into_the_app():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in [root / "dashboard.py", *sorted((root / "stockwatch").glob("*.py"))]:
        if path.name not in ("sec_audit.py", "sec_quality.py", "valuation_lab.py"):
            text = path.read_text()
            assert "sec_audit" not in text and "sec_quality" not in text and "valuation_lab" not in text, path.name


# ---- SEC data quality (read-only; Phase 1B of the valuation work)

from stockwatch import sec_quality as sq

QDAY = date(2026, 10, 22)


def _q(val, start, end, form="10-K", filed="2026-02-15", accn="0000000001-26-000005"):
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed, "accn": accn}


def _qi(val, end, form="10-Q", filed="2026-07-30", accn="0000000001-26-000020"):
    return {"end": end, "val": val, "form": form, "filed": filed, "accn": accn}


FY24, FY25 = ("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31")
QUALITY_COMPANY = {"entityName": "Quality Example Corp", "cik": 1, "facts": {
    "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        # two share classes on the cover page
        _qi(300e6, "2026-07-20", filed="2026-07-30"), _qi(600e6, "2026-07-20", filed="2026-07-30")]}}},
    "us-gaap": {
        # FY2025 first filed at 1.20B, then amended to 1.26B; year-to-date figures for TTM
        "Revenues": {"units": {"USD": [
            _q(1000e6, *FY24, filed="2025-02-15", accn="0000000001-25-000004"), _q(1200e6, *FY25),
            _q(1260e6, *FY25, form="10-K/A", filed="2026-05-01", accn="0000000001-26-000011"),
            _q(600e6, "2025-01-01", "2025-06-30", "10-Q", "2025-07-30", "0000000001-25-000020"),
            _q(700e6, "2026-01-01", "2026-06-30", "10-Q", "2026-07-30", "0000000001-26-000020")]}},
        # another tag disagrees for FY2025
        "NetIncomeLoss": {"units": {"USD": [_q(100e6, *FY25)]}},
        "ProfitLoss": {"units": {"USD": [_q(120e6, *FY25)]}},
        # one filing, two values for the same period
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [_q(150e6, *FY25), _q(160e6, *FY25)]}},
        # last reported for 2012: stale next to FY2025
        "OperatingIncomeLoss": {"units": {"USD": [_q(80e6, "2012-01-01", "2012-12-31", filed="2013-02-15",
                                                     accn="0000000001-13-000002")]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [_q(50e6, *FY25)]}},
        # a tag for the same measure with a different amount: a real conflict
        "PurchaseOfPropertyPlantAndEquipment": {"units": {"USD": [_q(55e6, *FY25)]}},
        "ProceedsFromSaleOfPropertyPlantAndEquipment": {"units": {"USD": [_q(2e6, *FY25)]}},
        # only a quarter, never a fiscal year
        "InterestExpense": {"units": {"USD": [_q(5e6, "2026-04-01", "2026-06-30", "10-Q", "2026-07-30",
                                                 "0000000001-26-000020")]}},
        "ShareBasedCompensation": {"units": {"EUR": [_q(9e6, *FY25)]}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [_qi(300e6, "2025-12-31", "10-K", "2026-02-15",
                                                                         "0000000001-26-000005"),
                                                                    _qi(400e6, "2026-06-30")]}},
        "StockholdersEquity": {"units": {"USD": [_qi(900e6, "2026-06-30")]}},
        "ShortTermInvestments": {"units": {"USD": [_qi(40e6, "2026-06-30")]}},
        "MarketableSecuritiesCurrent": {"units": {"USD": [_qi(45e6, "2026-06-30")]}},
        "LongTermDebtCurrent": {"units": {"USD": [_qi(10e6, "2023-12-31", "10-K", "2024-02-15",
                                                       "0000000001-24-000003")]}},
        "LongTermDebt": {"units": {"USD": [_qi(500e6, "2026-06-30")]}},
        "LongTermDebtNoncurrent": {"units": {"USD": [_qi(450e6, "2013-12-31", "10-K", "2014-02-15",
                                                          "0000000001-14-000002")]}},
        "OperatingLeaseLiabilityNoncurrent": {"units": {"USD": [_qi(70e6, "2026-06-30")]}},
        "OperatingLeaseLiabilityCurrent": {"units": {"USD": [_qi(8e6, "2026-06-30")]}},
        "WeightedAverageNumberOfSharesOutstandingBasic": {"units": {"shares": [
            _q(880e6, *FY25), _q(890e6, "2026-01-01", "2026-06-30", "10-Q", "2026-07-30", "0000000001-26-000020"),
            _q(895e6, "2026-04-01", "2026-06-30", "10-Q", "2026-07-30", "0000000001-26-000020")]}},
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber": {"units": {
            "shares": [_qi(12e6, "2025-12-31", "10-K", "2026-02-15", "0000000001-26-000005")]}},
        # last disclosed in 2019: not current
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber": {
            "units": {"shares": [_qi(3e6, "2019-12-31", "10-K", "2020-02-15", "0000000001-20-000002")]}},
    }}}


def test_sec_quality_selects_with_provenance_and_no_look_ahead():
    ref = sq.reference(QUALITY_COMPANY, QDAY)
    assert ref == {"end": "2026-06-30", "fy_end": "2025-12-31", "age": 114}
    rev = sq.select(QUALITY_COMPANY, "revenue", QDAY, ref)
    assert rev["selected"] == {"concept": "Revenues", "value": 1260e6, "start": "2025-01-01", "end": "2025-12-31",
                               "form": "10-K/A", "filed": "2026-05-01", "accn": "0000000001-26-000011"}
    assert rev["first"]["accn"] == "0000000001-26-000005" and rev["first"]["value"] == 1200e6
    assert rev["status"] == sq.RECONCILE
    assert any(i.startswith("revised: first filed as 1.2B on 2026-02-15") for i in rev["issues"])
    assert any("amended filing (10-K/A)" in i for i in rev["issues"])
    # as of March 2026 the amendment hadn't been filed: the original figure, nothing revised
    march = date(2026, 3, 1)
    early = sq.select(QUALITY_COMPANY, "revenue", march, sq.reference(QUALITY_COMPANY, march))
    assert early["selected"]["value"] == 1200e6 and early["status"] == sq.USABLE and not early["issues"]
    # before the FY2025 10-K was filed, FY2024 is the latest fiscal year
    jan = date(2026, 1, 31)
    assert sq.select(QUALITY_COMPANY, "revenue", jan, sq.reference(QUALITY_COMPANY, jan))["selected"]["end"] == "2024-12-31"


def test_sec_quality_flags_conflicts_duplicates_stale_and_unknown():
    r = sq.quality_company("qex", QUALITY_COMPANY, None, QDAY)
    f = r["fields"]
    ni = f["net_income"]                        # ProfitLoss includes noncontrolling interests: scope, not conflict
    assert ni["status"] == sq.USABLE and ni["selected"]["concept"] == "NetIncomeLoss"
    assert ni["issues"] == ["other tags with a different scope: ProfitLoss 120.0M (+20.0%; includes noncontrolling "
                            "interests)"]
    capex = f["capex"]
    assert capex["status"] == sq.RECONCILE and capex["issues"] == [
        "other tags disagree for the same period: PurchaseOfPropertyPlantAndEquipment 55.0M (+10.0%) vs "
        "PaymentsToAcquirePropertyPlantAndEquipment 50.0M"]
    ocf = f["operating_cash_flow"]
    assert ocf["status"] == sq.RECONCILE and "the same filing reports different values" in ocf["issues"][0]
    assert ocf["selected"]["value"] is None and not any("revised" in i for i in ocf["issues"])   # not a revision
    ebit = f["operating_income"]
    assert ebit["status"] == sq.STALE and "already reported the year ending 2025-12-31" in ebit["issues"][0]
    debt = f["debt_long"]                       # the newest tag wins over a noncurrent figure from 2013
    assert debt["selected"]["concept"] == "LongTermDebt" and debt["status"] == sq.RECONCILE
    assert debt["issues"] == ["selected tag LongTermDebt (total including the current portion): check it's the "
                              "definition wanted"]
    assert "OperatingLeaseLiabilityNoncurrent (noncurrent portion only)" in f["operating_leases"]["issues"][0]
    cur = f["debt_current"]
    assert cur["status"] == sq.STALE and "2023-12-31" in cur["issues"][0]
    assert f["sbc"]["status"] == sq.UNKNOWN and "only in EUR" in f["sbc"]["issues"][0]
    assert f["interest_expense"]["status"] == sq.UNKNOWN and "only shorter periods" in f["interest_expense"]["issues"][0]
    assert f["dna"]["status"] == sq.UNKNOWN and f["dna"]["selected"] is None      # missing is unknown, never 0
    assert f["cash"]["status"] == sq.USABLE and f["cash"]["selected"]["end"] == "2026-06-30"
    cover = f["shares_outstanding"]
    assert cover["status"] == sq.RECONCILE and "several share classes" in cover["issues"][0]
    assert cover["selected"]["value"] is None and len(cover["issues"]) == 1    # no class passed off as the total
    assert sum(r["counts"].values()) == len(sq.FIELDS) and r["sector"]["kind"] is None


def test_sec_quality_ttm_shows_its_parts_and_says_why_when_it_cant():
    ref = sq.reference(QUALITY_COMPANY, QDAY)
    t = sq.ttm(QUALITY_COMPANY, "revenue", QDAY, ref)
    assert t["value"] == pytest.approx(1360e6)                                     # 700 + 1260 - 600
    assert [name for name, _ in t["parts"]] == ["year to date", "+ last fiscal year", "- same period a year earlier"]
    assert t["parts"][1][1]["accn"] == "0000000001-26-000011"                     # the amended fiscal year
    # the amended fiscal year makes the TTM contested, naming both filings
    assert t["status"] == sq.RECONCILE and "2025-01-01 to 2025-12-31 was revised: 1.2B (0000000001-26-000005" in t[
        "reason"] and "1.3B (0000000001-26-000011" in t["reason"]
    # annual-only figure: the fiscal year itself
    assert sq.ttm(QUALITY_COMPANY, "net_income", QDAY, ref)["parts"][0][0] == "fiscal year"
    # two values for the fiscal year in one filing: no TTM number at all
    ocf = sq.ttm(QUALITY_COMPANY, "operating_cash_flow", QDAY, ref)
    assert ocf["status"] == sq.UNKNOWN and ocf["value"] is None and "no number is trusted" in ocf["reason"]
    # the fiscal year's own conflicting tags carry over from select()
    sel = sq.select(QUALITY_COMPANY, "capex", QDAY, ref)
    capex = sq.ttm(QUALITY_COMPANY, "capex", QDAY, ref, sel)
    assert capex["status"] == sq.STALE and "fiscal-year figure: other tags disagree" in capex["reason"]   # stale ranks higher
    assert "other tags disagree" not in sq.ttm(QUALITY_COMPANY, "capex", QDAY, ref)["reason"]   # without it: only the age
    # a quarter with nothing to complete it
    t = sq.ttm(QUALITY_COMPANY, "interest_expense", QDAY, ref)
    assert t["status"] == sq.UNKNOWN and t["value"] is None and "no last fiscal year" in t["reason"]


def test_sec_quality_balance_sheet_is_one_date_and_dilution_is_never_estimated():
    r = sq.quality_company("qex", QUALITY_COMPANY, None, QDAY)
    bs = r["balance_sheet"]
    assert bs["date"] == "2026-06-30"
    rows = {x["key"]: x for x in bs["rows"]}
    assert rows["cash"]["value"] == 400e6 and rows["cash"]["status"] == sq.USABLE
    assert rows["short_term_investments"]["value"] == 40e6 and "MarketableSecuritiesCurrent 45.0M" in rows[
        "short_term_investments"]["notes"][0]
    # an old short-term debt figure isn't carried forward to the balance-sheet date
    assert rows["debt_current"]["status"] == sq.UNKNOWN and rows["debt_current"]["value"] is None
    assert "latest is for 2023-12-31, not used" in rows["debt_current"]["notes"][0]
    assert rows["debt_long"]["status"] == sq.RECONCILE and "including the current portion" in rows["debt_long"]["notes"][0]
    assert rows["operating_leases"]["status"] == sq.RECONCILE
    assert "current portion 8.0M (OperatingLeaseLiabilityCurrent), reported separately" in rows["operating_leases"]["notes"]
    assert rows["finance_leases"]["status"] == sq.UNKNOWN and "never reported" in rows["finance_leases"]["notes"][0]
    sh = r["shares"]
    basic = next(x for x in sh["rows"] if x["key"] == "basic_shares")
    assert basic["source"]["value"] == 895e6 and basic["source"]["start"] == "2026-04-01"   # the latest quarter
    assert next(x for x in sh["rows"] if x["key"] == "diluted_shares")["status"] == sq.UNKNOWN
    cover = next(x for x in sh["rows"] if x["key"] == "cover")
    assert cover["values"] == [300e6, 600e6] and cover["status"] == sq.RECONCILE
    dil = {x["key"]: x for x in sh["dilution"]}
    assert dil["options"]["source"]["value"] == 12e6 and dil["options"]["status"] == sq.USABLE   # latest fiscal year
    assert dil["unvested_awards"]["status"] == sq.STALE and "2192 days before" in dil["unvested_awards"]["notes"][0]
    assert dil["antidilutive"]["status"] == sq.UNKNOWN
    assert sh["fully_diluted"]["status"] == sq.UNKNOWN and "not computed" in sh["fully_diluted"]["reason"]


def test_sec_quality_marks_generic_measures_not_applicable_for_banks_and_insurers():
    bank = sq.quality_company("BNK", QUALITY_COMPANY, {"sic": "6021", "sicDescription": "National Commercial Banks",
                                                       "tickers": ["BNK"]}, QDAY)
    f = bank["fields"]
    for key in ("operating_income", "operating_cash_flow", "capex", "debt_current", "debt_long"):
        assert f[key]["status"] == sq.NOT_APPLICABLE and f[key]["issues"][0].startswith("not applicable (bank)")
    # the staleness is still stated, not hidden behind "not applicable"
    assert any("already reported the year ending" in i for i in f["operating_income"]["issues"])
    assert bank["sector"]["kind"] == "bank" and "CET1" in " ".join(bank["sector"]["needs"])
    assert "free cash flow (operating cash flow minus capex)" in bank["sector"]["not_applicable"]
    ins = sq.quality_company("BRK-B", QUALITY_COMPANY, {"sic": "6331", "tickers": ["BRK-A", "BRK-B"]}, QDAY)
    assert ins["sector"]["kind"] == "insurance" and "BRK-A, BRK-B" in ins["sector"]["multi_class_notes"][0]
    assert ins["counts"][sq.NOT_APPLICABLE] == len(sq.GENERIC_NOT_APPLICABLE)
    plain = sq.sector({"sic": "3674", "tickers": ["MU"]}, 1)
    assert plain["kind"] is None and not plain["not_applicable"] and not plain["multi_class_notes"]


INSTANCE = b"""<?xml version="1.0" encoding="utf-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:us-gaap="http://fasb.org/us-gaap/2025"
  xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:dei="http://xbrl.sec.gov/dei/2025"
  xmlns:cur="http://www.xbrl.org/2003/iso4217">
 <xbrli:unit id="usd"><xbrli:measure>cur:USD</xbrli:measure></xbrli:unit>
 <xbrli:unit id="eur"><xbrli:measure>cur:EUR</xbrli:measure></xbrli:unit>
 <xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>cur:USD</xbrli:measure>
  </xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator>
  </xbrli:divide></xbrli:unit>
 <xbrli:context id="FY"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
  </xbrli:entity><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate>
  </xbrli:period></xbrli:context>
 <xbrli:context id="FY_seg"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
  <xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">x:CloudMember</xbrldi:explicitMember>
  </xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate>
  <xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
 <us-gaap:Revenues contextRef="FY" unitRef="usd" decimals="-6">1200000000</us-gaap:Revenues>
 <us-gaap:NetIncomeLoss contextRef="FY" unitRef="usd" decimals="-6">99000000</us-gaap:NetIncomeLoss>
 <us-gaap:NetCashProvidedByUsedInOperatingActivities contextRef="FY_seg" unitRef="usd" decimals="-6">150000000</us-gaap:NetCashProvidedByUsedInOperatingActivities>
 <us-gaap:PaymentsToAcquirePropertyPlantAndEquipment contextRef="FY" unitRef="usd" decimals="-6">50000000</us-gaap:PaymentsToAcquirePropertyPlantAndEquipment>
 <dei:DocumentType contextRef="FY">10-K</dei:DocumentType>
</xbrli:xbrl>"""


def test_sec_quality_checks_figures_against_the_filing_itself():
    import json
    folder = "https://www.sec.gov/Archives/edgar/data/1/000000000126000005"
    asked = []

    def get_bytes(url):
        asked.append(url)
        if url == f"{folder}/index.json":
            return json.dumps({"directory": {"item": [{"name": "FilingSummary.xml"}, {"name": "x-20251231_cal.xml"},
                                                      {"name": "x-20251231_htm.xml"}]}}).encode()
        if url == f"{folder}/x-20251231_htm.xml":
            return INSTANCE
        raise OSError("404")
    r = sq.quality_company("QEX", QUALITY_COMPANY, None, QDAY, reconcile_cik=1, get_bytes=get_bytes)
    rows = {x["key"]: x for x in r["reconciliation"]["rows"]}
    # revenue's selected figure comes from the amendment, whose folder isn't there: said, not guessed
    assert rows["revenue"]["result"] == "unverified" and "filing not read: OSError: 404" in rows["revenue"]["reason"]
    assert rows["net_income"]["result"] == "differs" and rows["net_income"]["filing_values"] == [99e6]
    # SEC's data has two values for the period: nothing to check against
    assert rows["operating_cash_flow"]["result"] == "unverified" and "several values" in rows["operating_cash_flow"]["reason"]
    # a segment figure isn't a company-wide one
    parsed = sq.parse_instance(INSTANCE)
    assert ("NetCashProvidedByUsedInOperatingActivities", "2025-01-01", "2025-12-31") not in parsed
    assert parsed[("Revenues", "2025-01-01", "2025-12-31")] == [(1200e6, "{http://www.xbrl.org/2003/iso4217}USD")]
    assert not any(k[0] == "DocumentType" for k in parsed)
    assert rows["capex"]["result"] == "matches" and rows["capex"]["filing"] == f"{folder}/0000000001-26-000005-index.htm"
    assert asked.count(f"{folder}/index.json") == 1                       # one download per filing
    ctx = {c["concept"]: c["value"] for c in r["reconciliation"]["capex_context"]}
    assert ctx["ProceedsFromSaleOfPropertyPlantAndEquipment"] == 2e6 and ctx["FinanceLeasePrincipalPayments"] is None
    assert sq.pick_instance(["a.xsd", "a_lab.xml", "a.xml"]) == "a.xml" and sq.pick_instance(["a.htm"]) is None


def test_sec_quality_report_and_command(monkeypatch):
    def get(url):
        if "companyfacts" in url:
            return QUALITY_COMPANY
        raise OSError("submissions down")
    ok = sq.quality_ticker("QEX", QDAY, get=get, lookup=lambda t: (1, None))
    assert ok["status"] == "ok" and ok["sector"]["sic"] is None and ok["reconciliation"] is None
    gone = sq.quality_ticker("ZZZZ", get=get, lookup=lambda t: (None, "not in SEC's ticker list"))
    assert gone == {"ticker": "ZZZZ", "status": "unavailable", "reason": "not in SEC's ticker list"}
    md = sq.markdown([ok, gone], QDAY, ua_status="configured")
    assert "**Status: PARTIAL**: 1 of 2 companies retrieved" in md and "Unavailable: not in SEC's ticker list" in md
    assert "| QEX | 2026-06-30 |" in md and "not requested" in md
    assert "| Revenue | needs reconciliation | 1.3B | 2025-01-01 to 2025-12-31 (364 days) | Revenues · 10-K/A" in md
    assert "### Balance sheet on 2026-06-30" in md and "| Fully diluted shares | unknown |" in md
    import re
    assert not re.search(r"\bnan\b", md.lower()) and "fair value" not in md.lower() and "buy-under" not in md.lower()
    for results, code in (([ok], 0), ([ok, gone], 1), ([gone], 2)):
        it = iter(results)
        monkeypatch.setattr(sq, "quality_ticker", lambda t, as_of, check: next(it))
        assert sq.main(["T"] * len(results) + ["--markdown", "/dev/null"]) == code


def test_sec_quality_checks_debt_adds_up_and_flags_stale_balance_sheet_figures():
    def bs(total, nc, cur):
        company = {"facts": {"us-gaap": {
            "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [_qi(10e6, "2026-06-30")]}},
            "LongTermDebt": {"units": {"USD": [_qi(total, "2026-06-30")]}},
            "LongTermDebtNoncurrent": {"units": {"USD": [_qi(nc, "2026-06-30")]}},
            "LongTermDebtCurrent": {"units": {"USD": [_qi(cur, "2026-06-30")]}},
            # one quarter old: stale next to the latest balance sheet, and not carried forward
            "OperatingLeaseLiability": {"units": {"USD": [_qi(7e6, "2026-03-31", filed="2026-04-30")]}}}}}
        r = sq.quality_company("D", company, None, QDAY)
        return {x["key"]: x for x in r["balance_sheet"]["rows"]}, r["fields"]
    rows, fields = bs(500e6, 450e6, 50e6)
    assert rows["debt_long"]["status"] == sq.USABLE and rows["debt_long"]["concept"] == "LongTermDebtNoncurrent"
    assert "adds up: LongTermDebt 500.0M = noncurrent 450.0M + current 50.0M" in rows["debt_long"]["notes"]
    assert fields["debt_long"]["status"] == sq.USABLE and "different scope: LongTermDebt 500.0M" in fields["debt_long"]["issues"][0]
    assert rows["operating_leases"]["status"] == sq.UNKNOWN
    assert fields["operating_leases"]["status"] == sq.STALE and "91 days before" in fields["operating_leases"]["issues"][0]
    rows, _ = bs(500e6, 400e6, 50e6)
    assert rows["debt_long"]["status"] == sq.RECONCILE and "doesn't equal noncurrent 400.0M plus current 50.0M" in \
        rows["debt_long"]["notes"][-1]


def test_sec_quality_ttm_with_a_contested_year_to_date():
    def company(ytd_facts):
        return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            _q(1000e6, *FY25), _q(450e6, "2025-01-01", "2025-06-30", "10-Q", "2025-07-30", "0000000001-25-000020"),
            *ytd_facts]}}}}}
    both = company([_q(500e6, "2026-01-01", "2026-06-30", "10-Q", "2026-07-30", "0000000001-26-000020"),
                    _q(520e6, "2026-01-01", "2026-06-30", "10-Q", "2026-07-30", "0000000001-26-000020")])
    t = sq.ttm(both, "revenue", QDAY, sq.reference(both, QDAY))
    assert t["status"] == sq.UNKNOWN and t["value"] is None and "0000000001-26-000020: 500.0M, 520.0M" in t["reason"]
    revised = company([_q(500e6, "2026-01-01", "2026-06-30", "10-Q", "2026-07-30", "0000000001-26-000020"),
                       _q(520e6, "2026-01-01", "2026-06-30", "10-Q/A", "2026-08-30", "0000000001-26-000030")])
    t = sq.ttm(revised, "revenue", QDAY, sq.reference(revised, QDAY))
    assert t["status"] == sq.RECONCILE and t["value"] == pytest.approx(1070e6)     # 520 + 1000 - 450, latest filed
    assert "500.0M (0000000001-26-000020" in t["reason"] and "520.0M (0000000001-26-000030" in t["reason"]
    clean = company([_q(500e6, "2026-01-01", "2026-06-30", "10-Q", "2026-07-30", "0000000001-26-000020")])
    t = sq.ttm(clean, "revenue", QDAY, sq.reference(clean, QDAY))
    assert t["status"] == sq.USABLE and t["value"] == pytest.approx(1050e6) and "reason" not in t


def test_sec_quality_filing_check_only_matches_usd():
    usd = "{http://www.xbrl.org/2003/iso4217}USD"
    parsed = sq.parse_instance(INSTANCE)
    assert parsed[("Revenues", "2025-01-01", "2025-12-31")] == [(1200e6, usd)]
    company = {"cik": 1, "facts": {"us-gaap": {k: {"units": {"USD": [_q(v, *FY25)]}} for k, v in (
        ("Revenues", 1200e6), ("NetIncomeLoss", 70e6), ("NetCashProvidedByUsedInOperatingActivities", 90e6),
        ("PaymentsToAcquirePropertyPlantAndEquipment", 30e6))}}}
    filing = INSTANCE.replace(b"</xbrli:xbrl>", b"""
 <us-gaap:NetIncomeLoss contextRef="FY_eur" unitRef="eur" decimals="-6">70000000</us-gaap:NetIncomeLoss>
 <us-gaap:NetCashProvidedByUsedInOperatingActivities contextRef="FY" unitRef="nowhere">90000000</us-gaap:NetCashProvidedByUsedInOperatingActivities>
 <us-gaap:EarningsPerShareDiluted contextRef="FY" unitRef="usdPerShare" decimals="2">1.5</us-gaap:EarningsPerShareDiluted>
</xbrli:xbrl>""").replace(b'<us-gaap:PaymentsToAcquirePropertyPlantAndEquipment contextRef="FY" unitRef="usd"',
              b'<us-gaap:PaymentsToAcquirePropertyPlantAndEquipment contextRef="FY" unitRef="eur"')
    # NetIncomeLoss: 99M in USD (differs) is in the context FY; the EUR copy needs its own context
    filing = filing.replace(b'<xbrli:context id="FY_seg">', b"""<xbrli:context id="FY_eur"><xbrli:entity>
  <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity><xbrli:period>
  <xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:context id="FY_seg">""")
    parsed = sq.parse_instance(filing)
    assert parsed[("EarningsPerShareDiluted", "2025-01-01", "2025-12-31")] == [
        (1.5, usd + "/{http://www.xbrl.org/2003/instance}shares")]
    assert sorted(parsed[("NetIncomeLoss", "2025-01-01", "2025-12-31")]) == [
        (70e6, "{http://www.xbrl.org/2003/iso4217}EUR"), (99e6, usd)]

    def get_bytes(url):
        if url.endswith("index.json"):
            return b'{"directory": {"item": [{"name": "x-20251231_htm.xml"}]}}'
        return filing
    fields = {k: sq.select(company, k, QDAY, sq.reference(company, QDAY)) for k in sq.FIELDS}
    rows = {r["key"]: r for r in sq.reconcile(1, company, fields, QDAY, get_bytes)["rows"]}
    assert rows["revenue"]["result"] == "matches"
    # the same number in euros doesn't confirm a USD figure; the USD value differs
    assert rows["net_income"]["result"] == "differs" and rows["net_income"]["filing_values"] == [99e6]
    assert rows["operating_cash_flow"]["result"] == "unverified"                   # only a segment and an undeclared unit
    assert "undeclared unit" in rows["operating_cash_flow"]["reason"]
    assert rows["capex"]["result"] == "unverified" and "only in EUR, not USD" in rows["capex"]["reason"]


def test_sec_quality_contested_share_and_balance_sheet_figures_are_not_passed_off():
    def company(cash, basic, debt):
        return {"facts": {"us-gaap": {
            "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": cash}},
            "LongTermDebt": {"units": {"USD": debt}},
            "LongTermDebtNoncurrent": {"units": {"USD": [_qi(450e6, "2026-06-30")]}},
            "LongTermDebtCurrent": {"units": {"USD": [_qi(50e6, "2026-06-30")]}},
            "WeightedAverageNumberOfSharesOutstandingBasic": {"units": {"shares": basic}}}}}
    q2 = ("2026-04-01", "2026-06-30")
    # one 10-Q, two values for the same date or quarter: no number is shown
    one = company([_qi(400e6, "2026-06-30"), _qi(410e6, "2026-06-30")],
                  [_q(900e6, *q2, "10-Q", "2026-07-30", "0000000001-26-000020"),
                   _q(950e6, *q2, "10-Q", "2026-07-30", "0000000001-26-000020")],
                  [_qi(500e6, "2026-06-30"), _qi(520e6, "2026-06-30")])
    r = sq.quality_company("C", one, None, QDAY)
    rows = {x["key"]: x for x in r["balance_sheet"]["rows"]}
    assert rows["cash"]["status"] == sq.UNKNOWN and rows["cash"]["value"] is None
    assert "no number is trusted" in rows["cash"]["notes"][0]
    assert r["fields"]["cash"]["status"] == sq.RECONCILE and r["fields"]["cash"]["selected"]["value"] is None
    # LongTermDebt is contested, so the total-vs-parts check isn't claimed either way
    assert "not checked: LongTermDebt has contested values" in rows["debt_long"]["notes"][-1]
    basic = next(x for x in r["shares"]["rows"] if x["key"] == "basic_shares")
    assert basic["status"] == sq.UNKNOWN and basic["source"]["value"] is None
    assert "0000000001-26-000020: 900,000,000 shares, 950,000,000 shares" in basic["notes"][0]
    # amended in a later filing: shown, but needs reconciliation with both filings named
    revised = company([_qi(400e6, "2026-06-30"), _qi(410e6, "2026-06-30", "10-Q/A", "2026-08-30", "0000000001-26-000030")],
                      [_q(900e6, *q2, "10-Q", "2026-07-30", "0000000001-26-000020"),
                       _q(950e6, *q2, "10-Q/A", "2026-08-30", "0000000001-26-000030")],
                      [_qi(500e6, "2026-06-30")])
    r = sq.quality_company("C", revised, None, QDAY)
    rows = {x["key"]: x for x in r["balance_sheet"]["rows"]}
    assert rows["cash"]["status"] == sq.RECONCILE and rows["cash"]["value"] == 410e6
    assert "400.0M (0000000001-26-000020" in rows["cash"]["notes"][0]
    assert "adds up: LongTermDebt 500.0M" in rows["debt_long"]["notes"][-1]
    basic = next(x for x in r["shares"]["rows"] if x["key"] == "basic_shares")
    assert basic["status"] == sq.RECONCILE and basic["source"]["value"] == 950e6


@pytest.mark.parametrize('sic', ['6021', '6331', '6200'])
def test_sec_quality_sector_applies_to_all_generic_sections(sic):
    r = sq.quality_company('FIN', QUALITY_COMPANY, {'sic': sic}, QDAY)
    for key in sq.GENERIC_NOT_APPLICABLE:
        f = r['fields'][key]
        assert f['status'] == sq.NOT_APPLICABLE
        if 'ttm' in f:
            assert f['ttm']['status'] == sq.NOT_APPLICABLE
            assert f['ttm']['reason'].startswith('not applicable')
            assert f['ttm']['data_status'] in sq.STATUSES
    for row in r['balance_sheet']['rows']:
        if row['key'] in sq.GENERIC_NOT_APPLICABLE:
            assert row['status'] == sq.NOT_APPLICABLE
            assert row['notes'][0].startswith('not applicable')
    # Applicability keeps raw sources and the existing staleness explanation.
    assert r['fields']['capex']['ttm']['parts']
    assert 'latest report' in r['fields']['capex']['ttm']['reason']
    assert next(x for x in r['balance_sheet']['rows'] if x['key'] == 'cash')['status'] == sq.USABLE


def test_sec_quality_balance_sheet_cross_concept_conflict_and_scope():
    import copy
    company = copy.deepcopy(QUALITY_COMPANY)
    def row(key):
        return next(x for x in sq.quality_company('Q', company, None, QDAY)['balance_sheet']['rows'] if x['key'] == key)
    investments = row('short_term_investments')
    assert investments['status'] == sq.RECONCILE
    assert 'other tags disagree' in ' '.join(investments['notes'])
    company['facts']['us-gaap']['MarketableSecuritiesCurrent']['units']['USD'] = [_qi(40e6, '2026-06-30')]
    assert row('short_term_investments')['status'] == sq.USABLE
    company['facts']['us-gaap']['CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents'] = {
        'units': {'USD': [_qi(450e6, '2026-06-30')]}}
    cash = row('cash')
    assert cash['status'] == sq.USABLE
    assert 'different scope' in ' '.join(cash['notes']) and 'restricted cash' in ' '.join(cash['notes'])


def test_sec_quality_capex_context_contested_and_revised():
    import copy
    company = copy.deepcopy(QUALITY_COMPANY)
    concept = 'ProceedsFromSaleOfPropertyPlantAndEquipment'
    facts = [_q(2e6, *FY25), _q(3e6, *FY25)]
    company['facts']['us-gaap'][concept] = {'units': {'USD': facts}}
    def report():
        return sq.quality_company('Q', company, None, QDAY, reconcile_cik=1,
                                  get_bytes=lambda url: (_ for _ in ()).throw(OSError('offline')))
    def context(r):
        return next(x for x in r['reconciliation']['capex_context'] if x['concept'] == concept)
    r = report()
    c = context(r)
    assert c['status'] == sq.UNKNOWN and c['value'] is None and c['source']['value'] is None
    assert 'no number is trusted' in c['notes'][0]
    assert 'unknown (unknown)' in sq.markdown([r], QDAY)
    facts[1] = _q(3e6, *FY25, '10-K/A', '2026-05-01', '0000000001-26-000011')
    r = report()
    c = context(r)
    assert c['status'] == sq.RECONCILE and c['value'] == 3e6
    assert c['source']['accn'] == '0000000001-26-000011'
    assert '0000000001-26-000005' in c['notes'][0] and '0000000001-26-000011' in c['notes'][0]
    assert 'was revised' in sq.markdown([r], QDAY)


def test_sec_quality_quarterly_shares_never_uses_annual_or_ytd():
    def company(facts):
        return {'facts': {'us-gaap': {c: {'units': {'shares': facts}} for c in (
            'WeightedAverageNumberOfSharesOutstandingBasic', 'WeightedAverageNumberOfDilutedSharesOutstanding')}}}
    annual = _q(100e6, *FY25)
    ytd = _q(110e6, '2025-01-01', '2025-09-30', '10-Q', '2025-10-30')
    for row in sq.shares(company([annual, ytd]), QDAY, {'end': '2025-12-31', 'fy_end': '2025-12-31'})['rows'][:2]:
        assert row['status'] == sq.UNKNOWN and row['source'] is None
        assert 'no quarter-length' in row['notes'][0]
    q3 = _q(115e6, '2025-07-01', '2025-09-30', '10-Q', '2025-10-30')
    rows = sq.shares(company([annual, ytd, q3]), QDAY, {'end': '2025-12-31', 'fy_end': '2025-12-31'})['rows'][:2]
    for row in rows:
        assert row['source']['value'] == 115e6 and row['source']['start'] == '2025-07-01'
        assert row['status'] == sq.STALE


def test_sec_quality_balance_scope_requires_established_field_pair(monkeypatch):
    # A description of one tag does not establish a relationship with another tag.
    monkeypatch.setitem(sq.SCOPE, 'MarketableSecuritiesCurrent', 'a separately described scope')
    r = sq.quality_company('Q', QUALITY_COMPANY, None, QDAY)
    row = next(x for x in r['balance_sheet']['rows'] if x['key'] == 'short_term_investments')
    assert row['status'] == sq.RECONCILE
    assert 'other tags disagree: MarketableSecuritiesCurrent 45.0M vs ShortTermInvestments 40.0M' in row['notes']
    assert row['concept'] == 'ShortTermInvestments' and row['accn']
    # An actual unrecognized pair containing LongTermDebt (already in SCOPE) must
    # also be described as a disagreement, rather than a verified scope difference.
    company = {'facts': {'us-gaap': {
        'CashAndCashEquivalentsAtCarryingValue': {'units': {'USD': [_qi(10e6, '2026-06-30')]}},
        'LongTermDebt': {'units': {'USD': [_qi(500e6, '2026-06-30')]}},
        'NoncurrentPortionOfNoncurrentBorrowings': {'units': {'USD': [_qi(400e6, '2026-06-30')]}}}}}
    r = sq.quality_company('Q', company, None, QDAY)
    row = next(x for x in r['balance_sheet']['rows'] if x['key'] == 'debt_long')
    assert row['status'] == sq.RECONCILE
    assert any('other tags disagree: NoncurrentPortionOfNoncurrentBorrowings' in n for n in row['notes'])


def test_sec_quality_selection_and_balance_share_scope_rules(monkeypatch):
    import copy
    monkeypatch.setitem(sq.SCOPE, 'MarketableSecuritiesCurrent', 'individually described scope')
    company = copy.deepcopy(QUALITY_COMPANY)
    company['facts']['us-gaap']['CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents'] = {
        'units': {'USD': [_qi(450e6, '2026-06-30')]}}
    r = sq.quality_company('Q', company, None, QDAY)
    rows = {x['key']: x for x in r['balance_sheet']['rows']}
    for section in (r['fields']['short_term_investments'], rows['short_term_investments']):
        assert section['status'] == sq.RECONCILE
        assert any('other tags disagree' in n for n in section.get('issues', section.get('notes', [])))
    for section in (r['fields']['cash'], rows['cash']):
        assert section['status'] == sq.USABLE
        assert any('different scope' in n for n in section.get('issues', section.get('notes', [])))
    assert r['fields']['cash']['selected']['accn'] == rows['cash']['accn']
    # Other field categories get no implicit equivalence from a global tag description.
    company = {'facts': {'us-gaap': {
        'PaymentsToAcquirePropertyPlantAndEquipment': {'units': {'USD': [_q(10e6, *FY25)]}},
        'PaymentsToAcquireProductiveAssets': {'units': {'USD': [_q(20e6, *FY25)]}}}}}
    r = sq.quality_company('Q', company, None, date(2026, 3, 1))
    assert r['fields']['capex']['status'] == sq.RECONCILE
    assert any('other tags disagree' in n for n in r['fields']['capex']['issues'])
    assert r['fields']['capex']['ttm']['status'] == sq.RECONCILE


# ---- Valuation research (read-only; Phase 2A-1)

from stockwatch import valuation_lab as vl

VDAY = date(2026, 3, 1)


def _vfy(y, v, accn=None, form="10-K"):
    return {"start": f"{y}-01-01", "end": f"{y}-12-31", "val": v, "form": form, "filed": f"{y + 1}-02-15",
            "accn": accn or f"0000000009-{str(y + 1)[2:]}-000001"}


def _vinst(day, v, filed="2026-02-15", form="10-K", accn="0000000009-26-000001"):
    return {"end": day, "val": v, "form": form, "filed": filed, "accn": accn}


def _vcompany(revenue=None, ocf=None, capex=30e6, op_income=None, cover=(100e6,), extra=None):
    """Six fiscal years, 2020-2025. Defaults: a steady cash compounder."""
    yrs = range(2020, 2026)
    revenue = revenue or [(500 + 50 * i) * 1e6 for i in range(6)]
    ocf = ocf or [(120 + 6 * i) * 1e6 for i in range(6)]
    op_income = op_income or [(100 + 10 * i) * 1e6 for i in range(6)]
    gaap = {
        "Revenues": {"units": {"USD": [_vfy(y, v) for y, v in zip(yrs, revenue)]}},
        "OperatingIncomeLoss": {"units": {"USD": [_vfy(y, v) for y, v in zip(yrs, op_income)]}},
        "NetIncomeLoss": {"units": {"USD": [_vfy(y, v * 0.8) for y, v in zip(yrs, op_income)]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [_vfy(y, v) for y, v in zip(yrs, ocf)]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [_vfy(y, capex) for y in yrs]}},
        "ShareBasedCompensation": {"units": {"USD": [_vfy(y, 20e6) for y in yrs]}},
        "DepreciationDepletionAndAmortization": {"units": {"USD": [_vfy(y, 25e6) for y in yrs]}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [_vinst("2025-12-31", 200e6)]}},
        "StockholdersEquity": {"units": {"USD": [_vinst("2025-12-31", 900e6)]}},
        "LongTermDebt": {"units": {"USD": [_vinst("2025-12-31", 300e6)]}},
        "LongTermDebtNoncurrent": {"units": {"USD": [_vinst("2025-12-31", 250e6)]}},
        "LongTermDebtCurrent": {"units": {"USD": [_vinst("2025-12-31", 50e6)]}},
    }
    gaap.update(extra or {})
    return {"entityName": "Valuation Example", "cik": 9, "facts": {
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [_vinst("2026-01-20", v) for v in cover]}}},
        "us-gaap": gaap}}


SOFTWARE = {"sic": "7372", "sicDescription": "Prepackaged Software", "tickers": ["VEX"]}
PRICE = vl._input("Share price", 10.0, "usable", "test")


def test_valuation_reverse_math_is_hand_checkable():
    # a flat perpetuity: 100 a year at 10% is worth 1,000, and 1,000 implies no growth
    value, terminal_share = vl.present_value(100, 0.0, 0.10, 0.0)
    assert value == pytest.approx(1000)
    assert vl.implied_growth(1000, 100, 0.10, 0.0)["growth"] == pytest.approx(0, abs=1e-9)
    # growth fades linearly: year 10 grows at exactly the terminal rate, so the terminal value is a clean Gordon step
    v = vl.present_value(100, 0.08, 0.10, 0.025)[0]
    assert vl.implied_growth(v, 100, 0.10, 0.025)["growth"] == pytest.approx(0.08, abs=1e-9)
    assert "more growth than this model can express" in vl.implied_growth(1e9, 100, 0.10, 0.025)["note"]
    assert "shrinking" in vl.implied_growth(1, 100, 0.10, 0.025)["note"]
    assert vl.implied_growth(1000, -5, 0.10, 0.025)["growth"] is None          # no positive cash flow: no answer


def test_valuation_compounder_reverse_grid_and_lease_adjustment():
    lease = {"RightOfUseAssetObtainedInExchangeForFinanceLeaseLiability": {"units": {"USD": [_vfy(2025, 40e6)]}}}
    r = vl.value_company("VEX", _vcompany(extra=lease), SOFTWARE, PRICE, VDAY)
    assert r["classification"]["family"] == vl.COMPOUNDER and "no cycle in 6 usable years" in r["classification"]["rule"]
    m = r["model"]
    assert m["status"] == vl.COMPUTED and m["market_cap"] == pytest.approx(1000e6)
    base, leased = m["grids"]
    assert base["fcf"] == pytest.approx(100e6) and leased["fcf"] == pytest.approx(60e6)   # 150 - 30 - 20; less 40
    for grid in m["grids"]:
        for cell in grid["rows"]:
            # every solved cell reproduces the market cap
            assert vl.present_value(grid["fcf"], cell["growth"], cell["rate"], cell["terminal"])[0] == pytest.approx(1000e6)
    cell = lambda g: next(x for x in g["rows"] if x["rate"] == 0.10 and x["terminal"] == 0.025)["growth"]
    assert cell(leased) > cell(base)            # less cash today needs more growth to justify the same price
    lenses = {x["lens"]: x["text"] for x in r["risk"]}
    assert lenses["Debt / TTM operating cash flow"] == "2.0 years of operating cash"   # 300 / 150, debt adds up
    assert lenses["Owner FCF yield ((OCF - capex - SBC) / market cap)"] == "10.0%"


def test_valuation_gates_refuse_instead_of_guessing():
    # two cover-page share classes: no clean denominator, so no market cap and no model
    r = vl.value_company("VEX", _vcompany(cover=(60e6, 40e6)), SOFTWARE, PRICE, VDAY)
    assert r["model"]["status"] == vl.UNAVAILABLE and "Shares outstanding (cover page) is needs reconciliation" in r[
        "model"]["reason"]
    # no price
    r = vl.value_company("VEX", _vcompany(), SOFTWARE, vl._input("Share price", None, "unknown", None, ["offline"]), VDAY)
    assert r["model"]["status"] == vl.UNAVAILABLE and "Share price is unknown; offline" in r["model"]["reason"]
    # no look-ahead: before the FY2025 10-K was filed, FY2024 is the latest year used
    r = vl.value_company("VEX", _vcompany(), SOFTWARE, PRICE, date(2026, 1, 31))
    ocf = next(i for i in r["model"]["inputs"] if i["label"].startswith("Operating cash flow"))
    assert ocf["value"] == 144e6 and "2024-12-31" in ocf["source"]


def test_valuation_classifies_cycles_burn_banks_and_unsupported():
    cyc = _vcompany(revenue=[500e6, 600e6, 700e6, 480e6, 650e6, 750e6])            # -31% in FY2023
    r = vl.value_company("CYC", cyc, SOFTWARE, PRICE, VDAY)
    assert r["classification"]["family"] == vl.CYCLICAL and "2023-12-31: revenue -31%" in r["classification"]["rule"]
    assert r["model"]["status"] == vl.DEFERRED and r["risk"]
    swing = _vcompany(op_income=[100e6, -20e6, 110e6, 120e6, 130e6, 140e6])
    assert vl.value_company("SW", swing, SOFTWARE, PRICE, VDAY)["classification"]["family"] == vl.CYCLICAL
    bank = vl.value_company("BNK", _vcompany(), {"sic": "6021", "sicDescription": "National Commercial Banks"},
                            PRICE, VDAY)
    assert bank["classification"]["family"] == vl.BANK and bank["model"]["status"] == vl.UNAVAILABLE
    assert "tangible common equity" in bank["model"]["reason"] and bank["risk"] == []
    ins = vl.value_company("INS", _vcompany(), {"sic": "6331", "sicDescription": "Fire, Marine & Casualty Insurance"},
                           PRICE, VDAY)
    assert ins["classification"]["family"] == vl.UNSUPPORTED and ins["model"]["status"] == vl.UNAVAILABLE
    short = _vcompany()
    for c in ("Revenues", "OperatingIncomeLoss", "NetCashProvidedByUsedInOperatingActivities",
              "PaymentsToAcquirePropertyPlantAndEquipment", "NetIncomeLoss"):
        short["facts"]["us-gaap"][c]["units"]["USD"] = short["facts"]["us-gaap"][c]["units"]["USD"][-3:]
    r = vl.value_company("NEW", short, SOFTWARE, PRICE, VDAY)
    assert r["classification"]["family"] == vl.INSUFFICIENT and "only 3 fiscal years" in r["classification"]["rule"]


def test_valuation_runway_for_a_cash_burner():
    q = "WeightedAverageNumberOfDilutedSharesOutstanding"
    extra = {"ShortTermInvestments": {"units": {"USD": [_vinst("2025-12-31", 100e6)]}},
             q: {"units": {"shares": [
                 {"start": "2024-10-01", "end": "2024-12-31", "val": 100e6, "form": "10-K", "filed": "2025-02-15",
                  "accn": "0000000009-25-000001"},
                 {"start": "2025-10-01", "end": "2025-12-31", "val": 120e6, "form": "10-K", "filed": "2026-02-15",
                  "accn": "0000000009-26-000001"}]}}}
    burner = _vcompany(ocf=[-100e6] * 6, capex=50e6, extra=extra)
    r = vl.value_company("BRN", burner, SOFTWARE, PRICE, VDAY)
    assert r["classification"]["family"] == vl.CASH_BURN
    m = r["model"]
    # liquidity 200 + 100 = 300; burn 50 - (-100) = 150 a year: 24 months
    assert m["status"] == vl.COMPUTED and m["liquidity"] == 300e6 and m["burn"] == 150e6
    assert m["months"] == pytest.approx(24)
    assert m["dilution"]["value"] == pytest.approx(0.20)
    assert any("Intrinsic value: unavailable" in n for n in m["notes"])


def test_valuation_debt_only_adds_reconciled_parts():
    day = "2025-12-31"
    debt = vl.total_debt(_vcompany(), VDAY, day)
    assert debt["value"] == 300e6 and debt["status"] == "usable" and "LongTermDebt 300.0M (noncurrent 250.0M)" in debt[
        "source"]
    only_nc = _vcompany()
    for c in ("LongTermDebt", "LongTermDebtCurrent"):
        del only_nc["facts"]["us-gaap"][c]
    d = vl.total_debt(only_nc, VDAY, day)
    assert d["value"] is None and d["status"] == "needs reconciliation" and "current portion" in d["notes"][0]
    mismatch = _vcompany(extra={"DebtCurrent": {"units": {"USD": [_vinst(day, 80e6)]}}})
    d = vl.total_debt(mismatch, VDAY, day)
    assert d["status"] == "needs reconciliation" and "doesn't match" in d["notes"][0]
    none = _vcompany()
    for c in ("LongTermDebt", "LongTermDebtCurrent", "LongTermDebtNoncurrent"):
        del none["facts"]["us-gaap"][c]
    assert vl.total_debt(none, VDAY, day)["status"] == "unknown"                # no debt tagged isn't zero debt


def test_valuation_price_is_the_close_on_or_before_the_as_of_date():
    hist = pd.DataFrame({"Close": [10.0, 11.0, 12.0]},
                        index=pd.to_datetime(["2026-02-26", "2026-02-27", "2026-03-02"]))
    assert vl.close_on(hist, VDAY) == (11.0, "2026-02-27")                     # 2026-03-01 is a Sunday
    assert vl.close_on(hist, date(2026, 1, 1)) == (None, None)


def test_valuation_report_and_command(monkeypatch):
    ok = vl.value_company("VEX", _vcompany(), SOFTWARE, PRICE, VDAY)
    gone = {"ticker": "ZZZZ", "status": "unavailable", "reason": "not in SEC's ticker list"}
    md = vl.markdown([ok, gone], VDAY, ua_status="configured")
    assert "**Status: PARTIAL**: 1 of 2 companies retrieved" in md and "Unavailable: not in SEC's ticker list" in md
    assert "sensitivity only" in md and "| discount 10% |" in md
    assert md.count("BUY") == 1 and "fair value of" not in md.lower()          # only the "no BUY/SELL" disclaimer
    import re
    assert not re.search(r"\bnan\b", md.lower())
    for results, code in (([ok], 0), ([ok, gone], 1), ([gone], 2)):
        it = iter(results)
        monkeypatch.setattr(vl, "value_ticker", lambda t, as_of, price, cfg: next(it))
        assert vl.main(["T"] * len(results) + ["--markdown", "/dev/null"]) == code
    assert vl._price_arg("msft=430.5") == ("MSFT", vl._input("Share price", 430.5, "usable", "given on the command line"))


def test_valuation_debt_contradictions_and_partial_net_debt_aren_t_trusted():
    day = "2025-12-31"
    # LongTermDebt 310 vs noncurrent 250 + current 50: contradictory, so no total and no debt lenses
    bad = _vcompany(extra={"LongTermDebt": {"units": {"USD": [_vinst(day, 310e6)]}}})
    d = vl.total_debt(bad, VDAY, day)
    assert d["status"] == "needs reconciliation" and d["value"] is None and "contradicts" in d["notes"][0]
    lenses = {x["lens"]: x for x in vl.value_company("VEX", bad, SOFTWARE, PRICE, VDAY)["risk"]}
    assert lenses["Debt / TTM operating cash flow"]["value"] is None
    assert lenses["Net debt (debt - cash - short-term investments)"]["value"] is None
    # commercial paper may sit inside short-term borrowings: not added blindly
    nested = _vcompany(extra={"ShortTermBorrowings": {"units": {"USD": [_vinst(day, 40e6)]}},
                              "CommercialPaper": {"units": {"USD": [_vinst(day, 30e6)]}}})
    assert vl.total_debt(nested, VDAY, day)["status"] == "needs reconciliation"
    # short-term investments not reported: net debt has no value, and the partial figure is labelled
    net = {x["lens"]: x for x in vl.value_company("VEX", _vcompany(), SOFTWARE, PRICE, VDAY)["risk"]}
    nd = net["Net debt (debt - cash - short-term investments)"]
    assert nd["value"] is None and "Partial only: debt less cash = 100.0M" in nd["text"]
    with_sti = _vcompany(extra={"ShortTermInvestments": {"units": {"USD": [_vinst(day, 60e6)]}}})
    nd = {x["lens"]: x for x in vl.value_company("VEX", with_sti, SOFTWARE, PRICE, VDAY)["risk"]}[
        "Net debt (debt - cash - short-term investments)"]
    assert nd["value"] == pytest.approx(40e6)


def _quarters(*facts):
    return {"WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
        {"start": s, "end": e, "val": v, "form": form, "filed": filed, "accn": accn}
        for s, e, v, form, filed, accn in facts]}}}


def test_valuation_dilution_needs_two_clean_comparable_quarters():
    ref = {"end": "2025-12-31", "fy_end": "2025-12-31", "age": 60}
    q24 = ("2024-10-01", "2024-12-31", 100e6, "10-K", "2025-02-15", "0000000009-25-000001")
    q25 = ("2025-10-01", "2025-12-31", 120e6, "10-K", "2026-02-15", "0000000009-26-000001")
    clean = vl._share_growth({"facts": {"us-gaap": _quarters(q24, q25)}}, VDAY, ref)
    assert clean["status"] == "usable" and clean["value"] == pytest.approx(0.20)
    assert "EPS denominator" in clean["label"] and "0000000009-25-000001" in clean["source"]
    # two values for the latest quarter in one filing: no percentage
    dup = vl._share_growth({"facts": {"us-gaap": _quarters(q24, q25, q25[:2] + (125e6,) + q25[3:])}}, VDAY, ref)
    assert dup["status"] == "unknown" and dup["value"] is None and "no number is trusted" in dup["notes"][0]
    # the year-earlier quarter revised by a later filing: needs reconciliation, no percentage
    revised = vl._share_growth({"facts": {"us-gaap": _quarters(
        q24, q25, q24[:2] + (110e6, "10-K", "2026-02-15", "0000000009-26-000001"))}}, VDAY, ref)
    assert revised["status"] == "needs reconciliation" and revised["value"] is None
    zero = vl._share_growth({"facts": {"us-gaap": _quarters(q24[:2] + (0.0,) + q24[3:], q25)}}, VDAY, ref)
    assert zero["value"] is None and "zero" in zero["notes"][-1]
    # a Q4 from the 10-K is current when Q4 is the latest period (clean case above), but not once the
    # company has reported 2026-Q2: a quarterly figure is judged against the latest period, not the fiscal year
    aged = vl._share_growth({"facts": {"us-gaap": _quarters(q24, q25)}}, VDAY,
                            {"end": "2026-06-30", "fy_end": "2025-12-31", "age": 10})
    assert aged["status"] == "stale" and aged["value"] is None and "181 days before" in aged["notes"][0]
    q_aged = ("2025-07-01", "2025-09-30", 118e6, "10-Q", "2025-11-01", "0000000009-25-000030")
    q_prev = ("2024-07-01", "2024-09-30", 98e6, "10-Q", "2024-11-01", "0000000009-24-000030")
    stale = vl._share_growth({"facts": {"us-gaap": _quarters(q_prev, q_aged)}}, VDAY, ref)
    assert stale["status"] == "stale" and stale["value"] is None


def test_valuation_classifier_ignores_untrusted_fiscal_years():
    # FY2023 revenue: two values in one filing, one of them a 30% drop. It can't trigger "cyclical",
    # and the company can't be called a compounder either: insufficient evidence, naming the year.
    dup = _vcompany(extra={})
    dup["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(_vfy(2023, 420e6))
    r = vl.value_company("DUP", dup, SOFTWARE, PRICE, VDAY)
    assert r["classification"]["family"] == vl.INSUFFICIENT
    assert "FY 2023-12-31: Revenue unknown" in r["classification"]["rule"]
    assert r["model"]["status"] == vl.UNAVAILABLE
    # FY2022 revenue revised by a later 10-K: the year needs reconciliation, so no compounder call
    rev = _vcompany()
    rev["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
        {"start": "2022-01-01", "end": "2022-12-31", "val": 640e6, "form": "10-K", "filed": "2024-02-15",
         "accn": "0000000009-24-000001"})
    r = vl.value_company("REV", rev, SOFTWARE, PRICE, VDAY)
    assert r["classification"]["family"] == vl.INSUFFICIENT and "FY 2022-12-31: Revenue needs reconciliation" in r[
        "classification"]["rule"]
    # another revenue tag disagreeing for a year (not a known scope pair) also blocks
    alt = _vcompany(extra={"RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [_vfy(2021, 400e6)]}}})
    r = vl.value_company("ALT", alt, SOFTWARE, PRICE, VDAY)
    assert r["classification"]["family"] == vl.INSUFFICIENT and "disagrees with Revenues" in r["classification"]["rule"]
    # a drop between two clean years is still evidence of a cycle, even with an untrusted year elsewhere
    cyc = _vcompany(revenue=[500e6, 600e6, 700e6, 480e6, 650e6, 750e6])
    cyc["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(_vfy(2020, 520e6))
    r = vl.value_company("CYC", cyc, SOFTWARE, PRICE, VDAY)
    assert r["classification"]["family"] == vl.CYCLICAL and "2023-12-31: revenue -31%" in r["classification"]["rule"]
    md = vl.markdown([r], VDAY, ua_status="configured")
    assert "| Data issues |" in md and "Revenue unknown" in md


def test_valuation_debt_needs_confirmed_long_term_coverage():
    day = "2025-12-31"

    def only(**tags):
        company = _vcompany()
        for c in ("LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtCurrent"):
            del company["facts"]["us-gaap"][c]
        company["facts"]["us-gaap"].update({c: {"units": {"USD": [_vinst(day, v)]}} for c, v in tags.items()})
        return company
    # only current items, no long-term tag: not a total, and no debt lenses
    for company in (only(DebtCurrent=50e6), only(ShortTermBorrowings=50e6)):
        d = vl.total_debt(company, VDAY, day)
        assert d["status"] == "needs reconciliation" and d["value"] is None and "no long-term debt tagged" in d["notes"][0]
        lenses = {x["lens"]: x for x in vl.value_company("D", company, SOFTWARE, PRICE, VDAY)["risk"]}
        assert lenses["Debt / TTM operating cash flow"]["value"] is None
    # an explicitly reported zero long-term debt is coverage: the total is usable
    d = vl.total_debt(only(LongTermDebtNoncurrent=0.0, DebtCurrent=50e6), VDAY, day)
    assert d["status"] == "usable" and d["value"] == 50e6
    # DebtCurrent contradicting the current portion implied by LongTermDebt - noncurrent (500 - 400 = 100)
    d = vl.total_debt(only(LongTermDebt=500e6, LongTermDebtNoncurrent=400e6, DebtCurrent=50e6), VDAY, day)
    assert d["status"] == "needs reconciliation" and d["value"] is None and "doesn't match" in d["notes"][0]
    d = vl.total_debt(only(LongTermDebt=500e6, LongTermDebtNoncurrent=400e6, DebtCurrent=100e6), VDAY, day)
    assert d["status"] == "usable" and d["value"] == 500e6


def test_valuation_missing_latest_year_blocks_a_compounder_call():
    # FY2025 revenue missing while FY2025 cash flow is reported: the year shows as unknown, not dropped
    gap = _vcompany()
    gap["facts"]["us-gaap"]["Revenues"]["units"]["USD"] = gap["facts"]["us-gaap"]["Revenues"]["units"]["USD"][:-1]
    r = vl.value_company("GAP", gap, SOFTWARE, PRICE, VDAY)
    assert r["classification"]["family"] == vl.INSUFFICIENT
    assert "FY 2025-12-31: Revenue not reported for this fiscal year" in r["classification"]["rule"]
    assert r["classification"]["evidence"][0]["end"] == "2025-12-31" and r["model"]["status"] == vl.UNAVAILABLE
    # the complete history is still a compounder, and a genuine pre-filing as-of isn't affected
    assert vl.value_company("OK", _vcompany(), SOFTWARE, PRICE, VDAY)["classification"]["family"] == vl.COMPOUNDER
    early = vl.value_company("OK", _vcompany(), SOFTWARE, PRICE, date(2026, 1, 31))
    assert early["classification"]["evidence"][0]["end"] == "2024-12-31"


def test_valuation_ambiguous_quarters_give_no_dilution_figure():
    ref = {"end": "2025-12-31", "fy_end": "2025-12-31", "age": 60}
    prior = ("2024-10-01", "2024-12-31", 90e6, "10-K", "2025-02-15", "0000000009-25-000001")
    a = ("2025-10-01", "2025-12-31", 100e6, "10-K", "2026-02-15", "0000000009-26-000001")
    b = ("2025-09-20", "2025-12-31", 120e6, "10-K", "2026-02-15", "0000000009-26-000001")
    for order in ((prior, a, b), (prior, b, a)):              # the answer doesn't depend on input order
        g = vl._share_growth({"facts": {"us-gaap": _quarters(*order)}}, VDAY, ref)
        assert g["status"] == "needs reconciliation" and g["value"] is None and "ambiguous" in g["notes"][0]
    other_prior = ("2024-09-25", "2024-12-31", 95e6, "10-K", "2025-02-15", "0000000009-25-000001")
    g = vl._share_growth({"facts": {"us-gaap": _quarters(prior, other_prior, a)}}, VDAY, ref)
    assert g["value"] is None and "a year earlier" in g["notes"][0]
    clean = vl._share_growth({"facts": {"us-gaap": _quarters(prior, a)}}, VDAY, ref)
    assert clean["status"] == "usable" and clean["value"] == pytest.approx(100 / 90 - 1)


def test_valuation_zero_revenue_and_zero_runway_are_reported_not_crashed():
    burner = _vcompany(revenue=[0.0] * 6, ocf=[-100e6] * 6, capex=50e6)
    burner["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"]["units"]["USD"] = [_vinst("2025-12-31", 0.0)]
    r = vl.value_company("ZERO", burner, SOFTWARE, PRICE, VDAY)
    assert r["status"] == "ok" and r["model"]["status"] == vl.COMPUTED and r["model"]["months"] == 0
    lenses = {x["lens"]: x["text"] for x in r["risk"]}
    assert lenses["Capex / revenue (TTM)"] == "n/a: no revenue over the last twelve months"
    md = vl.markdown([r], VDAY, ua_status="configured")
    assert "runway exhausted" in md and "not burning cash" not in md


def test_valuation_fiscal_years_align_one_to_one():
    # latest revenue is a June fiscal year; the cash-flow years end in December. The June figure must not
    # fill both December rows, so the latest year has no revenue and there's no compounder call.
    shifted = _vcompany()
    rev = shifted["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    rev[-1] = dict(rev[-1], start="2024-07-01", end="2025-06-30")
    r = vl.value_company("SHF", shifted, SOFTWARE, PRICE, VDAY)
    ev = r["classification"]["evidence"]
    assert r["classification"]["family"] == vl.INSUFFICIENT and r["model"]["status"] == vl.UNAVAILABLE
    fills = [e["end"] for e in ev if e["sources"]["revenue"] and "2025-06-30" in e["sources"]["revenue"]]
    assert fills == ["2025-06-30"]                                  # used once, on its own row
    assert ev[0]["end"] == "2025-12-31" and ev[0]["revenue"] is None and ev[0]["status"]["revenue"] == "unknown"
    assert "2024-07-01 to 2025-06-30" in next(e for e in ev if e["end"] == "2025-06-30")["periods"]
    # a 52/53-week calendar a few days off still lines up as the same fiscal year
    weekly = _vcompany()
    rev = weekly["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    rev[-1] = dict(rev[-1], start="2024-12-29", end="2025-12-27")
    r = vl.value_company("WK", weekly, SOFTWARE, PRICE, VDAY)
    assert r["classification"]["family"] == vl.COMPOUNDER
    row = r["classification"]["evidence"][0]
    assert row["revenue"] == 750e6 and sorted(row["periods"]) == ["2024-12-29 to 2025-12-27", "2025-01-01 to 2025-12-31"]
