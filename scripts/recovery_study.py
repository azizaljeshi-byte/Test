"""Run the 'recovery pattern' study on the S&P 500 daily bars (internet, Yahoo). Read only: prints a report.
The download is kept in data/study_cache_5y.pkl for a day, so a repeat run starts at once."""
from __future__ import annotations

import logging
import pickle
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from stockwatch import recovery_study
from stockwatch.market import load_universe

CACHE = ROOT / "data" / "study_cache_5y.pkl"


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


def load() -> tuple:
    try:
        if CACHE.exists() and time.time() - CACHE.stat().st_mtime < 86400:
            return pickle.loads(CACHE.read_bytes())
    except Exception:
        pass
    tickers = list(load_universe()["ticker"])
    print(f"Downloading 5 years of daily bars for {len(tickers)} stocks...", flush=True)
    frames = fetch(tickers)
    spy = fetch(["SPY"]).get("SPY")
    mkt = spy["Close"] if spy is not None else None
    try:
        CACHE.write_bytes(pickle.dumps((frames, mkt)))
    except Exception:
        pass
    return frames, mkt


def main() -> None:
    frames, mkt = load()
    print(f"{len(frames)} stocks read. Working out the cases...", flush=True)
    text = recovery_study.report(recovery_study.study(frames, mkt, progress=lambda i, n: print(f"  {i}/{n} stocks", flush=True)))
    print("\n" + text)
    try:
        from stockwatch import backup
        folder = backup.backup_dir() / "Study results"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "recovery_study.txt").write_text(text, encoding="utf-8")
        print(f"\nSaved a copy on Drive: {folder / 'recovery_study.txt'}")
    except Exception as e:
        print(f"\n(Could not save the Drive copy: {e})")


if __name__ == "__main__":
    main()
