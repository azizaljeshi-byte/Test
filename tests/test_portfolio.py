"""The Portfolio account: seeding from the holdings, trims, size-downs, proposals, adds, new names and the owner's taps."""
import json
from datetime import datetime, timedelta

import pytest

from stockwatch import paper_layout as pl, paper_live, portfolio
from stockwatch.config import Holding
from stockwatch.data import NY

D = datetime(2026, 11, 9, 11, 0, tzinfo=NY)             # a Monday, 11:00 New York
LATE = datetime(2026, 11, 9, 15, 46, tzinfo=NY)


class FakeStore:
    def __init__(self, snaps=None):
        self.s, self._snaps = {}, snaps or []

    def get_setting(self, k):
        return self.s.get(k)

    def set_setting(self, k, v):
        self.s[k] = v

    def latest_snapshots(self):
        return self._snaps

    def snapshot(self, t):
        return next((x for x in self._snaps if x["ticker"] == t), None)


def snap(t="AAA", call="ADD", fund=85.0, fair=0.30, methods=2, analyst=0.25, grade="Moderate", chart="strong_uptrend", mom="strong",
         line=92.0, earn=None, chg=0.005, vol=1_500_000.0, price=100.0, tier=1):
    oc = {"known": True, "call": call, "why": "test", "exit_line": line, "band_line": line - 1, "risk": {"grade": grade}}
    return {"ticker": t, "tier": tier, "price": price, "fundamental_score": fund, "technical_score": 60.0,
            "payload": {"technical": {"one_call": oc, "atr": 2.0, "vol_avg20": 1_000_000.0, "momentum": {"known": True, "momentum": mom},
                                      "price_status": {"code": chart, "label": chart}},
                        "quote": {"live_change": chg, "live_volume": vol}, "events": {"days_to_earnings": earn},
                        "fundamental": {"analyst_upside": analyst},
                        "research": {"valuation": {"fair_value": {"mid": price * (1 + fair), "methods": {f"m{i}": {} for i in range(methods)}}}}}}


def book_with(**pos):
    b = portfolio.new_book()
    b["positions"] = {t: {"shares": s, "entry": e, "base": s, "source": "holding", "opened": "2026-11-08 12:00"} for t, (s, e) in pos.items()}
    cost = sum(s * e for s, e in pos.values())
    b["cash"] = round(cost * 0.1, 2)
    b["start"] = round(cost * 1.1, 2)
    return b


def money_ok(b):
    used = sum(p["shares"] * p["entry"] for p in b["positions"].values())
    realized = b["cash"] + used - b["start"]
    assert realized == pytest.approx(sum(a["result"] or 0.0 for a in b["actions"]), abs=0.02)


# ------------------------------------------------------------------ seeding

def test_seed_mirrors_the_holdings_at_cost_with_a_ten_percent_cash_reserve():
    store = FakeStore([snap("CCC", price=50.0)])
    hs = [Holding("AAA", 1, 10, 100.0), Holding("BBB", 2, 0, None), Holding("CCC", 1, 20, None), Holding("DDD", 1, 5, None)]
    out = portfolio.seed(store, D, hs)
    assert out["ok"] and "DDD left out" in out["note"] and "CCC taken at its latest price" in out["note"]
    b = portfolio.load_book(store)
    assert set(b["positions"]) == {"AAA", "CCC"} and b["positions"]["AAA"]["entry"] == 100.0 and b["positions"]["CCC"]["entry"] == 50.0
    assert b["cash"] == pytest.approx(200.0) and b["start"] == pytest.approx(2200.0)
    money_ok(b)
    assert not portfolio.seed(FakeStore(), D, [Holding("X", 1, 0, None)])["ok"]


# ------------------------------------------------------------------ trims

