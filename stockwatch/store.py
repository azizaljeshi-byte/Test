"""SQLite persistence: scan snapshots (for score history) and de-duplicated alerts."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT
from .engine import Evaluation
from .signals import Signal

DEFAULT_DB = ROOT / "data" / "stockwatch.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY, scanned_at TEXT, ticker TEXT, tier INTEGER, price REAL,
    technical_score REAL, fundamental_score REAL, composite REAL, verdict TEXT, payload TEXT
);
CREATE INDEX IF NOT EXISTS ix_snap_ticker ON snapshots(ticker, scanned_at);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY, created_at TEXT, ticker TEXT, kind TEXT, source TEXT,
    code TEXT, severity INTEGER, message TEXT, price REAL
);
CREATE INDEX IF NOT EXISTS ix_alert_key ON alerts(ticker, code, created_at);
"""


class Store:
    def __init__(self, path: str | Path = DEFAULT_DB):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def save_snapshot(self, e: Evaluation) -> None:
        payload = {"technical": e.technical, "fundamental": e.fundamental, "position": e.position,
                   "signals": [s.to_dict() for s in e.signals], "name": e.name, "error": e.error,
                   "watchlist": e.watchlist}
        self.conn.execute(
            "INSERT INTO snapshots (scanned_at, ticker, tier, price, technical_score, fundamental_score,"
            " composite, verdict, payload) VALUES (?,?,?,?,?,?,?,?,?)",
            (e.scanned_at, e.ticker, e.tier, e.price, e.technical_score, e.fundamental_score,
             e.composite, e.verdict, json.dumps(payload, default=str)))
        self.conn.commit()

    def record_alerts(self, e: Evaluation, cooldown_hours: float, min_severity: int = 2) -> list[Signal]:
        """Store signals that are new (not alerted within the cooldown) and return them."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)).isoformat(timespec="seconds")
        fresh = []
        for s in e.signals:
            if s.severity < min_severity:
                continue
            seen = self.conn.execute(
                "SELECT 1 FROM alerts WHERE ticker=? AND code=? AND created_at>=? LIMIT 1",
                (e.ticker, s.code, cutoff)).fetchone()
            if seen:
                continue
            self.conn.execute(
                "INSERT INTO alerts (created_at, ticker, kind, source, code, severity, message, price)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (e.scanned_at, e.ticker, s.kind, s.source, s.code, s.severity, s.message, e.price))
            fresh.append(s)
        self.conn.commit()
        return fresh

    def recent_alerts(self, limit: int = 200) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM alerts ORDER BY created_at DESC, id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def latest_snapshots(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT s.* FROM snapshots s JOIN (SELECT ticker, MAX(id) mid FROM snapshots GROUP BY ticker) m"
            " ON s.id = m.mid ORDER BY s.tier, s.composite DESC")
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

    def history(self, ticker: str, limit: int = 500) -> list[dict]:
        rows = self.conn.execute(
            "SELECT scanned_at, price, technical_score, fundamental_score, composite, verdict"
            " FROM snapshots WHERE ticker=? ORDER BY id DESC LIMIT ?", (ticker, limit))
        return [dict(r) for r in rows][::-1]
