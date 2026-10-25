from datetime import datetime

from stockwatch import decision, paper
from stockwatch.data import NY
from test_dayboard import make


def at(h, m):
    return datetime(2026, 10, 26, h, m, tzinfo=NY)          # a Monday


def buy_snap(**kw):
    s = make("NOW", "strong_uptrend", mom="strong", **kw)
    s["ticker"] = "AAA"
    s["payload"]["plan"].update(entry=99.5, risk_per_share=4.5)
    return s


def held(**kw):
    return {"shares": 50, "entry": 99.5, "stop": 95.0, "stage": "full", "t1_done": False, "below_since": None, **kw}


def test_no_entry_in_the_first_hour_then_enters_in_the_zone_with_a_limit():
    s = buy_snap()
    assert decision.decide(s, None, 99.5, at(10, 0))["action"] == "NONE"
    d = decision.decide(s, None, 99.5, at(11, 30))
    assert d["action"] == "ENTER" and d["limit"] == 99.5
    assert decision.decide(s, None, 103.0, at(11, 30))["reason"] == "price is not in the entry zone"
    assert decision.decide(s, None, 99.5, at(8, 0))["reason"] == "market closed"
    assert decision.decide(s, None, None, at(11, 0))["reason"] == "no price"


def test_a_failed_gate_or_earnings_blocks_the_entry_and_the_block_is_recorded():
    bad = make("NOW", "strong_uptrend", mom="falling")
    bad["ticker"] = "BBB"
    d = decision.decide(bad, None, 99.5, at(11, 30))
    assert d["action"] == "NONE" and d["blocked"] and "momentum is falling" in d["reason"]
    soon = buy_snap()
    soon["payload"]["events"] = {"days_to_earnings": 1}
    assert "earnings in 1 day" in decision.decide(soon, None, 99.5, at(11, 30))["reason"]
    book = paper.Book()
    paper.step(book, {"BBB": bad}, {"BBB": 99.5}, at(11, 30))
    paper.step(book, {"BBB": bad}, {"BBB": 99.5}, at(11, 40))
    assert len(book.blocked) == 1 and book.blocked[0]["ticker"] == "BBB"


def test_a_dip_through_the_floor_is_only_an_alert_until_3_45_then_sells_half():
    s = buy_snap()
    d = decision.decide(s, held(), 97.0, at(14, 0))
    assert d["action"] == "ALERT" and "3:45" in d["reason"]
    d = decision.decide(s, held(), 97.0, at(15, 45))
    assert d["action"] == "SELL_PART" and d["fraction"] == 0.5
    assert decision.decide(s, held(stage="half"), 97.0, at(15, 50))["action"] == "HOLD"
    assert decision.decide(s, held(), 97.0, at(15, 45), decision.Config(half_on_warning=False))["action"] == "SELL_ALL"


def test_the_crwv_morning_a_dip_below_the_stop_that_recovers_never_sells():
    s = buy_snap()
    pos = held()
    d = decision.decide(s, pos, 94.0, at(9, 45))                      # down through the stop in the first minutes
    assert d["action"] == "ALERT" and d["mark_below"]
    pos["below_since"] = at(9, 45)
    d = decision.decide(s, pos, 98.5, at(10, 5))                      # it recovers
    assert d["action"] == "HOLD" and d["clear_below"]
    pos["below_since"] = None
    decision.decide(s, pos, 94.0, at(10, 40))
    pos["below_since"] = at(10, 40)
    assert decision.decide(s, pos, 94.0, at(11, 0))["action"] == "ALERT"            # only 20 of 30 minutes
    assert decision.decide(s, pos, 94.0, at(11, 15))["action"] == "SELL_ALL"        # 35 minutes, past the first hour


def test_a_gap_far_through_the_stop_sells_at_once_and_a_first_hour_breach_waits():
    s = buy_snap()
    s["payload"]["technical"]["atr"] = 2.0
    assert decision.decide(s, held(), 90.0, at(9, 35))["action"] == "SELL_ALL"      # 5 below the stop, 2.5 ranges
    pos = held(below_since=at(9, 35))
    assert decision.decide(s, pos, 94.0, at(10, 0))["action"] == "ALERT"            # confirmed 25 min and still inside the first hour


def test_the_first_target_sells_a_third_and_moves_the_stop_to_the_entry():
    s = buy_snap()
    mixed = make("NOW", "strong_uptrend", mom="stabilising")             # not strong: the old rule
    mixed["ticker"] = "AAA"
    mixed["payload"]["plan"].update(entry=99.5, risk_per_share=4.5)
    d = decision.decide(mixed, held(), 108.5, at(13, 0))
    assert d["action"] == "SELL_PART" and abs(d["fraction"] - 1 / 3) < 1e-9 and d["move_stop_to_entry"]
    assert decision.decide(s, held(), 108.5, at(13, 0), decision.Config(stretch=False))["action"] == "SELL_PART"


def stretching(**kw):
    return held(**{"stretch": True, "stop0": 95.0, "weak_since": None, **kw})


def test_a_strong_trend_at_the_first_target_stretches_instead_of_selling():
    s = buy_snap()
    s["payload"]["technical"]["price_status"]["levels"] = {"support_low": 104.0}
    d = decision.decide(s, held(), 108.5, at(13, 0))
    assert d["action"] == "HOLD" and d["start_stretch"] and d["set_stop"] == 104.0
    s["payload"]["technical"]["price_status"]["levels"] = {"support_low": 98.0}
    assert decision.decide(s, held(), 108.5, at(13, 0))["set_stop"] == 99.5            # never below the entry


