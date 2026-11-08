"""Approval mode (owner, 8 Nov): the Portfolio account trades nothing by itself; every sell, trim and buy waits for Approve or Skip."""
from datetime import timedelta

import pytest

from stockwatch import paper_live, portfolio
from tests.test_portfolio import D, LATE, FakeStore, book_with, money_ok, snap

try:
    from tests.test_portfolio import ready
except ImportError:                                              # pragma: no cover
    ready = None


@pytest.fixture(autouse=True)
def _open(monkeypatch):
    monkeypatch.setattr(portfolio, "us_session", lambda: "REGULAR")


def _px(monkeypatch, v):
    monkeypatch.setattr(paper_live, "fresh_price", lambda s, n: (v, ""))


def test_approval_mode_is_the_default():
    assert portfolio.APPROVAL_MODE is True


def test_a_hard_stop_becomes_an_order_and_sells_only_when_approved(monkeypatch):
    b = book_with(AAA=(10.0, 100.0))
    s = snap("AAA", price=90.0, line=92.0)
    portfolio.step(b, {"AAA": s}, {"AAA": 100.0}, D)
    stop = b["positions"]["AAA"]["stop"]
    did = portfolio.step(b, {"AAA": s}, {"AAA": stop - 1}, D + timedelta(minutes=1))
    assert [a["action"] for a in did] == ["PROPOSE HARD STOP"] and b["positions"]["AAA"]["shares"] == 10.0
    assert b["orders"]["AAA"]["side"] == "sell"
    assert portfolio.step(b, {"AAA": s}, {"AAA": stop - 2}, D + timedelta(minutes=2)) == []        # one order, price refreshed
    assert b["orders"]["AAA"]["price"] == stop - 2
    store = FakeStore([s])
    portfolio.save_book(store, b)
    _px(monkeypatch, stop - 2)
    out = portfolio.approve_order(store, "AAA", D + timedelta(minutes=3))
    nb = portfolio.load_book(store)
    assert out["ok"] and "AAA" not in nb["positions"] and not nb["orders"] and nb["actions"][-1]["action"] == "HARD STOP"
    money_ok(nb)


def test_an_order_is_withdrawn_when_the_price_is_back_over_the_stop():
    b = book_with(AAA=(10.0, 100.0))
    s = snap("AAA", price=90.0, line=92.0)
    portfolio.step(b, {"AAA": s}, {"AAA": 100.0}, D)
    stop = b["positions"]["AAA"]["stop"]
    portfolio.step(b, {"AAA": s}, {"AAA": stop - 1}, D + timedelta(minutes=1))
    portfolio.step(b, {"AAA": s}, {"AAA": stop + 3}, D + timedelta(minutes=2))
    assert not b["orders"] and b["positions"]["AAA"]["shares"] == 10.0
    assert b["actions"][-1]["action"] == "ORDER WITHDRAWN"


def test_a_poor_position_gets_a_trim_order_not_a_sale(monkeypatch):
    b = book_with(AAA=(100.0, 50.0), BIG=(1000.0, 50.0))
    poor = snap(call="EXIT", chart="weakening", mom="falling", price=45.0, line=47.0)
    did = portfolio.step(b, {"AAA": poor}, {"AAA": 45.0}, LATE)
    assert [a["action"] for a in did] == ["PROPOSE TRIM"] and b["positions"]["AAA"]["shares"] == 100.0
    store = FakeStore([poor])
    portfolio.save_book(store, b)
    _px(monkeypatch, 45.0)
    assert portfolio.approve_order(store, "AAA", LATE)["ok"]
    nb = portfolio.load_book(store)
    assert nb["positions"]["AAA"]["shares"] == 75.0 and nb["positions"]["AAA"]["trims"] == 1
    money_ok(nb)


