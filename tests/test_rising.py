import json
from datetime import datetime

import pandas as pd

from stockwatch import rising
from stockwatch.data import NY

DAY = "2026-11-06"
NOW = datetime(2026, 11, 6, 9, 40, 30, tzinfo=NY)          # 10 completed minutes: 09:30 ... 09:39


def minute_bars(day, start, minutes, price, vol):
    idx = pd.DatetimeIndex([pd.Timestamp(f"{day} 09:30", tz="America/New_York") + pd.Timedelta(minutes=start + i) for i in range(minutes)])
    p = price if isinstance(price, list) else [price] * minutes
    return pd.DataFrame({"Open": p, "High": p, "Low": p, "Close": p, "Volume": float(vol)}, index=idx)


def base_for(*tickers, closes=None, per_min=1000, avg_day=2_000_000):
    down = closes or [round(100 - 0.2 * i, 2) for i in range(60)]          # a slow slide: RSI low, MACD histogram negative
    return {"built_on": DAY, "closes": {t: list(down) for t in tickers}, "avg_day": {t: avg_day for t in tickers},
            "cum": {t: [per_min * MARKS for MARKS in range(5, 395, 5)] for t in tickers}}   # usual: 1,000 shares a minute


def test_expected_volume_runs_between_the_five_minute_marks():
    marks = [100, 200, 300]
    assert rising.expected_volume(marks, 5) == 100 and abs(rising.expected_volume(marks, 7) - 140) < 1e-9
    assert abs(rising.expected_volume(marks, 2) - 40) < 1e-9 and rising.expected_volume(marks, 500) == 300
    assert rising.expected_volume(marks, 0) is None and rising.expected_volume([], 10) is None


def test_a_full_day_gives_cumulative_marks_and_a_half_day_is_not_used():
    full = minute_bars("2026-11-05", 0, 390, 50.0, 1)
    marks = rising._cum_marks(full, pd.Timestamp("2026-11-05").date())
    assert marks[0] == 5 and marks[-1] == 390 and len(marks) == 78
    assert rising._cum_marks(minute_bars("2026-11-05", 0, 210, 50.0, 1), pd.Timestamp("2026-11-05").date()) is None


def test_baseline_leaves_out_today_and_averages_the_usual_days():
    daily = pd.DataFrame({"Close": [10.0 + i for i in range(60)]}, index=pd.DatetimeIndex(
        [pd.Timestamp("2026-08-10", tz="America/New_York") + pd.Timedelta(days=i) for i in range(60)]))
    daily.index = daily.index.tz_convert("America/New_York")
    last = daily.index[-1].date()
    mins = pd.concat([minute_bars("2026-11-04", 0, 390, 50, 2), minute_bars("2026-11-05", 0, 390, 50, 4), minute_bars(DAY, 0, 10, 50, 999)])
    b = rising.build_base(NOW, tickers=["AAA", "NONE"], daily={"AAA": daily}, minutes={"AAA": mins})
    assert "NONE" not in b["closes"] and "NONE" not in b["cum"]
    assert b["cum"]["AAA"][0] == 15 and b["avg_day"]["AAA"] == 390 * 3          # usual first five minutes: (2 + 4) / 2 x 5
    assert b["closes"]["AAA"][-1] == round(float(daily["Close"].iloc[-1]), 4) and last         # the daily bars all end before today


def test_a_stock_that_jumps_on_heavy_volume_is_on_the_list():
    b = base_for("UP")
    r = rising.evaluate("UP", b, minute_bars(DAY, 0, 10, 95.0, 5000), NOW)
    assert r["fails"] == [] and r["rsi_1d"] > 0 and r["rsi_3d"] > 0 and r["hist_1d"] > 0 and r["vol_x"] == 5.0 and r["chg"] > 0


