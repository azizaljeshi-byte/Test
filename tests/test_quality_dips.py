"""Quality dips (stockwatch/quality_dips.py): the three chart signs, the strong-fundamentals test, the table and the sheet write."""
import json
from datetime import datetime, timezone

import gspread
import pandas as pd

from stockwatch import quality_dips as qd
from stockwatch.data import NY

AFTER = datetime(2026, 11, 13, 17, 0, tzinfo=NY)
NOW = datetime(2026, 11, 13, 22, 0, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self):
        self.d = {}

    def get_setting(self, k, default=None):
        return self.d.get(k, default)

    def set_setting(self, k, v):
        self.d[k] = v


def frame(closes, end="2026-11-10"):
    idx = pd.bdate_range(end=end, periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1000}, index=idx)


def rising(n=260, start=50, step=0.2):
    return [start + step * i for i in range(n)]


def flags(closes):
    x = qd.technicals(frame(closes), AFTER)
    return None if x is None else x["flags"]


def test_a_healthy_uptrend_has_no_sign():
    assert flags(rising()) == []


def test_near_the_52_week_low_is_flagged_and_far_from_it_is_not():
    base = [100.0] * 250
    assert "low" in flags(base + [100] * 10)                         # sitting on its low
    assert "low" in flags(rising(250) + [50] * 10)                   # fell all the way back to where the year started
    up = rising()
    assert "low" not in flags(up)


def test_below_the_50_day_average():
    up = rising(250)
    assert "ema" in flags(up + [up[-1] - 6, up[-1] - 7, up[-1] - 8])
    assert "ema" not in flags(up)


def test_two_down_sessions_with_low_rsi():
    down = [100 - 0.6 * i for i in range(40)]
    f = flags(rising(220, 100, 0.1) + down)
    assert "rsi" in f
    # two down days but RSI still high: not flagged on that sign
    up = rising(260)
    assert "rsi" not in flags(up + [up[-1] - 0.1, up[-1] - 0.2])


def test_today_unfinished_bar_is_never_used_and_short_history_is_skipped():
    h = frame(rising(260), end="2026-11-13")
    live = datetime(2026, 11, 13, 11, 0, tzinfo=NY)                  # mid-session: the 13 Nov bar is unfinished
    assert qd.technicals(h, live)["price"] == round(float(h["Close"].iloc[-2]), 2)
    assert qd.technicals(frame(rising(100)), AFTER) is None
    assert qd.candidates({"AAA": frame(rising(100))}, AFTER) == []


def test_candidates_are_ordered_by_signs_present():
    low = [100.0] * 250 + [90, 85, 80, 78, 76]                       # near low, below average, down days, low RSI
    only_ema = rising(250) + [rising(250)[-1] - 8] * 3
    out = qd.candidates({"ONE": frame(only_ema), "ALL": frame(low), "NONE": frame(rising())}, AFTER)
    assert [c["t"] for c in out] == ["ALL", "ONE"] and len(out[0]["flags"]) == 3 and len(out[1]["flags"]) == 1


STRONG = {"name": "Strong Co", "sector": "Technology", "revenue_growth": 0.12, "earnings_growth": 0.2, "operating_margin": 0.25, "roe": 0.3,
          "free_cash_flow": 5e9, "debt_to_equity": 0.4, "current_ratio": 1.8, "pe_forward": 16, "target_mean_price": 130}


def test_strong_fundamentals_pass_and_each_failing_pillar_blocks():
    assert qd.quality(STRONG, 100)["passed"] is True
    for k, v in (("free_cash_flow", -1e9), ("revenue_growth", -0.05), ("operating_margin", -0.02), ("debt_to_equity", 2.5), ("earnings_growth", -0.4)):
        q = qd.quality({**STRONG, k: v}, 100)
        assert q["passed"] is False and q["why_not"].startswith("fails"), k


def test_unknown_is_never_a_fail_and_too_little_is_not_strong():
    q = qd.quality({k: v for k, v in STRONG.items() if k not in ("debt_to_equity", "current_ratio")}, 100)
    assert q["passed"] is True                                        # one pillar unknown, the rest strong
    q = qd.quality({"revenue_growth": 0.2, "operating_margin": 0.3}, 100)
    assert q["passed"] is False and "known" in q["why_not"]            # only 2 of 5 known
    assert qd.quality({}, 100)["passed"] is False and qd.quality(None)["known"] == 0


def test_the_table_lists_only_strong_companies_and_counts_those_waiting():
    cands = [{"t": "AAA", "price": 100, "day": -2.0, "above_low": 3.0, "below_high": -30, "vs_ema": -8, "rsi": 30, "down": 3, "flags": ["low", "ema", "rsi"]},
             {"t": "BBB", "price": 50, "day": -1.0, "above_low": 20, "below_high": -10, "vs_ema": -2, "rsi": 45, "down": 1, "flags": ["ema"]},
             {"t": "CCC", "price": 20, "day": -3.0, "above_low": 1, "below_high": -50, "vs_ema": -9, "rsi": 28, "down": 4, "flags": ["low", "ema"]},
             {"t": "DDD", "price": 10, "day": 0.5, "above_low": 2, "below_high": -40, "vs_ema": -5, "rsi": 40, "down": 0, "flags": ["low", "ema"]}]
    cache = {"AAA": {"t": "x", "f": STRONG}, "BBB": {"t": "x", "f": {**STRONG, "name": "B Co"}},
             "CCC": {"t": "x", "f": {**STRONG, "free_cash_flow": -3e9}}}          # DDD has no fundamentals yet
    out = qd.build(cands, cache)
    assert [r[0] for r in out["rows"]] == ["AAA", "BBB"] and out["waiting"] == 1 and out["strong"] == 2 and out["flagged"] == 4
    assert all(len(r) == len(qd.COLS) for r in out["rows"])
    assert out["rows"][0][5] == "Near its 52-week low | Below its 50-day average | Down 2 sessions with low RSI" and out["rows"][0][6] == 3
    assert qd.row_of(cands[0], STRONG, qd.quality(STRONG, 100))[17] == 30.0          # analyst target 130 over price 100


