"""Run the 'flat after a fall' study on the S&P 500 daily bars (internet, Yahoo). Read only: prints a report."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import warnings
warnings.filterwarnings("ignore")

from stockwatch import candle_break, stab_study
from stockwatch.market import load_universe


def main() -> None:
    tickers = list(load_universe()["ticker"])
    print(f"Downloading 5 years of daily bars for {len(tickers)} stocks...", flush=True)
    frames = candle_break.fetch(tickers)
    print(f"{len(frames)} stocks read. Working out the cases...", flush=True)
    text = stab_study.report(stab_study.study(frames))
    print(text)
    save_to_drive(text)


def save_to_drive(text: str) -> None:
    """Also keep the report in the Google Drive backup folder (owner, 4 Nov: save it on Drive to share). A missing Drive changes nothing."""
    try:
        from stockwatch import backup
        folder = backup.backup_dir() / "Study results"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "stab_study.txt").write_text(text, encoding="utf-8")
        print(f"\nSaved a copy on Drive: {folder / 'stab_study.txt'}")
    except Exception as e:
        print(f"\n(Could not save the Drive copy: {e})")


if __name__ == "__main__":
    main()
