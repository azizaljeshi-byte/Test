"""Test the 10/20 EMA "crossback" idea (Oliver Kell style) on the S&P 500 daily bars (internet, Yahoo). Read only: prints a report.
Setup (all on closed daily bars, no look-ahead): uptrend = EMA10 above EMA20 and EMA20 rising; the stock dips into the EMA zone (low at or under EMA10)
but closes above EMA20, then a later day closes above the previous day's high (the bounce). Buy at that close. Stop = lowest low of the dip, minus 0.2%.
Exit = the first of: stop (a close under it, sold at the close), "extension" (close 3 ATR or more above EMA10), or "crossback failed" (close under both EMAs).
Compared with a plain baseline: buying the same number of random uptrend days and holding for the same days. Costs ignored. Uses the S&P 500 list and 5 years,
so it carries survivorship bias (today's members only). The download is kept in data/ema_cache_5y.pkl for a day."""
from __future__ import annotations

import logging
import pickle
import random
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

CACHE = ROOT / "data" / "ema_cache_5y.pkl"
OLD_CACHE = ROOT / "data" / "study_cache_5y.pkl"   # the recovery study's file; an earlier run of this script wrongly wrote an empty one there
DIP_BARS, MAX_HOLD, EXT_ATRS, STOP_PAD, MAX_RISK = 5, 60, 3.0, 0.002, 0.12


def fetch(tickers: list, period: str = "5y") -> dict:
    import yfinance as yf
    frames = {}
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i + 100]
        df = yf.download(chunk, period=period, interval="1d", group_by="ticker", auto_adjust=True, threads=True, progress=False)
        for t in chunk:
            try:
                d = df[t].dropna(how="all")
                if len(d) > 250:
                    frames[t] = d
            except Exception:
                pass
    return frames


def load(tickers: list) -> dict:
    try:
        if isinstance(pickle.loads(OLD_CACHE.read_bytes()), dict):   # wrong format for the recovery study: remove it
            OLD_CACHE.unlink()
    except Exception:
        pass
    try:
        if CACHE.exists() and time.time() - CACHE.stat().st_mtime < 86400:
            frames = pickle.loads(CACHE.read_bytes())
            if frames:
                return frames
    except Exception:
        pass
    frames = fetch(tickers)
    if frames:
        CACHE.write_bytes(pickle.dumps(frames))
    return frames


def prepare(d: pd.DataFrame) -> pd.DataFrame:
    d = d[["Open", "High", "Low", "Close"]].copy()
    d["e10"] = d["Close"].ewm(span=10, adjust=False).mean()
    d["e20"] = d["Close"].ewm(span=20, adjust=False).mean()
    pc = d["Close"].shift()
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - pc).abs(), (d["Low"] - pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    d["up"] = (d["e10"] > d["e20"]) & (d["e20"] > d["e20"].shift(3))
    return d


def exit_from(d: pd.DataFrame, i: int, entry: float, stop: float):
    """Walk forward from the entry bar i. Returns (exit index, exit price, reason)."""
    last = min(i + MAX_HOLD, len(d) - 1)
    for k in range(i + 1, last + 1):
        r = d.iloc[k]
        if r["Close"] <= stop:
            return k, float(r["Close"]), "stop"
        if r["Close"] >= r["e10"] + EXT_ATRS * r["atr"]:
            return k, float(r["Close"]), "extension"
        if r["Close"] < r["e10"] and r["Close"] < r["e20"]:
            return k, float(r["Close"]), "crossback failed"
    return last, float(d["Close"].iloc[last]), "time"


def setups(d: pd.DataFrame) -> list[dict]:
    out, i, n = [], 40, len(d)
    while i < n - 2:
        r, p = d.iloc[i], d.iloc[i - 1]
        window = d.iloc[i - DIP_BARS:i]
        dipped = bool(((window["Low"] <= window["e10"]) & (window["Close"] > window["e20"])).any())
        if r["up"] and dipped and r["Close"] > p["High"] and r["Close"] > r["e20"] and r["Close"] > r["Open"]:
            stop = float(window["Low"].min()) * (1 - STOP_PAD)
            entry = float(r["Close"])
            risk = (entry - stop) / entry
            if 0.005 < risk <= MAX_RISK:
                k, px, why = exit_from(d, i, entry, stop)
                out.append({"day": d.index[i], "i": i, "ret": px / entry - 1, "r": (px - entry) / (entry - stop), "days": k - i, "why": why})
                i = k + 1
                continue
        i += 1
    return out


def baseline(d: pd.DataFrame, picks: list[int], hold: int) -> list[float]:
    return [float(d["Close"].iloc[min(i + hold, len(d) - 1)] / d["Close"].iloc[i] - 1) for i in picks]


def stats(name: str, rets: list[float], rs: list[float] | None = None, days: list[int] | None = None) -> None:
    a = np.array(rets)
    if not len(a):
        print(f"{name}: no trades")
        return
    w, l = a[a > 0], a[a <= 0]
    pf = w.sum() / -l.sum() if len(l) and l.sum() < 0 else float("inf")
    line = f"{name:<26} trades {len(a):>5}  win rate {len(w) / len(a):>5.0%}  avg {a.mean():>+6.2%}  avg win {w.mean() if len(w) else 0:>+6.2%}  avg loss {l.mean() if len(l) else 0:>+6.2%}  profit factor {pf:>4.2f}"
    if days:
        line += f"  avg hold {np.mean(days):>4.1f} days"
    if rs:
        line += f"  avg R {np.mean(rs):>+5.2f}"
    print(line)


def main() -> None:
    from stockwatch.market import load_universe
    tickers = list(load_universe()["ticker"])
    print(f"Downloading {len(tickers)} tickers (5 years of daily bars)...")
    frames = load(tickers)
    print(f"Got {len(frames)} tickers.\n")
    if not frames:
        print("No prices came back from Yahoo; try again in a few minutes.")
        return
    random.seed(1)
    trades, base, hold_all = [], [], []
    for t, raw in frames.items():
        d = prepare(raw)
        s = setups(d)
        for x in s:
            x["t"] = t
        trades += s
        ups = [i for i in range(40, len(d) - 2) if d["up"].iloc[i] and d["Close"].iloc[i] > d["e20"].iloc[i]]
        if s and ups:
            picks = random.sample(ups, min(len(s), len(ups)))
            base += baseline(d, picks, int(np.mean([x["days"] for x in s])) or 1)
        hold_all.append(float(d["Close"].iloc[-1] / d["Close"].iloc[40] - 1))
    stats("EMA crossback (the rule)", [x["ret"] for x in trades], [x["r"] for x in trades], [x["days"] for x in trades])
    stats("random uptrend day, same hold", base)
    print(f"{'buy and hold (avg stock)':<26} {np.mean(hold_all):+.0%} over the whole period\n")
    print("How the trades ended:")
    if not trades:
        return
    df = pd.DataFrame(trades)
    for why, g in df.groupby("why"):
        print(f"  {why:<17} {len(g):>5} trades  avg {g['ret'].mean():+.2%}")
    print("\nBy year:")
    df["year"] = pd.to_datetime(df["day"]).dt.year
    for y, g in df.groupby("year"):
        print(f"  {y}: {len(g):>5} trades  win rate {(g['ret'] > 0).mean():.0%}  avg {g['ret'].mean():+.2%}")
    print("\nLimits: today's S&P 500 members only (survivorship bias), no costs, closes used for exits, no market filter, no stock picking.")


if __name__ == "__main__":
    main()
