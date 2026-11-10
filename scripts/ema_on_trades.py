"""Did the 10/20 EMA setup help the Quick and New call paper trades? Read only: loads both books from the app's database, looks at each closed trade's stock
on the last finished daily bar before the entry day, and compares the results of trades that had the setup with those that did not. Internet needed (Yahoo daily bars).
Test sells ("forced sell") and trades sold by hand ("owner override") are left out. Tags (all from finished daily bars, no look-ahead):
  uptrend   EMA10 above EMA20 and EMA20 rising
  dip       in the last 5 days the low touched EMA10 while the close held above EMA20 (the pullback)
  near      the entry price is within 1 ATR of EMA10 (not stretched)
  setup     uptrend + dip (the 'crossback' pattern)
Prices are cached in data/ema_trades_cache.pkl for a day."""
from __future__ import annotations

import logging
import pickle
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
CACHE = ROOT / "data" / "ema_trades_cache.pkl"


def skip(t) -> bool:
    r = str(t.get("exit_reason") or "")
    return t.get("status") != "CLOSED" or r.startswith("forced sell") or r.startswith("owner override")


def fetch(tickers: list[str]) -> dict:
    try:
        if CACHE.exists() and time.time() - CACHE.stat().st_mtime < 86400:
            have = pickle.loads(CACHE.read_bytes())
            if all(t in have for t in tickers):
                return have
    except Exception:
        pass
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), 50):
        chunk = tickers[i:i + 50]
        df = yf.download(chunk, period="2y", interval="1d", group_by="ticker", auto_adjust=True, threads=True, progress=False)
        for t in chunk:
            try:
                d = df[t][["Open", "High", "Low", "Close"]].dropna()
                if len(d) > 60:
                    out[t] = d
            except Exception:
                pass
    CACHE.write_bytes(pickle.dumps(out))
    return out


def prepare(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["e10"] = d["Close"].ewm(span=10, adjust=False).mean()
    d["e20"] = d["Close"].ewm(span=20, adjust=False).mean()
    pc = d["Close"].shift()
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - pc).abs(), (d["Low"] - pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    return d


def tags(d: pd.DataFrame, opened: str, entry: float) -> dict | None:
    day = pd.Timestamp(opened[:10])
    idx = d.index.tz_localize(None) if d.index.tz is not None else d.index
    pos = int(idx.searchsorted(day)) - 1            # the last bar before the entry day
    if pos < 25:
        return None
    r, w = d.iloc[pos], d.iloc[pos - 4:pos + 1]
    up = bool(r["e10"] > r["e20"] and r["e20"] > d["e20"].iloc[pos - 3])
    dip = bool(((w["Low"] <= w["e10"]) & (w["Close"] > w["e20"])).any())
    near = bool(abs(entry - r["e10"]) <= r["atr"])
    return {"uptrend": up, "dip": dip, "near": near, "setup": up and dip}


def block(title: str, trades: list[dict]) -> None:
    print(f"\n{title}")
    print(f"  {'group':<22}{'trades':>7}{'win rate':>10}{'total $':>11}{'avg $':>9}{'profit factor':>15}")
    for name, test in (("all trades", lambda x: True), ("has the setup", lambda x: x["tag"]["setup"]), ("no setup", lambda x: not x["tag"]["setup"]),
                       ("uptrend", lambda x: x["tag"]["uptrend"]), ("not uptrend", lambda x: not x["tag"]["uptrend"]),
                       ("dip (pullback)", lambda x: x["tag"]["dip"]), ("no dip", lambda x: not x["tag"]["dip"]),
                       ("near EMA10", lambda x: x["tag"]["near"]), ("stretched", lambda x: not x["tag"]["near"])):
        g = [x["result"] for x in trades if test(x)]
        if not g:
            print(f"  {name:<22}{0:>7}")
            continue
        w, l = [v for v in g if v > 0], [v for v in g if v < 0]
        pf = f"{sum(w) / -sum(l):.2f}" if l else "-"
        print(f"  {name:<22}{len(g):>7}{len(w) / len(g):>10.0%}{sum(g):>11,.0f}{sum(g) / len(g):>9,.1f}{pf:>15}")


def main() -> None:
    from stockwatch import paper_newcall, quick
    from stockwatch.store import Store
    store = Store()
    books = {"QUICK": [t for t in quick.load_book(store, migrate=False)["trades"] if not skip(t)],
             "NEW CALL": [t for t in paper_newcall.load_book(store).trades if not skip(t)]}
    tickers = sorted({t["ticker"] for ts in books.values() for t in ts})
    print(f"{sum(len(v) for v in books.values())} real closed trades in {len(tickers)} stocks. Downloading daily bars...", flush=True)
    frames = {k: prepare(v) for k, v in fetch(tickers).items()}
    for name, ts in books.items():
        rows, missing = [], 0
        for t in ts:
            d = frames.get(t["ticker"])
            tg = tags(d, str(t["opened"]), float(t["entry"])) if d is not None else None
            if tg is None:
                missing += 1
                continue
            rows.append({"result": float(t["result"]), "tag": tg, "day": str(t["opened"])[:10]})
        block(f"{name} ({len(rows)} trades read, {missing} without enough price history)", rows)
        by = defaultdict(list)
        for x in rows:
            by[x["day"]].append(x)
        print("  Setup share by day: " + ", ".join(f"{d[5:]} {sum(1 for x in v if x['tag']['setup'])}/{len(v)}" for d, v in sorted(by.items())))
    print("\nRead: if 'has the setup' earns more per trade than 'no setup' it helps; small groups (under about 30 trades) prove little.")


if __name__ == "__main__":
    main()
