"""The market-crash flag and the way back: it asks the owner, pauses new entries, and never decides alone."""
from datetime import datetime, timedelta

from stockwatch import crash, paper, paper_layout as pl, paper_live, paper_newcall, quick
from stockwatch.data import NY

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=NY)


class FakeStore:
    def __init__(self):
        self.s = {}

    def get_setting(self, k):
        return self.s.get(k)

    def set_setting(self, k, v):
        self.s[k] = v

    def snapshot(self, t):
        return {"ticker": t, "payload": {}}


def market(chg, n=30):
    return {f"S{i}": {"payload": {"quote": {"live_change": chg}}} for i in range(n)}


def mixed(down, chg_down=-0.002, chg_up=0.004, n=30):
    k = int(n * down)
    return {f"S{i}": {"payload": {"quote": {"live_change": chg_down if i < k else chg_up}}} for i in range(n)}


def run(store, acct, snaps, start, minutes):
    out = ""
    for m in range(minutes + 1):
        out = crash.check(store, acct, snaps, start + timedelta(minutes=m))
    return out


def test_a_crash_raises_the_flag_only_after_it_holds_and_pushes_once(monkeypatch):
    pushes = []
    monkeypatch.setattr("stockwatch.events._push", lambda *a, **k: pushes.append(a[0]) or "sent")
    store = FakeStore()
    assert run(store, "quick", market(-0.02), T0, 1) == ""                       # two minutes: not yet
    assert crash.load(store, "quick", T0)["state"] == "watching"
    halt = run(store, "quick", market(-0.02), T0 + timedelta(minutes=2), 5)
    assert "waiting for the owner" in halt and crash.load(store, "quick", T0)["state"] == "asked"
    assert len(pushes) == 1 and "crashing" in pushes[0]
    assert crash.check(store, "newcall", market(-0.02), T0) == ""                # each account has its own state


def test_a_dip_that_does_not_hold_and_a_thin_sample_never_flag(monkeypatch):
    monkeypatch.setattr("stockwatch.events._push", lambda *a, **k: "sent")
    store = FakeStore()
    crash.check(store, "quick", market(-0.02), T0)
    crash.check(store, "quick", market(0.0), T0 + timedelta(minutes=2))          # recovered before three minutes: the clock resets
    assert crash.check(store, "quick", market(-0.02), T0 + timedelta(minutes=4)) == ""
    assert crash.reading(market(-0.05, n=5)) is None
    assert crash.check(FakeStore(), "quick", market(-0.05, n=5), T0) == ""


def test_keep_going_lifts_the_pause_and_does_not_ask_again(monkeypatch):
    monkeypatch.setattr("stockwatch.events._push", lambda *a, **k: "sent")
    store = FakeStore()
    run(store, "quick", market(-0.02), T0, 4)
    assert crash.answer(store, "quick", "keep", T0)["ok"]
    assert crash.check(store, "quick", market(-0.03), T0 + timedelta(minutes=10)) == ""
    assert crash.load(store, "quick", T0)["state"] == "kept"


def test_stop_sells_everything_open_and_the_pause_stays(monkeypatch):
    monkeypatch.setattr("stockwatch.events._push", lambda *a, **k: "sent")
    monkeypatch.setattr(quick, "us_session", lambda: "REGULAR")
    monkeypatch.setattr(paper_live, "fresh_price", lambda snap, now: (99.0, ""))
    store = FakeStore()
    book = quick.new_book()
    quick._enter(book, "AAA", "bounce", "t", 100.0, 98.0, 1.0, T0)
    quick._enter(book, "BBB", "breakout", "t", 50.0, 49.0, 1.0, T0)
    quick.save_book(store, book)
    run(store, "quick", market(-0.02), T0, 4)
    out = crash.answer(store, "quick", "stop", T0 + timedelta(minutes=6))
    assert out["ok"] and "Sold 2" in out["note"]
    book = quick.load_book(store, migrate=False)
    assert book["positions"] == {} and all("market crash stop" in t["exit_reason"] and pl.is_override(t) for t in book["trades"])
    assert book["cash"] == book["start"] + sum(t["result"] for t in book["trades"])
    assert crash.check(store, "quick", market(-0.02), T0 + timedelta(minutes=7)) == crash.HALTED["stopped"]


