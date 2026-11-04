"""Run the 'close back above a ceiling after a fall' study on the S&P 500 daily bars (internet, Yahoo). Read only: prints a report."""
from __future__ import annotations

import logging
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)      # keeps yfinance's per-ticker warnings out of the report

from stockwatch import reclaim_study
from stockwatch.market import load_universe


def fetch(tickers: list, period: str = "5y") -> dict:
    import yfinance as yf
    frames = {}
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i + 100]
        df = yf.download(chunk, period=period, interval="1d", group_by="ticker", auto_adjust=True, threads=True, progress=False)
        for t in chunk:
            try:
                sub = df[t][["Open", "High", "Low", "Close", "Volume"]].dropna()
                if len(sub) > 300:
                    frames[t] = sub
            except Exception:
                continue
    return frames


def main() -> None:
    tickers = list(load_universe()["ticker"])
    print(f"Downloading 5 years of daily bars for {len(tickers)} stocks...", flush=True)
    frames = fetch(tickers)
    print(f"{len(frames)} stocks read. Working out the cases (about 15 minutes)...", flush=True)
    text = reclaim_study.report(reclaim_study.study(frames, progress=lambda i, n: print(f"  {i}/{n} stocks", flush=True)))
    print("\n" + text)
    try:
        from stockwatch import backup
        folder = backup.backup_dir() / "Study results"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "reclaim_study.txt").write_text(text, encoding="utf-8")
        print(f"\nSaved a copy on Drive: {folder / 'reclaim_study.txt'}")
    except Exception as e:
        print(f"\n(Could not save the Drive copy: {e})")


if __name__ == "__main__":
    main()
