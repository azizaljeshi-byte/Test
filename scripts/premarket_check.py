"""Which price source shows the real pre-market price? Read only: prints, for PODD and NVDA, the last price and its time from each source
the app can use (Yahoo 1-minute bars, Yahoo quote fields, Massive snapshot and last trade, Finnhub quote), with how many minutes old each is.
Run it while the pre-market is open (10:00 to 17:30 Riyadh). Writes nothing but its report."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import warnings
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
TICKERS = ["PODD", "NVDA"]
NOW = datetime.now(timezone.utc)


def age(ts) -> str:
    try:
        ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return f"{(NOW - ts).total_seconds() / 60:.0f} min old"
    except Exception:
        return "age unknown"


def from_epoch(v) -> datetime | None:
    try:
        v = float(v)
        v = v / 1e9 if v > 1e14 else v / 1e3 if v > 1e11 else v
        return datetime.fromtimestamp(v, timezone.utc)
    except Exception:
        return None


def show(name: str, price, ts) -> None:
    when = ts.astimezone().strftime("%H:%M:%S") if ts else "?"
    print(f"  {name:<22} {price!s:>10}   at {when} (PC time)   {age(ts) if ts else ''}", flush=True)


def get_json(url: str, headers: dict) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
        return json.loads(r.read().decode())


def main() -> None:
    import yfinance as yf
    print(f"Pre-market price check, {NOW:%Y-%m-%d %H:%M} UTC\n", flush=True)
    mkey, fkey = os.getenv("STOCKWATCH_MASSIVE_KEY", "").strip(), os.getenv("FINNHUB_API_KEY", "").strip()
    for t in TICKERS:
        print(t, flush=True)
        try:
            b = yf.Ticker(t).history(period="1d", interval="1m", prepost=True)
            if len(b):
                show("Yahoo 1-minute bars", round(float(b["Close"].iloc[-1]), 2), b.index[-1].to_pydatetime())
            else:
                print("  Yahoo 1-minute bars    no bars")
        except Exception as e:
            print(f"  Yahoo 1-minute bars    failed: {e}")
        try:
            info = yf.Ticker(t).info or {}
            show("Yahoo preMarketPrice", info.get("preMarketPrice"), from_epoch(info.get("preMarketTime")))
            show("Yahoo regular price", info.get("regularMarketPrice"), from_epoch(info.get("regularMarketTime")))
        except Exception as e:
            print(f"  Yahoo quote fields     failed: {e}")
        if mkey:
            h = {"Authorization": f"Bearer {mkey}", "User-Agent": "StockWatch"}
            for name, url, pick in (
                ("Massive last trade", f"https://api.massive.com/v2/last/trade/{t}", lambda d: (d["results"]["p"], d["results"]["t"])),
                ("Massive snapshot", f"https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers/{t}",
                 lambda d: (d["ticker"]["lastTrade"]["p"], d["ticker"]["lastTrade"]["t"]))):
                try:
                    p, ts = pick(get_json(url, h))
                    show(name, p, from_epoch(ts))
                except Exception as e:
                    print(f"  {name:<22} not available on this plan ({str(e)[:60]})")
                time.sleep(13)           # the free plan allows 5 requests a minute
        else:
            print("  Massive                no key set")
        if fkey:
            try:
                d = get_json(f"https://finnhub.io/api/v1/quote?symbol={t}&token={fkey}", {"Accept": "application/json"})
                show("Finnhub quote", d.get("c"), from_epoch(d.get("t")))
                time.sleep(1.1)
            except Exception as e:
                print(f"  Finnhub quote          failed: {e}")
        else:
            print("  Finnhub                no key set")
        print(flush=True)
    print("Read: the source with the newest time and a price close to Investing.com is the one to use for the pre-market.")


if __name__ == "__main__":
    main()
