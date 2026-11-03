import copy
import json
from datetime import datetime, timezone

from stockwatch import paper_wide, whynot
from stockwatch.data import NY
from stockwatch.store import Store
from test_dayboard import make
from test_paper import buy_snap

NOW = datetime(2026, 10, 26, 11, 30, tzinfo=NY)


def test_a_clean_buy_would_enter_and_a_weak_chart_is_named_as_the_block():
    good = buy_snap()
    bad = copy.deepcopy(make("NOW", "weakening"))
    bad["ticker"] = "BBB"
    bad["payload"]["plan"].update(entry=99.5, risk_per_share=4.5)
    g, b = whynot.diagnose(good, 99.5, NOW), whynot.diagnose(bad, 99.5, NOW)
    assert g["action"] == "ENTER" and g["flags"] == []
    assert b["action"] == "NONE" and "chart" in b["flags"]


def test_the_study_counts_each_check_and_lists_who_would_enter_first():
    bad = copy.deepcopy(make("NOW", "weakening"))              # the shared test fixtures reuse nested dicts: copy before changing
    bad["ticker"], bad["price"] = "BBB", 99.5
    far = copy.deepcopy(buy_snap())
    far["ticker"], far["price"] = "CCC", 99.5
    far["payload"]["plan"].update(entry_low=50.0, entry_high=60.0)
    good = copy.deepcopy(buy_snap())
    good["price"] = 99.5
    res = whynot.study([bad, far, good], NOW)
    assert res["would_enter"] == ["AAA"] and res["counts"]["chart"] == 1 and res["counts"]["zone"] >= 1
    assert res["only"]["zone"] == 1
    assert "Why stocks are not bought" in whynot.html(res) and "would enter now" in whynot.html(res)


def test_the_study_works_outside_the_session_by_asking_at_eleven_on_the_last_weekday():
    sat = datetime(2026, 10, 24, 15, 0, tzinfo=NY)
    t = whynot.session_time(sat)
    assert (t.weekday(), t.hour) == (4, 11)


def test_the_whole_watchlist_account_trades_every_tracked_stock_apart_from_the_main_account(tmp_path, monkeypatch):
    store = Store(tmp_path / "t.db")
    s = buy_snap()
    utc = NOW.astimezone(timezone.utc)
    s["payload"]["quote"] = {"market_state": "REGULAR", "live_price": 99.5, "live_change": 0.0, "live_time": utc.isoformat(),
                             "fetched_at": utc.isoformat(timespec="seconds")}
    store.conn.execute("INSERT INTO snapshots (scanned_at, ticker, tier, price, technical_score, fundamental_score, composite, verdict, payload)"
                       " VALUES (?,?,?,?,?,?,?,?,?)", ("2026-10-26T15:00:00", "AAA", 2, 99.5, 0, 0, 0, "BUY", json.dumps(s["payload"], default=str)))
    store.conn.commit()
    monkeypatch.setattr(paper_wide, "us_session", lambda: "REGULAR")
    st = paper_wide.tick(store, NOW)
    book = paper_wide.status(store)["book"]
    assert st["tickers"] == ["AAA"] and [t["ticker"] for t in book.trades] == ["AAA"]
    assert store.get_setting("paper_book") is None                     # the main Paper account was never touched
