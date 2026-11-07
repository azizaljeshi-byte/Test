"""How good was Quick's selection on the last session, entered or not? Lists every stock Quick selected (its ranked list plus the setups it skipped),
whether it entered, why not, and what the price did in the next 60 minutes on 5-minute bars. Read only: changes nothing.
Run: job selection_report -> data/selection_report.txt. The day is the last one in Quick's records (GATE_DAY overrides)."""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pandas as pd  # noqa: E402

from gate_replay import exit_run, ny  # noqa: E402
from scenario_search import first_touch, path  # noqa: E402


def norm(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\d.,$%]+", "#", str(s or ""))).strip()[:60]


def candidates(book: dict, day: str) -> list[dict]:
    """One row per stock, setup and outcome: the earliest time it was selected, and whether Quick took it."""
    trades = [t for t in book["trades"] if str(t["opened"])[:10] == day]
    out, seen = [], {}
    for r in book.get("ranked", []):
        if r.get("day") != day or not r.get("price"):
            continue
        key = (r["ticker"], r["kind"], bool(r.get("taken")), norm(r.get("why_not")))
        if key in seen:
            continue
        seen[key] = 1
        out.append({"t": r["ticker"], "time": r["time"], "kind": r["kind"], "grade": r.get("grade"), "rank": r.get("rank"), "of": r.get("of"), "p0": float(r["price"]),
                    "entered": bool(r.get("taken")), "why": "" if r.get("taken") else norm(r.get("why_not")) or "not stated"})
    have = {(c["t"], c["time"][:4]) for c in out}
    for s in book.get("skipped", []):
        if s.get("day") == day and s.get("price") and (s["ticker"], s["time"][:4]) not in have:
            out.append({"t": s["ticker"], "time": s["time"], "kind": s.get("kind", ""), "grade": None, "rank": None, "of": None, "p0": float(s["price"]), "entered": False, "why": norm(s.get("reason"))})
    # a stock with a real trade is "entered" even if its ranked row said otherwise (it was taken at another moment)
    by = defaultdict(list)
    for t in trades:
        by[t["ticker"]].append(t)
    for c in out:
        c["trade"] = None
        if c["entered"]:
            near = [t for t in by.get(c["t"], []) if abs((ny(t["opened"]) - pd.Timestamp(f"{day} {c['time']}").tz_localize("America/New_York")).total_seconds()) <= 300]
            c["trade"] = near[0] if near else (by[c["t"]][0] if by.get(c["t"]) else None)
    return sorted(out, key=lambda c: (c["time"], c["rank"] or 99))


def measure(c: dict, frames: dict, day: str) -> bool:
    f = frames.get(c["t"])
    if f is None:
        return False
    d = f[f.index.normalize() == pd.Timestamp(day, tz="America/New_York")]
    when = pd.Timestamp(f"{day} {c['time']}").tz_localize("America/New_York")
    idx = d.index[d.index <= when]
    if len(d) < 20 or not len(idx):
        return False
    i = d.index.get_loc(idx[-1])
    c.update(path(d, i, c["p0"]))
    c["c_pct"] = (exit_run(d, i, c["p0"], 1.5, 0.7, 0.7)[0] / c["p0"] - 1) * 100
    c["touch"] = first_touch(d, i, c["p0"], 1.5, 1.0)                  # +1% before -1.5% within 60 minutes?
    return True


def line(label: str, rows: list[dict]) -> str:
    if not rows:
        return f"  {label:<34} n=  0"
    n = len(rows)
    w = len([r for r in rows if r["c_pct"] > 0])
    hit = len([r for r in rows if r["touch"] > 0])
    return (f"  {label:<34} n={n:>3}  +1% before -1.5%: {100 * hit / n:>3.0f}%  wins(exit C) {100 * w / n:>3.0f}%  avg {sum(r['c_pct'] for r in rows) / n:+5.2f}%  "
            f"avg best {sum(r['mfe'] for r in rows) / n:+5.2f}%  avg worst {sum(r['mae'] for r in rows) / n:+5.2f}%  total ${sum(2500 * r['c_pct'] / 100 for r in rows):>+6,.0f}")


