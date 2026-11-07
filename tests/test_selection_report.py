import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import selection_report as sr  # noqa: E402


def frame(seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.DatetimeIndex([pd.Timestamp("2026-11-06 09:30", tz="America/New_York") + pd.Timedelta(minutes=5 * i) for i in range(78)])
    c = 100 + np.cumsum(rng.normal(0, 0.15, 78))
    return pd.DataFrame({"Open": c, "High": c + 0.1, "Low": c - 0.1, "Close": c, "Volume": 1000.0}, index=idx)


def test_candidates_mark_entered_and_not_entered_and_measure_both():
    book = {"trades": [{"ticker": "AAA", "opened": "2026-11-06 10:00", "entry": 100.0, "result": -5.0, "exit_reason": "stop hit"}],
            "ranked": [{"day": "2026-11-06", "time": "10:00", "ticker": "AAA", "kind": "breakout", "grade": "A", "rank": 1, "of": 3, "taken": True, "why_not": "", "price": 100.0},
                       {"day": "2026-11-06", "time": "10:00", "ticker": "BBB", "kind": "breakout", "grade": "B", "rank": 2, "of": 3, "taken": False, "why_not": "pace: 3 in 10 min", "price": 50.0},
                       {"day": "2026-11-06", "time": "10:05", "ticker": "BBB", "kind": "breakout", "grade": "B", "rank": 2, "of": 3, "taken": False, "why_not": "pace: 3 in 10 min", "price": 50.2}],
            "skipped": [{"day": "2026-11-06", "time": "12:00", "ticker": "CCC", "kind": "bounce", "price": 20.0, "reason": "daily loss stop: down $513 today"}]}
    cs = sr.candidates(book, "2026-11-06")
    assert [(c["t"], c["entered"]) for c in cs] == [("AAA", True), ("BBB", False), ("CCC", False)]      # BBB twice with the same reason counts once
    assert cs[0]["trade"]["result"] == -5.0 and cs[1]["why"] == "pace: # in # min" and cs[2]["why"].startswith("daily loss stop")
    frames = {t: frame(i) for i, t in enumerate(("AAA", "BBB", "CCC"))}
    assert all(sr.measure(c, frames, "2026-11-06") for c in cs) and "n=  3" in sr.line("x", cs) and "n=  0" in sr.line("none", [])
