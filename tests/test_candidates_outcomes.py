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


def test_wide_rows_only_for_untracked_big_movers():
    import json
    st = Store()
    st.s[funnel.KEY_MOVES] = json.dumps({"at": T(10, 0).isoformat(), "moves": {"AAA": [5.0, 10.0], "BBB": [3.5, 20.0], "CCC": [1.0, 5.0], "DDD": [-4.0, 8.0]}})
    day = {"rows": {}, "scans": []}
    assert candidates.scan_wide(st, day, T(10, 1), "refresh") == 2
    assert set(day["wide"]) == {"BBB", "DDD"}
    assert candidates.scan_wide(st, day, T(10, 2), "refresh") == 0          # not added twice


def test_wide_ignores_old_funnel_read():
    import json
    st = Store()
    st.s[funnel.KEY_MOVES] = json.dumps({"at": T(9, 0).isoformat(), "moves": {"BBB": [9.0, 20.0]}})
    assert candidates.scan_wide(st, {"rows": {}, "scans": []}, T(10, 0), "refresh") == 0


def test_funnel_moves_has_change_and_price():
    import pandas as pd
    idx = pd.to_datetime(["2026-11-02 15:55", "2026-11-03 09:35", "2026-11-03 09:55"]).tz_localize(NY)
    fr = {"XYZ": pd.DataFrame({"Close": [100.0, 101.0, 104.0]}, index=idx)}
    assert funnel.moves(fr, T(10, 0))["XYZ"] == [4.0, 104.0]