def test_a_poor_position_is_trimmed_a_quarter_then_another_then_proposed_and_never_sold_to_zero():
    b = book_with(AAA=(100.0, 50.0), BIG=(1000.0, 50.0))
    poor = snap(call="EXIT", chart="weakening", mom="falling", price=45.0, line=47.0)
    assert portfolio.poor_reason(poor)
    day = LATE
    did = portfolio.step(b, {"AAA": poor}, {"AAA": 45.0}, day)
    assert [a["action"] for a in did] == ["TRIM"] and b["positions"]["AAA"]["shares"] == 75.0
    assert portfolio.step(b, {"AAA": poor}, {"AAA": 45.0}, day + timedelta(seconds=30)) == []       # once a day
    for n in (1, 2):                                                                                   # two more days still poor
        did = portfolio.step(b, {"AAA": poor}, {"AAA": 45.0}, day + timedelta(days=n))
    assert b["positions"]["AAA"]["shares"] == 50.0 and did[0]["action"] == "TRIM"
    did = portfolio.step(b, {"AAA": poor}, {"AAA": 45.0}, day + timedelta(days=3))
    assert [a["action"] for a in did] == ["PROPOSE EXIT"] and "AAA" in b["proposals"]
    for n in range(4, 9):
        portfolio.step(b, {"AAA": poor}, {"AAA": 45.0}, day + timedelta(days=n))
    assert b["positions"]["AAA"]["shares"] == 50.0                                                     # half stays until the owner says yes
    money_ok(b)


def test_exit_without_a_weak_chart_or_a_weak_chart_without_exit_is_not_poor():
    assert portfolio.poor_reason(snap(call="EXIT", chart="strong_uptrend", mom="strong")) is None
    assert portfolio.poor_reason(snap(call="ADD", chart="weakening", mom="falling")) is None


def test_a_recovered_position_resets_the_count_and_withdraws_a_proposal():
    b = book_with(AAA=(100.0, 50.0))
    poor = snap(call="EXIT", chart="weakening", price=45.0, line=47.0)
    portfolio.step(b, {"AAA": poor}, {"AAA": 45.0}, LATE)
    fine = snap(call="HOLD", price=50.0)
    portfolio.step(b, {"AAA": fine}, {"AAA": 50.0}, LATE + timedelta(days=1))
    assert b["poor"]["AAA"] == [] and b["positions"]["AAA"]["trims"] == 0
    b["proposals"]["AAA"] = {"since": "x", "price": 1, "shares": 1, "why": "x"}
    portfolio.step(b, {"AAA": fine}, {"AAA": 50.0}, LATE + timedelta(days=2))
    assert "AAA" not in b["proposals"]


def test_nothing_is_sold_on_an_intraday_dip_only_at_1545():
    b = book_with(AAA=(100.0, 50.0))
    poor = snap(call="EXIT", chart="weakening", price=45.0, line=47.0)
    assert portfolio.step(b, {"AAA": poor}, {"AAA": 45.0}, D) == []
    assert b["positions"]["AAA"]["shares"] == 100.0


def test_a_position_over_its_cap_is_sized_down_but_not_below_half_of_the_most_held():
    b = book_with(AAA=(100.0, 100.0), BBB=(10.0, 100.0))
    big = snap("AAA", call="HOLD", price=100.0)
    did = portfolio.step(b, {"AAA": big}, {"AAA": 100.0}, LATE)
    a = [x for x in did if x["action"] == "SIZE DOWN"]
    assert a and "cap is 15%" in a[0]["why"] and b["positions"]["AAA"]["shares"] >= 50.0
    hi = snap("BBB", call="HOLD", grade="High", price=100.0)
    assert portfolio.cap_pct(hi) == 8.0
    money_ok(b)


# ------------------------------------------------------------------ adds

def ready(**kw):
    return snap(**kw)


def test_a_holding_that_is_undervalued_and_strong_is_added_in_a_small_step():
    b = book_with(AAA=(10.0, 100.0), BBB=(400.0, 100.0))
    did = portfolio.step(b, {"AAA": ready()}, {"AAA": 100.0}, D)
    assert [a["action"] for a in did] == ["ADD"]
    p = b["positions"]["AAA"]
    assert p["shares"] > 10 and 0.01 <= p["shares"] - 10 <= 0.05 * portfolio.equity(b, {}) / 100 + 0.01 and p["shares"] * 100 <= 0.15 * portfolio.equity(b, {"AAA": 100.0, "BBB": 100.0}) + 100
    assert "fair value" in did[0]["why"]
    money_ok(b)


