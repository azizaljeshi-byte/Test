"""The nightly code backup (owner, 2026-10-26): once a day, after the US extended session closes (8:05 pm New York, 3:05 am
Riyadh), the app zips its own code into the Google Drive folder on this PC, so a dead disk costs nothing.

Two zips, both into the owner's private Drive folder (owner, 2026-10-26: "don't leave anything"):
  StockWatch_code_DATE.zip   the code, tests and docs: no settings file, data, virtual environment, caches or update files
  StockWatch_data_DATE.zip   everything private: a safe copy of the database (the paper and Quick accounts, history, alerts),
                             the settings file with its keys and links, and portfolio.yaml if there is one
It writes a temporary file first and renames it, so Drive never syncs half a zip. The last `KEEP` code backups and the last
`KEEP_DATA` data backups are kept; older ones named like these are removed. Nothing here touches a card, score, call, alert
or paper account, and any failure is logged and retried at most every ten minutes.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from .data import NY

log = logging.getLogger("stockwatch.backup")
DEFAULT_DIR = r"G:\My Drive\StockWatch Code Backup"
PREFIX, KEEP = "StockWatch_code_", 14
DATA_PREFIX, KEEP_DATA = "StockWatch_data_", 7        # the database is large, so fewer copies
AFTER = (20, 5)                      # New York, after the extended session closes
SKIP_DIRS = {".venv", "venv", "data", "previous", "__pycache__", ".git", ".pytest_cache", "node_modules"}
SKIP_FILES = {"update_ready.txt", "update_ready.txt.done"}
RETRY_SECONDS = 600
_last_try = {"at": 0.0}
_worker = {"t": None}


def backup_dir() -> Path:
    return Path(os.getenv("STOCKWATCH_BACKUP_DIR", "").strip() or DEFAULT_DIR)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def wanted(rel: Path) -> bool:
    """True for a file that belongs in the backup."""
    parts = set(rel.parts[:-1])
    name = rel.name.lower()
    if parts & SKIP_DIRS or rel.name in SKIP_FILES or name.endswith((".pyc", ".db", ".sqlite", ".sqlite3", ".log")):
        return False
    return not name.startswith("my_settings") or "template" in name        # the real settings file holds keys


def make_zip(root: Path, target: Path) -> int:
    """Write the zip to `target` (temporary name, then rename). Returns the number of files."""
    tmp = target.with_name(target.name + ".part")
    n = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            if p.is_file() and wanted(p.relative_to(root)):
                z.write(p, p.relative_to(root).as_posix())
                n += 1
    os.replace(tmp, target)
    return n


def make_data_zip(root: Path, target: Path) -> int:
    """The private zip: a consistent copy of every database (sqlite's own backup, safe while the app writes), the real settings
    file and portfolio.yaml. Returns the number of files."""
    tmp = target.with_name(target.name + ".part")
    n = 0
    with tempfile.TemporaryDirectory() as td, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for db in sorted((root / "data").glob("*.db")):
            copy = Path(td) / db.name
            try:
                src, dst = sqlite3.connect(f"file:{db}?mode=ro", uri=True), sqlite3.connect(copy)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
                z.write(copy, f"data/{db.name}")
            except sqlite3.Error:                       # not readable as a database: keep the raw file rather than nothing
                z.write(db, f"data/{db.name}")
            n += 1
        for p in sorted(root.glob("my_settings*")) + [root / "portfolio.yaml"]:
            if p.is_file() and "template" not in p.name.lower():
                z.write(p, p.name)
                n += 1
    os.replace(tmp, target)
    return n


def prune(folder: Path, keep: int = KEEP, prefix: str = PREFIX) -> list[str]:
    old = sorted(folder.glob(f"{prefix}*.zip"))[:-keep] if keep > 0 else []
    gone = []
    for p in old:
        try:
            p.unlink()
            gone.append(p.name)
        except OSError:
            pass
    return gone


def due(now: datetime, folder: Path, prefix: str = PREFIX) -> bool:
    """After 8:05 pm New York, once per New York date for each kind of zip."""
    if (now.hour, now.minute) < AFTER:
        return False
    return not (folder / f"{prefix}{now.date().isoformat()}.zip").exists()


def run(store=None, now: datetime | None = None, root: Path | None = None, folder: Path | None = None) -> str:
    """Make today's backup if it is due. Returns a one-line result ('' when nothing was due); never raises."""
    now = (now or datetime.now(NY)).astimezone(NY)
    folder = folder or backup_dir()
    try:
        if not folder.is_dir():
            if (now.hour, now.minute) >= AFTER and time.time() - _last_try["at"] >= RETRY_SECONDS:
                _last_try["at"] = time.time()
                msg = f"backup folder not found: {folder}"
                log.warning(msg)
                if store:
                    store.set_setting("backup_status", msg)
                return msg
            return ""
        todo = [k for k in ("code", "data") if due(now, folder, PREFIX if k == "code" else DATA_PREFIX)]
        if not todo or time.time() - _last_try["at"] < RETRY_SECONDS:
            return ""
        _last_try["at"] = time.time()
        root, day, parts = root or project_root(), now.date().isoformat(), []
        if "code" in todo:
            n = make_zip(root, folder / f"{PREFIX}{day}.zip")
            gone = prune(folder)
            parts.append(f"code {n} files" + (f", removed {len(gone)} old" if gone else ""))
        if "data" in todo:
            n = make_data_zip(root, folder / f"{DATA_PREFIX}{day}.zip")
            gone = prune(folder, KEEP_DATA, DATA_PREFIX)
            parts.append(f"private data {n} files" + (f", removed {len(gone)} old" if gone else ""))
        msg = f"backup saved {now:%Y-%m-%d %H:%M}: " + "; ".join(parts)
        log.info(msg)
        if store:
            store.set_setting("backup_status", msg)
        return msg
    except Exception as e:
        log.exception("backup failed")
        if store:
            store.set_setting("backup_status", f"backup failed: {e}"[:200])
        return f"backup failed: {e}"


def run_async(now: datetime | None = None) -> None:
    """Start `run` on its own thread unless one is still going, so a slow or unreachable Drive can never hold up the tracker."""
    t = _worker["t"]
    if t is not None and t.is_alive():
        return
    _worker["t"] = threading.Thread(target=run, kwargs={"now": now}, name="stockwatch-backup", daemon=True)
    _worker["t"].start()
