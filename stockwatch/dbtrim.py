"""Keeps the database small (owner, 2026-10-30: the app lags; the database had grown to 2 GB).

Every 2-minute sweep saves a full copy of each stock, and nothing was ever deleted: about 500 MB a day. This thins the saved
copies of the stocks, and nothing else:

  last 3 hours       every copy is kept (the "what changed since the last scan" comparison reads these)
  3 hours to 2 days  the last copy of each stock in each hour
  older than 2 days  the last copy of each stock on each day (the score history keeps its daily points)

It never touches the paper accounts, Quick, the New call account, settings, alerts or holdings (those live in other tables),
and the newest copy of every stock is always kept. The market scan summaries keep their newest 100.
It runs once at start-up (before the app opens the file, then shrinks the file if a lot of room was freed) and then once an
hour on its own thread. Deleting happens in small batches with a commit after each, so a stop half-way loses nothing, and any
failure is logged and skipped: a clean-up must never stop the app.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("stockwatch.dbtrim")

KEEP_ALL_HOURS = 3
HOURLY_DAYS = 2
KEEP_SCANS = 100
CHUNK = 500
EVERY_SECONDS = 3600
VACUUM_MIN_FREE = 300 * 1024 * 1024        # shrink the file only when at least this much room is free inside it
_state = {"t": None, "at": 0.0}


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=60, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def _ids_to_drop(conn, lo: str | None, hi: str, width: int) -> list[int]:
    """Rows in [lo, hi) that are not the last copy of their stock in their hour (width 13) or day (width 10)."""
    span, args = ("scanned_at < ?", [hi]) if lo is None else ("scanned_at >= ? AND scanned_at < ?", [lo, hi])
    keep = {r[0] for r in conn.execute(
        f"SELECT MAX(id) FROM snapshots WHERE {span} GROUP BY ticker, substr(scanned_at, 1, {width})", args)}
    return [r[0] for r in conn.execute(f"SELECT id FROM snapshots WHERE {span}", args) if r[0] not in keep]


def thin(conn, now: datetime | None = None, budget_seconds: float | None = None) -> int:
    """Delete the extra saved copies. Returns how many rows went."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    t3, t48 = _iso(now - timedelta(hours=KEEP_ALL_HOURS)), _iso(now - timedelta(days=HOURLY_DAYS))
    started, gone = time.time(), 0
    for lo, hi, width in ((t48, t3, 13), (None, t48, 10)):
        ids = _ids_to_drop(conn, lo, hi, width)
        for i in range(0, len(ids), CHUNK):
            if budget_seconds is not None and time.time() - started > budget_seconds:
                return gone
            conn.executemany("DELETE FROM snapshots WHERE id = ?", [(x,) for x in ids[i:i + CHUNK]])
            conn.commit()
            gone += len(ids[i:i + CHUNK])
    conn.execute("DELETE FROM market_scans WHERE id NOT IN (SELECT id FROM market_scans ORDER BY id DESC LIMIT ?)", (KEEP_SCANS,))
    conn.commit()
    return gone


def _room(conn) -> tuple[int, int]:
    """(bytes free inside the file, bytes in use)."""
    size = conn.execute("PRAGMA page_size").fetchone()[0]
    return (conn.execute("PRAGMA freelist_count").fetchone()[0] * size,
            (conn.execute("PRAGMA page_count").fetchone()[0] - conn.execute("PRAGMA freelist_count").fetchone()[0]) * size)


def shrink(conn, path, min_free: int | None = None) -> str:
    """Give the freed room back to the disk. Needs a few times the live size free on the disk; skipped otherwise."""
    free, live = _room(conn)
    if free < (VACUUM_MIN_FREE if min_free is None else min_free):
        return "file not shrunk (little room to give back)"
    disk_free = shutil.disk_usage(Path(path).parent).free
    if disk_free < live * 3 + 500 * 1024 * 1024:
        return f"file not shrunk (disk has {disk_free // 2**20} MB free, needs {(live * 3) // 2**20 + 500} MB)"
    conn.commit()
    conn.isolation_level = None
    conn.execute("VACUUM")
    return f"file shrunk by about {free // 2**20} MB"


def _record(conn, text: str) -> None:
    conn.execute("INSERT INTO settings (key, value) VALUES ('db_trim', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (text,))
    conn.commit()


def run(path, with_shrink: bool = False, budget_seconds: float | None = None, now: datetime | None = None) -> str:
    """One clean-up pass on its own connection. Never raises."""
    try:
        path = Path(path)
        if not path.exists():
            return ""
        conn = _connect(path)
        try:
            before = path.stat().st_size
            gone = thin(conn, now, budget_seconds)
            note = ""
            if with_shrink:
                note = "; " + shrink(conn, path)
            conn.isolation_level = ""
            after = path.stat().st_size
            stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
            msg = f"{stamp}: removed {gone} extra saved copies; file {before // 2**20} MB -> {after // 2**20} MB{note}"
            _record(conn, msg)
            log.info("db clean-up: %s", msg)
            return msg
        finally:
            conn.close()
    except Exception as e:
        log.exception("db clean-up failed")
        return f"db clean-up failed: {e}"[:200]


def startup(path) -> str:
    """Before the app opens the file: thin, then shrink if a lot of room was freed."""
    _state["at"] = time.time()
    return run(path, with_shrink=True)


def run_async(path) -> None:
    """Once an hour, on its own thread (a time budget keeps it short), so the tracker never waits for it."""
    t = _state["t"]
    if (t is not None and t.is_alive()) or time.time() - _state["at"] < EVERY_SECONDS:
        return
    _state["at"] = time.time()
    _state["t"] = threading.Thread(target=run, args=(path,), kwargs={"budget_seconds": 60}, name="stockwatch-dbtrim", daemon=True)
    _state["t"].start()