@pytest.mark.parametrize("kw,why", [
    (dict(fund=74.0), "needs 75"),
    (dict(fair=0.10), "fair value only"),
    (dict(methods=1), "1 method"),
    (dict(analyst=0.05), "analyst target only"),
    (dict(call="HOLD"), "not BUY or ADD"),
    (dict(grade="High"), "risk grade High"),
    (dict(earn=1), "earnings in 1 day"),
    (dict(chart="weakening", mom="falling"), "weak"),
    (dict(chg=-0.01), "down 1.0% today"),
    (dict(vol=300_000.0), "volume only"),
])
def test_each_add_test_can_stop_an_add(kw, why):
    b = book_with(AAA=(10.0, 100.0))
    ok, reason = portfolio.add_check(snap(**kw), 100.0, True, 90.0, False, "", b, D, kw.get("chg", 0.005), 1.5 if "vol" not in kw else 0.3)
    assert not ok and why in reason


def test_timing_stops_the_opening_half_hour_the_late_session_and_a_falling_market():
    b = book_with(AAA=(10.0, 100.0))
    s = snap()
    assert not portfolio.add_check(s, 100.0, True, 20.0, False, "", b, D, 0.005, 1.5)[0]
    assert not portfolio.add_check(s, 100.0, True, 370.0, True, "", b, D, 0.005, 1.5)[0]
    ok, why = portfolio.add_check(s, 100.0, True, 90.0, False, "market gate: 70% of stocks are down", b, D, 0.005, 1.5)
    assert not ok and "market gate" in why
    assert portfolio.add_check(s, 100.0, True, 90.0, False, "", b, D, 0.005, 1.5)[0]


def test_a_new_name_needs_the_same_bar_starts_small_and_at_most_two_adds_a_day():
    b = book_with(AAA=(10.0, 100.0), BBB=(400.0, 100.0))
    assert not portfolio.add_check(snap("NEW", fund=74.0), 100.0, False, 90.0, False, "", b, D, 0.005, 1.5)[0]
    assert portfolio.add_check(snap("NEW", fund=75.0), 100.0, False, 90.0, False, "", b, D, 0.005, 1.5)[0]
    snaps = {t: snap(t, fund=90.0) for t in ("N1", "N2", "N3")}
    did = portfolio.step(b, snaps, {t: 100.0 for t in snaps}, D)
    assert [a["action"] for a in did] == ["NEW NAME", "NEW NAME"]
    assert all(b["positions"][a["ticker"]]["shares"] * 100 <= 0.03 * portfolio.equity(b, {}) + 1 for a in did)
    assert any("adds a day is the limit" in x["reason"] for x in b["blocked"])
    assert portfolio.step(b, snaps, {t: 100.0 for t in snaps}, D + timedelta(minutes=1)) == []        # one add per name per day, the limit stays


def test_a_trimmed_stock_is_not_added_to_for_three_trading_days():
    b = book_with(AAA=(100.0, 50.0), BBB=(10.0, 100.0))
    poor = snap(call="EXIT", chart="weakening", price=45.0, line=47.0)
    portfolio.step(b, {"AAA": poor}, {"AAA": 45.0}, LATE)
    assert b["locks"]["AAA"] == "2026-11-12"
    ok, why = portfolio.add_check(snap(), 100.0, True, 90.0, False, "", b, datetime(2026, 11, 10, 11, 0, tzinfo=NY), 0.005, 1.5)
    assert not ok and "trimmed recently" in why


def test_a_too_small_add_is_not_made_and_fractions_are_allowed():
    b = book_with(AAA=(10.0, 100.0), BBB=(400.0, 100.0))
    s = snap("AAA", price=500.0, line=450.0)
    b["cash"] = 300.0
    assert 0 < portfolio.add_size(b, 500.0, s["payload"]["technical"]["one_call"], True, s, {}) < 1                # a part of a share
    b["cash"] = 10.0
    assert portfolio.add_size(b, 100.0, snap()["payload"]["technical"]["one_call"], True, snap(), {}) == 0.0     # under $25


