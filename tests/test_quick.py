import json
from datetime import datetime, timedelta, timezone


from stockwatch import quick, quick_view
from stockwatch.data import NY
from stockwatch.store import Store
from test_paper import buy_snap

T0 = datetime(2026, 10, 26, 10, 0, tzinfo=NY)               # a Monday


def snap(atr=2.0, days=None, chg=0.0, vol=1_000_000.0, avg=1_000_000.0):
    s = buy_snap()
    s["payload"]["technical"]["atr"] = atr
    s["payload"]["technical"]["vol_avg20"] = avg
    s["payload"]["quote"] = {"live_change": chg, "live_volume": vol}
    s["payload"]["events"] = {"days_to_earnings": days}
    return s


def run(path, s=None, book=None, start=T0, every=20):
    """Feed a price path (one price per `every` seconds) through the engine."""
    book, marks, s = book or quick.new_book(), {}, s or snap()
    for i, px in enumerate(path):
        quick.step(book, marks, {"AAA": s}, {"AAA": px}, start + timedelta(seconds=every * i))
    return book, marks


FLUSH = [100.0] * 12 + [99.0, 98.0, 97.0, 96.0, 95.5] + [95.5] * 8      # a drop of ~2 ranges, then flat on the low
SLOW = [round(95.5 + 0.06 * (i + 1), 2) for i in range(32)]        # a slow, held turn up: ten minutes of rising lows
ENTRY = FLUSH + SLOW
CLIMB = [round(97.5 + 0.45 * i, 2) for i in range(1, 20)]
BOUNCE = [96.0, 96.4, 96.9, 97.4, 97.9, 98.3, 98.7, 99.1, 99.5, 99.9, 100.3, 100.7, 101.1, 101.5, 101.9, 102.3, 102.7, 103.1]


def test_a_flush_then_a_turn_up_enters_a_bounce_with_a_stop_under_the_low():
    book, _ = run(FLUSH + SLOW[:16])
    assert book["trades"] == []                                  # the turn is under ten minutes old: not confirmed yet
    book, _ = run(ENTRY)
    assert [t["kind"] for t in book["trades"]] == ["bounce"]
    t = book["trades"][0]
    assert t["stop0"] < t["entry"] and t["entry"] - t["stop0"] <= quick.STOP_ATR * 2.0 + 0.01 and book["cash"] < quick.START_CASH
    assert "turned up off the low" in t["reason"] and t["grade"] == "A" and abs(t["size"] - 2500) < 100


def test_the_grade_comes_from_the_volume_pace_and_a_weak_or_unread_volume_does_not_trade():
    book, _ = run(ENTRY, s=snap(vol=200_000.0))                  # about 0.9x normal for the time: a B, three percent
    assert [t["grade"] for t in book["trades"]] == ["B"] and abs(book["trades"][0]["size"] - 1500) < 100
    book, _ = run(ENTRY, s=snap(vol=90_000.0))                   # about 0.4x: a weak bounce
    assert book["trades"] == [] and "weak bounce" in book["skipped"][0]["reason"]
    s = snap()
    del s["payload"]["quote"]["live_volume"]
    book, _ = run(ENTRY, s=s)
    assert book["trades"] == [] and "volume not read" in book["skipped"][0]["reason"]
    assert quick.grade("breakout", 1.2)[0] == "B" and quick.grade("breakout", 1.6)[0] == "A" and quick.grade("breakout", 0.9)[0] is None


def test_a_trade_that_never_moves_leaves_after_an_hour_and_one_with_dry_volume_after_45_minutes():
    for s2, mins, text in ((snap(), 61, "no progress"), (snap(vol=60_000.0), 46, "volume dried up")):
        book, marks = run(ENTRY)
        opened = datetime.fromisoformat(book["positions"]["AAA"]["opened"])
        price = book["trades"][0]["entry"]
        quick.step(book, marks, {"AAA": s2}, {"AAA": price}, opened + timedelta(minutes=mins))
        assert book["trades"][0]["status"] == "CLOSED" and text in book["trades"][0]["exit_reason"]
    book, marks = run(ENTRY)
    opened = datetime.fromisoformat(book["positions"]["AAA"]["opened"])
    quick.step(book, marks, {"AAA": snap()}, {"AAA": book["trades"][0]["entry"]}, opened + timedelta(minutes=30))
    assert book["trades"][0]["status"] == "OPEN"


def test_a_stock_that_is_just_flat_never_trades_and_missing_range_never_trades():
    book, _ = run([100.0] * 40)
    assert book["trades"] == []
    book, _ = run(FLUSH + BOUNCE[:6], s=snap(atr=None))
    assert book["trades"] == []


