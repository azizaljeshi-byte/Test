"""Small-cap screen with invented companies and fake data; nothing here touches scoring."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from stockwatch import smallcap as sc

GOOD = dict(name="Good Co", market_cap=800e6, revenue_growth=0.25, earnings_growth=0.3, profit_margin=0.1, debt_to_equity=0.4,
            current_ratio=2.0, free_cash_flow=20e6, total_cash=50e6, peg=1.0)
NOW = datetime(2026, 11, 10, 22, 0, tzinfo=timezone.utc)      # after the close, so the day bar is whole


def test_universe_cleans_dedupes_and_skips_headers():
    text = "Ticker,Name\nabcd,x\nABCD,dup\n  brk.b ,y\n\n$$$,bad\nsymbol\nWAYTOOLONGTICKER,z\n"
    assert sc.load_universe(text) == ["ABCD", "BRK-B"]


def test_a_good_company_qualifies_and_size_bands_are_named():
    c = sc.fund_check(GOOD, 10.0)
    assert c["passed"] and c["band"] == "Small" and c["value"] == "Cheap"
    assert [sc.band_of(x) for x in (10e6, 100e6, 1e9, 5e9, 50e9, None)] == [None, "Tiny", "Small", "Mid", None, None]


def test_no_profit_needs_significant_revenue_growth_and_cash_runway():
    base = dict(GOOD, profit_margin=-0.2, earnings_growth=None, eps_trailing=-1.0, peg=None, price_to_sales=1.5, free_cash_flow=-10e6, total_cash=40e6)
    assert sc.fund_check(dict(base, revenue_growth=0.35), 5.0)["passed"]
    slow = sc.fund_check(dict(base, revenue_growth=0.10), 5.0)
    assert not slow["passed"] and "growth" in slow["why_not"]
    short = sc.fund_check(dict(base, revenue_growth=0.35, total_cash=10e6), 5.0)     # only a year of cash
    assert not short["passed"] and "cash" in short["why_not"]


def test_debt_and_thin_balance_sheet_fail_but_unknown_does_not_fail():
    assert not sc.fund_check(dict(GOOD, debt_to_equity=3.0), 10.0)["passed"]
    assert not sc.fund_check(dict(GOOD, current_ratio=0.8), 10.0)["passed"]
    c = sc.fund_check({k: v for k, v in GOOD.items() if k not in ("debt_to_equity", "current_ratio")}, 10.0)
    assert c["pillars"]["debt"][0] is None and c["passed"]                      # 3 of 4 known, none failing
    c = sc.fund_check({k: v for k, v in GOOD.items() if k not in ("debt_to_equity", "current_ratio", "free_cash_flow")}, 10.0)
    assert not c["passed"] and "only 2 of 4" in c["why_not"]                    # too little known: not shown, and not scored 0


def test_rich_price_and_unknown_size_are_kept_out_with_a_reason():
    assert "expensive" in sc.fund_check(dict(GOOD, peg=4.0), 10.0)["why_not"]
    assert sc.fund_check({k: v for k, v in GOOD.items() if k != "market_cap"}, 10.0)["why_not"] == "size unknown"
    assert "outside" in sc.fund_check(dict(GOOD, market_cap=90e9), 10.0)["why_not"]


def test_arrows_and_baseline():
    assert [sc.arrow(5, 4, .1), sc.arrow(3, 4, .1), sc.arrow(4.05, 4, .1), sc.arrow(4, None, .1)] == ["▲", "▼", "▶", "·"]
    snaps = [{"t": (NOW - timedelta(minutes=m)).isoformat(), "v": {"A": {"rsi": m}}} for m in (130, 70, 20)]
    assert sc.baseline(snaps, NOW)["A"]["rsi"] == 70                           # newest one at least ~an hour old
    assert sc.baseline(snaps[-1:], NOW) == {}                                  # nothing old enough yet: no arrows, not guesses


class Store:
    def __init__(self): self.d = {}
    def get_setting(self, k, default=None): return self.d.get(k, default)
    def set_setting(self, k, v): self.d[k] = v


def bars(n=300, drift=0.001, last_jump=0.0, vol=2_000_000, price=20.0):
    idx = pd.bdate_range(end="2026-11-10", periods=n)
    close = price * np.cumprod(1 + np.full(n, drift) + np.sin(np.arange(n)) * 0.01)
    close[-1] = close[-2] * (1 + last_jump)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * .99, "Close": close, "Volume": np.full(n, float(vol))}, index=idx)


class Provider:
    def __init__(self, funds, hist): self.funds, self.hist, self.calls = funds, hist, []
    def bulk_history(self, tickers, period="2y"): return {t: self.hist[t] for t in tickers if t in self.hist}
    def fundamentals(self, t):
        self.calls.append(t)
        if t not in self.funds: raise RuntimeError("blocked")
        return self.funds[t]


def test_run_shows_only_qualified_flags_movement_and_never_invents_missing_data(monkeypatch):
    monkeypatch.setattr(sc, "levels_of", lambda h, n: {"support": 18.5, "resistance": None})
    hist = {"GOOD": bars(last_jump=0.12, vol=3_000_000), "QUIET": bars(), "WEAK": bars(), "THIN": bars(vol=100), "PENNY": bars(price=0.5),
            "BLOCK": bars(), "NOHIST": bars(n=20)}
    funds = {"GOOD": GOOD, "QUIET": GOOD, "WEAK": dict(GOOD, revenue_growth=-0.2, earnings_growth=-0.5, profit_margin=-.1)}
    store, p = Store(), Provider(funds, hist)
    res = sc.run(p, list(hist), store, NOW)
    assert {r["ticker"] for r in res["rows"]} == {"GOOD", "QUIET"}
    assert res["rows"][0]["ticker"] == "GOOD" and res["rows"][0]["moving"] == "Moving up" and res["rows"][1]["moving"] == "Quiet"
    assert res["dropped"] == {"no prices": 1, "thin trading or under $1": 2}
    assert res["fundamentals_missing"] == 1 and res["first_hour_no_arrows"] and res["rows"][0]["rsi_arrow"] == "·"
    assert "BLOCK" in p.calls and "THIN" not in p.calls                          # untradable names cost no fundamentals request
    table = sc.shortlist_rows(res)
    assert table[0][0] == "Ticker" and table[1][0] == "GOOD" and "unknown" in table[1]       # missing resistance is unknown, not 0
    assert "0.00" not in table[1][14]


def test_second_hour_gets_arrows_cache_is_reused_and_log_shows_entries_and_exits(monkeypatch):
    monkeypatch.setattr(sc, "levels_of", lambda h, n: {"support": None, "resistance": None})
    hist = {"AAA": bars(), "BBB": bars()}
    store, p = Store(), Provider({"AAA": GOOD, "BBB": GOOD}, hist)
    sc.run(p, ["AAA", "BBB"], store, NOW)
    assert sorted(p.calls) == ["AAA", "BBB"]
    p.funds["BBB"] = dict(GOOD, revenue_growth=-0.3)
    store.d["smallcap_fund"] = store.d["smallcap_fund"].replace(NOW.isoformat(), (NOW - timedelta(days=8)).isoformat())   # BBB goes stale
    res = sc.run(p, ["AAA", "BBB"], store, NOW + timedelta(minutes=65))
    assert not res["first_hour_no_arrows"] and res["rows"][0]["rsi_arrow"] in "▲▼▶"
    assert [(r["ticker"], r["event"]) for r in res["log"]] == [("BBB", "Left the shortlist")]
    calls_before = len(p.calls)
    sc.run(p, ["AAA", "BBB"], store, NOW + timedelta(minutes=130))
    assert len(p.calls) == calls_before                                          # fundamentals are kept for days, not re-read hourly


def test_failed_fundamentals_keep_the_old_numbers_and_retry_later():
    cache = {"AAA": {"t": (NOW - timedelta(days=9)).isoformat(), "f": GOOD}}
    p = Provider({}, {})
    sc.refresh_fundamentals(p, ["AAA"], cache, NOW)
    assert cache["AAA"]["f"] == GOOD and cache["AAA"]["err"]
    p.calls.clear()
    sc.refresh_fundamentals(p, ["AAA"], cache, NOW + timedelta(minutes=10))
    assert p.calls == []                                                          # not hammered every run
    sc.refresh_fundamentals(p, ["AAA"], cache, NOW + timedelta(minutes=70))
    assert p.calls == ["AAA"]


def test_csv_output(tmp_path):
    res = {"rows": [], "log": [{"time": "10 Nov 18:00", "ticker": "AAA", "event": "Entered the shortlist"}]}
    paths = sc.write_csv(res, tmp_path)
    assert [p.name for p in paths] == ["shortlist.csv", "log.csv"] and "Entered" in paths[1].read_text()


def _rows(n, start=0):
    return {"data": [{"s": f"NASDAQ:T{i}", "d": [f"T{i}", 5e8, 10.0, 1e6]} for i in range(start, start + n)]}


def test_screener_asks_for_stocks_in_the_size_bands_and_the_list_rebuilds_weekly_and_survives_a_failure():
    pl = sc.screener_payload()
    sizes = [f for f in pl["filter"] if f["left"] == "market_cap_basic"][0]["right"]
    assert sizes == [50e6, 10e9] and pl["markets"] == ["america"]
    store, calls = Store(), []

    def good(payload): calls.append(1); return _rows(30)
    t, note = sc.universe(store, NOW, good)
    assert len(t) == 30 and "new list" in note and calls == [1]
    t, note = sc.universe(store, NOW + timedelta(days=3), good)               # fresh enough: no new request
    assert "list from" in note and calls == [1]

    def bad(payload): raise OSError("blocked")
    t, note = sc.universe(store, NOW + timedelta(days=8), bad)                # stale and the screener is down: keep the old list
    assert len(t) == 30 and "kept the list" in note
    try:
        sc.universe(Store(), NOW, bad)
        assert False
    except RuntimeError as e:
        assert "--universe" in str(e)
    try:
        sc.fetch_universe(lambda p: _rows(5))                                 # a near-empty answer is a failure, not a list
        assert False
    except ValueError:
        pass


def test_sheet_queue_is_saved_before_event_baseline_advances(monkeypatch):
    monkeypatch.setattr(sc, "levels_of", lambda h, n: {"support": None, "resistance": None})
    store = Store()
    p = Provider({"AAA": GOOD, "BBB": GOOD}, {"AAA": bars(), "BBB": bars()})
    sc.run(p, ["AAA"], store, NOW)
    saved = []

    def queue(result):
        import json
        assert json.loads(store.get_setting("smallcap_list")) == ["AAA"]
        saved.extend(result["log"])
        raise OSError("disk full")

    import pytest
    with pytest.raises(OSError):
        sc.run(p, ["AAA", "BBB"], store, NOW + timedelta(hours=1), on_result=queue)
    assert [(r["ticker"], r["event"]) for r in saved] == [("BBB", "Entered the shortlist")]
    assert store.get_setting("smallcap_list") == '["AAA"]'


def test_fundamental_refresh_never_exceeds_40_and_next_run_covers_the_rest():
    tickers = [f"T{i}" for i in range(55)]
    provider, cache = Provider({t: GOOD for t in tickers}, {}), {}
    assert sc.refresh_fundamentals(provider, tickers, cache, NOW) == 40
    assert len(provider.calls) == 40
    assert sc.refresh_fundamentals(provider, tickers, cache, NOW + timedelta(hours=1)) == 15
    assert len(set(provider.calls)) == 55


def test_levels_come_from_the_real_level_finder_not_a_missing_module():
    rng = np.random.default_rng(3)
    n = 500
    idx = pd.bdate_range(end="2026-11-10", periods=n)
    c = 20 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, n)))
    h = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * .99, "Close": c, "Volume": np.full(n, 2e6)}, index=idx)
    lv = sc.levels_of(h, datetime(2026, 11, 10, 22, 0, tzinfo=timezone.utc))
    assert lv["support"] is not None and lv["support"] > 0


def test_volume_so_far_is_compared_with_a_normal_morning():
    open_now = datetime(2026, 11, 10, 16, 0, tzinfo=timezone.utc)            # 11:00 New York: 90 of the 390 session minutes
    assert abs(sc.session_fraction("2026-11-10", open_now) - 90 / 390) < 1e-9
    assert sc.session_fraction("2026-11-09", open_now) == 1.0                  # an old bar is a whole day
    assert sc.session_fraction("2026-11-10", datetime(2026, 11, 10, 23, 0, tzinfo=timezone.utc)) == 1.0     # after the close
    h = bars(vol=1_000_000)
    h.iloc[-1, h.columns.get_loc("Volume")] = 1_000_000 * 90 / 390
    assert abs(sc.tech_values(h, open_now)["relvol"] - 1.0) < 0.05             # a normal morning reads as normal
    assert sc.tech_values(h)["relvol"] < 0.3                                  # without the clock it would look dead
