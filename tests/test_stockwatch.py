import numpy as np
import pandas as pd
import pytest

from stockwatch import fundamental, technical
from stockwatch.config import Holding, Portfolio, Settings, TierRules, load_portfolio
from stockwatch.data import DemoProvider
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
    class T:
        def __init__(self, sym):
            self.info = info

        def history(self, **kw):
            return bars if bars is not None else pd.DataFrame()

    yp = YahooProvider.__new__(YahooProvider)
    yp._yf = type("yf", (), {"Ticker": T})
    return yp


def test_yahoo_quote_reads_pre_and_post_market():
    post = _fake_yahoo({"marketState": "POST", "regularMarketPrice": 100.0, "postMarketPrice": 92.0,
                        "postMarketTime": 1761080000}).quote("X")
    assert post["ext_session"] == "post" and abs(post["ext_change"] + 0.08) < 1e-9 and post["ext_time"].tzinfo
    pre = _fake_yahoo({"marketState": "PRE", "regularMarketPrice": 50.0, "preMarketPrice": 51.0,
                       "postMarketPrice": 49.0}).quote("X")
    assert pre["ext_session"] == "pre" and pre["ext_price"] == 51.0       # stale post price ignored pre-market
    live = _fake_yahoo({"marketState": "REGULAR", "regularMarketPrice": 50.0, "postMarketPrice": 49.0}).quote("X")
    assert live["ext_price"] is None                                         # no extended price during the session


def test_yahoo_quote_falls_back_to_extended_bars():
    idx = pd.DatetimeIndex([pd.Timestamp("2026-10-21 19:55", tz="America/New_York")])
    bars = pd.DataFrame({"Close": [105.0]}, index=idx)
    q = _fake_yahoo({"marketState": "POST", "regularMarketPrice": 100.0}, bars).quote("X")
    assert q["ext_session"] == "post" and abs(q["ext_change"] - 0.05) < 1e-9


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
