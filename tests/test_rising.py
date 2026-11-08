import json
import math
from datetime import datetime

import pandas as pd

from stockwatch import rising
from stockwatch.data import NY

DAY = "2026-11-06"
NOW = datetime(2026, 11, 6, 9, 46, 0, tzinfo=NY)           # slots 09:30, 09:35, 09:40 are finished; the 09:45 bar is still forming


def bars(day, start_slot, n, closes, vol):
    idx = pd.DatetimeIndex([pd.Timestamp(f"{day} 09:30", tz="America/New_York") + pd.Timedelta(minutes=5 * (start_slot + i)) for i in range(n)])
    c = list(closes)
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": float(vol)}, index=idx)


def past_day(day, level=100.0, vol=1000):
    wobble = [level + 0.4 * math.sin(i / 3) for i in range(78)]               # a calm day: RSI near the middle
    return bars(day, 0, 78, wobble, vol)


def frame(today_closes, today_vol=3000, past_vol=1000, scale=1000):
    """Volumes are per 5-minute bar, times `scale`: the default makes a 78,000-share bar-day x 10 = a 780,000-share day, over the 500,000 floor."""
    parts = [past_day(d, vol=past_vol * scale / 100) for d in ("2026-11-02", "2026-11-03", "2026-11-05")]
    parts.append(bars(DAY, 0, len(today_closes), today_closes, today_vol * scale / 100))
    return pd.concat(parts)


CLIMB = [100.0, 100.4, 100.9, 101.6]                         # four bars up: RSI, MACD and volume all building
FALL = [100.0, 99.6, 99.1, 98.4]


def test_a_stock_climbing_on_heavy_volume_is_on_the_main_list():
    r = rising.evaluate("UP", frame(CLIMB), NOW)
    assert r["miss"] == [] and r["blocked"] is None and r["vol_x"] == 3.0 and r["chg"] > 0 and r["rsi"] > 50
    assert r["rsi_d"] > 0 and r["hist_d"] > 0 and r["rsi_day"] is None


def test_each_missed_test_is_named_and_volume_uses_only_finished_bars():
    quiet = rising.evaluate("Q", frame(CLIMB, today_vol=1200), NOW)               # 1.2x: under 1.5x
    assert quiet["miss"] == ["volume 1.2x, under 1.5x"]
    falling = rising.evaluate("F", frame(FALL), NOW)
    assert falling["miss"] == ["RSI not rising", "MACD not improving"]
    # three finished bars of 3,000 each against three of 1,000: the forming 09:45 bar adds nothing to volume
    assert rising.evaluate("UP", frame(CLIMB), NOW)["vol_x"] == 3.0
    assert rising.evaluate("UP", frame(CLIMB), datetime(2026, 11, 6, 9, 51, 0, tzinfo=NY))["miss"] != ["volume unknown"]


def test_price_and_thin_stocks_are_blocked_not_listed():
    cheap = rising.evaluate("C", frame([x / 25 for x in CLIMB]), NOW)
    assert cheap["blocked"] == "price under $5"
    thin = rising.evaluate("T", frame(CLIMB, scale=1), NOW)
    assert thin["blocked"] == "trades too little in a day"


def test_missing_old_or_short_data_is_unknown_never_a_pass_or_a_zero():
    assert rising.evaluate("X", None, NOW)["unknown"] == "too little history"
    assert rising.evaluate("X", frame(CLIMB).iloc[-40:], NOW)["unknown"] == "too little history"
    only_past = pd.concat([past_day(d) for d in ("2026-11-02", "2026-11-03", "2026-11-05")])
    assert rising.evaluate("X", only_past, NOW)["unknown"] == "no price today"
    old = frame(CLIMB[:1])                                                         # last bar 09:30, run at 09:46: 16 minutes
    assert rising.evaluate("X", old, NOW)["unknown"] == "last trade is old"
    short_history = pd.concat([past_day("2026-11-05"), bars(DAY, 0, 4, CLIMB, 3000)])
    assert rising.evaluate("X", short_history, NOW)["unknown"] == "too little history"


