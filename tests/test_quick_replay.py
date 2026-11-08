import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import quick_replay as qr  # noqa: E402


def frame(day, prev, price0, drift):
    idx = pd.date_range(f"{day} 09:30", periods=78, freq="5min", tz="America/New_York")
    c = price0 + drift * np.arange(78) + np.sin(np.arange(78) / 3) * 0.4
    return pd.DataFrame({"Open": c - 0.05, "High": c + 0.3, "Low": c - 0.3, "Close": c, "Volume": 200_000.0}, index=idx)


def test_bar_prices_walk_open_low_high_close():
    p = qr.bar_prices(100, 102, 99, 101)
    assert len(p) == qr.PER_BAR and p[0] == 100 and p[-1] == 101 and min(p) == 99 and max(p) == 102


def test_the_replay_runs_the_real_engine_on_a_day_and_reports_both_rule_sets():
    f = pd.concat([frame("2026-11-05", 0, 100, 0.0), frame("2026-11-06", 0, 100, 0.03)])
    data = qr.prepare({"AAA": f, "SPY": f}, "2026-11-06")
    assert list(data) == ["AAA"] and data["AAA"]["atr"] > 0
    book = qr.replay(data, "2026-11-06")
    assert isinstance(book["trades"], list)
    text = "\n".join(qr.report("x", book))
    assert "trades" in text and "not entered" in text
