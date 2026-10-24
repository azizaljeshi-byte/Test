"""The in-app US pre-market briefing (stockwatch/premarket.py and its screen). Offline, synthetic data only."""
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from stockwatch import premarket, ui

PRE = datetime(2026, 10, 23, 12, 55, tzinfo=timezone.utc)        # Fri 08:55 New York: pre-market
REGULAR = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)      # Fri 11:00 New York
CLOSED_SAT = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def daily(closes, end="2026-10-22"):
    idx = pd.bdate_range(end=end, periods=len(closes))
    c = np.asarray(closes, float)
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": np.full(len(c), 1e6)}, index=idx)


class FakeProvider:
    def __init__(self, hist=None, quotes=None, boom=False):
        self.hist, self.quotes, self.boom = hist or {}, quotes or {}, boom

    def bulk_history(self, symbols, period="2y"):
        if self.boom:
            raise RuntimeError("Yahoo refused")
        return {s: self.hist[s] for s in symbols if s in self.hist}

    def bulk_quotes(self, symbols):
        if self.boom:
            raise RuntimeError("Yahoo refused")
        return {s: self.quotes.get(s, {}) for s in symbols}


def snap(ticker, sector="Technology", value=1000.0, held=True, day=None, quote=None, news=None):
    return {"ticker": ticker, "payload": {"watchlist": not held, "position": {"value": value} if held else {},
                                          "profile": {"sector": sector}, "technical": {"day_change": day},
                                          "quote": quote or {}, "events": {"news": news or []}}}


# ---- prices

def test_prior_session_change_uses_the_last_completed_bar():
    last, ch, day = premarket.prior_session(daily([100, 100, 100, 110]), "SPY", PRE)
    assert (last, round(ch, 3), day) == (110.0, 0.1, "2026-10-22")


def test_a_bar_dated_today_is_dropped_while_it_can_be_partial():
    df = daily([100, 100, 100, 110, 121], end="2026-10-23")             # the last bar is Friday's, still in progress
    assert premarket.prior_session(df, "SPY", REGULAR)[1] == pytest.approx(0.1)
    assert premarket.prior_session(df, "SPY", PRE)[1] == pytest.approx(0.1)
    assert premarket.prior_session(df, "SPY", CLOSED_SAT)[1] == pytest.approx(0.1)     # Saturday: Friday's bar is complete -> 121/110
    assert premarket.prior_session(df, "SPY", CLOSED_SAT)[0] == 121.0


def test_futures_and_crypto_bars_dated_today_are_never_complete():
    df = daily([100, 100, 100, 110, 99], end="2026-10-23")             # the last bar is dated Friday
    after_close = datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc)   # Friday 18:00 New York: equities are done for the day
    assert premarket.prior_session(df, "SPY", after_close)[0] == 99.0
    for sym in ("ES=F", "BTC-USD"):
        assert premarket.prior_session(df, sym, after_close)[0] == 110.0


def test_missing_or_short_history_is_unknown():
    assert premarket.prior_session(None, "SPY", PRE) == (None, None, None)
    assert premarket.prior_session(daily([100, 101]), "SPY", PRE) == (None, None, None)
    assert premarket.prior_session(pd.DataFrame({"Open": [1, 2, 3]}), "SPY", PRE) == (None, None, None)
    nan = daily([100, 100, np.nan, np.nan])
    assert premarket.prior_session(nan, "SPY", PRE)[0] is None or premarket.prior_session(nan, "SPY", PRE)[1] is not None


def test_live_change_prefers_live_then_extended_and_never_invents():
    assert premarket.live_change({"live_change": 0.01, "ext_change": 0.02}) == 0.01
    assert premarket.live_change({"live_change": None, "ext_change": -0.02}) == -0.02
    assert premarket.live_change({}) is None and premarket.live_change(None) is None
    assert premarket.live_change({"live_change": float("nan")}) is None


