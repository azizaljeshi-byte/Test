"""Runs a past day through the REAL Quick code (quick.step), once with the rules before 7 Nov and once with the new ones, on the same data, so the live
code can be checked before it is deployed. Read only: it uses its own empty account and never touches the app's book. Job: quick_replay -> data/quick_replay.txt
Day: env QUICK_REPLAY_DAY (YYYY-MM-DD), default the last day Quick traded. Stocks: every stock Quick ranked, skipped or traded that day (more is better: the market gate
and the sector read use them too).
Limits (read before trusting a number): Yahoo 5-minute bars only. Quick reads a price every 20 seconds, so each bar is turned into 15 prices that walk open -> low -> high -> close
(or open -> high -> low -> close for a falling bar); the order of the high and the low inside a bar is a guess, which matters most for the pullback rule. The daily range (ATR) is the
average high-low of the previous days, volume is the day's running total, and there is no earnings, sector or daily-call data. So read the trade count and the shape, not the dollars."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

PER_BAR = 15            # 20-second prices in a 5-minute bar


def snap_for(t: str, atr: float, avg_vol: float) -> dict:
    return {"ticker": t, "technical_score": None,
            "payload": {"technical": {"atr": atr, "vol_avg20": avg_vol}, "quote": {"live_change": 0.0, "live_volume": 0.0}, "events": {"days_to_earnings": None}, "profile": {}}}


def bar_prices(o: float, h: float, lo: float, c: float) -> list[float]:
    way = [o, lo, h, c] if c >= o else [o, h, lo, c]
    at = [0, 5, 10, PER_BAR - 1]
    out = []
    for i in range(PER_BAR):
        k = max(j for j in range(3) if at[j] <= i)
        out.append(round(way[k] + (way[k + 1] - way[k]) * (i - at[k]) / (at[k + 1] - at[k]), 4))
    return out


def prepare(frames: dict, day: str) -> dict:
    d0 = pd.Timestamp(day, tz="America/New_York")
    out = {}
    for t, f in frames.items():
        if t == "SPY" or f is None or len(f) < 40:
            continue
        today = f[f.index.normalize() == d0]
        before = f[f.index.normalize() < d0]
        if len(today) < 30 or before.empty:
            continue
        daily = before.groupby(before.index.normalize()).agg(High=("High", "max"), Low=("Low", "min"), Volume=("Volume", "sum"))
        out[t] = {"bars": today, "prev": float(before.iloc[-1]["Close"]), "atr": float((daily["High"] - daily["Low"]).tail(10).mean()),
                  "vol": float(daily["Volume"].tail(10).mean())}
    return out


def replay(data: dict, day: str) -> dict:
    from stockwatch import quick
    book, marks = quick.new_book(), {}
    start = pd.Timestamp(f"{day} 09:30", tz="America/New_York")
    cum = {t: 0.0 for t in data}
    n = max(len(v["bars"]) for v in data.values())
    for bi in range(n):
        for j in range(PER_BAR):
            snaps, prices = {}, {}
            now = (start + pd.Timedelta(minutes=5 * bi) + pd.Timedelta(seconds=20 * j)).to_pydatetime()
            for t, v in data.items():
                if bi >= len(v["bars"]):
                    continue
                b = v["bars"].iloc[bi]
                px = bar_prices(float(b["Open"]), float(b["High"]), float(b["Low"]), float(b["Close"]))[j]
                s = snap_for(t, v["atr"], v["vol"])
                s["payload"]["quote"] = {"live_change": px / v["prev"] - 1, "live_volume": cum[t] + float(b["Volume"]) * (j + 1) / PER_BAR}
                snaps[t], prices[t] = s, px
            quick.step(book, marks, snaps, prices, now)
        for t, v in data.items():
            if bi < len(v["bars"]):
                cum[t] += float(v["bars"].iloc[bi]["Volume"])
    return book


def report(label: str, book: dict) -> list[str]:
    tr = book["trades"]
    closed = [t for t in tr if t["status"] == "CLOSED"]
    res = [t["result"] for t in closed]
    pct = [t["pct"] for t in closed]
    w = [x for x in pct if x > 0]
    out = [f"\n===== {label} =====",
           f"  trades {len(tr)}  closed {len(closed)}  wins {100 * len(w) / max(len(closed), 1):.0f}%  total ${sum(res):+,.0f}  avg {sum(pct) / max(len(pct), 1):+.2f}%  "
           f"avg win {(sum(w) / len(w)) if w else 0:+.2f}%  avg loss {(sum(x for x in pct if x <= 0) / max(len(pct) - len(w), 1)):+.2f}%  worst {min(pct, default=0):+.2f}%"]
    why: dict = {}
    for t in closed:
        k = str(t["exit_reason"]).split(":")[0].split("(")[0].strip()
        a = why.setdefault(k, [0, 0.0])
        a[0] += 1
        a[1] += t["result"]
    for k, (c, s) in sorted(why.items(), key=lambda kv: -kv[1][0]):
        out.append(f"    exit: {k:<44}{c:>4}  ${s:>+8,.0f}")
    drop: dict = {}
    for s in book.get("skipped", []):
        r = str(s["reason"])
        key = r.split(":")[0] if not r.startswith("waited") else r
        key = " ".join(key.split()[:9])
        drop[key] = drop.get(key, 0) + 1
    out.append("  not entered:")
    for k, v in sorted(drop.items(), key=lambda kv: -kv[1])[:10]:
        out.append(f"    {k:<70}{v:>4}")
    out.append("  trades (time, stock, setup, entry, exit, result, why out):")
    for t in tr[:80]:
        extra = f"  signal {t['signal']:.2f}" if t.get("signal") else ""
        out.append(f"    {str(t['opened'])[11:16]} {t['ticker']:<6}{t['kind']:<9}{t['entry']:>9.2f} -> {t.get('exit') or 0:>9.2f}  {t.get('pct') or 0:>+6.2f}%  ${t['result']:>+7.0f}  {str(t.get('exit_reason'))[:50]}{extra}")
    return out


def main() -> None:
    from stockwatch import quick, rising
    from stockwatch.store import Store
    book0 = quick.load_book(Store(), migrate=False)
    days = sorted({str(t["opened"])[:10] for t in book0["trades"] if t.get("opened")})
    day = os.getenv("QUICK_REPLAY_DAY") or days[-1]
    names = {t["ticker"] for t in book0["trades"] if str(t.get("opened"))[:10] == day}
    names |= {r["ticker"] for r in book0.get("ranked", []) if r.get("day") == day}
    names |= {s["ticker"] for s in book0.get("skipped", []) if s.get("day") == day}
    real = [t for t in book0["trades"] if str(t.get("opened"))[:10] == day and t["status"] == "CLOSED"]
    print(f"QUICK REPLAY for {day}: {len(names)} stocks. Quick really took {len(real)} trades that day and made ${sum(t['result'] for t in real):+,.0f}.")
    frames = rising.fetch(sorted(names), "1mo", "5m")
    data = prepare(frames, day)
    print(f"{len(data)} stocks had usable bars.")
    old = {"PULLBACK_GATE": False, "TAKE_FIRST": False, "OPENING_CAP": False, "MAX_LOSS_PCT": 2.0}
    keep = {k: getattr(quick, k) for k in old}
    for k, v in old.items():
        setattr(quick, k, v)
    try:
        print("\n".join(report("RULES BEFORE 7 NOV (buy at the signal, trailing exit, 2% stop, 30 free minutes)", replay(data, day))))
    finally:
        for k, v in keep.items():
            setattr(quick, k, v)
    print("\n".join(report("NEW RULES (pullback entry, 3 in the first 15 minutes, 1.5% stop, +1% unless riding)", replay(data, day))))
    print("\n" + __doc__.split("Limits")[1])


if __name__ == "__main__":
    main()