def test_the_daily_rsi_is_added_when_daily_closes_are_known():
    closes = [100 - 0.2 * i for i in range(60)]
    r = rising.evaluate("UP", frame(CLIMB), NOW, closes)
    assert r["rsi_day"] is not None and r["rsi_day"] > 50                  # daily: a slide, then a jump on today's price


def test_run_has_a_watch_group_names_gaps_and_marks_arrows_new_fading_and_left():
    names = ["AAA", "BBB", "CCC", "GAP"]
    f1 = {"AAA": frame(CLIMB), "BBB": frame(CLIMB), "CCC": frame(CLIMB, today_vol=1200)}            # CCC: volume short only
    r1 = rising.build_run(names, f1, NOW, None, tracked=["BBB"])
    assert [r["t"] for r in r1["rows"]] == ["AAA", "BBB"] and r1["early"] is False and r1["pass"] == 2
    assert [(w["t"], w["miss"]) for w in r1["watch"]] == [("CCC", "volume 1.2x, under 1.5x")]
    assert r1["nodata"] == ["GAP"] and r1["unknown"] == 1 and r1["read"] == 3                         # named, counted, not scored
    assert {r["t"]: r["tracked"] for r in r1["rows"]} == {"AAA": False, "BBB": True} and all(r["dir"] is None and r["tag"] == "" for r in r1["rows"])
    assert rising.build_run(names, f1, datetime(2026, 11, 6, 9, 41, tzinfo=NY), None)["early"] is True                  # before 09:45: volume still settling
    later = datetime(2026, 11, 6, 9, 51, 0, tzinfo=NY)
    up2, down2 = CLIMB + [102.4], CLIMB + [100.9]
    f2 = {"AAA": frame(down2), "BBB": frame(up2), "CCC": frame(up2), "DDD": frame(up2)}
    r2 = rising.build_run(names + ["DDD"], f2, later, r1)
    by = {r["t"]: r for r in r2["rows"]}
    assert "AAA" not in by or by["AAA"]["tag"] in ("", "FADING")
    assert by["BBB"]["dir"]["price"] == 1 and by["BBB"]["tag"] == "" and by["CCC"]["tag"] == "NEW" and by["DDD"]["tag"] == "NEW"
    assert r2["early"] is False and r2["nodata"] == ["GAP"]
    assert all(x["why"] for x in r2["left"])


def test_fading_means_price_rsi_and_macd_all_lower_than_the_previous_run():
    names = ["AAA"]
    r1 = rising.build_run(names, {"AAA": frame(CLIMB + [102.0])}, datetime(2026, 11, 6, 9, 51, tzinfo=NY), None)
    r2 = rising.build_run(names, {"AAA": frame(CLIMB + [101.2, 101.6])}, datetime(2026, 11, 6, 9, 56, tzinfo=NY), r1)     # still rising on its own bars, lower than 5 minutes ago
    assert r2["rows"][0]["dir"] == {"price": -1, "rsi": -1, "hist": -1, "vol": 0} and r2["rows"][0]["tag"] == "FADING"
    r3 = rising.build_run(names, {"AAA": frame(CLIMB + [102.0, 102.6])}, datetime(2026, 11, 6, 9, 56, tzinfo=NY), r1)
    assert r3["rows"][0]["tag"] == "" and r3["rows"][0]["dir"]["price"] == 1


def test_a_stock_that_leaves_names_the_first_test_it_fails():
    names = ["AAA"]
    r1 = rising.build_run(names, {"AAA": frame(CLIMB)}, NOW, None)
    r2 = rising.build_run(names, {"AAA": frame(CLIMB, today_vol=900)}, NOW, r1)
    assert r2["rows"] == [] and r2["left"] == [{"t": "AAA", "why": "volume 0.9x, under 1.5x"}]
    r3 = rising.build_run(names, {}, NOW, r1)
    assert r3["left"] == [{"t": "AAA", "why": "no data this run"}] and r3["nodata"] == ["AAA"]


class FakeStore:
    def __init__(self): self.d = {}
    def get_setting(self, k, default=None): return self.d.get(k, default)
    def set_setting(self, k, v): self.d[k] = v
    def latest_snapshots(self): return [{"ticker": "AAA"}]


