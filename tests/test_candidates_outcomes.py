from datetime import datetime

from stockwatch import candidates, funnel
from stockwatch.data import NY


def T(h, m):
    return datetime(2026, 11, 3, h, m, tzinfo=NY)


def test_follow_reads_30_and_60_and_best_worst():
    r = {"found_at": T(10, 0).isoformat(), "price": 100.0}
    assert candidates._follow(r, 101.0, 100.0, T(10, 10))
    assert r["best"] == 1.0 and r.get("p30") is None
    candidates._follow(r, 99.0, 100.0, T(10, 31))
    assert r["p30"] == -1.0 and r["worst"] == -1.0
    candidates._follow(r, 103.0, 100.0, T(11, 2))
    assert r["p60"] == 3.0 and r["p30"] == -1.0 and r["best"] == 3.0


def test_late_reading_is_left_unknown():
    r = {"found_at": T(10, 0).isoformat()}
    candidates._follow(r, 105.0, 100.0, T(10, 50))          # 50 min after found: past the +30 window, before +60
    assert r.get("p30") is None and r.get("p60") is None


def test_missing_price_never_becomes_zero():
    r = {"found_at": T(10, 0).isoformat()}
    assert not candidates._follow(r, None, 100.0, T(10, 30))
    assert r.get("p30") is None and r.get("best") is None


def test_close_only_when_allowed():
    r = {"found_at": T(10, 0).isoformat()}
    candidates._follow(r, None, 100.0, T(16, 5), reg_close=102.0, closed_ok=False)
    assert r.get("close_pct") is None
    candidates._follow(r, None, 100.0, T(16, 5), reg_close=102.0, closed_ok=True)
    assert r["close_pct"] == 2.0


class Store:
    def __init__(self):
        self.s = {}

    def get_setting(self, k):
        return self.s.get(k)

    def set_setting(self, k, v):
        self.s[k] = v

    def latest_snapshots(self):
        return [{"ticker": "AAA"}]


STATS = {"BBB": {"atr": 1.0, "sector": "Energy"}, "DDD": {"atr": 1.0, "sector": "Materials"}, "CCC": {"atr": 1.0, "sector": "Utilities"},
         "AAA": {"atr": 1.0, "sector": "Tech"}, "EEE": {}}


def _universe_store(moves, at=None):
    import json
    st = Store()
    st.s[funnel.KEY_MOVES] = json.dumps({"at": (at or T(10, 0)).isoformat(), "moves": moves})
    st.s[candidates.KEY_STATS] = json.dumps({"stats": STATS})
    return st


def test_universe_adds_untracked_movers_by_the_same_rules():
    # BBB +3.5% on 20 = 0.7 daily ranges (breakout); DDD -9% on 8 = -0.8 (bounce); CCC +1% is too small
    st = _universe_store({"AAA": [5.0, 10.0], "BBB": [3.5, 20.0], "CCC": [1.0, 5.0], "DDD": [-9.0, 8.0], "EEE": [9.0, 9.0], "FFF": [9.0, 9.0]})
    day = {"rows": {}, "scans": []}
    assert candidates.scan_universe(st, day, T(10, 1), None) == 2
    assert set(day["rows"]) == {"BBB", "DDD"}                          # AAA is tracked; CCC too small; EEE has no range; FFF has no stats
    r = day["rows"]["BBB"]
    assert r["tracked"] == "S&P only" and "breakout candidate" in r["qualified"] and r["sector"] == "Energy" and r["price"] == 20.0
    assert "bounce candidate" in day["rows"]["DDD"]["qualified"]
    assert candidates.scan_universe(st, day, T(10, 2), None) == 0      # not added twice


def test_universe_keeps_the_biggest_movers_when_capped(monkeypatch):
    monkeypatch.setattr(candidates, "UNIVERSE_MAX", 1)
    st = _universe_store({"BBB": [3.5, 20.0], "DDD": [-9.0, 8.0]})
    day = {"rows": {}, "scans": []}
    candidates.scan_universe(st, day, T(10, 1), None)
    assert set(day["rows"]) == {"DDD"}


def test_universe_ignores_old_funnel_read_and_missing_stats():
    old = _universe_store({"BBB": [9.0, 20.0]}, at=T(9, 0))
    assert candidates.scan_universe(old, {"rows": {}, "scans": []}, T(10, 0), None) == 0
    nostats = _universe_store({"BBB": [9.0, 20.0]})
    nostats.s.pop(candidates.KEY_STATS)
    assert candidates.scan_universe(nostats, {"rows": {}, "scans": []}, T(10, 0), None) == 0


def test_track_follows_universe_rows_from_the_funnel():
    import json
    st = _universe_store({"BBB": [3.5, 20.0]})
    day = {"rows": {}, "scans": []}
    candidates.scan_universe(st, day, T(10, 0), None)
    st.s[candidates.KEY] = json.dumps({"days": {"2026-11-03": day}})
    st.s[funnel.KEY_MOVES] = json.dumps({"at": T(10, 31).isoformat(), "moves": {"BBB": [4.0, 20.4]}})
    assert candidates.track(st, [], T(10, 31))
    r = candidates.load(st)["days"]["2026-11-03"]["rows"]["BBB"]
    assert r["p30"] == 2.0 and r["best"] == 2.0


def test_funnel_moves_has_change_and_price():
    import pandas as pd
    idx = pd.to_datetime(["2026-11-02 15:55", "2026-11-03 09:35", "2026-11-03 09:55"]).tz_localize(NY)
    fr = {"XYZ": pd.DataFrame({"Close": [100.0, 101.0, 104.0]}, index=idx)}
    assert funnel.moves(fr, T(10, 0))["XYZ"] == [4.0, 104.0]
