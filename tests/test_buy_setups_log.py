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
