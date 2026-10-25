import json
from datetime import datetime

import pytest

from stockwatch import paper, paper_io, paper_live, paper_view
from stockwatch.data import NY
from stockwatch.store import Store
from test_paper import buy_snap

LIST = "Ticker,Paper\nAAA,yes\nbbb,Yes\nCCC,no\nAAA,yes\n,yes\nDDD,\n"


def test_parse_list_reads_yes_rows_once_in_upper_case():
    assert paper_io.parse_list(LIST) == ["AAA", "BBB"]
    assert paper_io.parse_list("Ticker\nAAA\nZZZ\n") == ["AAA", "ZZZ"]      # no Paper column: every row counts
    assert paper_io.parse_list("Symbol\nAAA\n") == [] and paper_io.parse_list("") == []
    many = "Ticker,Paper\n" + "\n".join(f"T{i},yes" for i in range(40))
    assert len(paper_io.parse_list(many)) == paper_io.MAX_TICKERS


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKWATCH_PAPER_LIST_URL", "https://example.test/list.csv")
    monkeypatch.delenv("STOCKWATCH_PAPER_WEBHOOK", raising=False)
    monkeypatch.delenv("STOCKWATCH_PAPER_TOKEN", raising=False)
    monkeypatch.setattr(paper_io, "load_list", lambda url: ["AAA", "NOPE"])
    paper_live._cache.update(list=None, at=0.0, error=None)
    store = Store(tmp_path / "t.db")
    s = buy_snap()
    s["payload"]["quote"] = {"market_state": "REGULAR", "live_price": 99.5, "live_change": 0.0}
    store.conn.execute("INSERT INTO snapshots (scanned_at, ticker, tier, price, technical_score, fundamental_score, composite, verdict, payload)"
                       " VALUES (?,?,?,?,?,?,?,?,?)", ("2026-10-26T15:00:00", "AAA", 2, 99.5, 0, 0, 0, "BUY", json.dumps(s["payload"], default=str)))
    store.conn.commit()
    return store


def test_tick_does_nothing_outside_the_regular_session(env, monkeypatch):
    monkeypatch.setattr(paper_live, "us_session", lambda: "CLOSED")
    st = paper_live.tick(env, datetime(2026, 10, 26, 11, 30, tzinfo=NY))
    assert "market closed" in st["note"] and not env.get_setting(paper_live.BOOK_KEY)


def test_tick_enters_in_session_skips_unknown_tickers_and_saves_the_book(env, monkeypatch):
    monkeypatch.setattr(paper_live, "us_session", lambda: "REGULAR")
    st = paper_live.tick(env, datetime(2026, 10, 26, 11, 30, tzinfo=NY))
    assert "NOPE" in st["skipped"] and "AAA" not in st["skipped"]
    book = paper_live.status(env)["book"]
    assert [t["ticker"] for t in book.trades] == ["AAA"] and book.cash < 50000
    paper_live.tick(env, datetime(2026, 10, 26, 11, 35, tzinfo=NY))            # a second cycle does not buy again
    assert len(paper_live.status(env)["book"].trades) == 1


def test_tick_without_a_list_link_trades_nothing(env, monkeypatch):
    monkeypatch.delenv("STOCKWATCH_PAPER_LIST_URL")
    st = paper_live.tick(env, datetime(2026, 10, 26, 11, 30, tzinfo=NY))
    assert st["tickers"] == [] and "STOCKWATCH_PAPER_LIST_URL" in st["note"]


def test_a_rebooted_app_restores_the_book_from_the_sheet(env, monkeypatch):
    monkeypatch.setenv("STOCKWATCH_PAPER_WEBHOOK", "https://example.test/exec")
    monkeypatch.setenv("STOCKWATCH_PAPER_TOKEN", "pw")
    saved = paper.Book()
    saved.cash = 123.0
    monkeypatch.setattr(paper_io, "pull", lambda w, t: saved.to_dict())
    assert paper_live.load_book(env).cash == 123.0


def test_the_paper_tab_renders_with_and_without_trades(env, monkeypatch):
    html = paper_view.html(paper_live.status(env))
    assert "Paper trading" in html and "No open trades" in html and "STOCKWATCH_PAPER_WEBHOOK" in html
    monkeypatch.delenv("STOCKWATCH_PAPER_LIST_URL")
    assert "STOCKWATCH_PAPER_LIST_URL" in paper_view.html(paper_live.status(env))
    monkeypatch.setenv("STOCKWATCH_PAPER_LIST_URL", "https://example.test/list.csv")
    monkeypatch.setattr(paper_live, "us_session", lambda: "REGULAR")
    paper_live.tick(env, datetime(2026, 10, 26, 11, 30, tzinfo=NY))
    html = paper_view.html(paper_live.status(env), {"AAA": 100.0})
    assert "AAA" in html and "OPEN" in html and "NOPE" in html


def test_an_empty_test_list_says_why(env):
    assert "first paper cycle" in paper_view.html(paper_live.status(env))
    env.set_setting(paper_live.STATE_KEY, json.dumps({"tickers": [], "skipped": {}, "note": ""}))
    assert "no rows with Paper = yes" in paper_view.html(paper_live.status(env))


def test_the_paper_account_can_enter_at_the_open_and_the_wait_can_be_restored(env, monkeypatch):
    monkeypatch.setattr(paper_live, "us_session", lambda: "REGULAR")
    monkeypatch.setenv("STOCKWATCH_PAPER_BLACKOUT_MIN", "60")
    paper_live.tick(env, datetime(2026, 10, 26, 9, 45, tzinfo=NY))
    assert paper_live.status(env)["book"].trades == []
    monkeypatch.delenv("STOCKWATCH_PAPER_BLACKOUT_MIN")
    paper_live.tick(env, datetime(2026, 10, 26, 9, 46, tzinfo=NY))
    assert [t["ticker"] for t in paper_live.status(env)["book"].trades] == ["AAA"]
