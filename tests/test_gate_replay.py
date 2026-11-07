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


def test_exit_study_runs_and_the_pace_limit_keeps_three_in_ten_minutes(capsys):
    closes = [99, 99.5, 100, 100.2, 100.4, 100.9, 101.5] + [100.0] * 71
    f = day(closes)
    trades = [{"ticker": f"T{i}", "opened": "2026-11-06 09:42", "entry": 100.0, "status": "CLOSED", "result": -10.0} for i in range(5)]
    g.exit_study(trades, {"ranked": []}, {f"T{i}": f for i in range(5)}, ["2026-11-06"])
    out = capsys.readouterr().out
    rows = [ln for ln in out.splitlines() if ln.startswith("  B stop")]
    assert any(" 5 " in ln for ln in rows if "none" in ln) and any(" 3 " in ln for ln in rows if "3 per 10m" in ln)