def test_after_a_stop_a_recovery_asks_to_resume_and_the_owner_decides(monkeypatch):
    pushes = []
    monkeypatch.setattr("stockwatch.events._push", lambda *a, **k: pushes.append(a[0]) or "sent")
    store = FakeStore()
    run(store, "newcall", market(-0.02), T0, 4)
    crash.answer(store, "newcall", "stop", T0 + timedelta(minutes=5))             # nothing open: fine
    halt = run(store, "newcall", mixed(0.5), T0 + timedelta(minutes=6), 3)   # recovering but not for five minutes yet
    assert halt == crash.HALTED["stopped"]
    halt = run(store, "newcall", mixed(0.5), T0 + timedelta(minutes=9), 4)
    assert crash.load(store, "newcall", T0)["state"] == "reopen_asked" and "recovering" in pushes[-1]
    assert halt == crash.HALTED["reopen_asked"]                                   # still paused until the owner answers
    assert crash.answer(store, "newcall", "resume", T0)["ok"]
    assert crash.check(store, "newcall", mixed(0.5), T0 + timedelta(minutes=20)) == ""


def test_stay_stopped_and_a_new_day_starts_clean(monkeypatch):
    monkeypatch.setattr("stockwatch.events._push", lambda *a, **k: "sent")
    store = FakeStore()
    run(store, "quick", market(-0.02), T0, 4)
    crash.answer(store, "quick", "stop", T0)
    run(store, "quick", mixed(0.5), T0 + timedelta(minutes=6), 8)
    crash.answer(store, "quick", "stay", T0)
    assert crash.check(store, "quick", market(0.01), T0 + timedelta(minutes=30)) == crash.HALTED["stayed"]
    assert not crash.answer(store, "quick", "keep", T0)["ok"]                      # a wrong tap for this state does nothing
    assert crash.check(store, "quick", market(0.01), T0 + timedelta(days=1)) == ""   # next day: watching again


def test_a_pause_blocks_new_entries_in_both_accounts_but_not_exits():
    from test_paper_newcall import snap as nc_snap
    book = paper.Book()
    did = paper_newcall.step(book, {"AAA": nc_snap(line=92.0, band=91.0)}, {"AAA": 100.0}, datetime(2026, 11, 5, 11, 0, tzinfo=NY), halt="paused: test")
    assert did == [] and not book.positions and "paused: test" in book.blocked[-1]["reason"]
    did = paper_newcall.step(book, {"AAA": nc_snap(line=92.0, band=91.0)}, {"AAA": 100.0}, datetime(2026, 11, 5, 11, 1, tzinfo=NY))
    assert did and "AAA" in book.positions                                         # without the pause the same stock is bought
    qb = quick.new_book()
    quick._enter(qb, "OPEN", "bounce", "t", 100.0, 98.0, 1.0, T0)
    from test_quick import snap as q_snap
    quick.step(qb, {}, {"OPEN": q_snap()}, {"OPEN": 97.0}, T0 + timedelta(minutes=1), halt="paused: test")
    assert "OPEN" not in qb["positions"]                                           # a stop is still honoured while paused


def test_crash_stop_sales_do_not_block_a_rebuy_after_a_resume():
    from test_paper_newcall import snap as nc_snap
    book = paper.Book()
    now = datetime(2026, 11, 5, 11, 0, tzinfo=NY)
    paper_newcall.step(book, {"AAA": nc_snap(line=92.0, band=91.0)}, {"AAA": 100.0}, now)
    paper._sell(book, "AAA", 99.0, 1.0, now, "owner override: market crash stop at 99.00")
    did = paper_newcall.step(book, {"AAA": nc_snap(line=92.0, band=91.0)}, {"AAA": 100.0}, now + timedelta(minutes=30))
    assert did and "AAA" in book.positions
