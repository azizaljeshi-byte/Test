import json
from datetime import datetime, timezone

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


def feed(store, now, price=99.5, ticker="AAA"):
    """A fresh regular-session quote at `now` (New York), as the tracker would store it."""
    utc = now.astimezone(timezone.utc)
    store.update_quote(ticker, {"market_state": "REGULAR", "live_price": price, "live_change": 0.0,
                                "live_time": utc.isoformat(), "fetched_at": utc.isoformat(timespec="seconds")})


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
    feed(env, datetime(2026, 10, 26, 11, 30, tzinfo=NY))
    st = paper_live.tick(env, datetime(2026, 10, 26, 11, 30, tzinfo=NY))
    assert "market closed" in st["note"] and not env.get_setting(paper_live.BOOK_KEY)


def test_tick_enters_in_session_skips_unknown_tickers_and_saves_the_book(env, monkeypatch):
    monkeypatch.setattr(paper_live, "us_session", lambda: "REGULAR")
    feed(env, datetime(2026, 10, 26, 11, 30, tzinfo=NY))
    st = paper_live.tick(env, datetime(2026, 10, 26, 11, 30, tzinfo=NY))
    assert "NOPE" in st["skipped"] and "AAA" not in st["skipped"]
    book = paper_live.status(env)["book"]
    assert [t["ticker"] for t in book.trades] == ["AAA"] and book.cash < 50000
    feed(env, datetime(2026, 10, 26, 11, 35, tzinfo=NY))
    paper_live.tick(env, datetime(2026, 10, 26, 11, 35, tzinfo=NY))            # a second cycle does not buy again
    assert len(paper_live.status(env)["book"].trades) == 1


def test_tick_without_a_list_link_trades_nothing(env, monkeypatch):
    monkeypatch.delenv("STOCKWATCH_PAPER_LIST_URL")
    feed(env, datetime(2026, 10, 26, 11, 30, tzinfo=NY))
    st = paper_live.tick(env, datetime(2026, 10, 26, 11, 30, tzinfo=NY))
    assert st["tickers"] == [] and "STOCKWATCH_PAPER_LIST_URL" in st["note"]


def test_a_rebooted_app_restores_the_book_from_the_sheet(env, monkeypatch):
    monkeypatch.setenv("STOCKWATCH_PAPER_WEBHOOK", "https://example.test/exec")
    monkeypatch.setenv("STOCKWATCH_PAPER_TOKEN", "pw")
    saved = paper.Book()
    saved.cash = 123.0
    monkeypatch.setattr(paper_io, "pull", lambda w, t: {"ok": True, "book": saved.to_dict()})
    book, note = paper_live.load_book(env)
    assert book.cash == 123.0 and note == ""


def test_the_paper_tab_renders_with_and_without_trades(env, monkeypatch):
    html = paper_view.html(paper_live.status(env))
    assert "Paper trading" in html and "No open trades" in html and "STOCKWATCH_PAPER_WEBHOOK" in html
    monkeypatch.delenv("STOCKWATCH_PAPER_LIST_URL")
    assert "STOCKWATCH_PAPER_LIST_URL" in paper_view.html(paper_live.status(env))
    monkeypatch.setenv("STOCKWATCH_PAPER_LIST_URL", "https://example.test/list.csv")
    monkeypatch.setattr(paper_live, "us_session", lambda: "REGULAR")
    feed(env, datetime(2026, 10, 26, 11, 30, tzinfo=NY))
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
    feed(env, datetime(2026, 10, 26, 9, 45, tzinfo=NY))
    paper_live.tick(env, datetime(2026, 10, 26, 9, 45, tzinfo=NY))
    assert paper_live.status(env)["book"].trades == []
    monkeypatch.delenv("STOCKWATCH_PAPER_BLACKOUT_MIN")
    feed(env, datetime(2026, 10, 26, 9, 46, tzinfo=NY))
    paper_live.tick(env, datetime(2026, 10, 26, 9, 46, tzinfo=NY))
    assert [t["ticker"] for t in paper_live.status(env)["book"].trades] == ["AAA"]


def test_a_stale_or_untimed_quote_never_enters(env, monkeypatch):
    monkeypatch.setattr(paper_live, "us_session", lambda: "REGULAR")
    now = datetime(2026, 10, 26, 11, 30, tzinfo=NY)
    for quote in (
        {"market_state": "REGULAR", "live_price": 99.5, "live_time": "2020-03-02T15:00:00+00:00", "fetched_at": "2020-03-02T15:00:05"},
        {"market_state": "REGULAR", "live_price": 99.5},                                           # no times at all
    ):
        env.update_quote("AAA", quote)
        st = paper_live.tick(env, now)
        assert "AAA" in st["skipped"] and paper_live.status(env)["book"].trades == []
    utc = now.astimezone(timezone.utc)
    env.update_quote("AAA", {"market_state": "REGULAR", "live_price": 99.5, "live_time": utc.isoformat(),
                             "fetched_at": (utc.replace(minute=utc.minute - 20)).isoformat(timespec="seconds")})   # fetched 20 min ago
    assert "older than 5 minutes" in paper_live.tick(env, now)["skipped"]["AAA"]


