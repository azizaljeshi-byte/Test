import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pullback_test as pt  # noqa: E402


def day(closes, highs, lows, opens=None):
    n = 78
    idx = pd.DatetimeIndex([pd.Timestamp("2026-11-06 09:30", tz="America/New_York") + pd.Timedelta(minutes=5 * i) for i in range(n)])
    pad = lambda a: np.array(list(a) + [a[-1]] * (n - len(a)), float)           # noqa: E731
    c = pad(closes)
    return pd.DataFrame({"Open": pad(opens) if opens is not None else c, "High": pad(highs), "Low": pad(lows), "Close": c, "Volume": 1000.0}, index=idx)


def stx_like():
    # signal at 465 (bar 10), a drop to 452 over three bars, a bounce bar, then a climb back to 465
    closes = [470] * 10 + [465, 460, 455, 452.5, 454.5, 457, 460, 463, 465, 466]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    lows[13] = 451.5
    return day(closes, highs, lows, opens=[470] * 10 + [465.5, 465, 460, 455, 452.5, 454.8, 457, 460, 463, 465])


def test_the_pullback_entry_buys_near_the_low_with_a_tight_stop_and_reaches_the_target():
    d = stx_like()
    got, why = pt.find_entry(d, 10, 465.0, 11)
    assert why is None
    k, entry, stop, risk = got
    assert 452 < entry < 458 and stop < 452 and risk < 1.5
    pct, _, xwhy = pt.exit_struct(d, k, entry, stop, "T2")
    assert xwhy == "took the profit" and abs(pct - 2.0) < 1e-6


def test_a_stock_that_runs_away_without_a_pullback_is_not_chased():
    closes = [465] * 10 + [466, 470, 474, 476, 478, 480]
    d = day(closes, [c + 0.5 for c in closes], [c - 0.5 for c in closes])
    assert pt.find_entry(d, 10, 465.0, 11) == (None, "ran away without a pullback")


def test_a_pullback_that_keeps_falling_is_not_bought_without_a_bounce():
    closes = [465] * 10 + [460, 455, 450, 445, 440, 436, 432, 430]
    d = day(closes, [c + 0.5 for c in closes], [c - 0.5 for c in closes])
    got, why = pt.find_entry(d, 10, 465.0, 11)
    assert got is None and why in ("no bounce confirmed", "stop too far from the entry")


def test_the_whole_report_runs_on_random_days(capsys):
    rng = np.random.default_rng(3)
    days = ["2026-11-05", "2026-11-06"]

    def frame():
        parts = []
        for d in days:
            c = 100 + np.cumsum(rng.normal(0, 0.3, 78))
            idx = pd.DatetimeIndex([pd.Timestamp(f"{d} 09:30", tz="America/New_York") + pd.Timedelta(minutes=5 * i) for i in range(78)])
            parts.append(pd.DataFrame({"Open": c, "High": c + 0.2, "Low": c - 0.2, "Close": c, "Volume": 1000.0}, index=idx))
        return pd.concat(parts)

    frames = {f"S{i}": frame() for i in range(6)}
    trades = [{"ticker": f"S{i}", "opened": f"{d} 10:{10 + 5 * i}", "entry": float(frames[f"S{i}"].loc[pd.Timestamp(f"{d} 10:{10 + 5 * i}", tz="America/New_York"), "Close"]), "kind": "bounce"}
              for d in days for i in range(6)]
    pt.run({"trades": trades, "ranked": [], "skipped": []}, trades, frames, days)
    out = capsys.readouterr().out
    assert "PULLBACK TEST: 12 campaigns" in out and "Why campaigns did not enter" in out and "By day" in out