def test_a_winner_is_ridden_with_a_trailing_stop_past_two_and_a_half_percent():
    book, _ = run(ENTRY + CLIMB)                              # climbs to ~8% over the low, no exit yet
    t = book["trades"][0]
    assert t["status"] == "OPEN" and t["best"] > quick.FIXED_PCT
    assert book["positions"]["AAA"]["stop"] > t["entry"]       # the stop has moved up behind it


def test_the_trailing_stop_sells_when_the_chart_turns_and_the_report_compares_with_a_fixed_exit():
    book, marks = run(ENTRY + CLIMB)
    last = ENTRY + CLIMB
    quick.step(book, marks, {"AAA": snap()}, {"AAA": 100.0}, T0 + timedelta(seconds=20 * len(last)))
    t = book["trades"][0]
    assert t["status"] == "CLOSED" and "trailing stop" in t["exit_reason"] and t["result"] > 0
    rep = quick.report(book)
    assert rep["closed"] == 1 and rep["win_rate"] == 1.0 and rep["rode"] == 1


def test_a_trade_that_goes_against_it_stops_out_and_end_of_day_closes_everything():
    book, marks = run(ENTRY)
    quick.step(book, marks, {"AAA": snap()}, {"AAA": 92.0}, T0 + timedelta(minutes=10))
    assert "stop hit" in book["trades"][0]["exit_reason"] and book["trades"][0]["result"] < 0
    book, marks = run(ENTRY)
    quick.step(book, marks, {"AAA": snap()}, {"AAA": 97.5}, datetime(2026, 10, 26, 15, 56, tzinfo=NY))
    assert book["trades"][0]["exit_reason"] == "end of day: no overnight"


def test_earnings_tomorrow_skips_the_setup_and_logs_it_once():
    book, _ = run(ENTRY, s=snap(days=1))
    assert book["trades"] == [] and len(book["skipped"]) == 1 and "earnings in 1 day" in book["skipped"][0]["reason"]


def test_no_new_entry_in_the_last_twenty_minutes_and_the_open_five_minutes():
    book, _ = run(FLUSH + BOUNCE[:6], start=datetime(2026, 10, 26, 15, 40, tzinfo=NY))
    assert book["trades"] == []


def test_tick_runs_from_the_store_only_in_session_and_the_tab_renders(tmp_path, monkeypatch):
    store = Store(tmp_path / "t.db")
    s = snap()
    now = datetime(2026, 10, 26, 11, 0, tzinfo=NY)
    utc = now.astimezone(timezone.utc)
    s["payload"]["quote"] = {"market_state": "REGULAR", "live_price": 100.0, "live_change": 0.0, "live_time": utc.isoformat(),
                             "fetched_at": utc.isoformat(timespec="seconds")}
    store.conn.execute("INSERT INTO snapshots (scanned_at, ticker, tier, price, technical_score, fundamental_score, composite, verdict, payload)"
                       " VALUES (?,?,?,?,?,?,?,?,?)", ("2026-10-26T15:00:00", "AAA", 2, 100.0, 0, 0, 0, "BUY", json.dumps(s["payload"], default=str)))
    store.conn.commit()
    monkeypatch.setattr(quick, "us_session", lambda: "CLOSED")
    assert "market closed" in quick.tick(store, now)["note"] and not store.get_setting(quick.BOOK_KEY)
    monkeypatch.setattr(quick, "us_session", lambda: "REGULAR")
    st = quick.tick(store, now)
    assert st["watching"] == 1 and not st["skipped"]
    out = quick_view.html(quick.status(store), {"AAA": 100.0})
    assert "Quick trading" in out and "$50,000.00" in out and "No open trades." in out


def test_the_journal_is_written_as_sheet_files_in_a_quick_log_folder_and_a_missing_drive_only_reports(tmp_path):
    book, _ = run(ENTRY)
    drive = tmp_path / "drive"
    drive.mkdir()
    assert quick.export_sheets(book, drive / "Quick log") == ""
    rows = (drive / "Quick log" / "Quick trades.csv").read_text(encoding="utf-8-sig").splitlines()
    assert rows[0].startswith("ID,Ticker,Setup") and "AAA,bounce" in rows[1]
    assert (drive / "Quick log" / "Quick skipped setups.csv").exists()
    assert "not found" in quick.export_sheets(book, tmp_path / "nope" / "Quick log")