def test_refresh_follows_the_hours_and_saves_every_run_with_a_compact_watch_list():
    st = FakeStore()
    f = {"AAA": frame(CLIMB), "CCC": frame(CLIMB, today_vol=1200)}
    assert rising.refresh(st, datetime(2026, 11, 6, 9, 34, tzinfo=NY), frames=f) is None             # before 09:35
    assert rising.refresh(st, datetime(2026, 11, 6, 16, 5, tzinfo=NY), frames=f) is None             # after the close
    assert rising.refresh(st, datetime(2026, 11, 7, 10, 0, tzinfo=NY), frames=f) is None             # Saturday
    s1 = rising.refresh(st, NOW, frames=f)
    assert s1["status"] == "ok" and s1["pass"] == 1 and s1["rows"][0]["tracked"] is True and len(s1["watch"]) == 1 and "price" in s1["watch"][0]
    s2 = rising.refresh(st, datetime(2026, 11, 6, 9, 51, tzinfo=NY), frames=f)
    saved = rising.runs(st, DAY)
    assert len(saved) == 2 and saved[0]["watch"] == [{"t": "CCC", "miss": "volume 1.2x, under 1.5x"}] and rising.days(st) == [DAY]
    assert json.loads(st.d[rising.KEY_STATE])["watch"][0].get("price") is not None and s2["rows"][0]["dir"] is not None


def test_daily_closes_are_kept_for_their_own_day_only():
    daily = pd.DataFrame({"Close": [100.0 - 0.1 * i for i in range(40)] + [90.0]}, index=pd.DatetimeIndex(
        [pd.Timestamp("2026-09-20", tz="America/New_York") + pd.Timedelta(days=i) for i in range(41)]).tz_convert("America/New_York"))
    b = rising.build_daily(datetime(2026, 11, 6, 9, 40, tzinfo=NY), names=["AAA", "NONE"], daily={"AAA": daily})
    assert b["built_on"] == DAY and "AAA" in b["closes"] and "NONE" not in b["closes"] and len(b["closes"]["AAA"]) <= rising.CLOSES_KEPT
    st = FakeStore()
    st.set_setting(rising.KEY_DAILY, json.dumps(b))
    assert rising.load_daily(st, DAY) is not None and rising.load_daily(st, "2026-11-09") is None


def test_history_keeps_a_day_per_key_and_trims_old_days():
    st = FakeStore()
    for i in range(rising.KEEP_DAYS + 2):
        d = f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}"
        rising.save_run(st, {"day": d, "at": d, "rows": [], "left": [], "watch": []})
    assert len(rising.days(st)) == rising.KEEP_DAYS and st.d[rising.KEY_DAY + "2025-01-01"] == "[]"


def test_the_page_table_links_the_stock_shows_arrows_watch_note_and_escapes():
    from stockwatch import rising_view
    row = {"t": "AB<C", "price": 188.33, "chg": 10.7, "rsi": 65.7, "rsi_d": 13.8, "rsi_day": 62.0, "hist": 1.25, "hist_d": 1.11, "vol_x": 5.6,
           "tracked": True, "tag": "FADING", "dir": {"price": -1, "rsi": -1, "hist": -1, "vol": 1}}
    html = rising_view.table([row])
    assert "AB&lt;C" in html and "AB<C" not in html and "FADING" in html and "yours" in html and "?view=target&t=AB&lt;C" in html
    assert html.count("▼") == 3 and html.count("▲") == 1 and "+10.7%" in html and "5.6×" in html and "day 62" in html
    watch = rising_view.table([{**row, "tag": "", "dir": None, "tracked": False, "miss": "RSI not rising", "vol_x": None, "rsi_day": None}])
    assert "missing: RSI not rising" in watch and "unknown" in watch and "day none" in watch and "▲" not in watch
    assert rising_view.left_line({"left": [{"t": "CCC", "why": "volume 0.1x, under 1.5x"}]}) == "Left the list: CCC (volume 0.1x, under 1.5x)"
    assert rising_view.left_line({"left": []}) == ""