class FakeTab:
    id = 7
    frozen_row_count = 0

    def __init__(self):
        self.writes, self.cleared = [], 0

    def clear(self):
        self.cleared += 1

    def update(self, range_name=None, values=None, value_input_option=None):
        self.writes.append((range_name, values))


class FakeSheet:
    def __init__(self, fail=False):
        self.tabs, self.fail, self.requests = {}, fail, []

    def worksheet(self, name):
        if self.fail:
            raise RuntimeError("boom https://docs.google.com/spreadsheets/d/SECRET")
        if name not in self.tabs:
            raise gspread.WorksheetNotFound(name)
        return self.tabs[name]

    def add_worksheet(self, title, rows, cols):
        self.tabs[title] = FakeTab()
        return self.tabs[title]

    def batch_update(self, body):
        self.requests.append(body)


def test_the_sheet_gets_the_header_the_rows_and_a_status_line(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_SMALLCAP_SHEET_URL", "x")
    sheet = FakeSheet()
    state = {"at": "2026-11-13T22:00:00+00:00", "rows": [["AAA"] + [""] * (len(qd.COLS) - 1)], "waiting": 4, "flagged": 9, "strong": 1}
    assert qd.to_google(state, connect=lambda env: sheet) == ""
    tab = sheet.tabs[qd.TAB]
    assert tab.writes[0][0] == "A1" and tab.writes[0][1][0] == qd.COLS and len(tab.writes[0][1]) == 2
    assert tab.writes[1][0] == "A4" and "4 still waiting" in tab.writes[1][1][0][0] and sheet.requests
    monkeypatch.delenv("STOCKWATCH_SMALLCAP_SHEET_URL")
    for e in ("STOCKWATCH_BREAKWATCH_SHEET_URL", "STOCKWATCH_BUYSIGNALS_SHEET_URL", "STOCKWATCH_BUYSETUP_SHEET_URL"):
        monkeypatch.delenv(e, raising=False)
    assert "not set up" in qd.to_google(state, connect=lambda env: sheet)


def test_a_google_error_is_reported_by_type_only(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_SMALLCAP_SHEET_URL", "x")
    msg = qd.to_google({"rows": []}, connect=lambda env: FakeSheet(fail=True))
    assert "RuntimeError" in msg and "SECRET" not in msg and "docs.google" not in msg


class FakeProvider:
    def __init__(self, data, fail=()):
        self.data, self.fail, self.calls = data, set(fail), []

    def fundamentals(self, t):
        self.calls.append(t)
        if t in self.fail:
            raise RuntimeError("rate limited")
        return self.data[t]


def test_work_fetches_the_most_damaged_first_keeps_a_cache_and_survives_a_failure(monkeypatch):
    monkeypatch.delenv("STOCKWATCH_SMALLCAP_SHEET_URL", raising=False)
    for e in ("STOCKWATCH_BREAKWATCH_SHEET_URL", "STOCKWATCH_BUYSIGNALS_SHEET_URL", "STOCKWATCH_BUYSETUP_SHEET_URL"):
        monkeypatch.delenv(e, raising=False)
    monkeypatch.setattr(qd, "FUND_PER_RUN", 2)
    cands = [{"t": t, "price": 100, "day": -1, "above_low": 2 + i, "below_high": -20, "vs_ema": -5, "rsi": 30, "down": 2, "flags": ["low"]}
             for i, t in enumerate(["AAA", "BBB", "CCC"])]
    prov = FakeProvider({"AAA": STRONG, "BBB": STRONG, "CCC": STRONG}, fail={"BBB"})
    store = FakeStore()
    qd.work(store, cands, prov, NOW)
    assert prov.calls == ["AAA", "BBB"]                                # two per run, most damaged first
    st = json.loads(store.d[qd.KEY])
    assert [r[0] for r in st["rows"]] == ["AAA"] and st["waiting"] == 2                  # BBB failed (unknown, not a fail), CCC not reached
    assert "err" in json.loads(store.d[qd.FUND_KEY])["BBB"]
    assert "not set up" in store.d[qd.ERROR_KEY]
    qd.work(store, cands, prov, NOW)                                  # BBB is retried only after the error wait, so CCC is next
    assert prov.calls[2:] == ["CCC"]
    assert [r[0] for r in json.loads(store.d[qd.KEY])["rows"]] == ["AAA", "CCC"]


def test_record_runs_in_the_foreground_when_asked(monkeypatch):
    monkeypatch.delenv("STOCKWATCH_SMALLCAP_SHEET_URL", raising=False)
    for e in ("STOCKWATCH_BREAKWATCH_SHEET_URL", "STOCKWATCH_BUYSIGNALS_SHEET_URL", "STOCKWATCH_BUYSETUP_SHEET_URL"):
        monkeypatch.delenv(e, raising=False)
    store = FakeStore()
    assert "not set up" in qd.record(store, [], FakeProvider({}), NOW, background=False)
    assert json.loads(store.d[qd.KEY])["flagged"] == 0
