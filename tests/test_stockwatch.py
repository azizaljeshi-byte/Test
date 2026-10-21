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
