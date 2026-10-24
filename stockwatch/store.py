"""SQLite persistence: scan snapshots (for score history) and de-duplicated alerts."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT, Holding, Portfolio
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
CREATE TABLE IF NOT EXISTS market_scans (
    id INTEGER PRIMARY KEY, scanned_at TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS ticker_overrides (
    ticker TEXT PRIMARY KEY, tier INTEGER, shares REAL, removed INTEGER DEFAULT 0, updated_at TEXT
);
"""


class Store:
    def __init__(self, path: str | Path = DEFAULT_DB):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def save_snapshot(self, e: Evaluation) -> None:
        payload = {"technical": e.technical, "fundamental": e.fundamental, "position": e.position,
                   "signals": [s.to_dict() for s in e.signals], "events": e.events, "research": e.research, "profile": e.profile, "quote": e.quote, "plan": e.plan, "name": e.name, "error": e.error,
                   "watchlist": e.watchlist}
        self.conn.execute(
            "INSERT INTO snapshots (scanned_at, ticker, tier, price, technical_score, fundamental_score,"
            " composite, verdict, payload) VALUES (?,?,?,?,?,?,?,?,?)",
            (e.scanned_at, e.ticker, e.tier, e.price, e.technical_score, e.fundamental_score,
             e.composite, e.verdict, json.dumps(payload, default=str)))
        self.conn.commit()

    def replace_latest(self, e: Evaluation) -> None:
        """Swap a ticker's latest snapshot for this one (the early copy of the same sweep)."""
        self.conn.execute("DELETE FROM snapshots WHERE id = (SELECT MAX(id) FROM snapshots WHERE ticker=?)", (e.ticker,))
        self.save_snapshot(e)

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

    def watermark(self) -> tuple[int, int, str]:
        """Changes when a sweep, a price refresh or a new alert lands; the page polls this cheaply."""
        snap = self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM snapshots").fetchone()[0]
        alert = self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM alerts").fetchone()[0]
        quotes = self.conn.execute("SELECT COALESCE(MAX(json_extract(payload, '$.quote.fetched_at')), '') "
                                   "FROM snapshots WHERE id IN (SELECT MAX(id) FROM snapshots GROUP BY ticker)").fetchone()[0]
        return snap, alert, quotes

    def alerts_after(self, alert_id: int) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM alerts WHERE id > ? ORDER BY id", (alert_id,))]

    def recent_alerts(self, limit: int = 200) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM alerts ORDER BY created_at DESC, id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def latest_snapshots(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT s.* FROM snapshots s JOIN (SELECT ticker, MAX(id) mid FROM snapshots GROUP BY ticker) m"
            " ON s.id = m.mid ORDER BY s.tier, s.composite DESC")
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

    def save_market_scan(self, scan: dict) -> None:
        """Keep the scan summary, and snapshots of the finalists so their detail pages work."""
        for e in scan.get("evaluations", []):
            self.save_snapshot(e)
        summary = {k: v for k, v in scan.items() if k != "evaluations"}
        self.conn.execute("INSERT INTO market_scans (scanned_at, payload) VALUES (?, ?)",
                          (datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps(summary, default=str)))
        self.conn.commit()

    def latest_market_scan(self, offset: int = 0) -> dict | None:
        r = self.conn.execute("SELECT * FROM market_scans ORDER BY id DESC LIMIT 1 OFFSET ?", (offset,)).fetchone()
        return {"scanned_at": r["scanned_at"], **json.loads(r["payload"])} if r else None

    def record_market_alerts(self, rows: list[dict], cooldown_hours: float = 24) -> list[dict]:
        """Log new S&P buy setups as alerts (once per ticker per cooldown); returns the new ones."""
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=cooldown_hours)).isoformat(timespec="seconds")
        fresh = []
        for r in rows:
            seen = self.conn.execute("SELECT 1 FROM alerts WHERE ticker=? AND code='sp500_buy_setup' AND created_at>=?",
                                     (r["ticker"], cutoff)).fetchone()
            if seen:
                continue
            trig = "; ".join(r.get("triggers", [])[:1])
            self.conn.execute(
                "INSERT INTO alerts (created_at, ticker, kind, source, code, severity, message, price)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (now.isoformat(timespec="seconds"), r["ticker"], "opportunity", "S&P scan", "sp500_buy_setup", 2,
                 f"S&P scan: new buy setup ({r.get('name') or r['ticker']})" + (f" - {trig}" if trig else ""),
                 r.get("price")))
            fresh.append(r)
        self.conn.commit()
        return fresh

    def snapshot(self, ticker: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM snapshots WHERE ticker=? ORDER BY id DESC LIMIT 1", (ticker,)).fetchone()
        return {**dict(r), "payload": json.loads(r["payload"])} if r else None

    def update_quote(self, ticker: str, quote: dict) -> None:
        """Patch the latest snapshot's extended-hours quote without a full re-scan."""
        r = self.conn.execute("SELECT id, payload FROM snapshots WHERE ticker=? ORDER BY id DESC LIMIT 1",
                              (ticker,)).fetchone()
        if r:
            payload = json.loads(r["payload"])
            payload["quote"] = quote
            self.conn.execute("UPDATE snapshots SET payload=? WHERE id=?", (json.dumps(payload, default=str), r["id"]))
            self.conn.commit()

    def previous_snapshot(self, ticker: str) -> dict | None:
        """The scan before the latest one, for "what changed" comparisons."""
        r = self.conn.execute("SELECT * FROM snapshots WHERE ticker=? ORDER BY id DESC LIMIT 1 OFFSET 1",
                              (ticker,)).fetchone()
        return {**dict(r), "payload": json.loads(r["payload"])} if r else None

    def history(self, ticker: str, limit: int = 500) -> list[dict]:
        rows = self.conn.execute(
            "SELECT scanned_at, price, technical_score, fundamental_score, composite, verdict"
            " FROM snapshots WHERE ticker=? ORDER BY id DESC LIMIT ?", (ticker, limit))
        return [dict(r) for r in rows][::-1]

    # ---- small display settings (for example the theme); display only

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        r = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (key, value))
        self.conn.commit()

    # ---- tickers added / removed from the dashboard, layered over portfolio.yaml

    def upsert_ticker(self, ticker: str, tier: int, shares: float = 0.0) -> None:
        self.conn.execute(
            "INSERT INTO ticker_overrides (ticker, tier, shares, removed, updated_at) VALUES (?,?,?,0,?)"
            " ON CONFLICT(ticker) DO UPDATE SET tier=excluded.tier, shares=excluded.shares, removed=0,"
            " updated_at=excluded.updated_at",
            (ticker.upper(), tier, shares, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        self.conn.commit()

    def remove_ticker(self, ticker: str) -> None:
        self.conn.execute(
            "INSERT INTO ticker_overrides (ticker, removed, updated_at) VALUES (?,1,?)"
            " ON CONFLICT(ticker) DO UPDATE SET removed=1, updated_at=excluded.updated_at",
            (ticker.upper(), datetime.now(timezone.utc).isoformat(timespec="seconds")))
        self.conn.commit()

    def apply_overrides(self, portfolio: Portfolio) -> Portfolio:
        by_ticker = {h.ticker: h for h in portfolio.holdings}
        for r in self.conn.execute("SELECT * FROM ticker_overrides ORDER BY updated_at"):
            if r["removed"]:
                by_ticker.pop(r["ticker"], None)
            else:
                prev = by_ticker.get(r["ticker"])
                by_ticker[r["ticker"]] = Holding(r["ticker"], int(r["tier"]), float(r["shares"] or 0),
                                                 prev.cost_basis if prev else None,
                                                 prev.target_price if prev else None)
        return Portfolio(list(by_ticker.values()), portfolio.tiers, portfolio.settings, portfolio.source)