def test_each_failed_test_is_named():
    b = base_for("A", "B", "C", "D")
    quiet = rising.evaluate("A", b, minute_bars(DAY, 0, 10, 95.0, 500), NOW)
    assert quiet["fails"] == ["volume is 0.5x, under 1.5x"]
    falling = rising.evaluate("B", b, minute_bars(DAY, 0, 10, 60.0, 5000), NOW)
    assert "RSI is no longer rising" in falling["fails"] and "MACD is no longer improving" in falling["fails"]
    cheap = base_for("C", closes=[round(4.0 - 0.01 * i, 2) for i in range(60)])
    assert "price under $5" in rising.evaluate("C", cheap, minute_bars(DAY, 0, 10, 3.9, 5000), NOW)["fails"]
    thin = base_for("D", avg_day=100_000)
    assert "trades too little in a day" in rising.evaluate("D", thin, minute_bars(DAY, 0, 10, 95.0, 5000), NOW)["fails"]


def test_missing_old_or_unusual_data_is_unknown_never_a_pass_or_a_zero():
    b = base_for("X")
    assert rising.evaluate("X", b, None, NOW)["unknown"] == "no price today"
    assert rising.evaluate("Y", b, minute_bars(DAY, 0, 10, 95.0, 5000), NOW)["unknown"] == "no usual-volume or daily history"
    old = minute_bars(DAY, 0, 3, 95.0, 5000)                                      # last bar 09:32, run at 09:40:30
    assert rising.evaluate("X", b, old, NOW)["unknown"] == "last trade is old"
    b["cum"]["X"] = []
    assert "unknown" in rising.evaluate("X", b, minute_bars(DAY, 0, 10, 95.0, 5000), NOW)


def test_the_bar_still_forming_is_not_counted():
    b = base_for("UP")
    bars = minute_bars(DAY, 0, 11, 95.0, 5000)                                    # includes the 09:40 bar, still forming at 09:40:30
    assert rising.evaluate("UP", b, bars, NOW)["vol_x"] == 5.0


def test_run_marks_new_arrows_fading_and_who_left():
    names = ["AAA", "BBB", "CCC"]
    b = base_for(*names)
    f1 = {"AAA": minute_bars(DAY, 0, 10, 95.0, 5000), "BBB": minute_bars(DAY, 0, 10, 96.0, 3000), "CCC": minute_bars(DAY, 0, 10, 95.0, 5000)}
    r1 = rising.build_run(b, f1, NOW, None, tracked=["BBB"])
    assert [r["t"] for r in r1["rows"]] == ["AAA", "CCC", "BBB"] and r1["pass"] == 3 and r1["early"] is True
    assert all(r["tag"] == "" and r["dir"] is None for r in r1["rows"]) and {r["t"]: r["tracked"] for r in r1["rows"]}["BBB"] is True
    later = datetime(2026, 11, 6, 9, 46, tzinfo=NY)
    f2 = {"AAA": minute_bars(DAY, 0, 16, 94.0, 5000),                              # price lower: AAA fades
          "BBB": minute_bars(DAY, 0, 16, 98.0, 5000),                              # price higher
          "CCC": minute_bars(DAY, 0, 16, 95.0, 100)}                               # volume dried up: leaves
    r2 = rising.build_run(b, f2, later, r1)
    by = {r["t"]: r for r in r2["rows"]}
    assert r2["early"] is False and set(by) == {"AAA", "BBB"}
    assert by["AAA"]["dir"]["price"] == -1 and by["AAA"]["dir"]["rsi"] == -1 and by["AAA"]["dir"]["hist"] == -1 and by["AAA"]["tag"] == "FADING"
    assert by["BBB"]["dir"]["price"] == 1 and by["BBB"]["tag"] == ""
    assert r2["left"] == [{"t": "CCC", "why": "volume is 0.1x, under 1.5x"}]
    r3 = rising.build_run(b, {**f2, "DDD": minute_bars(DAY, 0, 16, 95.0, 5000)}, later, r1)
    assert r3["left"][0]["t"] == "CCC"
    b2 = base_for(*names, "DDD")
    assert [r["tag"] for r in rising.build_run(b2, {**f1, "DDD": minute_bars(DAY, 0, 10, 95.0, 9000)}, NOW, r1)["rows"] if r["t"] == "DDD"] == ["NEW"]


