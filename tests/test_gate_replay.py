import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import gate_replay as g  # noqa: E402


def day(closes):
    idx = pd.DatetimeIndex([pd.Timestamp("2026-11-06 09:30", tz="America/New_York") + pd.Timedelta(minutes=5 * i) for i in range(len(closes))])
    c = np.array(closes, float)
    return pd.DataFrame({"Open": c, "High": c + 0.1, "Low": c - 0.1, "Close": c, "Volume": 1000.0}, index=idx)


def test_a_spike_that_fades_is_skipped_by_hold_and_stopped_when_bought_now():
    closes = [99, 99.5, 100, 100, 100] + [99.2, 98.8, 98.4] + [98.0] * 70
    r = g.run_one(day(closes), pd.Timestamp("2026-11-06 09:45", tz="America/New_York"), 100.0)
    assert r["NOW"]["in"] and r["NOW"]["pct"] < 0 and r["NOW"]["why"] == "stop"
    assert r["HOLD"] == {"in": False, "why": "broke under the level"}


def test_too_little_data_is_reported_not_scored():
    assert "err" in g.run_one(day([100] * 10), pd.Timestamp("2026-11-06 09:45", tz="America/New_York"), 100.0)
