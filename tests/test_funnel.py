from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from stockwatch import funnel
from stockwatch.data import NY

NOW = datetime(2026, 10, 30, 11, 0, tzinfo=NY)


def frame(change, last=NOW, prev_close=100.0):
    y = pd.date_range("2026-10-29 09:30", "2026-10-29 15:55", freq="5min", tz=NY)
    t = pd.date_range("2026-10-30 09:30", last.replace(tzinfo=None), freq="5min", tz=NY)
    close = np.r_[np.full(len(y), prev_close), np.full(len(t), prev_close * (1 + change))]
    return pd.DataFrame({"Close": close}, index=y.append(t))


def labels(n_up, n_down, sector, industry="Ind"):
    return {f"{sector}{i}": [sector, industry] for i in range(n_up + n_down)}


def test_changes_skips_stale_and_missing_never_zero():
    frames = {"A": frame(0.02), "STALE": frame(0.02, last=NOW - timedelta(minutes=40)), "EMPTY": frame(0.0).iloc[0:0]}
    ch = funnel.changes(frames, NOW)
    assert set(ch) == {"A"} and abs(ch["A"] - 0.02) < 1e-9


def test_sector_and_industry_levels_and_small_groups_are_unknown():
    lab = {**{f"E{i}": ["Energy", "Oil"] for i in range(5)}, **{f"T{i}": ["Tech", "Chips"] for i in range(5)},
           "S1": ["Small", "Tiny"], "S2": ["Small", "Tiny"]}
    ch = {**{f"E{i}": 0.01 for i in range(5)}, **{f"T{i}": -0.03 for i in range(5)}, "S1": 0.02, "S2": 0.02}
    st = funnel.summarize(ch, lab, NOW)
    assert st["sectors"]["Energy"]["healthy"] is True and st["sectors"]["Tech"]["healthy"] is False
    assert st["sectors"]["Small"]["healthy"] is None
    assert st["industries"]["Energy|Oil"]["healthy"] is True
    assert funnel.verdict("E1", st, NOW).startswith("PASS: Energy")
    assert funnel.verdict("T1", st, NOW).startswith("WOULD BLOCK at sector level: Tech")
    assert funnel.verdict("S1", st, NOW).startswith("no read")
    assert funnel.verdict("UNKNOWN", st, NOW) is None


def test_industry_block_inside_a_healthy_sector():
    lab = {f"F{i}": ["Fin", "Banks" if i < 5 else "Insurance"] for i in range(10)}
    ch = {**{f"F{i}": 0.02 for i in range(5)}, **{f"F{i}": -0.02 for i in range(5, 9)}, "F9": 0.001}
    st = funnel.summarize(ch, lab, NOW)
    assert st["sectors"]["Fin"]["healthy"] is True
    assert funnel.verdict("F7", st, NOW).startswith("WOULD BLOCK at industry level")
    assert funnel.verdict("F1", st, NOW).startswith("PASS")


def test_market_crash_stop_and_old_picture_not_used():
    lab = labels(0, 120, "Tech")
    st = funnel.summarize({t: -0.02 for t in lab}, lab, NOW)
    assert st["market"]["crash"] is True
    assert funnel.verdict("Tech1", st, NOW).startswith("WOULD BLOCK at market level")
    assert funnel.verdict("Tech1", st, NOW + timedelta(minutes=funnel.STATE_MAX_AGE_MIN + 1)) is None


def test_trend_against_an_hour_ago():
    lab = labels(6, 0, "Mat")
    first = funnel.summarize({t: -0.01 for t in lab}, lab, NOW - timedelta(minutes=60))
    second = funnel.summarize({t: 0.01 for t in lab}, lab, NOW, first["history"])
    assert second["sectors"]["Mat"]["trend"] == "improving"
    assert first["sectors"]["Mat"]["trend"] is None
    assert len(second["history"]) == 2


def test_refresh_saves_and_loads_with_fake_frames(tmp_path):
    from stockwatch.store import Store
    store = Store(tmp_path / "t.db")
    lab = labels(5, 0, "Energy")
    funnel.refresh(store, NOW, {t: frame(0.01) for t in lab}, lab)
    st = funnel.load(store)
    assert st["sectors"]["Energy"]["healthy"] is True


def test_stamp_writes_funnel_gate(tmp_path):
    from stockwatch import sectors
    from stockwatch.store import Store
    store = Store(tmp_path / "t.db")
    lab = labels(5, 0, "Energy")
    st = funnel.summarize({t: 0.01 for t in lab}, lab, datetime.now(NY))
    store.set_setting(funnel.KEY, __import__("json").dumps(st))
    trades = [{"id": 1, "ticker": "Energy1", "status": "OPEN"}]
    sectors.stamp(trades, [{"ticker": "Energy1", "action": "ENTER"}], {}, store)
    assert trades[0]["funnel_gate"].startswith("PASS: Energy")