class FakeStore:
    def __init__(self): self.d = {}
    def get_setting(self, k, default=None): return self.d.get(k, default)
    def set_setting(self, k, v): self.d[k] = v
    def latest_snapshots(self): return [{"ticker": "AAA"}]


def test_refresh_follows_the_hours_waits_for_the_baseline_and_saves_every_run():
    st = FakeStore()
    assert rising.refresh(st, datetime(2026, 11, 6, 9, 34, tzinfo=NY), frames={}) is None            # before 09:35
    assert rising.refresh(st, datetime(2026, 11, 6, 16, 5, tzinfo=NY), frames={}) is None            # after the close
    assert rising.refresh(st, datetime(2026, 11, 7, 10, 0, tzinfo=NY), frames={}) is None            # Saturday
    waiting = rising.refresh(st, NOW, frames={})
    assert waiting["status"] == "baseline" and waiting["rows"] == [] and rising.load_state(st)["status"] == "baseline"
    st.set_setting(rising.KEY_BASE, json.dumps(base_for("AAA", "BBB")))
    f = {"AAA": minute_bars(DAY, 0, 10, 95.0, 5000), "BBB": minute_bars(DAY, 0, 10, 95.0, 5000)}
    s1 = rising.refresh(st, NOW, frames=f)
    assert s1["status"] == "ok" and s1["pass"] == 2 and {r["t"]: r["tracked"] for r in s1["rows"]} == {"AAA": True, "BBB": False}
    f2 = {"AAA": minute_bars(DAY, 0, 15, 95.0, 5000), "BBB": minute_bars(DAY, 0, 15, 95.0, 5000)}
    rising.refresh(st, datetime(2026, 11, 6, 9, 45, 30, tzinfo=NY), frames=f2)
    saved = rising.runs(st, DAY)
    assert len(saved) == 2 and saved[1]["rows"][0]["dir"] is not None and rising.days(st) == [DAY]
    assert rising.load_base(st, "2026-11-09") is None and rising.load_base(st, DAY) is not None        # a baseline is for its own day only


def test_history_keeps_a_day_per_key_and_trims_old_days():
    st = FakeStore()
    for i in range(rising.KEEP_DAYS + 2):
        d = f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}"
        rising.save_run(st, {"day": d, "at": d, "rows": [], "left": []})
    kept = rising.days(st)
    assert len(kept) == rising.KEEP_DAYS and st.d[rising.KEY_DAY + "2025-01-01"] == "[]"


def test_the_page_table_links_the_stock_shows_arrows_and_escapes():
    from stockwatch import rising_view
    row = {"t": "AB<C", "price": 188.33, "chg": 10.7, "rsi": 65.7, "rsi_1d": 13.8, "hist": 1.25, "hist_1d": 1.11, "vol_x": 5.6, "tracked": True,
           "tag": "FADING", "dir": {"price": -1, "rsi": -1, "hist": -1, "vol": 1}}
    html = rising_view.table([row])
    assert "AB&lt;C" in html and "AB<C" not in html and "FADING" in html and "yours" in html and "?view=target&t=AB&lt;C" in html
    assert html.count("▼") == 3 and html.count("▲") == 1 and "+10.7%" in html and "5.6×" in html
    new = rising_view.table([{**row, "tag": "NEW", "dir": None, "tracked": False}])
    assert "NEW" in new and "▲" not in new and "▼" not in new
    assert rising_view.left_line({"left": [{"t": "CCC", "why": "volume is 0.1x, under 1.5x"}]}) == "Left the list: CCC (volume is 0.1x, under 1.5x)"
    assert rising_view.left_line({"left": []}) == ""
