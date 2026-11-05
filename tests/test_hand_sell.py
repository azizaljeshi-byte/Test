"""The owner's sell-by-hand override on the Quick and New call accounts."""
import json
from datetime import datetime

from stockwatch import paper, paper_layout as pl, paper_live, paper_newcall, paper_view, quick, quick_view
from stockwatch.data import NY

NOW = datetime(2026, 11, 4, 11, 0, tzinfo=NY)


class FakeStore:
    def __init__(self):
        self.s = {}

    def get_setting(self, k):
        return self.s.get(k)

    def set_setting(self, k, v):
        self.s[k] = v

    def snapshot(self, t):
        return {"ticker": t, "payload": {}}


def quick_with_open(store):
    book = quick.new_book()
    quick._enter(book, "SPCX", "bounce", "test", 138.0, 136.0, 2.0, datetime(2026, 11, 4, 10, 28, tzinfo=NY))
    quick.save_book(store, book)


def test_quick_sells_by_hand_and_marks_it_an_override(monkeypatch):
    store = FakeStore()
    quick_with_open(store)
    monkeypatch.setattr(quick, "us_session", lambda: "REGULAR")
    monkeypatch.setattr(paper_live, "fresh_price", lambda snap, now: (136.5, ""))
    out = quick.sell_by_hand(store, "SPCX", NOW)
    assert out["ok"] and "136.50" in out["note"]
    book = quick.load_book(store, migrate=False)
    t = book["trades"][0]
    assert t["status"] == "CLOSED" and pl.is_override(t) and "SPCX" not in book["positions"]
    assert book["cash"] + 0 == book["start"] + t["result"]                    # the money adds up
    assert quick.sell_by_hand(store, "SPCX", NOW)["ok"] is False             # already sold


def test_quick_refuses_without_a_fresh_price_or_outside_the_session(monkeypatch):
    store = FakeStore()
    quick_with_open(store)
    monkeypatch.setattr(quick, "us_session", lambda: "CLOSED")
    assert "market is closed" in quick.sell_by_hand(store, "SPCX", NOW)["note"]
    monkeypatch.setattr(quick, "us_session", lambda: "REGULAR")
    monkeypatch.setattr(paper_live, "fresh_price", lambda snap, now: (None, "the stored quote is older than 5 minutes"))
    out = quick.sell_by_hand(store, "SPCX", NOW)
    assert not out["ok"] and "No fresh price" in out["note"]
    assert "SPCX" in quick.load_book(store, migrate=False)["positions"]       # nothing was sold


def test_new_call_sells_by_hand_and_does_not_buy_it_back_today(monkeypatch):
    from test_paper_newcall import snap
    store = FakeStore()
    book = paper.Book()
    paper_newcall.step(book, {"AAA": snap(line=92.0, band=91.0)}, {"AAA": 100.0}, NOW)
    store.set_setting(paper_newcall.BOOK_KEY, json.dumps(book.to_dict(), default=str))
    monkeypatch.setattr(paper_newcall, "us_session", lambda: "REGULAR")
    monkeypatch.setattr(paper_live, "fresh_price", lambda snap, now: (99.0, ""))
    out = paper_newcall.sell_by_hand(store, "AAA", NOW)
    assert out["ok"]
    book = paper_newcall.load_book(store)
    assert "AAA" not in book.positions and pl.is_override(book.trades[0]) and book.trades[0]["result"] < 0
    did = paper_newcall.step(book, {"AAA": snap(line=92.0, band=91.0)}, {"AAA": 100.0}, datetime(2026, 11, 4, 11, 30, tzinfo=NY))
    assert did == [] and "AAA" not in book.positions                          # a BUY call, but it was sold by hand today
    assert "sold it by hand today" in book.blocked[-1]["reason"]


def test_views_tag_hand_sales_and_give_one_card_per_open_trade():
    book = quick.new_book()
    quick._enter(book, "AAA", "bounce", "t", 100.0, 99.0, 1.0, NOW)
    quick._enter(book, "BBB", "breakout", "t", 50.0, 49.0, 1.0, NOW)
    quick._exit(book, "BBB", 49.0, NOW, "owner override: sold by hand at 49.00")
    top, opens, rest = quick_view.parts({"book": book, "state": {}, "sheet_error": None}, {"AAA": 101.0}, NOW)
    assert [t for t, _c in opens] == ["AAA"] and "SOLD BY HAND" in rest and "SOLD BY HAND" not in top
    assert quick_view.html({"book": book, "state": {}, "sheet_error": None}, {"AAA": 101.0}, NOW).count("Open now") == 1
    assert paper_view.parts is not None