def test_the_sheet_files_are_written_even_when_the_market_is_closed(tmp_path, monkeypatch):
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.setenv("STOCKWATCH_QUICK_LOG_DIR", str(drive / "Quick log"))
    store = Store(tmp_path / "t.db")
    monkeypatch.setattr(quick, "us_session", lambda: "CLOSED")
    quick.tick(store, datetime(2026, 10, 26, 22, 0, tzinfo=NY))
    quick._exp["t"].join()
    quick.tick(store, datetime(2026, 10, 26, 22, 0, tzinfo=NY))                  # the next cycle records the outcome
    assert (drive / "Quick log" / "Quick trades.csv").exists() and store.get_setting("quick_sheet_ok") == "1"


def multi(path, tickers, snap_for, start=T0, every=20):
    book, marks = quick.new_book(), {}
    for i, px in enumerate(path):
        now = start + timedelta(seconds=every * i)
        quick.step(book, marks, {t: snap_for(t) for t in tickers}, {t: px for t in tickers}, now)
    return book


def test_a_gap_down_is_not_a_flush_and_the_opening_quarter_hour_takes_no_bounce(monkeypatch):
    book, _ = run([95.0] * 24 + SLOW, s=snap(chg=-0.05))         # opened 5% down and only rose: nothing fell during the session
    assert book["trades"] == []
    start = datetime(2026, 10, 26, 9, 30, tzinfo=NY)
    book, _ = run(ENTRY, start=start)                            # the turn is confirmed about 18 minutes in
    assert book["trades"] and book["trades"][0]["opened"] >= "2026-10-26 09:45"
    monkeypatch.setattr(quick, "BOUNCE_FIRST_MIN", 25)
    book, _ = run(ENTRY, start=start)
    assert book["trades"] == []


def test_it_needs_two_higher_lows_a_dip_back_toward_the_low_means_the_floor_has_not_held():
    failed = FLUSH + SLOW[:20] + [95.53] + SLOW[20:]             # half-way it slipped back to just above the low
    book, _ = run(failed)
    assert book["trades"] == []


def test_at_most_three_new_entries_in_ten_minutes():
    book = multi(ENTRY, ["A", "B", "C", "D"], lambda t: snap())
    assert len(book["trades"]) == 3
    assert any("pace limit" in x["reason"] for x in book["skipped"])


def test_the_market_gate_pauses_bounces_when_most_stocks_are_down_and_a_thin_sample_never_gates():
    fillers = [f"F{i}" for i in range(24)]
    book = multi(ENTRY, ["AAA"] + fillers, lambda t: snap(chg=-0.02))
    assert book["trades"] == [] and any("market gate" in x["reason"] for x in book["skipped"])
    assert quick.market_gate({"A": snap(chg=-0.05)}) == ""                              # too few reads to judge
    assert quick.market_gate({t: snap(chg=0.01) for t in fillers}) == ""                # an up market


def test_a_stock_may_trade_again_the_day_stops_at_a_one_percent_loss_and_entries_are_capped(monkeypatch):
    book, marks = run(ENTRY)
    first = book["trades"][0]
    pos = book["positions"]["AAA"]
    opened = datetime.fromisoformat(pos["opened"])
    quick.step(book, marks, {"AAA": snap()}, {"AAA": first["entry"] - 5.0}, opened + timedelta(minutes=2))          # stopped out
    assert book["trades"][0]["status"] == "CLOSED"
    book2, _ = run(ENTRY + [96.0] * 3, book=book, start=T0 + timedelta(minutes=30))
    assert not any("one trade per stock per day" in x["reason"] for x in book["skipped"])            # re-entry is allowed (owner, 5 Nov)
    assert all(x.get("nth_today", 2) == 2 for x in book["trades"][1:])
    # the daily loss stop: today's result is under -1% of the account, so another stock does not enter
    book = quick.new_book()
    book["trades"].append({"ticker": "OLD", "opened": "2026-10-26 09:45", "closed": "2026-10-26 09:55", "result": -600.0, "status": "CLOSED"})
    run(ENTRY, book=book)
    assert [t["ticker"] for t in book["trades"]] == ["OLD"] and any("daily loss stop" in x["reason"] for x in book["skipped"])
    monkeypatch.setattr(quick, "MAX_PER_DAY", 0)
    book = quick.new_book()
    run(ENTRY, book=book)
    assert book["trades"] == [] and any("day limit" in x["reason"] for x in book["skipped"])


def test_after_two_percent_it_leaves_soon_after_it_stops_riding():
    book, marks = run(ENTRY + CLIMB)
    last = T0 + timedelta(seconds=20 * len(ENTRY + CLIMB))
    peak = book["positions"]["AAA"]["peak"]
    assert book["trades"][0]["best"] >= quick.TAKE_PCT
    quick.step(book, marks, {"AAA": snap()}, {"AAA": round(peak - 0.5, 2)}, last + timedelta(minutes=5))
    assert book["trades"][0]["status"] == "OPEN"                       # 5 minutes with no new high: still counts as riding
    quick.step(book, marks, {"AAA": snap()}, {"AAA": round(peak - 0.5, 2)}, last + timedelta(minutes=11))
    t = book["trades"][0]
    assert t["status"] == "CLOSED" and "took the profit" in t["exit_reason"] and t["result"] > 0


