"""Quick and the New call account may trade market stocks outside the watchlist (owner, 30 Oct): the live sweep adds the
best setups of the last S&P scan and any stock with an open trade, with no alerts and no Radar card."""
import json

from stockwatch import live
from stockwatch.config import Holding, Portfolio
from stockwatch.scanner import analyse
from stockwatch.store import Store


def store_with(tmp_path, results=(), quick_open=(), nc_open=()):
    st = Store(tmp_path / "t.db")
    if results:
        st.conn.execute("INSERT INTO market_scans (scanned_at, payload) VALUES ('2026-10-30T10:00:00', ?)",
                        (json.dumps({"results": [{"ticker": t, "verdict": v} for t, v in results]}),))
        st.conn.commit()
    if quick_open:
        st.set_setting("quick_book", json.dumps({"positions": {t: {} for t in quick_open}}))
    if nc_open:
        st.set_setting("paper_newcall_book", json.dumps({"positions": {t: {} for t in nc_open}}))
    return st


def test_extras_are_the_scan_setups_not_already_held(tmp_path):
    st = store_with(tmp_path, [("AAA", "BUY SETUP"), ("HELD", "WATCH"), ("BBB", "WATCH"), ("CCC", "AVOID"), ("DDD", "WATCH")])
    assert live.wide_extras(st, {"HELD"}, limit=2) == ["AAA", "BBB"]
    assert live.wide_extras(st, {"HELD"}, limit=0) == []


def test_open_trades_are_always_tracked_even_past_the_limit(tmp_path):
    st = store_with(tmp_path, [("AAA", "BUY SETUP"), ("BBB", "WATCH")], quick_open=["QQ"], nc_open=["NN", "QQ"])
    assert live.wide_extras(st, set(), limit=1) == ["QQ", "NN", "AAA"]
    assert live.wide_extras(st, {"QQ"}, limit=0) == []             # switched off: nothing added


def test_no_scan_yet_means_no_extras(tmp_path):
    assert live.wide_extras(store_with(tmp_path), set(), limit=5) == []


def test_extras_are_swept_light_and_raise_no_alerts(tmp_path, monkeypatch):
    from stockwatch import data
    from stockwatch.config import TierRules
    TR = TierRules(0.5, 0.5, 8.0, 2.0, 10.0)
    st = Store(tmp_path / "t.db")
    base = Portfolio(holdings=[Holding("AAPL", 1, 0)], tiers={1: TR, 2: TR})
    wide = Portfolio(holdings=base.holdings + [Holding("MSFT", 2, 0)], tiers=base.tiers, extras=frozenset({"MSFT"}))
    evals, alerts = analyse(wide, data.get_provider("demo"), st)
    assert {e.ticker for e in evals} == {"AAPL", "MSFT"}
    assert not [a for a in alerts if a[0] == "MSFT"]
    assert st.snapshot("MSFT") is not None                        # saved, so Quick and the New call account can read it


def test_a_sweep_reads_positions_first_then_watchlist_then_market_extras():
    from types import SimpleNamespace
    from stockwatch import engine
    from stockwatch.config import TierRules
    TR = TierRules(0.5, 0.5, 8.0, 2.0, 10.0)
    seen = []

    def fake(h, portfolio, provider, light=False):
        seen.append(h.ticker)
        return SimpleNamespace(ticker=h.ticker, error="skip", watchlist=True)

    pf = Portfolio(holdings=[Holding("W1", 2, 0), Holding("H1", 1, 5), Holding("X1", 2, 0), Holding("W2", 2, 0), Holding("H2", 2, 3)],
                   tiers={1: TR, 2: TR}, extras=frozenset({"X1"}))
    orig, engine.evaluate = engine.evaluate, fake
    try:
        out = [e.ticker for e in engine.scan(pf, None, workers=1)]
    finally:
        engine.evaluate = orig
    assert seen == ["H1", "H2", "W1", "W2", "X1"]
    assert out == ["W1", "H1", "X1", "W2", "H2"]               # results keep the order of the list


def _funnel_moves(st, moves, minutes_ago=1):
    from datetime import datetime, timedelta
    from stockwatch import funnel
    from stockwatch.data import NY
    at = (datetime.now(NY) - timedelta(minutes=minutes_ago)).isoformat()
    st.set_setting(funnel.KEY_MOVES, json.dumps({"at": at, "moves": moves}))


def test_whole_sp500_feeds_in_turn_one_call_buys_then_risers_then_scan_setups(tmp_path):
    st = store_with(tmp_path, [("SCAN1", "WATCH"), ("SCAN2", "WATCH")], quick_open=["OPEN"])
    st.set_setting(live.BUYS_KEY, json.dumps({"at": "x", "buys": ["B1", "B2", "B3"]}))
    _funnel_moves(st, {"R1": [4.0, 10], "R2": [2.5, 10], "DOWN": [-3.0, 10], "HELD": [9.0, 10]})
    got = live.wide_extras(st, {"HELD"}, limit=6)
    assert got == ["OPEN", "B1", "R1", "SCAN1", "B2", "R2", "SCAN2"][:7]       # open trade first, then one from each list in turn
    assert "DOWN" not in got and "HELD" not in got
    assert len(live.wide_extras(st, set(), limit=2)) == 1 + 2                   # the ceiling counts new stocks only


def test_stale_risers_are_ignored_and_a_stock_is_added_once(tmp_path):
    st = store_with(tmp_path, [("B1", "WATCH")])
    st.set_setting(live.BUYS_KEY, json.dumps({"at": "x", "buys": ["B1"]}))
    _funnel_moves(st, {"OLD": [8.0, 10]}, minutes_ago=60)
    assert live.wide_extras(st, set(), limit=10) == ["B1"]


def test_whole_sp500_one_call_pass_lists_only_known_buys(monkeypatch):
    import pandas as pd
    from stockwatch import market, onecall
    calls = {"AAA": {"known": True, "call": "BUY", "distance_swings": 1.2, "exit_line": 9.0},
             "BBB": {"known": True, "call": "BUY", "distance_swings": 0.4, "exit_line": 8.0},
             "CCC": {"known": True, "call": "WAIT", "distance_swings": 3, "exit_line": 7.0},
             "DDD": {"known": False, "call": "UNKNOWN"}}
    monkeypatch.setattr(onecall, "assess", lambda h, now=None, **k: calls[h.attrs["t"]])
    hs = {}
    for t in list(calls) + ["SHORT"]:
        df = pd.DataFrame({"Close": [1.0] * (10 if t == "SHORT" else 200)})
        df.attrs["t"] = t
        hs[t] = df
    assert [b["ticker"] for b in market.one_call_buys(hs)] == ["BBB", "AAA"]     # closest to the exit line first; short and unknown skipped


def test_the_scan_saves_the_one_call_buys_for_the_live_sweep(tmp_path, monkeypatch):
    from stockwatch import market
    st = Store(tmp_path / "t.db")
    monkeypatch.setattr(live, "current_portfolio", lambda store, wide=False: Portfolio(holdings=[], tiers={}))
    monkeypatch.setattr(market, "run", lambda *a, **k: {"results": [], "stats": None, "buys": [{"ticker": "ZZZ"}, {"ticker": "YYY"}]})
    live.market_scan(None, st)
    assert json.loads(st.get_setting(live.BUYS_KEY))["buys"] == ["ZZZ", "YYY"]
    assert live.wide_extras(st, set(), limit=5) == ["ZZZ", "YYY"]
