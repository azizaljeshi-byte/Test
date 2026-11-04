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
    print(stab_study.report(stab_study.study(frames)))


if __name__ == "__main__":
    main()