def test_a_stretch_trails_the_stop_up_and_never_down():
    s = buy_snap()
    s["payload"]["technical"]["price_status"]["levels"] = {"support_low": 106.0}
    d = decision.decide(s, stretching(stop=104.0), 112.0, at(13, 0))
    assert d["action"] == "HOLD" and d["set_stop"] == 106.0
    s["payload"]["technical"]["price_status"]["levels"] = {"support_low": 101.0}
    assert "set_stop" not in decision.decide(s, stretching(stop=104.0), 112.0, at(13, 5))


def test_a_stretch_sells_a_third_at_the_cap_and_everything_when_the_trend_stays_turned():
    s = buy_snap()
    d = decision.decide(s, stretching(stop=104.0), 114.5, at(13, 0))                    # 99.5 + 3 x 4.5 = 113
    assert d["action"] == "SELL_PART" and d["end_stretch"] and abs(d["fraction"] - 1 / 3) < 1e-9
    bad = make("NOW", "strong_uptrend", mom="falling")
    bad["ticker"] = "AAA"
    bad["payload"]["plan"].update(entry=99.5, risk_per_share=4.5)
    d = decision.decide(bad, stretching(stop=99.5), 108.0, at(13, 0))
    assert d["action"] == "ALERT" and d["mark_weak"]
    assert decision.decide(bad, stretching(stop=99.5, weak_since=at(12, 50)), 108.0, at(13, 0))["action"] == "ALERT"   # 10 of 30
    assert decision.decide(bad, stretching(stop=99.5, weak_since=at(12, 20)), 108.0, at(13, 0))["action"] == "SELL_ALL"
    d = decision.decide(s, stretching(stop=99.5, weak_since=at(12, 50)), 108.0, at(13, 0))     # it recovered
    assert d["action"] == "HOLD" and d["clear_weak"]


def test_a_stretched_trade_is_journalled_and_compared_with_selling_at_the_target():
    s = buy_snap()
    s["payload"]["technical"]["price_status"]["levels"] = {"support_low": 104.0}
    book = paper.Book()
    paper.step(book, {"AAA": s}, {"AAA": 99.5}, at(11, 30))
    done = paper.step(book, {"AAA": s}, {"AAA": 108.5}, at(13, 0))
    pos = book.positions["AAA"]
    assert done[0]["action"] == "STRETCH" and pos["stretch"] and pos["stop"] == 104.0 and pos["shares"] == book.trades[0]["shares"]
    paper.step(book, {"AAA": s}, {"AAA": 103.0}, at(13, 5))                              # falls through the trailed stop
    paper.step(book, {"AAA": s}, {"AAA": 103.0}, at(13, 40))
    t = book.trades[0]
    assert t["status"] == "CLOSED" and t["stretched"] and t["at_target"] > t["result"]
    r = paper.report(book)
    assert r["stretched"] == 1 and r["stretch_gain"] < 0


def test_a_day_on_the_book_buys_sells_and_journals_with_r():
    s = buy_snap()
    book = paper.Book()
    done = paper.step(book, {"AAA": s}, {"AAA": 99.5}, at(11, 30))
    assert [x["action"] for x in done] == ["ENTER"] and "AAA" in book.positions
    pos = book.positions["AAA"]
    assert pos["shares"] * 99.5 <= 0.15 * 50000 + 100 and book.cash < 50000          # capped by the 15% limit
    paper.step(book, {"AAA": s}, {"AAA": 108.5}, at(13, 0), decision.Config(stretch=False))   # a third at the target, stop to entry
    assert book.positions["AAA"]["stop"] == 99.5 and book.positions["AAA"]["t1_done"]
    paper.step(book, {"AAA": s}, {"AAA": 97.0}, at(15, 45))                         # warning exit: half of what is left
    big = {**s, "payload": {**s["payload"], "plan": {**s["payload"]["plan"], "stop": 99.5}}}
    pos["below_since"] = at(13, 0).isoformat()
    paper.step(book, {"AAA": big}, {"AAA": 97.0}, at(15, 55))
    t = book.trades[0]
    assert t["status"] == "CLOSED" and t["result"] is not None and t["exit_reason"] and t["worst"] <= 0 <= t["best"]
    r = paper.report(book)
    assert r["closed"] == 1 and "Too few trades" in r["verdict"] and r["blocked"] == 0


def test_the_report_waits_for_thirty_trades_and_the_book_round_trips():
    book = paper.Book()
    book.trades = [{"status": "CLOSED", "result": 100.0 if i % 2 else -50.0, "r": 1.0 if i % 2 else -0.5} for i in range(30)]
    assert paper.report(book)["verdict"].startswith("KEEP")
    book.trades = [{"status": "CLOSED", "result": -50.0, "r": -0.5} for _ in range(30)]
    assert paper.report(book)["verdict"].startswith("TIGHTEN")
    again = paper.Book.from_dict(book.to_dict())
    assert again.cash == book.cash and len(again.trades) == 30 and paper.Book.from_dict(None).cash == paper.START_CASH
