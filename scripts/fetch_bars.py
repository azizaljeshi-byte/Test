"""Download daily bars for a few named stocks (owner, 17 Nov: ASTS, CRDO, APP, GOOGL) so a study can run on them.
Read-only: it writes data/fetch_bars.csv (ticker, date, Open, High, Low, Close, Volume; split/dividend adjusted) and prints a one-line summary
per stock. Add or change tickers in TICKERS. It never touches the app's database or settings."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TICKERS = ["ASTS", "CRDO", "APP", "GOOGL"]
PERIOD = "3y"


def main() -> None:
    import pandas as pd
    import yfinance as yf
    parts = []
    for t in TICKERS:
        try:
            df = yf.Ticker(t).history(period=PERIOD, interval="1d", auto_adjust=True)[["Open", "High", "Low", "Close", "Volume"]].dropna()
            if df.empty:
                print(f"{t}: no data")
                continue
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            df.index.name = "date"
            df.insert(0, "ticker", t)
            parts.append(df.reset_index())
            print(f"{t}: {len(df)} sessions, {df.index[0].date()} to {df.index[-1].date()}")
        except Exception as e:
            print(f"{t}: failed ({type(e).__name__})")
    if parts:
        out = ROOT / "data" / "fetch_bars.csv"
        pd.concat(parts, ignore_index=True).to_csv(out, index=False)
        print(f"Saved {out.name}")


if __name__ == "__main__":
    sys.exit(main())