def test_skip_logs_it_and_the_same_offer_is_not_made_again_today(monkeypatch):
    b = book_with(AAA=(100.0, 50.0), BIG=(1000.0, 50.0))
    poor = snap(call="EXIT", chart="weakening", mom="falling", price=45.0, line=47.0)
    portfolio.step(b, {"AAA": poor}, {"AAA": 45.0}, LATE)
    store = FakeStore([poor])
    portfolio.save_book(store, b)
    assert portfolio.skip_order(store, "AAA", LATE)["ok"]
    nb = portfolio.load_book(store)
    assert not nb["orders"] and nb["actions"][-1]["action"] == "SKIPPED" and nb["positions"]["AAA"]["shares"] == 100.0
    nb["checked"].clear()
    assert portfolio.step(nb, {"AAA": poor}, {"AAA": 45.0}, LATE + timedelta(minutes=1)) == []
    assert not nb["orders"]


def test_an_add_is_an_order_and_buys_only_when_approved(monkeypatch):
    if ready is None:
        pytest.skip("no ready() helper")
    b = book_with(AAA=(10.0, 100.0), BBB=(400.0, 100.0))
    did = portfolio.step(b, {"AAA": ready()}, {"AAA": 100.0}, D)
    assert [a["action"] for a in did] == ["PROPOSE ADD"] and b["positions"]["AAA"]["shares"] == 10.0 and b["adds_day"]["n"] == 1
    store = FakeStore([ready()])
    portfolio.save_book(store, b)
    _px(monkeypatch, 100.0)
    assert portfolio.approve_order(store, "AAA", D)["ok"]
    nb = portfolio.load_book(store)
    assert nb["positions"]["AAA"]["shares"] > 10.0 and not nb["orders"]
    money_ok(nb)


def test_a_buy_order_never_spends_more_than_the_cash(monkeypatch):
    b = book_with(AAA=(10.0, 100.0))
    b["orders"]["AAA"] = {"side": "buy", "action": "ADD", "shares": 50.0, "price": 100.0, "why": "w", "since": "x", "day": D.date().isoformat()}
    b["cash"] = 150.0
    store = FakeStore([snap("AAA", price=100.0)])
    portfolio.save_book(store, b)
    _px(monkeypatch, 100.0)
    assert portfolio.approve_order(store, "AAA", D)["ok"]
    assert portfolio.load_book(store)["cash"] >= 0


def test_orders_end_with_the_day_and_nothing_trades_when_the_market_is_closed(monkeypatch):
    b = book_with(AAA=(10.0, 100.0))
    b["orders"]["AAA"] = {"side": "buy", "action": "ADD", "shares": 1.0, "price": 100.0, "why": "w", "since": "x", "day": D.date().isoformat()}
    portfolio.step(b, {}, {}, D + timedelta(days=1))
    assert not b["orders"] and b["actions"][-1]["action"] == "ORDER WITHDRAWN"
    b["orders"]["AAA"] = {"side": "buy", "action": "ADD", "shares": 1.0, "price": 100.0, "why": "w", "since": "x", "day": D.date().isoformat()}
    store = FakeStore([snap("AAA")])
    portfolio.save_book(store, b)
    monkeypatch.setattr(portfolio, "us_session", lambda: "CLOSED")
    assert not portfolio.approve_order(store, "AAA", D)["ok"] and portfolio.load_book(store)["orders"]


def test_rebuy_waits_for_a_yes(monkeypatch):
    b = book_with(GOOG=(75.0, 40.0))
    b["cash"] = 5000.0
    b["rebuys"]["GOOG"] = {"shares": 25.0, "price": 40.0, "until": "2026-12-30"}
    turned = snap("GOOG", call="ADD", chart="strong_uptrend", price=40.5, line=37.0, chg=0.01, fund=50.0)
    did = portfolio.step(b, {"GOOG": turned}, {"GOOG": 40.5}, D)
    assert [a["action"] for a in did] == ["PROPOSE REBUY"] and b["positions"]["GOOG"]["shares"] == 75.0
    store = FakeStore([turned])
    portfolio.save_book(store, b)
    _px(monkeypatch, 40.5)
    assert portfolio.approve_order(store, "GOOG", D)["ok"]
    nb = portfolio.load_book(store)
    assert nb["positions"]["GOOG"]["shares"] == 100.0 and not nb["rebuys"]
