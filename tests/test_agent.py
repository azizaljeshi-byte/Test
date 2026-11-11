"""The AI agent (stockwatch/agent.py) and how New call takes its orders. No network: the API caller is faked."""
import json
from datetime import datetime, timedelta

import pytest

from stockwatch import agent, paper, paper_newcall, quick
from stockwatch.data import NY


@pytest.fixture(autouse=True)
def _agent_log_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKWATCH_AGENT_LOG_DIR", str(tmp_path / "agent_log"))


class FakeStore:
    def __init__(self):
        self.d = {}

    def get_setting(self, k, default=None):
        return self.d.get(k, default)

    def set_setting(self, k, v):
        self.d[k] = v


NOW = datetime(2026, 10, 27, 11, 0, tzinfo=NY)
NONE_HELD = {"quick": set(), "newcall": set()}


def ins(**kw):
    base = {"account": "quick", "ticker": "AAA", "action": "BUY_L1", "state": "turning", "reason": "higher low on volume", "confidence": 4}
    base.update(kw)
    return base


def test_mode_defaults(monkeypatch):
    monkeypatch.delenv("STOCKWATCH_AGENT_MODE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert agent.mode() == "off" and not agent.active()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert agent.mode() == "shadow" and agent.active()
    monkeypatch.setenv("STOCKWATCH_AGENT_MODE", "drive")
    assert agent.mode() == "drive"


def test_vet_rules():
    held = {"quick": {"HHH"}, "newcall": set()}
    known = {"AAA", "HHH"}
    assert agent.vet(ins(), held, known)[0]["ticker"] == "AAA"
    assert agent.vet(ins(state="falling"), held, known)[0] is None
    assert agent.vet(ins(state="basing"), held, known)[0] is None
    assert agent.vet(ins(confidence=2), held, known)[0] is None
    assert agent.vet(ins(ticker="ZZZ"), held, known)[0] is None
    assert agent.vet(ins(ticker="HHH"), held, known)[0] is None
    assert agent.vet(ins(action="BUY_L2", state="turning", ticker="HHH"), held, known)[0] is None
    assert agent.vet(ins(action="BUY_L2", state="riding", ticker="HHH"), held, known)[0] is not None
    assert agent.vet(ins(action="BUY_L2", state="riding"), held, known)[0] is None
    assert agent.vet(ins(action="SELL", state="falling", ticker="HHH"), held, known)[0] is not None
    assert agent.vet(ins(action="SELL"), held, known)[0] is None
    assert agent.vet(ins(reason=""), held, known)[0] is None


def test_parse():
    assert agent.parse('text {"a": 1} tail') == {"a": 1}
    with pytest.raises(agent.AgentError):
        agent.parse("no json")


def test_orders_wait_for_watch_time_and_only_in_drive(monkeypatch):
    st = FakeStore()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("STOCKWATCH_AGENT_MODE", "drive")
    agent.apply_answer(st, NOW - timedelta(minutes=5), {"instructions": [ins(action="WAIT", state="basing")]}, NONE_HELD, {"AAA"}, "review")
    agent.apply_answer(st, NOW - timedelta(minutes=1), {"instructions": [ins()]}, NONE_HELD, {"AAA"}, "review")
    assert agent.orders_for(st, "quick", NOW) == []
    agent.apply_answer(st, NOW + timedelta(minutes=14), {"instructions": [ins()]}, NONE_HELD, {"AAA"}, "review")
    got = agent.orders_for(st, "quick", NOW + timedelta(minutes=15))
    assert [o["ticker"] for o in got] == ["AAA"]
    assert agent.orders_for(st, "quick", NOW + timedelta(minutes=40)) == []
    monkeypatch.setenv("STOCKWATCH_AGENT_MODE", "shadow")
    assert agent.orders_for(st, "quick", NOW + timedelta(minutes=15)) is None


def test_shadow_orders_never_reach_accounts(monkeypatch):
    st = FakeStore()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("STOCKWATCH_AGENT_MODE", "shadow")
    agent.apply_answer(st, NOW - timedelta(minutes=40), {"instructions": [ins(action="WAIT", state="basing")]}, NONE_HELD, {"AAA"}, "review")
    agent.apply_answer(st, NOW, {"instructions": [ins()]}, NONE_HELD, {"AAA"}, "review")
    monkeypatch.setenv("STOCKWATCH_AGENT_MODE", "drive")
    assert agent.orders_for(st, "quick", NOW) == []


def test_failed_caller_never_raises(monkeypatch):
    st = FakeStore()
    snap = {"ticker": "AAA", "price": 10, "payload": {}}
    monkeypatch.setattr(agent, "_live_inputs", lambda store, now, desk=False: ({"AAA": snap}, {"AAA": 10.0}, {}))
    monkeypatch.setattr(agent, "_accounts_view", lambda store, prices, now: (NONE_HELD, {}))
    monkeypatch.setattr(agent, "shortlist", lambda *a, **k: ["AAA"])
    monkeypatch.setattr(agent, "pack", lambda *a, **k: {"t": "AAA"})
    monkeypatch.setattr(agent, "market_pack", lambda *a, **k: {})

    def boom(s, u):
        raise agent.AgentError("down")
    res = agent.review(st, NOW, caller=boom)
    assert res["ok"] is False and "agent error" in res["note"]
    answer = json.dumps({"market": {"call": "mixed", "note": "n"}, "instructions": [ins(action="WAIT", state="basing")]})
    good = agent.review(st, NOW, caller=lambda s, u: (answer, {"input_tokens": 5, "output_tokens": 5}))
    assert good["ok"] and good["accepted"] == 1


def nc_snap(line=92.0, band=91.0, change=0.005, atr=2.0):
    oc = {"known": True, "call": "BUY", "why": "t", "exit_line": line, "band_line": band, "risk": {"grade": "Moderate"}}
    return {"ticker": "AAA", "payload": {"technical": {"one_call": oc, "atr": atr, "vol_avg20": 1_000_000.0},
                                         "quote": {"live_change": change, "live_volume": 1_000_000.0}}}


def order(action="BUY_L1", state="turning"):
    return {"id": "o1", "ticker": "AAA", "action": action, "state": state, "reason": "turn", "confidence": 4}


def run(book, price, when, orders, **kw):
    res = {}
    did = paper_newcall.step(book, {"AAA": nc_snap(**kw)}, {"AAA": price}, when, orders=orders, results=res)
    return did, res


def test_newcall_without_order_buys_nothing():
    book = paper.Book()
    did, _ = run(book, 100.0, NOW, [])
    assert did == [] and not book.positions


def test_newcall_level1_is_half_then_level2_adds():
    book = paper.Book()
    _, res = run(book, 100.0, NOW, [order()])
    assert res["o1"][0] == "done" and book.positions["AAA"]["shares"] == 62
    _, res2 = run(book, 100.6, NOW + timedelta(minutes=20), [order("BUY_L2", "riding")])
    assert res2["o1"][0] == "done" and book.positions["AAA"]["shares"] > 62 and book.trades[0]["levels"] == 2


def test_newcall_level2_refused_when_not_above_entry():
    book = paper.Book()
    run(book, 100.0, NOW, [order()])
    _, res2 = run(book, 99.5, NOW + timedelta(minutes=20), [order("BUY_L2", "riding")])
    assert res2["o1"][0] == "rejected"


def test_newcall_hard_rules_still_apply():
    book = paper.Book()
    _, res = run(book, 100.0, NOW.replace(hour=9, minute=33), [order()])
    assert res["o1"][0] == "rejected" and not book.positions
    _, res = run(book, 100.0, NOW, [order()], change=-0.02)
    assert res["o1"][0] == "rejected" and not book.positions


def test_newcall_agent_sell():
    book = paper.Book()
    run(book, 100.0, NOW, [order()])
    _, res2 = run(book, 100.5, NOW + timedelta(minutes=30), [order("SELL", "falling")])
    assert res2["o1"][0] == "done" and "AAA" not in book.positions


def test_flying_helper():
    assert quick.is_flying(103.0, 100.0, 103.0, 2.0)
    assert not quick.is_flying(103.0, 100.0, 106.0, 2.0)
    assert not quick.is_flying(100.5, 100.0, 100.5, 2.0)


# ---- intraday features: opening range, VWAP, volume against the clock
def _bars(days, vol=100_000.0, drift=0.0):
    import numpy as np
    import pandas as pd
    idx = []
    for d in days:
        idx += list(pd.date_range(f"{d} 09:30", f"{d} 15:55", freq="5min", tz="America/New_York"))
    idx = pd.DatetimeIndex(idx)
    c = 100 + np.arange(len(idx)) * drift
    return pd.DataFrame({"Open": c, "High": c + 0.2, "Low": c - 0.2, "Close": c, "Volume": np.full(len(idx), vol)}, index=idx)


def test_features_opening_range_vwap_and_no_lookahead():
    bars = _bars(["2026-10-27", "2026-10-28", "2026-10-29"])
    now = datetime(2026, 10, 29, 10, 2, tzinfo=NY)               # the 10:00 bar is still open
    f = agent.features_for(bars, now)
    assert f["opening_range"]["frozen"] and f["opening_range"]["high"] == 100.2 and f["opening_range"]["low"] == 99.8
    assert f["last_bars"][-1][0] == "09:55"                       # 10:00 has not closed yet: not used
    assert f["vwap"] is not None and f["cum_volume_vs_same_time"] == 1.0
    assert f["last_bars"][-1][7] == 1.0                           # this bar against the same slot on earlier days
    early = agent.features_for(bars, datetime(2026, 10, 29, 9, 41, tzinfo=NY))
    assert early["opening_range"] is None                         # not frozen before 09:45: nothing opening-range may be traded


def test_features_vwap_cross_count_and_volume_ratio():
    bars = _bars(["2026-10-28", "2026-10-29"], drift=0.0)
    day = bars.index.strftime("%Y-%m-%d") == "2026-10-29"
    bars.loc[day, "Volume"] = 300_000.0
    f = agent.features_for(bars, datetime(2026, 10, 29, 11, 0, tzinfo=NY))
    assert f["cum_volume_vs_same_time"] == 3.0 and f["vwap_crossings_last_12"] == 0


def test_features_unknown_without_bars_or_download():
    assert agent.features_for(None, NOW) is None
    assert agent.intraday_features(["AAA"], NOW, fetch=lambda names: (_ for _ in ()).throw(RuntimeError("down"))) == {}
    assert agent.intraday_features([], NOW) == {}


def test_review_sends_intraday_block(monkeypatch):
    st = FakeStore()
    snap = {"ticker": "AAA", "price": 10, "payload": {}}
    monkeypatch.setattr(agent, "_live_inputs", lambda store, now, desk=False: ({"AAA": snap}, {"AAA": 10.0}, {}))
    monkeypatch.setattr(agent, "_accounts_view", lambda store, prices, now: (NONE_HELD, {}))
    monkeypatch.setattr(agent, "shortlist", lambda *a, **k: ["AAA"])
    monkeypatch.setattr(agent, "pack", lambda *a, **k: {"ticker": "AAA"})
    monkeypatch.setattr(agent, "market_pack", lambda *a, **k: {})
    bars = _bars(["2026-10-26", "2026-10-27"])
    seen = {}

    def caller(s, u):
        seen["u"] = json.loads(u)
        return json.dumps({"market": {"call": "mixed", "note": "n"}, "instructions": []}), {}
    import pandas as pd
    fetch = lambda names: pd.concat({"AAA": _bars(["2026-10-26", "2026-10-27"])}, axis=1)      # noqa: E731
    agent.review(st, datetime(2026, 10, 27, 11, 0, tzinfo=NY), caller=caller, fetch=fetch)
    assert seen["u"]["stocks"][0]["intraday"]["opening_range"]["frozen"] is True
    agent.review(st, datetime(2026, 10, 27, 11, 0, tzinfo=NY), caller=caller, fetch=lambda n: (_ for _ in ()).throw(RuntimeError("x")))
    assert "intraday" not in seen["u"]["stocks"][0]                # a failed download: the block is simply absent
    assert bars is not None


# ---- pacing and spending
def test_review_pacing_five_minutes_early_fifteen_later(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("STOCKWATCH_AGENT_MODE", "shadow")
    st = FakeStore()
    early = datetime(2026, 10, 27, 10, 0, tzinfo=NY)             # 30 minutes in
    st.set_setting(agent.KEY_STATE, json.dumps({"last_run": (early - timedelta(seconds=240)).isoformat()}))
    assert agent.due(st, early) == ""                              # 4 minutes ago: not yet
    st.set_setting(agent.KEY_STATE, json.dumps({"last_run": (early - timedelta(seconds=300)).isoformat()}))
    assert agent.due(st, early) == "review"
    late = datetime(2026, 10, 27, 12, 0, tzinfo=NY)              # 150 minutes in
    st.set_setting(agent.KEY_STATE, json.dumps({"last_run": (late - timedelta(seconds=600)).isoformat()}))
    assert agent.due(st, late) == ""                               # 10 minutes ago: waits for 15
    st.set_setting(agent.KEY_STATE, json.dumps({"last_run": (late - timedelta(seconds=900)).isoformat()}))
    assert agent.due(st, late) == "review"
    assert agent.due(st, datetime(2026, 10, 31, 11, 0, tzinfo=NY)) == ""      # Saturday: never
    assert agent.due(st, datetime(2026, 10, 27, 17, 0, tzinfo=NY)) == ""      # after the close: never


def test_pacing_env_and_spending_cap(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_AGENT_LATE_EVERY_S", "1800")
    assert agent.cadence() == (120, 300, 1800)
    st = FakeStore()
    monkeypatch.delenv("STOCKWATCH_AGENT_MODEL", raising=False)
    agent._add_usage(st, NOW, {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_input_tokens": 1_000_000})
    assert agent.usage_today(st, NOW)["usd"] == 3.1                  # 2.0 in + 1.0 out + 0.1 cached read
    monkeypatch.setenv("STOCKWATCH_AGENT_MAX_USD", "3")
    assert "spending cap" in agent.within_caps(st, NOW)
    monkeypatch.setenv("STOCKWATCH_AGENT_MAX_USD", "5")
    assert agent.within_caps(st, NOW) == ""
    assert agent.price_per_mtok("claude-haiku-5-5")["out"] == 0.5 and agent.price_per_mtok("claude-unknown")["in"] == 4.0


# ---- EMA 8/20, RSI(14), ADX(14) as context data
def _ohlc(closes):
    import pandas as pd
    idx = pd.date_range("2026-10-29 09:30", periods=len(closes), freq="5min", tz=NY)
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"Open": c.shift().fillna(c.iloc[0]), "High": c + 0.1, "Low": c - 0.1, "Close": c, "Volume": 1000.0})


def test_indicators_trend_up_and_down_and_chop():
    up = agent.indicator_block(_ohlc([100 + 0.2 * i for i in range(60)]))
    assert up["ema8_above_ema20"] is True and up["rsi14"] > 90 and up["adx14"] > 40 and up["ema20_slope_pct_3bars"] > 0
    down = agent.indicator_block(_ohlc([100 - 0.2 * i for i in range(60)]))
    assert down["ema8_above_ema20"] is False and down["rsi14"] < 10 and down["adx14"] > 40 and down["ema20_slope_pct_3bars"] < 0
    chop = agent.indicator_block(_ohlc([100 + (0.3 if i % 2 else -0.3) for i in range(60)]))
    assert 40 < chop["rsi14"] < 60 and chop["adx14"] < 20


def test_indicators_match_a_plain_wilder_rsi_and_are_unknown_without_enough_bars():
    closes = [100, 101, 100.5, 102, 101.5, 103, 102, 104, 103.5, 105, 104, 106, 105.5, 107, 106.5, 108, 107]
    gains = [max(b - a, 0) for a, b in zip(closes, closes[1:])]
    losses = [max(a - b, 0) for a, b in zip(closes, closes[1:])]
    ag = sum(gains[:14]) / 14
    al = sum(losses[:14]) / 14
    for g, l in zip(gains[14:], losses[14:]):
        ag, al = (ag * 13 + g) / 14, (al * 13 + l) / 14
    ref = 100 - 100 / (1 + ag / al)
    got = agent.indicator_block(_ohlc(closes))["rsi14"]
    assert abs(got - ref) < 0.2
    few = agent.indicator_block(_ohlc([100 + i for i in range(12)]))
    assert few["ema20"] is None and few["rsi14"] is None and few["adx14"] is None and few["ema8_above_ema20"] is None


def test_features_carry_indicators_without_lookahead(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_AGENT_INDICATORS", "1")
    bars = _bars(["2026-10-27", "2026-10-28", "2026-10-29"], drift=0.01)
    f = agent.features_for(bars, datetime(2026, 10, 29, 10, 2, tzinfo=NY))
    assert f["indicators"]["ema20"] is not None and f["indicators"]["adx14"] is not None
    cut = bars[bars.index <= bars.index[bars.index.strftime("%Y-%m-%d %H:%M") == "2026-10-29 09:55"][0]]
    g = agent.features_for(cut, datetime(2026, 10, 29, 10, 2, tzinfo=NY))
    assert g["indicators"] == f["indicators"]                       # later bars never change an earlier reading


def test_indicators_are_off_by_default(monkeypatch):
    monkeypatch.delenv("STOCKWATCH_AGENT_INDICATORS", raising=False)
    f = agent.features_for(_bars(["2026-10-27", "2026-10-28", "2026-10-29"], drift=0.01), datetime(2026, 10, 29, 10, 2, tzinfo=NY))
    assert "indicators" not in f and f["vwap"] is not None


def test_review_writes_a_plain_text_log_to_read_between_sessions(monkeypatch, tmp_path):
    st = FakeStore()
    snap = {"ticker": "AAA", "price": 10, "payload": {}}
    monkeypatch.setattr(agent, "_live_inputs", lambda store, now, desk=False: ({"AAA": snap}, {"AAA": 10.0}, {}))
    monkeypatch.setattr(agent, "_accounts_view", lambda store, prices, now: (NONE_HELD, {}))
    monkeypatch.setattr(agent, "shortlist", lambda *a, **k: ["AAA"])
    monkeypatch.setattr(agent, "pack", lambda *a, **k: {"ticker": "AAA"})
    monkeypatch.setattr(agent, "market_pack", lambda *a, **k: {})
    monkeypatch.setattr(agent, "intraday_features", lambda *a, **k: {})
    ans = {"market": {"call": "mixed", "note": "quiet tape"}, "instructions": []}
    usage = {"input_tokens": 1000, "output_tokens": 500}
    now = datetime(2026, 10, 27, 11, 0, tzinfo=NY)
    agent.review(st, now, caller=lambda s, u: (json.dumps(ans), usage))
    f = tmp_path / "agent_log" / "2026-10-27.txt"
    text = f.read_text(encoding="utf-8")
    assert "11:00 NY (18:00 Riyadh)" in text and "market: mixed - quiet tape" in text and "instructions: none (no clean setup)" in text
    assert "this call $0.007" in text
    agent._note_state(st, now, {"ok": False, "note": "nothing to review"})
    assert "no call: nothing to review" in f.read_text(encoding="utf-8")
