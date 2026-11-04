"""Run the 'buy zone after earnings' study on the S&P 500 daily bars (internet, Yahoo). Read only: prints a report.
Daily bars come from data/study_cache_5y.pkl when it is under a day old; earnings dates are kept in data/earnings_dates_cache.pkl for a week."""
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

from stockwatch import earnings_study
from stockwatch.market import load_universe

BARS = ROOT / "data" / "study_cache_5y.pkl"
DATES = ROOT / "data" / "earnings_dates_cache.pkl"


def fetch_bars(tickers: list, period: str = "5y") -> dict:
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


def load_bars() -> dict:
    try:
        if BARS.exists() and time.time() - BARS.stat().st_mtime < 86400:
            return pickle.loads(BARS.read_bytes())[0]
    except Exception:
        pass
    print("Downloading 5 years of daily bars...", flush=True)
    frames = fetch_bars(list(load_universe()["ticker"]))
    try:
        BARS.write_bytes(pickle.dumps((frames, None)))
    except Exception:
        pass
    return frames


def load_dates(tickers: list) -> dict:
    try:
        if DATES.exists() and time.time() - DATES.stat().st_mtime < 7 * 86400:
            return pickle.loads(DATES.read_bytes())
    except Exception:
        pass
    import yfinance as yf
    out, failed = {}, 0
    print(f"Fetching earnings dates for {len(tickers)} stocks (about {len(tickers) // 3} seconds)...", flush=True)
    for n, t in enumerate(tickers, 1):
        try:
            ed = yf.Ticker(t).get_earnings_dates(limit=40)
            out[t] = sorted({d.date() for d in ed.index}) if ed is not None and len(ed) else []
        except Exception:
            out[t] = []
            failed += 1
        if n % 50 == 0:
            print(f"  dates {n}/{len(tickers)} (failed {failed})", flush=True)
        time.sleep(0.3)
    try:
        DATES.write_bytes(pickle.dumps(out))
    except Exception:
        pass
    return out


def low_priority() -> None:
    """Run behind the app (Windows below-normal priority) so the dashboard stays responsive while this works."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass


def main() -> None:
    low_priority()
    frames = load_bars()
    dates = load_dates(list(frames))
    print(f"{len(frames)} stocks, earnings dates for {sum(1 for v in dates.values() if v)}. Working out the cases...", flush=True)
    text = earnings_study.report(earnings_study.study(frames, dates, progress=lambda i, n: print(f"  {i}/{n} stocks", flush=True)))
    print("\n" + text)
    try:
        from stockwatch import backup
        folder = backup.backup_dir() / "Study results"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "earnings_study.txt").write_text(text, encoding="utf-8")
        print(f"\nSaved a copy on Drive: {folder / 'earnings_study.txt'}")
    except Exception as e:
        print(f"\n(Could not save the Drive copy: {e})")


if __name__ == "__main__":
    main()
