import json
from datetime import datetime

import pandas as pd

from stockwatch import extended
from stockwatch.data import NY


def bars(rows):
    idx = pd.DatetimeIndex([pd.Timestamp(t, tz="America/New_York") for t, *_ in rows])
    return pd.DataFrame({"Close": [r[1] for r in rows], "High": [r[1] + 0.1 for r in rows], "Low": [r[1] - 0.1 for r in rows],
                         "Volume": [r[2] for r in rows]}, index=idx)


def day(date, close, vol=1000):
    return [(f"{date} 10:00", close, vol), (f"{date} 15:59", close, vol)]


NOW = datetime(2026, 11, 3, 7, 25, tzinfo=NY)


def test_pre_market_move_and_volume_against_a_normal_day():
    rows = day("2026-11-02", 100.0, 50_000) + [(f"2026-11-03 07:{m:02d}", 105.0, 5_000) for m in range(0, 20)]
    s = extended.stats(bars(rows), NOW, "PRE")
    assert s["ref_close"] == 100.0 and s["price"] == 105.0 and s["move"] == 5.0
    assert s["volume"] == 100_000 and s["thin"] is False
    assert round(s["pct_of_day"]) == 100                       # 100,000 shares against a 100,000-share day


def test_thin_when_little_trading_or_old_last_bar():
    thin = extended.stats(bars(day("2026-11-02", 100.0) + [("2026-11-03 07:00", 101.0, 10)]), NOW, "PRE")
    assert thin["thin"] is True and thin["why"] == "very little trading"
    old = day("2026-11-02", 100.0) + [(f"2026-11-03 05:{m:02d}", 100.0, 20_000) for m in range(0, 20)]
    assert extended.stats(bars(old), NOW, "PRE")["why"] == "last trade is old"


def test_no_prior_close_is_no_read_and_no_trades_is_thin_not_zero():
    assert extended.stats(bars([("2026-11-03 07:00", 100.0, 99999)]), NOW, "PRE") is None
    none_yet = extended.stats(bars(day("2026-11-02", 100.0)), NOW, "PRE")
    assert none_yet["move"] is None and none_yet["thin"] is True


def test_after_hours_uses_todays_close():
    rows = day("2026-11-03", 50.0, 10_000) + [(f"2026-11-03 17:{m:02d}", 45.0, 10_000) for m in range(0, 15)]
    s = extended.stats(bars(rows), datetime(2026, 11, 3, 17, 16, tzinfo=NY), "POST")
    assert s["ref_close"] == 50.0 and s["move"] == -10.0 and s["thin"] is False


class FakeStore:
    def __init__(self): self.d = {}
    def get_setting(self, k): return self.d.get(k)
    def set_setting(self, k, v): self.d[k] = v


def test_refresh_saves_state_and_ranks_by_size_of_move_only_outside_regular():
    st = FakeStore()
    pre = [(f"2026-11-03 07:{m:02d}", 105.0, 5_000) for m in range(0, 20)]
    frames = {"UP": bars(day("2026-11-02", 100.0, 50_000) + pre), "THIN": bars(day("2026-11-02", 100.0) + [("2026-11-03 07:00", 120.0, 1)])}
    state = extended.refresh(st, NOW, frames=frames)
    assert state["active"] == 1 and [t for t, _ in extended.ranked(state)] == ["UP"]
    assert json.loads(st.d[extended.KEY_LOG])[0]["top"][0]["t"] == "UP"
    assert extended.refresh(st, datetime(2026, 11, 3, 11, 0, tzinfo=NY), frames=frames) is None      # regular session: nothing
