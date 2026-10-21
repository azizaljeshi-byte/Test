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

    def history(self, ticker, period="2y"):
        return self.df

    def fundamentals(self, ticker):
        return self.f

    def events(self, ticker):
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
        def history(self, ticker, period="2y"):
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
        def history(self, ticker, period="2y"):
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
