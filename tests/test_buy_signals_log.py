"""Buy signals on the owner's sheet (stockwatch/buy_signals_log.py): one row per New buy / Add signal, readings from the stored snapshot."""
import csv
import json
from datetime import datetime

import gspread

from stockwatch import buy_signals_log as bs, events, notify
from stockwatch.config import Holding
from stockwatch.data import NY


class FakeStore:
    def __init__(self):
        self.d = {}

    def get_setting(self, k, default=None):
        return self.d.get(k, default)

    def set_setting(self, k, v):
        self.d[k] = v


def snap(t="AVGO", call="BUY", full=True):
    oc = {"known": True, "call": call, "close": 359.0, "exit_line": 316.69, "band_line": 308.4, "as_of": "2026-11-12", "why": "close to the exit line"}
    tech = {"one_call": oc, "price": 359.0, "rsi": 59.5, "sma50": 345.4, "sma200": 366.4, "atr": 17.2, "high_52w": 479.9, "volume_ratio": 1.63}
    if full:
        tech["zones"] = {"known": True, "support": [{"high": 345.04}], "resistance": [{"low": 349.42}]}
        tech["momentum"] = {"known": True, "facts": {"macd_above_signal": True}}
    return {"ticker": t, "price": 359.0, "payload": {"technical": tech, "name": "Broadcom Inc.", "profile": {"sector": "Technology"},
                                                       "plan": {"trigger": "a close above 366.39", "stop": 349.52, "sma20": 330.0}}}


NOW = datetime(2026, 11, 12, 16, 18, tzinfo=NY)


def test_row_has_the_readings_and_blanks_what_is_unknown():
    r = dict(zip(bs.COLS, bs.row_of(snap(), None, False, NOW)))
    assert r["Date (NY)"] == "2026-11-12" and r["Time (NY)"] == "16:18" and r["Ticker"] == "AVGO" and r["Signal"] == "New buy signal"
    assert r["Support"] == 345.04 and r["Resistance"] == 349.42 and r["Major support (exit line)"] == 316.69
    assert r["RSI"] == 59.5 and r["MACD"] == "bullish" and r["SMA 20"] == 330.0 and r["You own it"] == "no"
    assert r["Entry plan"] == "a close above 366.39 · stop 349.52" and r["From 52w high %"] == -25.2
    bare = dict(zip(bs.COLS, bs.row_of(snap(full=False), "WAIT", True, NOW)))
    assert bare["Support"] == "" and bare["Resistance"] == "" and bare["MACD"] == "" and bare["You own it"] == "yes"   # unknown, never 0
    assert len(bs.row_of(snap(), None, False, NOW)) == len(bs.COLS)


def test_csv_gets_the_rows_with_a_header(tmp_path):
    folder = tmp_path / "log"
    assert bs.append([bs.row_of(snap(), None, False, NOW)], folder) == ""
    assert bs.append([bs.row_of(snap("AMZN"), None, False, NOW)], folder) == ""
    rows = list(csv.reader(open(folder / bs.FILE, encoding="utf-8-sig")))
    assert rows[0] == bs.COLS and [r[2] for r in rows[1:]] == ["AVGO", "AMZN"]


class FakeTab:
    col_count = 99
    frozen_row_count = 0
    id = 5

    def __init__(self):
        self.rows, self.updates = [], []

    def append_rows(self, rows, value_input_option=None):
        self.rows += rows

    def update(self, range_name=None, values=None, value_input_option=None, **k):
        self.updates.append((range_name, values))


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


def test_google_gets_rows_and_creates_the_log_and_the_day_picker_tab(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_SMALLCAP_SHEET_URL", "x")
    st, sheet = FakeStore(), FakeSheet()
    assert bs.to_google(st, [bs.row_of(snap(), None, False, NOW)], connect=lambda env: sheet) == ""
    assert len(sheet.tabs[bs.TAB].rows) == 1 and st.d[bs.PENDING_KEY] == "[]"
    day = dict(sheet.tabs[bs.DAY_TAB].updates)
    assert day["B1"] == [["=TODAY()"]] and "FILTER" in day["A3"][0][0] and "yyyy-mm-dd" in day["A3"][0][0]
    assert any("setDataValidation" in r for body in sheet.requests for r in body["requests"])          # the date picker
    assert any("addBanding" in r for body in sheet.requests for r in body["requests"])                 # the log's look


def test_failure_keeps_rows_waiting_and_never_leaks_the_link(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_SMALLCAP_SHEET_URL", "x")
    st = FakeStore()
    err = bs.to_google(st, [bs.row_of(snap(), None, False, NOW)], connect=lambda env: FakeSheet(fail=True))
    assert "SECRET" not in err and "docs.google" not in err and "1 row" in err
    assert len(json.loads(st.d[bs.PENDING_KEY])) == 1
    sheet = FakeSheet()
    assert bs.to_google(st, [bs.row_of(snap("AMZN"), None, False, NOW)], connect=lambda env: sheet) == ""
    assert [r[2] for r in sheet.tabs[bs.TAB].rows] == ["AVGO", "AMZN"]


def test_not_configured_says_so_and_keeps_the_rows(monkeypatch):
    for v in ("STOCKWATCH_BUYSIGNALS_SHEET_URL", "STOCKWATCH_BUYSETUP_SHEET_URL", "STOCKWATCH_SMALLCAP_SHEET_URL"):
        monkeypatch.delenv(v, raising=False)
    st = FakeStore()
    assert "not set up" in bs.to_google(st, [bs.row_of(snap(), None, False, NOW)])
    assert len(json.loads(st.d[bs.PENDING_KEY])) == 1


def test_only_buy_and_add_signals_are_logged_and_the_push_is_unchanged(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(notify, "ntfy_send", lambda title, text, priority=3, tags="", click=None, channel="calls": sent.append(text) or "sent")
    got = []
    monkeypatch.setattr(bs, "record", lambda store, items, **k: got.extend(items))
    st, hold = FakeStore(), [Holding("OWN", 5, 10)]

    def s(t, call):
        x = snap(t, call)
        x["payload"]["technical"]["one_call"]["as_of"] = call
        return x
    events.call_flips(st, [s("AAA", "WAIT"), s("BBB", "WAIT"), s("OWN", "HOLD")], hold)                     # the first look only learns
    assert got == []
    events.call_flips(st, [s("AAA", "BUY"), s("BBB", "EXIT"), s("OWN", "ADD")], hold)
    assert sorted((x[0]["ticker"], x[1], x[2]) for x in got) == [("AAA", "WAIT", False), ("OWN", "HOLD", True)]   # BBB's exit is not logged
    assert sent and "AAA: New buy signal" in sent[-1]
