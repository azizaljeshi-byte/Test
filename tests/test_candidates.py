"""The shared candidates list (stockwatch/candidates.py): who qualifies, the two scan times and the per-account rows."""
import json
from datetime import datetime

from stockwatch import candidates, paper, paper_newcall, quick
from stockwatch.data import NY
from stockwatch.store import Store


def snap(t, ext=None, prev=100.0, atr=2.0, call="WAIT", days=None, live=None):
    oc = {"known": True, "call": call, "why": "x", "exit_line": 95.0, "band_line": 94.0, "risk": {"grade": "Moderate"}}
    q = {"regular_price": prev, "ext_session": "pre" if ext else None, "ext_price": ext, "ext_stale": False}
    if live:
        q.update(live_price=live, live_change=live / prev - 1)
    return {"ticker": t, "payload": {"technical": {"atr": atr, "one_call": oc}, "quote": q, "events": {"days_to_earnings": days}}}


def put(store, s):
    store.conn.execute("INSERT INTO snapshots (scanned_at, ticker, tier, price, technical_score, fundamental_score, composite, verdict, payload)"
                       " VALUES (?,?,?,?,?,?,?,?,?)", ("2026-10-30T12:00:00", s["ticker"], 2, 100.0, 0, 0, 0, "BUY", json.dumps(s["payload"])))
    store.conn.commit()


def test_a_gap_down_a_gap_up_and_a_buy_call_qualify_and_earnings_or_a_quiet_stock_do_not():
    assert "bounce candidate" in candidates.qualify(snap("A", ext=97.0), "pre-open")["qualified"]        # -3% = 1.5 ranges
    assert "breakout candidate" in candidates.qualify(snap("B", ext=102.0), "pre-open")["qualified"]     # +2% = 1.0 range
    both = candidates.qualify(snap("C", ext=102.0, call="ADD"), "pre-open")
    assert "Quick" in both["qualified"] and "New call: ADD" in both["qualified"]
    assert candidates.qualify(snap("D", ext=100.4), "pre-open") is None                                   # quiet and not a buy call
    assert candidates.qualify(snap("E", ext=97.0, days=1), "pre-open") is None                           # earnings tomorrow
    assert candidates.qualify(snap("F", ext=None), "pre-open") is None                                   # no pre-market trade: unknown, never a pass
    assert candidates.qualify(snap("G", live=102.0), "refresh")["move_pct"] == 2.0


def test_the_scans_run_once_each_at_0920_and_1000_new_york_and_the_rows_follow_the_accounts(tmp_path):
    store = Store(tmp_path / "t.db")
    put(store, snap("A", ext=97.0))
    put(store, snap("B", ext=100.1, call="BUY"))
    day = datetime(2026, 10, 30, 9, 15, tzinfo=NY)
    assert candidates.tick(store, day)["scanned"] is None                                                 # too early
    assert candidates.tick(store, day.replace(minute=20)) == {"scanned": "pre-open", "added": 2}
    assert candidates.tick(store, day.replace(minute=25))["scanned"] is None                              # once only
    rows = candidates.load(store)["days"]["2026-10-30"]["rows"]
    assert set(rows) == {"A", "B"} and rows["A"]["found"].startswith("pre-open 09:20")
    # a Quick trade on A and a held-back New call buy on B; the rows show both, and an unlisted trade is added
    qb = quick.new_book()
    qb["trades"].append({"ticker": "A", "opened": "2026-10-30 09:50", "entry": 98.0, "kind": "bounce", "grade": "A", "status": "CLOSED",
                         "pct": 1.2, "result": 60.0, "exit_reason": "momentum faded"})
    qb["trades"].append({"ticker": "Z", "opened": "2026-10-30 10:30", "entry": 50.0, "kind": "breakout", "grade": "B", "status": "OPEN"})
    quick.save_book(store, qb)
    nb = paper.Book()
    nb.blocked.append({"day": "2026-10-30", "time": "x", "ticker": "B", "price": 100.0, "reason": "BUY held back: volume only 0.4x normal"})
    store.set_setting(paper_newcall.BOOK_KEY, json.dumps(nb.to_dict(), default=str))
    candidates.record(store, datetime(2026, 10, 30, 10, 31, tzinfo=NY))
    rows = candidates.load(store)["days"]["2026-10-30"]["rows"]
    assert "bought 09:50 at 98.00, grade A" in rows["A"]["quick"] and "+1.20%" in rows["A"]["quick_result"]
    assert rows["A"]["newcall"] == "not a buy call"
    assert rows["B"]["quick"] == "no setup yet" and "volume only 0.4x" in rows["B"]["newcall"]
    assert rows["Z"]["found"] == "not on the list" and rows["Z"]["quick_result"] == "open"


def test_the_refresh_adds_new_qualifiers_without_touching_old_rows_and_the_csv_is_written(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKWATCH_QUICK_LOG_DIR", str(tmp_path / "Quick log"))
    store = Store(tmp_path / "t.db")
    put(store, snap("A", ext=97.0))
    candidates.tick(store, datetime(2026, 10, 30, 9, 21, tzinfo=NY))
    put(store, snap("N", live=103.0))
    monkeypatch.setattr(candidates, "us_session", lambda now=None: "REGULAR")
    assert candidates.tick(store, datetime(2026, 10, 30, 10, 1, tzinfo=NY)) == {"scanned": "refresh", "added": 1}
    assert set(candidates.load(store)["days"]["2026-10-30"]["rows"]) == {"A", "N"}
    text = (tmp_path / "Quick log" / "Candidates log.csv").read_text(encoding="utf-8-sig")
    assert text.splitlines()[0].startswith("Day,Ticker,Found") and "breakout candidate" in text


def test_the_scan_time_follows_new_york_across_the_november_clock_change():
    # 09:20 in New York is 16:20 in Riyadh in October (UTC-4) and 17:20 after the clock change (UTC-5)
    from zoneinfo import ZoneInfo
    riyadh = ZoneInfo("Asia/Riyadh")
    before = datetime(2026, 10, 30, 9, 20, tzinfo=NY).astimezone(riyadh)
    after = datetime(2026, 11, 2, 9, 20, tzinfo=NY).astimezone(riyadh)
    assert (before.hour, after.hour) == (16, 17)
    assert candidates.SCAN_PRE_MIN == 9 * 60 + 20
