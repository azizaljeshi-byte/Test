import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import rule_test as rt  # noqa: E402


def day(path, highs=None, lows=None):
    idx = pd.DatetimeIndex([pd.Timestamp("2026-11-06 09:30", tz="America/New_York") + pd.Timedelta(minutes=5 * i) for i in range(78)])
    c = np.array(list(path) + [path[-1]] * (78 - len(path)), float)
    h = c + 0.05 if highs is None else np.array(list(highs) + [c[-1]] * (78 - len(highs)), float)
    lo = c - 0.05 if lows is None else np.array(list(lows) + [c[-1]] * (78 - len(lows)), float)
    return pd.DataFrame({"Open": c, "High": h, "Low": lo, "Close": c, "Volume": 1000.0}, index=idx)


def test_take_profit_at_one_percent_unless_the_bar_closes_near_its_high():
    weak = day([100, 100, 100.4, 100.2], highs=[100.1, 100.1, 101.3, 100.3], lows=[99.9, 99.9, 100.0, 100.0])        # touches +1.3%, closes mid-bar: not riding
    assert rt.sim_exit(weak, 1, 100.0, "TP1_RIDE")[0] == 1.0 and rt.sim_exit(weak, 1, 100.0, "TP1")[0] == 1.0
    strong = day([100, 100, 101.3, 102.0, 102.5, 102.2], highs=[100.1, 100.1, 101.35, 102.1, 102.6, 102.3], lows=[99.9, 99.9, 100.9, 101.5, 102.0, 101.8])
    pct, k, why = rt.sim_exit(strong, 1, 100.0, "TP1_RIDE")
    assert why == "stop" and pct > 1.5 and rt.sim_exit(strong, 1, 100.0, "TP1")[0] == 1.0           # riding kept it past +1.5% before the trail was hit


def test_stop_beats_target_in_the_same_bar_and_the_hard_stop_is_one_and_a_half_percent():
    d = day([100, 100, 98.0], highs=[100.1, 100.1, 101.5], lows=[99.9, 99.9, 97.9])
    pct, _, why = rt.sim_exit(d, 1, 100.0, "TP1_RIDE")
    assert why == "stop" and -2.1 <= pct <= -1.5


def test_the_opening_cap_keeps_the_three_best_ranked_and_drops_the_rest():
    d = day([100.0] * 78)
    w = pd.Timestamp("2026-11-06 09:42", tz="America/New_York")
    evs = [{"d": "2026-11-06", "t": f"T{i}", "w": w, "p0": 100.0, "rank": 9 - i, "took": True, "day": d, "i": 2} for i in range(6)]
    got = rt.simulate(sorted(evs, key=lambda e: (e["w"], e["rank"])), "TP1", 15)
    assert sorted(r["t"] for r in got) == ["T3", "T4", "T5"]
    assert len(rt.simulate(sorted(evs, key=lambda e: (e["w"], e["rank"])), "A", None)) == 6                       # today: no limit in the first 30 minutes
