import json
from datetime import datetime

from stockwatch import testlist
from stockwatch.data import NY


class FakeStore:
    def __init__(self, snaps=None, cands=None):
        self.d = {}
        self.snaps = snaps or {}
        if cands is not None:
            self.d["candidates_log"] = json.dumps({"days": {"2026-11-04": {"rows": cands}}})

    def get_setting(self, k): return self.d.get(k)
    def set_setting(self, k, v): self.d[k] = v
    def snapshot(self, t): return self.snaps.get(t)


NOW = datetime(2026, 11, 4, 10, 5, tzinfo=NY)


def snap(atr=2.0, res_low=None, price=100.0):
    zones = {"known": True, "support": [], "resistance": [] if res_low is None else [{"low": res_low, "high": res_low + 0.2, "grade": "good", "touches": 3}]}
    return {"ticker": "X", "payload": {"technical": {"atr": atr, "zones": zones},
            "quote": {"regular_price": price, "live_price": price}}}


def row(t, call, qualified="Quick: up 3.0% = 1.2 daily ranges (breakout candidate)", price=100.0, found="2026-11-04T09:50:00-05:00", tracked="yes"):
    return {"ticker": t, "call": call, "qualified": qualified, "price": price, "found_at": found, "tracked": tracked}


def test_levels_stop_is_half_a_range_and_target_is_two_risks():
    lv, why = testlist.levels(snap(atr=2.0), 100.0)
    assert why is None and lv["stop"] == 99.0 and lv["target"] == 102.0 and lv["reward_risk"] == 2.0


def test_target_is_capped_at_resistance_or_the_stock_is_left_out():
    lv, _ = testlist.levels(snap(atr=2.0, res_low=101.4), 100.0)          # resistance about 101.5: 1.5 risks of room -> target there
    assert lv["target"] == 101.5 and lv["reward_risk"] == 1.5
    lv, why = testlist.levels(snap(atr=2.0, res_low=100.6), 100.0)        # about 0.7 risks of room
    assert lv is None and why == "no room under resistance"
    assert testlist.levels(snap(atr=None), 100.0)[0] is None


def test_pick_tiers_breakouts_only_tracked_only_and_after_0945():
    cands = {"AAA": row("AAA", "BUY"), "BBB": row("BBB", "HOLD"), "CCC": row("CCC", "EXIT"), "DDD": row("DDD", None),
             "EEE": row("EEE", "BUY", qualified="Quick: down 3% = 1 daily ranges (bounce candidate)"),
             "FFF": row("FFF", "ADD", tracked="S&P only"), "GGG": row("GGG", "BUY", found="2026-11-04T09:20:00-05:00")}
    st = FakeStore({t: snap() for t in cands}, cands)
    assert testlist.pick(st, NOW) == 2
    got = {r["ticker"]: r for r in testlist.load(st)["days"]["2026-11-04"]["rows"]}
    assert set(got) == {"AAA", "BBB"} and got["AAA"]["tier"] == 1 and got["BBB"]["tier"] == 2
    assert testlist.pick(st, NOW) == 0                                       # nothing is added twice


def test_cap_of_ten_and_six_for_tier_two():
    cands = {f"H{i}": row(f"H{i}", "HOLD", found=f"2026-11-04T09:{50 + i % 9}:00-05:00") for i in range(9)}
    cands.update({f"B{i}": row(f"B{i}", "BUY", found="2026-11-04T09:59:00-05:00") for i in range(6)})
    st = FakeStore({t: snap() for t in cands}, cands)
    testlist.pick(st, NOW)
    rows = testlist.load(st)["days"]["2026-11-04"]["rows"]
    assert len(rows) == 10 and sum(r["tier"] == 2 for r in rows) == 6 and sum(r["tier"] == 1 for r in rows) == 4


def test_follow_marks_target_stop_and_time_exit(monkeypatch):
    st = FakeStore({"AAA": snap(), "BBB": snap(), "CCC": snap()}, {t: row(t, "BUY") for t in ("AAA", "BBB", "CCC")})
    testlist.pick(st, NOW)
    prices = {"AAA": 102.5, "BBB": 98.5, "CCC": 100.4}
    monkeypatch.setattr(testlist.paper_live, "fresh_price", lambda s, now: (prices[s["_t"]], ""))
    for t in prices:
        st.snaps[t]["_t"] = t
    assert testlist.follow(st, NOW) is True
    rows = {r["ticker"]: r for r in testlist.load(st)["days"]["2026-11-04"]["rows"]}
    assert rows["AAA"]["status"] == "target" and rows["AAA"]["result_pct"] == 2.0
    assert rows["BBB"]["status"] == "stopped" and rows["BBB"]["result_pct"] == -1.0
    assert rows["CCC"]["status"] == "open" and rows["CCC"]["last"] == 100.4
    late = datetime(2026, 11, 4, 15, 51, tzinfo=NY)
    testlist.follow(st, late)
    assert {r["ticker"]: r for r in testlist.load(st)["days"]["2026-11-04"]["rows"]}["CCC"]["status"] == "time"


def test_an_old_price_changes_nothing(monkeypatch):
    st = FakeStore({"AAA": snap()}, {"AAA": row("AAA", "BUY")})
    testlist.pick(st, NOW)
    monkeypatch.setattr(testlist.paper_live, "fresh_price", lambda s, now: (None, "old"))
    assert testlist.follow(st, NOW) is False
    assert testlist.load(st)["days"]["2026-11-04"]["rows"][0]["status"] == "open"
