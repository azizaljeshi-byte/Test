import csv
from datetime import datetime

from stockwatch import buy_setups_log as b
from stockwatch.data import NY

NOW = datetime(2026, 11, 11, 10, 40, tzinfo=NY)
R = {"ticker": "ABC", "name": "Abc Inc", "sector": "Energy", "price": 12.345, "composite": 71.26, "triggers": ["Golden cross"],
     "earnings_days": 9, "top_risks": ["Thin volume"]}


def test_rows_are_appended_with_one_header(tmp_path):
    f = tmp_path / "Quick log"
    assert b.append([R], f, NOW) == ""
    assert b.append([{**R, "ticker": "XYZ"}], f, NOW) == ""
    rows = list(csv.reader(open(f / b.FILE, encoding="utf-8-sig")))
    assert rows[0] == b.COLS and [r[2] for r in rows[1:]] == ["ABC", "XYZ"]
    assert rows[1][:8] == ["2026-11-11", "10:40", "ABC", "Abc Inc", "Energy", "12.35", "71.3", "Golden cross"]


def test_missing_drive_folder_never_raises(tmp_path):
    assert "not found" in b.append([R], tmp_path / "nodrive" / "Quick log", NOW)
    assert b.append([], tmp_path / "x", NOW) == ""


def test_a_new_setup_found_by_the_scan_is_written(tmp_path, monkeypatch):
    from stockwatch import live, market
    from stockwatch.config import Portfolio
    from stockwatch.store import Store
    monkeypatch.setenv("STOCKWATCH_QUICK_LOG_DIR", str(tmp_path / "Quick log"))
    st = Store(tmp_path / "t.db")
    monkeypatch.setattr(live, "current_portfolio", lambda store, wide=False: Portfolio(holdings=[], tiers={}))
    monkeypatch.setattr(market, "run", lambda *a, **k: {"results": [{**R, "verdict": "BUY SETUP"}], "stats": None})
    assert [r["ticker"] for r in live.market_scan(None, st)] == ["ABC"]
    assert [r["ticker"] for r in live.market_scan(None, st)] == []           # not new the second time
    rows = list(csv.reader(open(tmp_path / "Quick log" / b.FILE, encoding="utf-8-sig")))
    assert len(rows) == 2


class FakeTab:
    def __init__(self):
        self.rows = []

    def append_rows(self, rows, value_input_option=None):
        self.rows += rows

    def update(self, **k):
        pass


class FakeSheet:
    def __init__(self, tab=None, fail=False):
        self.tab, self.fail = tab, fail

    def worksheet(self, name):
        if self.fail:
            raise RuntimeError("boom https://docs.google.com/spreadsheets/d/SECRET")
        return self.tab


def test_google_sheet_gets_the_rows_and_failures_wait_for_the_next_scan(tmp_path, monkeypatch):
    from stockwatch.store import Store
    st = Store(tmp_path / "t.db")
    monkeypatch.delenv("STOCKWATCH_BUYSETUP_SHEET_URL", raising=False)
    monkeypatch.delenv("STOCKWATCH_SMALLCAP_SHEET_URL", raising=False)
    assert "not set up" in b.to_google(st, [R], NOW, connect=lambda env: None)   # says why on screen; the CSV still has the rows
    assert st.get_setting(b.PENDING_KEY) is None                                # nothing queued without a sheet (the CSV has them)
    monkeypatch.setenv("STOCKWATCH_SMALLCAP_SHEET_URL", "https://docs.google.com/spreadsheets/d/x")
    err = b.to_google(st, [R], NOW, connect=lambda env: FakeSheet(fail=True))
    assert "RuntimeError" in err and "SECRET" not in err and "docs.google" not in err
    tab = FakeTab()
    assert b.to_google(st, [{**R, "ticker": "XYZ"}], NOW, connect=lambda env: FakeSheet(tab)) == ""
    assert [r[2] for r in tab.rows] == ["ABC", "XYZ"] and st.get_setting(b.PENDING_KEY) == "[]"


def test_a_new_tab_starts_with_the_rows_already_in_the_csv(tmp_path, monkeypatch):
    import gspread
    from stockwatch.store import Store
    monkeypatch.setenv("STOCKWATCH_QUICK_LOG_DIR", str(tmp_path / "Quick log"))
    monkeypatch.setenv("STOCKWATCH_SMALLCAP_SHEET_URL", "https://docs.google.com/spreadsheets/d/x")
    b.append([{**R, "ticker": "OLD1"}, {**R, "ticker": "OLD2"}], tmp_path / "Quick log", NOW)
    tab = FakeTab()

    class NewTabSheet:
        def worksheet(self, name):
            raise gspread.WorksheetNotFound(name)

        def add_worksheet(self, **k):
            return tab
    st = Store(tmp_path / "t.db")
    b.append([{**R, "ticker": "NEW"}], tmp_path / "Quick log", NOW)          # the scan writes the CSV first, then the Google tab
    assert b.to_google(st, [{**R, "ticker": "NEW"}], NOW, connect=lambda env: NewTabSheet()) == ""
    assert [r[2] for r in tab.rows] == ["OLD1", "OLD2", "NEW"]                # no duplicate of the row just written