def test_unknown_data_never_passes():
    b = book_with(AAA=(10.0, 100.0))
    s = snap()
    s["fundamental_score"] = None
    assert not portfolio.add_check(s, 100.0, True, 90.0, False, "", b, D, 0.005, 1.5)[0]
    s = snap()
    s["payload"]["research"] = {}
    ok, why = portfolio.add_check(s, 100.0, True, 90.0, False, "", b, D, 0.005, 1.5)
    assert not ok and "fair value is not known" in why


# ------------------------------------------------------------------ the owner's taps and the cycle

def test_sell_by_hand_sells_all_and_clears_a_proposal_and_keep_it_silences_one(monkeypatch):
    store = FakeStore([snap()])
    b = book_with(AAA=(10.0, 100.0))
    b["proposals"]["AAA"] = {"since": "x", "price": 1, "shares": 10, "why": "x"}
    portfolio.save_book(store, b)
    assert portfolio.keep_it(store, "AAA", D)["ok"] and "AAA" not in portfolio.load_book(store)["proposals"]
    monkeypatch.setattr(portfolio, "us_session", lambda: "CLOSED")
    assert "market is closed" in portfolio.sell_by_hand(store, "AAA", D)["note"]
    monkeypatch.setattr(portfolio, "us_session", lambda: "REGULAR")
    monkeypatch.setattr(paper_live, "fresh_price", lambda s, n: (110.0, ""))
    out = portfolio.sell_by_hand(store, "AAA", D)
    assert out["ok"] and "+100.00" in out["note"]
    b = portfolio.load_book(store)
    assert "AAA" not in b["positions"] and b["actions"][-1]["why"].startswith("owner override")
    money_ok(b)
    assert not portfolio.sell_by_hand(store, "AAA", D)["ok"]


def test_tick_seeds_itself_runs_in_session_and_does_nothing_when_closed(monkeypatch):
    s = snap(call="HOLD", price=100.0)
    store = FakeStore([s])
    monkeypatch.setattr(portfolio, "us_session", lambda: "CLOSED")
    assert "market closed" in portfolio.tick(store, D)["note"] and portfolio.load_book(store)["positions"] == {}
    monkeypatch.setattr(portfolio, "us_session", lambda: "REGULAR")
    monkeypatch.setattr(paper_live, "fresh_price", lambda sn, n: (100.0, ""))
    from stockwatch import live
    monkeypatch.setattr(live, "current_portfolio", lambda st, wide=False: type("P", (), {"holdings": [Holding("AAA", 1, 10, 90.0)]})())
    out = portfolio.tick(store, D)
    assert out["watching"] == 1 and "AAA" in portfolio.load_book(store)["positions"]
    assert portfolio.status(store)["book"]["seeded"]


def test_the_view_data_adds_up_with_the_shared_money_summary():
    b = book_with(AAA=(10.0, 100.0), BBB=(5.0, 50.0))
    m = pl.money(b["cash"], b["start"], b["positions"], {"AAA": 110.0, "BBB": 40.0})
    assert m["realized"] == pytest.approx(0.0) and m["unreal"] == pytest.approx(50.0)
    json.dumps(b)


def test_the_page_renders_every_part_and_escapes_text():
    from stockwatch import portfolio_view as pv
    b = book_with(AAA=(3.0, 100.0), BBB=(10.0, 50.0))
    b["seeded"] = "2026-11-08 12:00"
    portfolio._log(b, D, "AAA", "TRIM", 1.0, 90.0, "the call is EXIT <b>and</b> weak", -10.0)
    b["proposals"]["BBB"] = {"since": "x", "price": 40.0, "shares": 10.0, "why": "weak"}
    portfolio._hold_back(b, D, "AAA", 90.0, "ADD held back: volume only 0.5x normal")
    html = pv.html({"book": b, "state": {"watching": 5, "gate": ""}}, {"AAA": 90.0, "BBB": 40.0}, D)
    assert "?view=target&t=AAA" in html and "EXIT PROPOSED" in html and "TRIMMED" in html or "1 trim or sale" in html
    assert "&lt;b&gt;" in html and "<b>and</b>" not in html
    assert "Not started yet" in pv.html({"book": portfolio.new_book(), "state": None})
