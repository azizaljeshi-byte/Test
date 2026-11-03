"""How did the candidate list's stocks do after they were found? READ ONLY: reads the app's database, downloads 5-minute bars from Yahoo,
writes data/candidates_outcomes.csv and prints a short summary. Changes nothing in the app.

For each row of the candidate list (last 10 days) it takes the price at the "found" time (pre-open rows: the 09:30 open, since nothing can
be bought before it) and measures the return after +30 min, +60 min and at the close, the best and worst point, and the same for SPY over
the same window. Rows are grouped by rule (bounce / breakout / New call), by when they were found and by sector.
Usage:  python scripts/candidates_outcomes.py [path to stockwatch.db]
"""
from __future__ import annotations

import csv
import json
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def kind_of(qualified: str) -> str:
    q = qualified or ""
    if "bounce candidate" in q:
        return "bounce"
    if "breakout candidate" in q:
        return "breakout"
    if "New call" in q:
        return "newcall"
    return "other"


def found_minutes(found: str) -> int | None:
    """'refresh 10:05' -> 605; 'pre-open 09:20' -> 570 (the open, the first moment it can be bought)."""
    try:
        phase, hhmm = found.rsplit(" ", 1)
        h, m = (int(x) for x in hhmm.split(":"))
    except (ValueError, AttributeError):
        return None
    return 9 * 60 + 30 if phase.startswith("pre") else h * 60 + m


def forward(closes: list[tuple[int, float]], start_min: int) -> dict | None:
    """closes = [(minute of day, close)] for one session, sorted. Returns returns from the first bar at/after start_min."""
    after = [(t, c) for t, c in closes if t >= start_min]
    if not after or after[0][0] - start_min > 10:
        return None
    t0, p0 = after[0]
    out = {"entry": p0}
    for name, mins in (("p30", 30), ("p60", 60)):
        later = [c for t, c in after if t >= t0 + mins]
        out[name] = round((later[0] / p0 - 1) * 100, 2) if later and after[-1][0] >= t0 + mins else None
    out["close"] = round((after[-1][1] / p0 - 1) * 100, 2)
    path = [(c / p0 - 1) * 100 for _t, c in after]
    out["best"], out["worst"] = round(max(path), 2), round(min(path), 2)
    return out


def summarize(rows: list[dict], key: str) -> list[tuple]:
    groups: dict = {}
    for r in rows:
        groups.setdefault(r[key], []).append(r)
    res = []
    for g, rs in sorted(groups.items(), key=lambda kv: str(kv[0])):
        def avg(f):
            v = [x[f] for x in rs if x.get(f) is not None]
            return (round(statistics.mean(v), 2), len(v)) if v else (None, 0)
        up = [x["p60"] > 0 for x in rs if x.get("p60") is not None]
        res.append((g, len(rs), avg("p30"), avg("p60"), avg("close"), avg("excess_p60"), None if not up else round(100 * sum(up) / len(up))))
    return res


def main(db: str) -> None:
    import pandas as pd
    import yfinance as yf
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    raw = con.execute("select value from settings where key='candidates_log'").fetchone()
    days = json.loads(raw[0])["days"] if raw else {}
    tickers = sorted({r["ticker"] for d in days.values() for r in d["rows"].values()} | {"SPY"})
    print(f"{sum(len(d['rows']) for d in days.values())} rows over {len(days)} days, {len(tickers)} tickers")
    sess: dict = {}
    for i in range(0, len(tickers), 40):
        ch = tickers[i:i + 40]
        df = yf.download(ch, period="60d", interval="5m", group_by="ticker", auto_adjust=True, threads=True, progress=False, prepost=False)
        for t in ch:
            try:
                s = df[t]["Close"].dropna()
                idx = pd.to_datetime(s.index)
                idx = idx.tz_convert("America/New_York") if idx.tz is not None else idx.tz_localize("America/New_York")
                for ts, c in zip(idx, s):
                    sess.setdefault(t, {}).setdefault(ts.date().isoformat(), []).append((ts.hour * 60 + ts.minute, float(c)))
            except Exception:
                continue
    out = []
    for day, d in sorted(days.items()):
        for r in d["rows"].values():
            sm = found_minutes(r.get("found", ""))
            bars = sess.get(r["ticker"], {}).get(day)
            if sm is None or not bars:
                continue
            f = forward(bars, sm)
            spy = forward(sess.get("SPY", {}).get(day, []), sm) if f else None
            if not f:
                continue
            row = {"day": day, "ticker": r["ticker"], "kind": kind_of(r.get("qualified")), "found": r.get("found"),
                   "bucket": f"{(sm // 60):02d}:{(sm % 60) // 30 * 30:02d}", "sector": r.get("sector") or "unknown",
                   "move_atr": r.get("move_atr"), **f}
            row["excess_p60"] = None if not spy or f["p60"] is None or spy["p60"] is None else round(f["p60"] - spy["p60"], 2)
            out.append(row)
    p = ROOT / "data" / "candidates_outcomes.csv"
    p.parent.mkdir(exist_ok=True)
    if out:
        with p.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(out[0]))
            w.writeheader()
            w.writerows(out)
    print(f"{len(out)} rows measured -> {p}\n")
    for key in ("kind", "bucket", "sector"):
        print(f"by {key}:  n | +30m avg (n) | +60m avg (n) | close avg (n) | +60m vs SPY | % up at +60m")
        for g, n, a30, a60, ac, ex, up in summarize(out, key):
            print(f"  {str(g):<24}{n:>4} | {a30[0]} ({a30[1]}) | {a60[0]} ({a60[1]}) | {ac[0]} ({ac[1]}) | {ex[0]} | {up}")
        print()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "data" / "stockwatch.db"))