def test_every_symbol_is_requested_once():
    syms = premarket.all_symbols()
    assert len(syms) == len(set(syms)) and {"SPY", "ES=F", "^VIX", "^TNX", "XLK", "XLRE"} <= set(syms)
    assert len(premarket.SECTORS) == 11


# ---- your own data

def test_exposure_is_percent_by_sector_and_never_an_amount():
    snaps = [snap("NVDA", "Technology", 600), snap("AMD", "Technology", 200), snap("DIS", "Communication Services", 200),
             snap("WATCH", "Energy", held=False)]
    ex = premarket.exposure(snaps)
    assert [(g["sector"], round(g["pct"], 2), g["names"]) for g in ex] == [
        ("Technology", 0.8, ["AMD", "NVDA"]), ("Communication", 0.2, ["DIS"])]
    assert "600" not in repr(ex) and "1000" not in repr(ex)
    assert premarket.exposure([snap("W", held=False)]) == [] and premarket.exposure([]) == []
    assert premarket.exposure([snap("X", value=0)]) == []


def test_movers_keep_only_major_moves_biggest_first():
    snaps = [snap("A", day=0.08), snap("B", day=-0.12), snap("C", day=0.01), snap("D", day=None),
             snap("E", held=False, day=-0.04, quote={"market_state": "PRE", "ext_change": 0.05, "ext_session": "pre"})]
    m = premarket.movers(snaps)
    assert [x["ticker"] for x in m["prior"]] == ["B", "A", "E"]
    assert [x["ticker"] for x in m["now"]] == ["E"] and m["now"][0]["session"] == "pre"
    assert m["prior"][2]["held"] is False


def test_holdings_news_is_recent_deduplicated_and_owned_names_come_first():
    fresh, old = "2026-10-23T08:00", "2026-10-10T08:00"
    snaps = [snap("W", held=False, news=[{"title": "Watch news", "published": fresh, "url": "u1"}]),
             snap("A", news=[{"title": "Big news", "published": fresh, "url": "u2", "tone": "positive"},
                             {"title": "Old news", "published": old}, {"title": "Big news", "published": fresh},
                             {"title": "", "published": fresh}, {"title": "No date"}])]
    out = premarket.holdings_news(snaps, PRE)
    assert [n["title"] for n in out] == ["Big news", "Watch news"] and out[0]["held"] is True


# ---- the whole briefing

def hist_for(symbols, closes=(100, 100, 100, 110)):
    return {s: daily(closes) for s in symbols}


def test_build_gathers_every_part_and_a_takeaway():
    syms = premarket.all_symbols()
    quotes = {"ES=F": {"ext_change": 0.004, "ext_session": "pre"}, "NQ=F": {"ext_change": -0.002}, "XLK": {"ext_change": 0.01}}
    b = premarket.build(FakeProvider(hist_for(syms), quotes), [snap("NVDA", value=100)], PRE,
                        news_fn=lambda: [{"title": "Fed holds", "publisher": "Wire", "url": "u", "published": PRE}])
    assert b["session"] == "PRE" and b["missing"] == [] and len(b["sectors"]) == 11 and len(b["indexes"]) == 4
    assert b["takeaway"] == "S&P 500 +0.4% · Nasdaq 100 -0.2% · VIX 110.0"
    assert b["market_news"][0]["title"] == "Fed holds" and b["market_news_why"] is None
    xlk = next(r for r in b["sectors"] if r["symbol"] == "XLK")
    assert xlk["names"] == ["NVDA"] and xlk["now"] == 0.01 and xlk["prior"] == pytest.approx(0.1)
    assert b["exposure"][0]["pct"] == 1.0


def test_a_failed_download_is_listed_not_hidden_and_never_crashes():
    b = premarket.build(FakeProvider(boom=True), [], PRE, news_fn=lambda: [])
    assert "market prices (history download failed)" in b["missing"] and "live and pre-market prices" in b["missing"]
    assert all(not r["known"] for r in b["indexes"]) and b["takeaway"] == "No market prices yet."


