"""The one extended card at the top of the Details page (stockwatch/stockhead.py)."""
from datetime import datetime, timezone

from stockwatch import stockhead


def snap(price=283.82, call="EXIT", news_age_h=3, tone="negative"):
    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    pub = (now.replace(hour=12 - news_age_h) if news_age_h < 12 else now).isoformat(timespec="minutes")
    return {"ticker": "GG", "tier": 1, "price": price, "composite": 66.0, "verdict": "RISK - REVIEW", "technical_score": 16.0,
            "fundamental_score": 93.0,
            "payload": {"name": "Gee Inc", "watchlist": False, "signals": [{"kind": "risk", "source": "analyst", "message": "Downgraded by X", "severity": 2}],
                        "quote": {"market_state": "PRE", "ext_price": 281.0, "ext_change": -0.009, "ext_session": "pre", "fetched_at": "2026-10-30T08:05:00+00:00"},
                        "events": {"days_to_earnings": 95, "earnings_date": "2027-02-02",
                                   "news": [{"title": "Shares tumble", "publisher": "Y", "url": "https://x.test/a", "published": pub, "tone": tone}]},
                        "fundamental": {"available": True, "pillar_growth": 100.0, "pe": 18.7, "analyst_upside": 0.48},
                        "plan": {"stop": 251.79},
                        "technical": {"day_change": -0.126, "trend": "down", "sma50": 340.0, "sma200": 340.6, "rsi": 22.0, "volume_ratio": 4.5,
                                      "drawdown_52w": -0.29, "rs_spy_3m": -0.23, "atr": 10.7,
                                      "momentum": {"known": True, "momentum": "falling", "momentum_label": "FALLING", "cause_label": "event-driven", "why": "A -13% day."},
                                      "zones": {"known": True, "support": [{"low": 270.0, "high": 271.77, "grade": "MEDIUM"}],
                                                "resistance": [{"low": 290.83, "high": 293.7, "grade": "MEDIUM"}]},
                                      "one_call": {"known": True, "call": call, "exit_line": 316.6, "band_line": 311.26, "as_of": "2026-10-29"}}}}


def test_ladder_is_ordered_and_has_every_level():
    rows = stockhead.ladder(snap())
    assert [r["label"] for r in rows] == ["Exit line", "Next resistance", "Now", "Next support", "Plan stop"]
    assert [r["level"] for r in rows] == sorted((r["level"] for r in rows), reverse=True)


def test_reading_says_falling_with_its_cause():
    word, tone, why = stockhead.reading(snap())
    assert (word, tone) == ("Falling", "bad") and "event-driven" in why


def test_reading_without_momentum_falls_back_to_the_trend():
    s = snap()
    s["payload"]["technical"]["momentum"] = {"known": False}
    assert stockhead.reading(s)[0] == "Down trend"


def test_card_has_levels_technicals_fundamentals_and_news():
    h = stockhead.html(snap(), now=datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc))
    for want in ("$316.60", "$290.83", "$271.77", "RSI", "oversold", "Growth", "Shares tumble", "Downgraded by X", "2027-02-02"):
        assert want in h


def test_old_news_is_left_out():
    assert stockhead.news(snap(news_age_h=11), now=datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)) == []


def test_missing_data_shows_unknown_not_zero():
    s = snap()
    s["payload"]["fundamental"] = {"available": False}
    s["payload"]["technical"].update({"rsi": None, "volume_ratio": float("nan")})
    h = stockhead.html(s)
    assert "unavailable" in h and "RSI" not in h and "Volume" not in h
