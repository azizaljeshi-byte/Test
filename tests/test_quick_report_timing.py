import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import quick_report as qr  # noqa: E402


def trade(kind, hhmm, result, best=1.0, why="stop hit (-2.0%)"):
    return {"kind": kind, "opened": f"2026-11-06 {hhmm}", "result": result, "best": best, "exit_reason": why}


def test_kind_by_timing_splits_each_kind_by_entry_slot(capsys):
    qr.kind_by_timing([trade("bounce", "09:42", -50), trade("bounce", "09:50", 30, why="took the profit"), trade("breakout", "10:45", -10), trade("breakout", "13:00", 20, why="end of day")])
    out = capsys.readouterr().out
    assert "SETUP BOUNCE BY ENTRY TIME (2 trades" in out and "SETUP BREAKOUT BY ENTRY TIME (2 trades" in out
    assert "09:30-09:45" in out and "10:30-11:00" in out and "ALL DAY" in out