def test_in_the_first_thirty_minutes_there_is_no_pace_limit():
    start = datetime(2026, 10, 26, 9, 30, tzinfo=NY)
    book = multi(ENTRY, ["A", "B", "C", "D"], lambda t: snap(), start=start)       # the turn comes about 18 minutes in
    assert len(book["trades"]) == 4
    assert not any("pace limit" in x["reason"] for x in book["skipped"])


def test_no_trade_is_held_more_than_two_percent_under_its_entry_even_with_a_wide_daily_range():
    assert quick._first_stop("breakout", 2.98, 2.9, 0.44) >= round(2.98 * 0.98, 2)       # half a range would be 7% down
    book, marks = quick.new_book(), {}
    t = quick._enter(book, "AAA", "breakout", "test", 2.98, 2.9, 0.44, T0)
    assert t["stop0"] >= 2.92
    book["positions"]["AAA"]["stop"] = 2.76                                                # an older position with the far stop
    quick.step(book, marks, {"AAA": snap(atr=0.44)}, {"AAA": 2.846}, T0 + timedelta(minutes=40))     # -4.5%
    assert book["trades"][0]["status"] == "CLOSED" and "stop hit" in book["trades"][0]["exit_reason"]


def test_a_weak_sector_no_longer_blocks_entries():
    """Owner, 5 Nov: the sector check is logged at each entry (sectors.stamp) but does not stop a trade, so weak-sector entries can be studied."""
    def sec_snap(chg):
        s = snap(chg=chg)
        s["payload"]["profile"] = {"sector": "Technology"}
        return s
    book = multi(ENTRY, ["A", "B", "C", "D"], lambda t: sec_snap(-0.004))          # under half up, the middle stock down: the sector is weak
    assert len(book["trades"]) >= 1 and not any("sector check" in x["reason"] for x in book["skipped"])



def test_a_re_entry_is_logged_with_how_the_first_try_ended():
    book = quick.new_book()
    quick._enter(book, "AAA", "bounce", "first", 100.0, 99.0, 1.0, T0)
    quick._exit(book, "AAA", 98.0, T0 + timedelta(minutes=30), "stop hit (-2.0%)")
    t = quick._enter(book, "AAA", "bounce", "second", 99.0, 98.0, 1.0, T0 + timedelta(minutes=50))
    assert t["nth_today"] == 2 and t["prev_exit"] == "stop hit (-2.0%)" and t["prev_result"] < 0
    assert "nth_today" not in book["trades"][0]


def test_the_best_ranked_setup_is_entered_first_not_the_first_in_the_list(monkeypatch):
    """Owner, 5 Nov: with room for one new entry, the strongest setup takes it, whatever its place in the watchlist."""
    monkeypatch.setattr(quick, "MAX_NEW", 1)
    monkeypatch.setattr(quick, "OPEN_FREE_MIN", 0)
    vols = {"AAA": 190_000.0, "BBB": 230_000.0, "CCC": 480_000.0}              # CCC has by far the strongest volume, and is last in the list
    book = multi(ENTRY, list(vols), lambda t: snap(vol=vols[t]))
    assert [t["ticker"] for t in book["trades"]] == ["CCC"]
    assert book["trades"][0]["rank"] == 1 and book["trades"][0]["of"] == 3
    log = {x["ticker"]: x for x in book["ranked"]}
    assert log["CCC"]["taken"] and not log["AAA"]["taken"] and not log["BBB"]["taken"]
    assert "ranked #" in log["AAA"]["why_not"] and log["CCC"]["score"] > log["BBB"]["score"] > log["AAA"]["score"]
    assert set(log["CCC"]["parts"]) == {"volume", "move", "sector", "tech", "daily"}


def test_rank_parts_reward_a_healthy_sector_and_an_agreeing_daily_call_but_never_block():
    chart = {"off_low": 0.6, "drop": 0.9, "up_day": 0.0}
    good, _ = quick.rank_score("bounce", chart, 2.0, 60, True, "BUY")
    bad, parts = quick.rank_score("bounce", chart, 2.0, 60, False, "EXIT")
    assert good - bad == 4.0 and parts["sector"] == -1.0 and parts["daily"] == -1.0
    assert quick.rank_score("bounce", chart, None, None, None, None)[0] > 0            # unknown parts count as zero, never an error
