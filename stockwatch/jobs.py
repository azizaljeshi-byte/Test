"""Run-once study jobs, started by a trigger file (owner, 4 Nov 2026: "run it for me").

Drop a file `data/run_job.txt` containing one job name from JOBS; within a tracker cycle the app starts that script on its own low-priority
process (the same interpreter as the app), writes its output to `data/<name>.txt`, and renames the trigger to `run_job.txt.done`. The
scripts are read-only studies: they never touch the app's database or settings. One job at a time; an unknown name is ignored and reported
in `data/run_job.txt.done`. Nothing runs unless the trigger file exists.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger("stockwatch.jobs")
JOBS = {"stab_study": "scripts/stab_study.py", "reclaim_study": "scripts/reclaim_study.py", "recovery_study": "scripts/recovery_study.py", "earnings_study": "scripts/earnings_study.py", "save_study_data": "scripts/save_study_data.py", "candle_break_backtest": "scripts/candle_break_backtest.py", "premarket_check": "scripts/premarket_check.py", "newcall_report": "scripts/newcall_report.py", "quick_report": "scripts/quick_report.py",
        "candidates_outcomes": "scripts/candidates_outcomes.py", "gate_replay": "scripts/gate_replay.py"}
_lock = threading.Lock()
_running = {"p": None}


def root() -> Path:
    return Path(__file__).resolve().parent.parent


def tick(base: Path | None = None, spawn=None) -> str | None:
    """Starts the requested job if the trigger file exists and none is running. Returns the job name started, else None. Never raises."""
    try:
        base = base or root()
        trig = base / "data" / "run_job.txt"
        p = _running["p"]
        if p is not None and p.poll() is None:
            return None
        if not trig.exists():
            return None
        name = trig.read_text(encoding="utf-8", errors="ignore").strip().lower()
        done = trig.with_name("run_job.txt.done")
        with _lock:
            if name not in JOBS or not (base / JOBS[name]).exists():
                done.write_text(f"unknown job: {name!r}\n", encoding="utf-8")
                trig.unlink()
                return None
            out = (base / "data" / f"{name}.txt").open("w", encoding="utf-8")
            flags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
            cmd = [sys.executable, "-W", "ignore", str(base / JOBS[name])]
            _running["p"] = (spawn or subprocess.Popen)(cmd, cwd=str(base), stdout=out, stderr=subprocess.STDOUT, creationflags=flags,
                                                       env={**os.environ, "PYTHONUNBUFFERED": "1"})
            done.write_text(f"started: {name}\n", encoding="utf-8")
            trig.unlink()
        log.info("started job %s", name)
        return name
    except Exception:
        log.exception("job runner failed")
        return None
