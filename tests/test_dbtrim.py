"""The database clean-up: thins old saved copies, keeps the newest, never touches the other tables."""
import sqlite3
from datetime import datetime, timedelta, timezone

from stockwatch import dbtrim
from stockwatch.store import Store

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def _db(tmp_path, rows):
    path = tmp_path / "t.db"
    Store(path)                      # creates the schema
    conn = sqlite3.connect(path)
    for ticker, ago_minutes in rows:
        at = (NOW - timedelta(minutes=ago_minutes)).isoformat(timespec="seconds")
        conn.execute("INSERT INTO snapshots (scanned_at, ticker, tier, price, payload) VALUES (?,?,?,?,?)", (at, ticker, 1, 1.0, "{}"))
    conn.commit()
    return path, conn


def _left(conn, ticker):
    return [r[0] for r in conn.execute("SELECT scanned_at FROM snapshots WHERE ticker=? ORDER BY id", (ticker,))]


def test_recent_copies_all_kept(tmp_path):
    path, conn = _db(tmp_path, [("AAA", m) for m in range(0, 170, 2)])      # every 2 minutes for under 3 hours
    assert dbtrim.thin(conn, NOW) == 0
    assert len(_left(conn, "AAA")) == 85


def test_one_per_hour_between_three_hours_and_two_days(tmp_path):
    path, conn = _db(tmp_path, [("AAA", 200 + m) for m in range(0, 180, 2)])  # 3h20m to 6h20m ago, every 2 minutes
    removed = dbtrim.thin(conn, NOW)
    kept = _left(conn, "AAA")
    assert removed > 80 and 3 <= len(kept) <= 5
    assert len({k[:13] for k in kept}) == len(kept)                       # one per hour


def test_one_per_day_after_two_days_and_stocks_kept_apart(tmp_path):
    rows = [(t, 60 * 24 * 3 + m) for t in ("AAA", "BBB") for m in range(0, 600, 10)]   # three days ago
    path, conn = _db(tmp_path, rows)
    dbtrim.thin(conn, NOW)
    for t in ("AAA", "BBB"):
        kept = _left(conn, t)
        assert len({k[:10] for k in kept}) == len(kept) and 1 <= len(kept) <= 2


def test_newest_copy_of_each_stock_survives_and_other_tables_untouched(tmp_path):
    path, conn = _db(tmp_path, [("AAA", 1), ("AAA", 500), ("AAA", 501), ("BBB", 5000), ("BBB", 5001)])
    conn.execute("INSERT INTO settings (key, value) VALUES ('quick_book', 'keep me')")
    conn.execute("INSERT INTO alerts (created_at, ticker, code, message) VALUES ('2026-10-01T00:00:00+00:00','AAA','x','old alert')")
    conn.commit()
    dbtrim.thin(conn, NOW)
    assert (NOW - timedelta(minutes=1)).isoformat(timespec="seconds") in _left(conn, "AAA")
    assert len(_left(conn, "BBB")) == 1
    assert conn.execute("SELECT value FROM settings WHERE key='quick_book'").fetchone()[0] == "keep me"
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1


def test_second_run_removes_nothing_and_market_scans_keep_newest(tmp_path):
    path, conn = _db(tmp_path, [("AAA", 400 + m) for m in range(0, 120, 2)])
    for i in range(130):
        conn.execute("INSERT INTO market_scans (scanned_at, payload) VALUES ('x','{}')")
    conn.commit()
    assert dbtrim.thin(conn, NOW) > 0
    assert dbtrim.thin(conn, NOW) == 0
    assert conn.execute("SELECT COUNT(*) FROM market_scans").fetchone()[0] == dbtrim.KEEP_SCANS


def test_run_records_result_shrinks_file_and_never_raises(tmp_path):
    rows = [("AAA", 400 + m) for m in range(0, 1500)]
    path, conn = _db(tmp_path, rows)
    conn.execute("UPDATE snapshots SET payload = ?", ("x" * 20000,))
    conn.commit(); conn.close()
    big = path.stat().st_size
    store = Store(path)
    original = dbtrim.VACUUM_MIN_FREE
    dbtrim.VACUUM_MIN_FREE = 1024
    try:
        msg = dbtrim.run(path, with_shrink=True, now=NOW)
    finally:
        dbtrim.VACUUM_MIN_FREE = original
    assert "removed" in msg and path.stat().st_size < big / 3
    assert "removed" in store.get_setting("db_trim")
    assert dbtrim.run(tmp_path / "missing.db") == ""
