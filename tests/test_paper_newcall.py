"""The New call paper account (stockwatch/paper_newcall.py): pure rule tests on a fake book."""
from datetime import datetime

from stockwatch import paper, paper_newcall
from stockwatch.data import NY


def at(h, m):                       # a Tuesday in New York
    return datetime(2026, 10, 27, h, m, tzinfo=NY)


def snap(call="BUY", line=95.0, band=94.0, grade="Moderate", known=True, change=0.005, vol=1_000_000.0, atr=2.0):
    oc = {"known": known, "call": call, "why": "test", "exit_line": line, "band_line": band, "risk": {"grade": grade}}
    return {"ticker": "AAA", "payload": {"technical": {"one_call": oc, "atr": atr, "vol_avg20": 1_000_000.0},
                                         "quote": {"live_change": change, "live_volume": vol}}}


def test_enters_on_buy_and_sizes_to_one_percent():
    book = paper.Book()
    did = paper_newcall.step(book, {"AAA": snap(line=92.0, band=91.0)}, {"AAA": 100.0}, at(11, 0))
    assert [d["action"] for d in did] == ["ENTER"]
    pos = book.positions["AAA"]
    assert pos["shares"] == 62 and pos["stop"] == 91.0           # $500 risk / $8 to the line
    assert book.trades[0]["risk"] == 496.0


def test_high_risk_gets_half_size_and_cap_applies():
    book = paper.Book()
    paper_newcall.step(book, {"AAA": snap(line=92.0, band=91.0, grade="High")}, {"AAA": 100.0}, at(11, 0))
    assert book.positions["AAA"]["shares"] == 31
    book2 = paper.Book()
    paper_newcall.step(book2, {"AAA": snap(line=99.9, band=99.0)}, {"AAA": 100.0}, at(11, 0))
    assert book2.positions["AAA"]["shares"] * 100 <= 50_000 * 0.15 + 100     # capped at 15% of the account


def test_no_entry_in_opening_hour_late_or_without_a_call():
    for when in (at(10, 15), at(15, 50)):
        book = paper.Book()
        assert paper_newcall.step(book, {"AAA": snap()}, {"AAA": 100.0}, when) == []
    for s in (snap(call="WAIT FOR TURN"), snap(known=False), snap(call="AVOID")):
        book = paper.Book()
        assert paper_newcall.step(book, {"AAA": s}, {"AAA": 100.0}, at(11, 0)) == []
    book = paper.Book()
    assert paper_newcall.step(book, {"AAA": snap()}, {"AAA": 100.0}, at(18, 0)) == []     # market closed


def test_price_under_the_line_does_not_enter():
    book = paper.Book()
    assert paper_newcall.step(book, {"AAA": snap()}, {"AAA": 94.0}, at(11, 0)) == []


def test_exit_on_call_turn_and_at_1545_under_band():
    book = paper.Book()
    paper_newcall.step(book, {"AAA": snap(atr=6.0)}, {"AAA": 100.0}, at(11, 0))
    # an intraday dip under the band does nothing before 15:45
    assert paper_newcall.step(book, {"AAA": snap(call="HOLD", atr=6.0)}, {"AAA": 94.7}, at(12, 0)) == []
    assert "AAA" in book.positions
    did = paper_newcall.step(book, {"AAA": snap(call="HOLD", atr=6.0)}, {"AAA": 93.0}, at(15, 46))
    assert did[0]["action"] == "SELL_ALL" and "AAA" not in book.positions
    book = paper.Book()
    paper_newcall.step(book, {"AAA": snap()}, {"AAA": 100.0}, at(11, 0))
    did = paper_newcall.step(book, {"AAA": snap(call="EXIT")}, {"AAA": 96.0}, at(12, 0))
    assert did[0]["action"] == "SELL_ALL" and book.trades[0]["status"] == "CLOSED"