def test_nothing_priced_is_reported():
    b = premarket.build(FakeProvider({"ZZZ": daily([1, 2, 3, 4])}), [], PRE, news_fn=lambda: [])
    assert "market prices (nothing could be priced)" in b["missing"]


def test_news_says_why_when_it_is_missing(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert "no FINNHUB_API_KEY" in premarket.build(FakeProvider(), [], PRE)["market_news_why"]

    def boom():
        raise RuntimeError("403")
    assert "didn't return" in premarket.build(FakeProvider(), [], PRE, news_fn=boom)["market_news_why"]


# ---- the screen

def built(**kw):
    return premarket.build(FakeProvider(hist_for(premarket.all_symbols()), kw.get("quotes", {})),
                           kw.get("snaps", [snap("NVDA", value=100, day=0.08)]), PRE,
                           news_fn=lambda: [{"title": "Fed <holds>", "publisher": "Wire", "url": "https://x.test/a", "published": PRE}])


def test_the_sections_come_in_reading_order_with_numbers():
    sections = ui.briefing_sections(built(), {"NVDA"})
    assert [t for t, _ in sections] == ["", "Where the market stands", "Macro", "Sectors · strongest first", "Your exposure by industry",
                                        "Biggest moves last session", "Biggest moves now (pre-market, after-hours, live)",
                                        "News on your names", "Market headlines"]
    html = "".join(h for _, h in sections)
    assert "S&amp;P 500" in html and "+10.0%" in html and "Fed &lt;holds&gt;" in html and "100%" in html
    assert 'href="?view=target&t=NVDA"' in html


def test_macro_tiles_read_yields_and_vix_the_right_way_round():
    hist = {s: daily([100, 100, 100, 110]) for s in premarket.all_symbols()}
    hist["^TNX"] = daily([42.0, 42.0, 42.0, 42.5])
    b = premarket.build(FakeProvider(hist), [], PRE, news_fn=lambda: [])
    tnx = ui._macro_tile(next(r for r in b["macro"] if r["symbol"] == "^TNX"))
    assert tnx[1] == "4.25%" and "bp" in tnx[2] and tnx[3] == ui.RISK                # a rising yield is shown as pressure
    vix = ui._macro_tile(next(r for r in b["macro"] if r["symbol"] == "^VIX"))
    assert vix[3] == ui.RISK                                                         # a rising VIX is bad news
    oil = ui._macro_tile(next(r for r in b["macro"] if r["symbol"] == "CL=F"))
    assert oil[3] == ui.OPP


def test_unpriced_rows_say_n_a_and_empty_parts_say_so():
    b = premarket.build(FakeProvider(), [], PRE, news_fn=lambda: [])
    html = "".join(h for _, h in ui.briefing_sections(b, set()))
    assert "n/a" in html and "No major moves" in html and "No fresh headlines" in html


def test_sectors_are_sorted_strongest_first_in_the_heat_map():
    syms = premarket.all_symbols()
    hist = {sym: daily([100, 100, 100, 100 + i]) for i, sym in enumerate(syms)}
    heat = dict(ui.briefing_sections(premarket.build(FakeProvider(hist), [], PRE, news_fn=lambda: []), set()))["Sectors · strongest first"]
    order = [sym for _, sym in premarket.SECTORS]
    expected = sorted(order, key=lambda sym: -syms.index(sym))
    positions = [heat.index(f"· {sym}</div>") for sym in expected]
    assert positions == sorted(positions)


def test_the_hero_says_how_the_market_is_leaning():
    up = premarket.build(FakeProvider(hist_for(premarket.all_symbols()), {"ES=F": {"ext_change": 0.006}, "NQ=F": {"ext_change": 0.008}}), [], PRE, news_fn=lambda: [])
    assert up["mood"]["word"] == "GREEN OPEN" and up["mood"]["tone"] == "up"
    down = premarket.build(FakeProvider(hist_for(premarket.all_symbols(), (100, 100, 110, 100)), {}), [], PRE, news_fn=lambda: [])
    assert down["mood"]["word"] == "RED OPEN"
    assert premarket.mood([], "PRE")["word"] == "NO READ"
    assert premarket.mood(up["indexes"], "REGULAR")["word"] == "TRADING UP" and premarket.mood(up["indexes"], "CLOSED")["word"] == "CLOSED UP"
    hero = ui.briefing_sections(up, set())[0][1]
    assert "GREEN OPEN" in hero and "bf-flow" in hero and "pre-market" in hero


def test_sparklines_and_donut_draw_only_with_enough_data():
    assert ui.spark([1, 2, 3], ui.OPP) == "" and ui.spark(None, ui.OPP) == ""
    assert "<polyline" in ui.spark([1, 2, 3, 4, 5, float("nan"), 6], ui.OPP)
    ring = ui.donut([(0.75, ui.OPP), (0.25, ui.INFO)], "2", "industries")
    assert ring.count("<circle") == 3 and ">2<" in ring
    long = premarket.build(FakeProvider(hist_for(premarket.all_symbols(), [100] * 12 + [110])), [], PRE, news_fn=lambda: [])
    assert "<polyline" in dict(ui.briefing_sections(long, set()))["Where the market stands"]
    assert "<polyline" not in dict(ui.briefing_sections(built(), set()))["Where the market stands"]       # 4 bars: too few to draw


def test_the_mover_bars_point_the_right_way():
    html = ui._mover_bars([{"ticker": "UP", "pct": 0.1, "held": True}, {"ticker": "DN", "pct": -0.1, "held": False}])
    assert "left:50%;width:50.0%" in html and "left:0.0%;width:50.0%" in html


# ---- background cache

def test_request_builds_once_in_the_background_and_reuses_a_fresh_result(monkeypatch):
    premarket._state.update(data=None, built=0.0, running=False, error=None)
    calls = []
    monkeypatch.setattr(premarket, "build", lambda provider, snaps: calls.append(1) or {"as_of": "x", "session": "PRE"})
    premarket.request(object(), [])
    for _ in range(50):
        if premarket.current()["data"]:
            break
        time.sleep(0.02)
    assert premarket.current()["data"] == {"as_of": "x", "session": "PRE"} and premarket.current()["age"] is not None
    premarket.request(object(), [])
    time.sleep(0.1)
    assert calls == [1]                                                  # fresh: no second build
    premarket.request(object(), [], force=True)
    time.sleep(0.2)
    assert calls == [1, 1]
    premarket._state.update(data=None, built=0.0, running=False, error=None)


def test_a_failed_build_keeps_the_last_good_briefing_and_reports_the_error(monkeypatch):
    premarket._state.update(data={"as_of": "old"}, built=time.monotonic() - 10_000, running=False, error=None)

    def boom(provider, snaps):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(premarket, "build", boom)
    premarket.request(object(), [])
    for _ in range(50):
        if premarket.current()["error"]:
            break
        time.sleep(0.02)
    cur = premarket.current()
    assert cur["data"] == {"as_of": "old"} and "kaboom" in cur["error"] and cur["running"] is False
    premarket._state.update(data=None, built=0.0, running=False, error=None)


def test_the_demo_provider_builds_a_briefing():
    from stockwatch.data import DemoProvider
    b = premarket.build(DemoProvider(), [], PRE, news_fn=lambda: [])
    assert len(b["sectors"]) == 11 and any(r["known"] for r in b["indexes"])
    assert ui.briefing_sections(b, set())


def test_the_missing_news_message_keeps_the_key_name_intact():
    b = premarket.build(FakeProvider(), [], PRE)
    html = dict(ui.briefing_sections(b, set()))["Market headlines"]
    assert "No FINNHUB_API_KEY is set" in html
