import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scenario_search as ss  # noqa: E402


def frame(seed, days=("2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06")):
    rng = np.random.default_rng(seed)
    parts = []
    for d in days:
        c = 100 + np.cumsum(rng.normal(0, 0.15, 78))
        idx = pd.DatetimeIndex([pd.Timestamp(f"{d} 09:30", tz="America/New_York") + pd.Timedelta(minutes=5 * i) for i in range(78)])
        parts.append(pd.DataFrame({"Open": c, "High": c + 0.1, "Low": c - 0.1, "Close": c, "Volume": rng.uniform(800, 1200, 78)}, index=idx))
    return pd.concat(parts)


def test_the_search_runs_end_to_end_and_reports_the_honest_walk_forward(capsys):
    frames = {f"S{i}": frame(i) for i in range(8)}
    days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    trades = [{"ticker": f"S{i}", "opened": f"{d} 10:{10 + 5 * (i % 6)}", "entry": float(frames[f"S{i}"].loc[pd.Timestamp(f"{d} 10:{10 + 5 * (i % 6)}", tz="America/New_York"), "Close"]), "kind": "breakout"}
              for d in days for i in range(8)]
    ss.run({"ranked": []}, trades, frames, days)
    out = capsys.readouterr().out
    assert "SCENARIO SEARCH: 32 setups" in out and "5. Walk-forward" in out and "ALL held-out days together" in out and "stop 1.5% target 2.0%" in out


def test_no_future_bars_leak_into_the_features():
    f = frame(1)
    when = pd.Timestamp("2026-11-06 10:00", tz="America/New_York")
    a = ss.features(f, when, 100.0)
    g = f.copy()
    g.loc[g.index >= when, ["Open", "High", "Low", "Close"]] *= 3                       # change the signal bar and everything after it
    b = ss.features(g, when, 100.0)
    assert a is not None and all(abs(a[k] - b[k]) < 1e-9 for k in ("rsi", "rsi_d", "hist_d", "vol_x", "gap"))