def test_an_unreadable_sheet_does_not_start_a_new_account(env, monkeypatch):
    monkeypatch.setattr(paper_live, "us_session", lambda: "REGULAR")
    monkeypatch.setenv("STOCKWATCH_PAPER_WEBHOOK", "https://example.test/exec")
    monkeypatch.setenv("STOCKWATCH_PAPER_TOKEN", "pw")
    monkeypatch.setattr(paper_io, "pull", lambda w, t: {"ok": False, "error": "timed out"})
    now = datetime(2026, 10, 26, 11, 30, tzinfo=NY)
    feed(env, now)
    st = paper_live.tick(env, now)
    assert "could not read the saved account" in st["note"] and not env.get_setting(paper_live.BOOK_KEY)
    monkeypatch.setattr(paper_io, "pull", lambda w, t: {"ok": True, "book": None})     # the Sheet says: no account yet
    env.set_setting("paper_restore_try", "0")
    feed(env, now)
    monkeypatch.setattr(paper_io, "push", lambda *a, **k: {"ok": True})
    paper_live.tick(env, now)
    assert [t["ticker"] for t in paper_live.status(env)["book"].trades] == ["AAA"]


def test_an_unsent_save_stays_pending_and_the_day_report_goes_out_after_the_close(env, monkeypatch):
    monkeypatch.setenv("STOCKWATCH_PAPER_WEBHOOK", "https://example.test/exec")
    monkeypatch.setenv("STOCKWATCH_PAPER_TOKEN", "pw")
    sent = []
    ok = {"v": False}
    monkeypatch.setattr(paper_io, "pull", lambda w, t: {"ok": True, "book": None})
    monkeypatch.setattr(paper_io, "push", lambda *a, **k: sent.append(a) or ({"ok": True} if ok["v"] else {"ok": False, "error": "busy"}))
    monkeypatch.setattr(paper_live, "us_session", lambda: "REGULAR")
    now = datetime(2026, 10, 26, 11, 30, tzinfo=NY)
    feed(env, now)
    paper_live.tick(env, now)                                         # buys, the save fails
    assert env.get_setting("paper_dirty") == "1" and len(sent) == 1
    ok["v"] = True
    env.set_setting("paper_try_at", "0")
    monkeypatch.setattr(paper_live, "us_session", lambda: "POST")      # after the close, with no change to the book
    paper_live.tick(env, datetime(2026, 10, 26, 16, 6, tzinfo=NY))
    assert env.get_setting("paper_dirty") == "0" and len(sent) == 2 and env.get_setting("paper_eod_day") == "2026-10-26"


def test_an_open_trade_is_watched_after_its_stock_leaves_the_list_and_nothing_new_is_bought(env, monkeypatch):
    monkeypatch.setattr(paper_live, "us_session", lambda: "REGULAR")
    now = datetime(2026, 10, 26, 11, 30, tzinfo=NY)
    feed(env, now)
    paper_live.tick(env, now)
    assert "AAA" in paper_live.status(env)["book"].positions
    monkeypatch.setattr(paper_io, "load_list", lambda url: ["NOPE"])                   # AAA is dropped from the list
    paper_live._cache.update(list=None, at=0.0, error=None)
    later = datetime(2026, 10, 26, 11, 40, tzinfo=NY)
    feed(env, later, price=90.0)                                                       # through the stop
    paper_live.tick(env, later)
    feed(env, datetime(2026, 10, 26, 12, 20, tzinfo=NY), price=90.0)
    st = paper_live.tick(env, datetime(2026, 10, 26, 12, 20, tzinfo=NY))
    assert paper_live.status(env)["book"].trades[0]["status"] == "CLOSED" and "AAA" not in st["skipped"]
    feed(env, datetime(2026, 10, 26, 13, 0, tzinfo=NY), price=99.5)
    paper_live.tick(env, datetime(2026, 10, 26, 13, 0, tzinfo=NY))
    assert len(paper_live.status(env)["book"].trades) == 1                              # not bought again


def test_the_empty_list_message_follows_the_setup(env, monkeypatch):
    monkeypatch.delenv("STOCKWATCH_PAPER_LIST_URL")
    assert paper_view.empty_reason(paper_live.status(env)) == "No test list link is set yet."


def test_win_rate_tile_shows_wins_of_closed_at_the_top(env):
    html = paper_view.html(paper_live.status(env))
    top = html.split("pp-k pp-k4")[1].split("Test list")[0]
    assert "Winning · losing" in top and "0 won · 0 lost" in top and "—" in top


def test_winning_and_losing_percentages_add_to_one_hundred():
    assert paper_view.wl({"closed": 25, "wins": 9}) == ("36%", "64%")
    assert paper_view.wl({"closed": 0, "wins": 0}) == ("—", "—")