def main() -> None:
    from stockwatch import quick, rising
    from stockwatch.store import Store
    book = quick.load_book(Store(), migrate=False)
    days = sorted({r["day"] for r in book.get("ranked", [])} | {str(t["opened"])[:10] for t in book["trades"]})
    day = os.getenv("GATE_DAY") or days[-1]
    cs = candidates(book, day)
    names = sorted({c["t"] for c in cs})
    print(f"SELECTION REPORT for {day}: {len(cs)} selected setups on {len(names)} stocks. Downloading 5-minute bars...")
    frames = rising.fetch(names, "5d", "5m")
    rows = [c for c in cs if measure(c, frames, day)]
    print(f"{len(rows)} measured, {len(cs) - len(rows)} without usable bars.\n")
    ent = [c for c in rows if c["entered"]]
    miss = [c for c in rows if not c["entered"]]
    print("1. Entered or not (what the price did in the 60 minutes after the signal; exit C = stop 1.5, lock at +0.7, trail 0.7; $2,500 a trade):")
    print(line("ALL selected", rows))
    print(line("ENTERED", ent))
    print(line("NOT ENTERED", miss))
    print("\n2. Why it was not entered:")
    why = defaultdict(list)
    for c in miss:
        why[c["why"]].append(c)
    for k, v in sorted(why.items(), key=lambda kv: -len(kv[1])):
        print(line(k[:34], v))
    print("\n3. By rank at the time of selection:")
    for lab, fn in (("rank 1", lambda r: r == 1), ("rank 2-3", lambda r: r in (2, 3)), ("rank 4+", lambda r: r is not None and r >= 4), ("no rank saved", lambda r: r is None)):
        print(line(lab, [c for c in rows if fn(c["rank"])]))
    print("\n4. By setup kind and grade:")
    for k in sorted({c["kind"] for c in rows}):
        print(line(f"kind {k}", [c for c in rows if c["kind"] == k]))
    for g in sorted({str(c["grade"]) for c in rows}):
        print(line(f"grade {g}", [c for c in rows if str(c["grade"]) == g]))
    print("\n5. By half hour (New York time):")
    for h0 in ("09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "13:00", "14:00", "15:00"):
        sel = [c for c in rows if c["time"] >= h0 and c["time"] < {"09:30": "10:00", "10:00": "10:30", "10:30": "11:00", "11:00": "11:30", "11:30": "12:00", "12:00": "13:00", "13:00": "14:00", "14:00": "15:00", "15:00": "16:00"}[h0]]
        if sel:
            print(line(f"{h0} on", sel))
    print("\n6. The biggest misses (not entered, biggest 60-minute run up):")
    for c in sorted(miss, key=lambda c: -c["mfe"])[:12]:
        print(f"  {c['t']:<6} {c['time']} {c['kind'][:10]:<10} rank {c['rank']} best {c['mfe']:+.1f}% worst {c['mae']:+.1f}%  exit C {c['c_pct']:+.1f}%   why not: {c['why']}")
    print("\n7. The worst entries (entered, worst result under exit C), with what Quick really got:")
    for c in sorted(ent, key=lambda c: c["c_pct"])[:12]:
        t = c.get("trade") or {}
        real = f"{t.get('result', 0):+.0f}$ {str(t.get('exit_reason'))[:30]}" if t else "no trade record"
        print(f"  {c['t']:<6} {c['time']} {c['kind'][:10]:<10} rank {c['rank']} best {c['mfe']:+.1f}% worst {c['mae']:+.1f}%  exit C {c['c_pct']:+.1f}%   Quick really: {real}")
    print("\n8. Every selected setup:")
    for c in rows:
        t = c.get("trade") or {}
        real = f" real {t.get('result', 0):+.0f}$" if c["entered"] and t else ""
        print(f"  {c['time']} {c['t']:<6} {c['kind'][:10]:<10} g {str(c['grade'])[:2]:<2} rank {str(c['rank']):>4}/{str(c['of']):<4} {'ENTERED' if c['entered'] else 'no     '} "
              f"best {c['mfe']:+5.1f}% worst {c['mae']:+5.1f}% C {c['c_pct']:+5.1f}%{real}  {c['why']}")


if __name__ == "__main__":
    main()
