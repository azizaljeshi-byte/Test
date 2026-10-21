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


def test_sec_ticker_lookup_uses_bundled_ciks(monkeypatch):
    sec._ticker_map.cache_clear()
    monkeypatch.setattr(sec, "_get", lambda url: (_ for _ in ()).throw(OSError("offline")))
    assert sec.cik_for("AAPL") == 320193 and sec.cik_for("brk.b") == 1067983
    sec._ticker_map.cache_clear()


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
        assert t.maybe_market_scan(store, background=False)          # nothing on record: scan now
        first = store.latest_market_scan()
        assert first and first["universe"] == 40
        assert not t.maybe_market_scan(store, background=False)      # just ran
        restarted = live.Tracker(get_provider("demo"), store_path=tmp_path / "m.db", start=False)
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