def test_max_positions():
    book = paper.Book()
    snaps = {f"T{i}": {**snap(line=80.0, band=79.0), "ticker": f"T{i}"} for i in range(12)}
    for m in (0, 16, 32, 48, 64):                                   # entries are paced: 3 per 15 minutes
        paper_newcall.step(book, snaps, {k: 100.0 for k in snaps}, at(11, 0) .replace(hour=11 + (m // 60), minute=m % 60))
    assert len(book.positions) == paper_newcall.MAX_POSITIONS


def test_same_day_check_holds_back_a_falling_or_unknown_day():
    for change, word in ((-0.012, "down 1.2%"), (None, "unknown")):
        book = paper.Book()
        assert paper_newcall.step(book, {"AAA": snap(change=change)}, {"AAA": 100.0}, at(11, 0)) == []
        assert not book.positions and word in book.blocked[-1]["reason"]
    book = paper.Book()
    paper_newcall.step(book, {"AAA": snap(change=-0.012)}, {"AAA": 100.0}, at(11, 0))
    paper_newcall.step(book, {"AAA": snap(change=-0.012)}, {"AAA": 100.0}, at(11, 1))
    assert len(book.blocked) == 1                      # the same reason is not logged every cycle
    did = paper_newcall.step(book, {"AAA": snap(change=0.0)}, {"AAA": 100.0}, at(11, 2))
    assert did and did[0]["action"] == "ENTER"


def test_forced_sell_closes_every_open_trade_and_enters_nothing():
    book = paper.Book()
    paper_newcall.step(book, {"AAA": snap()}, {"AAA": 100.0}, at(11, 0))
    assert "AAA" in book.positions
    did = paper_newcall.step(book, {"AAA": snap()}, {"AAA": 101.0}, at(11, 1), force=True)
    assert [d["action"] for d in did] == ["SELL_ALL"] and "AAA" not in book.positions
    assert "forced sell" in book.trades[0]["exit_reason"] if "exit_reason" in book.trades[0] else True
    assert paper_newcall.step(book, {"AAA": snap()}, {"AAA": 101.0}, at(11, 2), force=True) == []       # nothing to sell, no entry either
    assert [d["action"] for d in paper_newcall.step(book, {"AAA": snap()}, {"AAA": 101.0}, at(11, 3))] == ["ENTER"]   # the next normal cycle picks again



def at_day(d, h, m):
    return datetime(2026, 10, d, h, m, tzinfo=NY)


def test_no_setup_no_buy_when_the_volume_is_light_or_unread():
    book = paper.Book()
    assert paper_newcall.step(book, {"AAA": snap(vol=100_000.0)}, {"AAA": 100.0}, at(11, 0)) == []     # about 0.3x normal
    assert "no setup is established" in book.blocked[-1]["reason"]
    s = snap()
    del s["payload"]["quote"]["live_volume"]
    book = paper.Book()
    assert paper_newcall.step(book, {"AAA": s}, {"AAA": 100.0}, at(11, 0)) == [] and "not read" in book.blocked[-1]["reason"]


def test_riding_trails_the_stop_under_the_peak_and_sells_when_it_is_hit():
    book = paper.Book()
    paper_newcall.step(book, {"AAA": snap(line=92.0, band=91.0)}, {"AAA": 100.0}, at(11, 0))
    assert paper_newcall.step(book, {"AAA": snap(line=92.0, band=91.0)}, {"AAA": 102.0}, at(11, 5)) == []
    pos = book.positions["AAA"]
    assert pos["trail"] == 100.0                                 # up one daily range: the stop is at least the entry
    paper_newcall.step(book, {"AAA": snap(line=92.0, band=91.0)}, {"AAA": 106.0}, at(12, 0))
    assert book.positions["AAA"]["trail"] == 104.0               # one range under the peak of 106
    did = paper_newcall.step(book, {"AAA": snap(line=92.0, band=91.0)}, {"AAA": 103.5}, at(12, 5))
    assert did[0]["action"] == "SELL_ALL" and "riding ended" in did[0]["reason"] and book.trades[0]["result"] > 0


def test_a_stalled_trade_with_a_tight_day_and_no_volume_is_sold_but_not_on_its_first_day_or_while_busy():
    book = paper.Book()
    paper_newcall.step(book, {"AAA": snap(line=92.0, band=91.0)}, {"AAA": 100.0}, at_day(27, 11, 0))
    quiet = snap(call="HOLD", line=92.0, band=91.0, vol=300_000.0)
    for m in range(0, 30, 5):                                      # the next day: a flat tape
        paper_newcall.step(book, {"AAA": quiet}, {"AAA": 99.8 + 0.1 * (m % 10 == 0)}, at_day(28, 10, m))
    assert "AAA" in book.positions                                 # before 14:00 nothing is judged
    busy = snap(call="HOLD", line=92.0, band=91.0, vol=3_000_000.0)
    assert paper_newcall.step(book, {"AAA": busy}, {"AAA": 99.9}, at_day(28, 14, 30)) == []
    did = paper_newcall.step(book, {"AAA": quiet}, {"AAA": 99.9}, at_day(28, 14, 35))
    assert did[0]["action"] == "SELL_ALL" and "stalled" in did[0]["reason"] and "to free the cash" in did[0]["reason"]
    book = paper.Book()                                            # the same flat day on the day it was bought: held
    paper_newcall.step(book, {"AAA": snap(line=92.0, band=91.0)}, {"AAA": 100.0}, at_day(28, 11, 0))
    assert paper_newcall.step(book, {"AAA": quiet}, {"AAA": 100.1}, at_day(28, 14, 35)) == []


def test_a_beaten_trade_is_sold_live_under_its_exit_line_or_far_under_the_entry():
    def open_at_100(**kw):
        book = paper.Book()
        paper_newcall.step(book, {"AAA": snap(atr=6.0, **kw)}, {"AAA": 100.0}, at(11, 0))
        return book

    book = open_at_100(line=95.0, band=80.0)                    # range 6: the quarter-range margin under the line 99 is 1.5
    assert paper_newcall.step(book, {"AAA": snap(line=99.0, band=80.0, atr=6.0)}, {"AAA": 97.6}, at(11, 30)) == []   # under by 1.4: held
    did = paper_newcall.step(book, {"AAA": snap(line=99.0, band=80.0, atr=6.0)}, {"AAA": 97.0}, at(11, 31))
    assert did[0]["action"] == "SELL_ALL" and "beaten" in did[0]["reason"] and "exit line 99.00" in did[0]["reason"]
    book = open_at_100(line=95.0, band=80.0)                    # the line far below: only the 1.5-range cut (under 91) can fire
    assert paper_newcall.step(book, {"AAA": snap(line=80.0, band=70.0, atr=6.0)}, {"AAA": 91.2}, at(11, 30)) == []
    did = paper_newcall.step(book, {"AAA": snap(line=80.0, band=70.0, atr=6.0)}, {"AAA": 90.9}, at(11, 31))
    assert did[0]["action"] == "SELL_ALL" and "daily ranges" in did[0]["reason"]
    book = open_at_100(line=95.0, band=80.0)                    # a winner above its line is never beaten
    assert paper_newcall.step(book, {"AAA": snap(line=95.0, band=80.0, atr=6.0)}, {"AAA": 104.0}, at(11, 30)) == []


def test_new_call_buys_are_paced_and_paused_by_the_market_gate():
    book = paper.Book()
    names = {f"S{i}": snap() for i in range(5)}
    for k, v in names.items():
        v["ticker"] = k
    did = paper_newcall.step(book, names, {k: 100.0 for k in names}, at(11, 0))
    assert [d["action"] for d in did] == ["ENTER"] * 3 and any("pace limit" in b["reason"] for b in book.blocked)
    paper_newcall.step(book, names, {k: 100.0 for k in names}, at(11, 20))       # 15+ minutes later two more can enter
    assert len(book.positions) == 5
    book = paper.Book()
    down = {f"D{i}": snap(change=-0.02) for i in range(25)}
    for k, v in down.items():
        v["ticker"] = k
    assert paper_newcall.step(book, down, {k: 100.0 for k in down}, at(11, 0)) == []


# ---- 1 Nov (owner): no weak stock, falling-or-stabilising at -1%, riding-or-stalled at +2%, ranked entries
def _status(code, momentum=None, second=None):
    s = snap(line=92.0, band=91.0)
    s["payload"]["technical"]["price_status"] = {"code": code, "second": second}
    if momentum:
        s["payload"]["technical"]["momentum"] = {"known": True, "momentum": momentum}
    return s


def test_a_weak_stock_is_not_bought_but_a_weak_chart_alone_is_not_weak():
    assert paper_newcall.weak_reason(_status("breakdown")).startswith("weak: a completed close under support")
    assert paper_newcall.weak_reason(_status("weakening")) is None                       # buying near support is the design
    assert "momentum is falling" in paper_newcall.weak_reason(_status("weakening", "falling"))
    assert "TradingView says SELL" in paper_newcall.weak_reason(_status("testing_support", second={"signal": "sell", "source": "TradingView"}))
    assert paper_newcall.weak_reason(_status("strong_uptrend", "falling")) is None
    assert paper_newcall.weak_reason(snap()) is None                                     # no status read: never blocks
    book = paper.Book()
    assert paper_newcall.step(book, {"AAA": _status("weakening", "falling")}, {"AAA": 100.0}, at(11, 0)) == []
    assert "weak: the chart reads weakening" in book.blocked[-1]["reason"]
    book2 = paper.Book()
    assert paper_newcall.step(book2, {"AAA": _status("pullback")}, {"AAA": 100.0}, at(11, 0))[0]["action"] == "ENTER"


def _open_one():
    book = paper.Book()
    paper_newcall.step(book, {"AAA": snap(line=92.0, band=91.0)}, {"AAA": 100.0}, at(11, 0))
    return book, {"AAA": snap(line=92.0, band=91.0)}


def test_down_one_percent_is_watched_and_a_stock_that_keeps_falling_is_abandoned():
    book, s = _open_one()
    assert paper_newcall.step(book, s, {"AAA": 98.8}, at(11, 10)) == []                  # -1.2%: the watch begins, nothing sold yet
    assert "watching" in book.positions["AAA"]["read"]
    did = paper_newcall.step(book, s, {"AAA": 98.2}, at(11, 15))                         # a new low with no bounce
    assert did[0]["action"] == "SELL_ALL" and did[0]["reason"].startswith("falling") and "not stabilising" in did[0]["reason"]


def test_down_one_percent_that_bounces_is_left_alone_and_one_that_just_sits_is_sold_after_twenty_minutes():
    book, s = _open_one()
    paper_newcall.step(book, s, {"AAA": 98.8}, at(11, 10))
    assert paper_newcall.step(book, s, {"AAA": 98.55}, at(11, 12)) == []                 # a slightly lower low: not yet a 0.5% slide
    assert paper_newcall.step(book, s, {"AAA": 98.9}, at(11, 20)) == []                  # bounced 0.35% off the low: stabilising
    assert "stabilising" in book.positions["AAA"]["read"]
    assert paper_newcall.step(book, s, {"AAA": 99.6}, at(11, 25)) == [] and book.positions["AAA"]["dip"] is None   # back above -1%
    book2, s2 = _open_one()
    paper_newcall.step(book2, s2, {"AAA": 98.8}, at(11, 10))
    paper_newcall.step(book2, s2, {"AAA": 98.7}, at(11, 20))
    did = paper_newcall.step(book2, s2, {"AAA": 98.7}, at(11, 31))                       # 21 minutes down, no bounce
    assert did[0]["action"] == "SELL_ALL" and "no bounce" in did[0]["reason"]


def test_up_two_percent_riding_is_held_and_stalled_is_sold_locking_the_profit():
    book, s = _open_one()
    paper_newcall.step(book, s, {"AAA": 102.1}, at(11, 10))                              # +2.1%: from here it is read
    assert book.positions["AAA"]["up2"]
    assert paper_newcall.step(book, s, {"AAA": 102.6}, at(11, 40)) == []                 # a new high 30 minutes later: riding
    assert "riding" in book.positions["AAA"]["read"]
    assert paper_newcall.step(book, s, {"AAA": 102.3}, at(12, 20)) == []                 # 40 minutes since the high: not yet 45
    did = paper_newcall.step(book, s, {"AAA": 101.9}, at(12, 30))                        # 50 minutes, 0.7% under the peak
    assert did[0]["action"] == "SELL_ALL" and did[0]["reason"].startswith("stalled: was up to 102.60") and book.trades[0]["result"] > 0


def test_setups_are_ranked_and_the_best_enter_first():
    book = paper.Book()
    names = {}
    for i, vol in enumerate([900_000.0, 3_000_000.0, 1_200_000.0, 2_500_000.0, 1_000_000.0]):
        k = f"S{i}"
        names[k] = snap(vol=vol, change=0.004)
        names[k]["ticker"] = k
    did = paper_newcall.step(book, names, {k: 100.0 for k in names}, at(11, 0))
    entered = [d["ticker"] for d in did]
    assert len(entered) == 3 and set(entered) == {"S1", "S3", "S2"}                      # the three with the most volume confirmation
    assert "[ranked #1 of 5" in did[0]["reason"]
    held = {b["ticker"]: b["reason"] for b in book.blocked}
    assert "ranked #4 of 5" in held["S4"] and "ranked #5 of 5" in held["S0"]
