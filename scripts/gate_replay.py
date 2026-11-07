"""What if Quick had waited before entering? Replays the setups of one day (default: the last day with trades) on 5-minute bars under three entry rules and
the same simple exit, so the three are comparable: NOW (enter at the setup price, as Quick did), HOLD (wait for a finished 5-minute bar that stays above the
setup price with rising RSI/MACD and building volume) and PULLBACK (wait for a dip under the setup price, then a bounce bar). Also replays a random few of the
setups Quick skipped. Read only: changes nothing. Run: gate_replay.bat (or the job gate_replay) -> data/gate_replay.txt
Limits: 5-minute bars, one simple exit model for all three (the real Quick exits are richer), no pace or loss limits, $2,500 a trade (5% of $50,000)."""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pandas as pd  # noqa: E402

SIZE, STOP_PCT, TRAIL_ARM, TRAIL_PCT = 2500.0, 1.5, 1.0, 1.0
WAIT_BARS, DIP_PCT, CANCEL_PCT, NO_PROGRESS_BARS, SAMPLE = 6, 0.3, 1.5, 12, int(os.getenv("GATE_SAMPLE", "12"))


def ny(s) -> pd.Timestamp:
    t = pd.Timestamp(str(s)[:16])
    return t.tz_localize("America/New_York") if t.tzinfo is None else t.tz_convert("America/New_York")


def indicators(f: pd.DataFrame) -> pd.DataFrame:
    from stockwatch import technical as ta
    out = f.copy()
    out["rsi"] = ta.rsi(out["Close"])
    line, sig = ta.macd(out["Close"])
    out["hist"] = line - sig
    out["vavg"] = out["Volume"].rolling(6).mean().shift(1)
    return out


def exit_run(f: pd.DataFrame, i0: int, entry: float, stop_pct: float = STOP_PCT, arm: float = TRAIL_ARM, trail: float = TRAIL_PCT) -> tuple[float, str, int]:
    """Walks bars after i0. Returns (exit price, reason, bars held)."""
    stop, peak = entry * (1 - stop_pct / 100), entry
    for k in range(i0 + 1, len(f)):
        b = f.iloc[k]
        if b["Low"] <= stop:
            return min(float(b["Open"]), stop), "stop", k - i0
        peak = max(peak, float(b["High"]))
        if peak >= entry * (1 + arm / 100):
            stop = max(stop, peak * (1 - trail / 100))
        if (k - i0) >= NO_PROGRESS_BARS and peak < entry * 1.005:
            return float(b["Close"]), "no progress", k - i0
        if f.index[k].hour == 15 and f.index[k].minute >= 55:
            return float(b["Close"]), "end of day", k - i0
    return float(f.iloc[-1]["Close"]), "end of data", len(f) - 1 - i0


def entry_now(f, i, p0):
    return i, p0


def entry_hold(f, i, p0):
    for k in range(i + 1, min(i + 1 + WAIT_BARS, len(f))):
        b, a = f.iloc[k], f.iloc[k - 1]
        if b["Close"] < p0 * (1 - 0.5 / 100):
            return None, "broke under the level"
        if b["Close"] >= p0 and b["rsi"] > a["rsi"] and b["hist"] > a["hist"] and b["Volume"] >= (b["vavg"] or 0):
            return k, float(b["Close"])
    return None, "never confirmed"


def entry_pullback(f, i, p0):
    dipped = None
    for k in range(i + 1, min(i + 1 + WAIT_BARS, len(f))):
        b, a = f.iloc[k], f.iloc[k - 1]
        if b["Close"] < p0 * (1 - CANCEL_PCT / 100):
            return None, "fell too far"
        if dipped is None and b["Low"] <= p0 * (1 - DIP_PCT / 100):
            dipped = k
            continue
        if dipped is not None and b["Close"] > a["High"] and b["Close"] >= f.iloc[dipped]["Low"]:
            return k, float(b["Close"])
    return None, "no pullback" if dipped is None else "no bounce"


def entry_hold2(f, i, p0):
    """A looser HOLD: a finished bar closes within 0.2% of the level or above, RSI or MACD rising, no volume test; cancel 1% under."""
    for k in range(i + 1, min(i + 1 + WAIT_BARS, len(f))):
        b, a = f.iloc[k], f.iloc[k - 1]
        if b["Close"] < p0 * (1 - 1.0 / 100):
            return None, "broke under the level"
        if b["Close"] >= p0 * (1 - 0.2 / 100) and (b["rsi"] > a["rsi"] or b["hist"] > a["hist"]):
            return k, float(b["Close"])
    return None, "never confirmed"


RULES = {"NOW": entry_now, "HOLD": entry_hold, "HOLD2": entry_hold2, "PULLBACK": entry_pullback}


def run_one(f: pd.DataFrame, when: pd.Timestamp, p0: float) -> dict:
    day = f[f.index.normalize() == when.normalize()]
    if len(day) < 20:
        return {"err": "too little data"}
    day = indicators(day)
    idx = day.index[day.index <= when]
    if not len(idx):
        return {"err": "setup before the first bar"}
    i = day.index.get_loc(idx[-1])
    res = {}
    for name, rule in RULES.items():
        k, px = rule(day, i, p0)
        if k is None:
            res[name] = {"in": False, "why": px}
            continue
        xp, why, held = exit_run(day, k, px)
        pct = (xp / px - 1) * 100
        res[name] = {"in": True, "at": day.index[k].strftime("%H:%M"), "px": px, "pct": pct, "usd": SIZE * pct / 100, "why": why, "held": held * 5}
    return res


def summary(rows: list[dict]) -> list[str]:
    out = [f"  {'rule':<9}{'trades':>7}{'skipped':>8}{'wins':>6}{'avg %':>8}{'total $':>10}{'worst %':>9}"]
    for name in RULES:
        got = [r[name] for r in rows if name in r and r[name]["in"]]
        n_all = len([r for r in rows if name in r])
        w = [g for g in got if g["pct"] > 0]
        out.append(f"  {name:<9}{len(got):>7}{n_all - len(got):>8}{(str(round(100 * len(w) / len(got))) + '%') if got else '-':>6}"
                   f"{(sum(g['pct'] for g in got) / len(got)) if got else 0:>+8.2f}{sum(g['usd'] for g in got):>+10,.0f}{min((g['pct'] for g in got), default=0):>+9.2f}")
    return out


def lines(title: str, items: list[dict]) -> list[str]:
    out = [f"\n{title}"]
    for it in items:
        if "err" in it["r"]:
            out.append(f"  {it['t']:<6} {it['time']} {it['p0']:>8.2f}  (not replayed: {it['r']['err']})")
            continue
        cells = []
        for name in RULES:
            x = it["r"][name]
            cells.append(f"{name} {x['pct']:+5.1f}% {x['at']}" if x["in"] else f"{name} no ({x['why']})")
        out.append(f"  {it['t']:<6} {it['time']} {it['p0']:>8.2f} " + " | ".join(cells) + (f"   [Quick really: {it['real']}]" if it.get("real") else ""))
    return out

EXITS = {"A loose (about Quick today)": (2.2, 2.0, 1.2), "B stop 1.5, lock at +1, trail 1": (1.5, 1.0, 1.0),
         "C stop 1.5, lock at +0.7, trail 0.7": (1.5, 0.7, 0.7), "D stop 1.2, lock at +0.7, trail 0.6": (1.2, 0.7, 0.6)}


def exit_study(trades, book, frames, days) -> None:
    """Same entries as Quick (NOW), different exits, with and without a pace limit of 3 new entries in any 10 minutes (best rank first)."""
    rank = {}
    for r in book.get("ranked", []):
        if r.get("taken"):
            rank[(r["day"], r["ticker"])] = r.get("rank", 99)
    entries = []
    for t in trades:
        d = str(t["opened"])[:10]
        f = frames.get(t["ticker"])
        if d not in days or f is None:
            continue
        w = ny(t["opened"])
        day = f[f.index.normalize() == w.normalize()]
        idx = day.index[day.index <= w]
        if len(day) < 20 or not len(idx):
            continue
        entries.append({"t": t["ticker"], "d": d, "w": w, "p0": float(t["entry"]), "day": day, "i": day.index.get_loc(idx[-1]), "rank": rank.get((d, t["ticker"]), 99)})

    def paced(es):
        ok, taken = [], []
        for e in sorted(es, key=lambda x: (x["w"], x["rank"])):
            if len([x for x in taken if x["d"] == e["d"] and (e["w"] - x["w"]).total_seconds() < 600]) < 3:
                taken.append(e)
                ok.append(e)
        return ok

    print("\n===== EXIT STUDY: the same entries as Quick, different exits (flat $2,500 a trade) =====")
    print(f"  {'exit rule':<40}{'pace':<10}{'trades':>7}{'wins':>6}{'avg %':>8}{'total $':>10}{'worst %':>9}")
    for name, (sp, arm, tr) in EXITS.items():
        for label, es in (("none", entries), ("3 per 10m", paced(entries))):
            res = []
            for e in es:
                xp, _, _ = exit_run(e["day"], e["i"], e["p0"], sp, arm, tr)
                res.append((xp / e["p0"] - 1) * 100)
            if res:
                print(f"  {name:<40}{label:<10}{len(res):>7}{str(round(100 * len([x for x in res if x > 0]) / len(res))) + '%':>6}{sum(res) / len(res):>+8.2f}{sum(SIZE * x / 100 for x in res):>+10,.0f}{min(res):>+9.2f}")
    print("  By day (exit B, no pace limit vs exit B with pace limit vs exit A):")
    for d in days:
        row = []
        for nm, sel in (("A", "A loose (about Quick today)"), ("B", "B stop 1.5, lock at +1, trail 1")):
            sp, arm, tr = EXITS[sel]
            for label, pool in (("", entries), ("+pace", paced(entries))):
                tot = sum(SIZE * (exit_run(e["day"], e["i"], e["p0"], sp, arm, tr)[0] / e["p0"] - 1) for e in pool if e["d"] == d)
                row.append(f"{nm}{label} {tot:+,.0f}")
        real = sum(t.get("result", 0) for t in trades if str(t["opened"])[:10] == d and t.get("status") == "CLOSED")
        print(f"    {d}  real {real:+,.0f} | " + " | ".join(row))


def one_day(want, trades, book, frames, pick_n):
    todays = [t for t in trades if str(t["opened"])[:10] == want]
    skipped = [s for s in book.get("skipped", []) if s.get("day") == want and s.get("price")]
    taken = {t["ticker"] for t in todays}
    seen, uniq = set(), []
    for s in skipped:
        if s["ticker"] not in taken and s["ticker"] not in seen:
            seen.add(s["ticker"])
            uniq.append(s)
    random.seed(7)
    pick = random.sample(uniq, min(pick_n, len(uniq)))
    real, skip = [], []
    for t in sorted(todays, key=lambda x: x["opened"]):
        f = frames.get(t["ticker"])
        r = run_one(f, ny(t["opened"]), float(t["entry"])) if f is not None else {"err": "no data"}
        real.append({"t": t["ticker"], "time": str(t["opened"])[11:16], "p0": float(t["entry"]), "r": r,
                     "real": f"{t.get('result', 0):+.0f}$ {str(t.get('exit_reason'))[:24]}" if t.get("status") == "CLOSED" else "still open"})
    for s in sorted(pick, key=lambda x: x["time"]):
        f = frames.get(s["ticker"])
        t0 = pd.Timestamp(f"{want} {s['time']}").tz_localize("America/New_York")
        r = run_one(f, t0, float(s["price"])) if f is not None else {"err": "no data"}
        skip.append({"t": s["ticker"], "time": s["time"], "p0": float(s["price"]), "r": r, "real": f"skipped: {str(s.get('reason'))[:40]}"})
    actual = sum(t.get("result", 0) for t in todays if t.get("status") == "CLOSED")
    return todays, uniq, real, skip, actual


def main() -> None:
    from stockwatch import quick, rising
    from stockwatch.store import Store
    book = quick.load_book(Store(), migrate=False)
    trades = [t for t in book["trades"] if t.get("opened")]
    days = sorted({str(t["opened"])[:10] for t in trades})
    want = [d for d in os.getenv("GATE_DAYS", "").replace(",", " ").split() if d] or days[-5:]
    plan = {}
    names = set()
    for d in want:
        todays = [t for t in trades if str(t["opened"])[:10] == d]
        sk = [s for s in book.get("skipped", []) if s.get("day") == d and s.get("price")]
        plan[d] = True
        names |= {t["ticker"] for t in todays} | {s["ticker"] for s in sk} | {r["ticker"] for r in book.get("ranked", []) if r.get("day") == d}
    print(f"GATE REPLAY for {', '.join(want)}. Downloading {len(names)} stocks, 5-minute bars (Yahoo keeps about 5 trading days)...")
    frames = rising.fetch(sorted(names), "5d", "5m")
    all_real, all_skip = [], []
    for d in want:
        todays, uniq, real, skip, actual = one_day(d, trades, book, frames, SAMPLE)
        ok_r = [x["r"] for x in real if "err" not in x["r"]]
        ok_s = [x["r"] for x in skip if "err" not in x["r"]]
        all_real += ok_r
        all_skip += ok_s
        print(f"\n===== {d}: Quick took {len(todays)} trades and really made {actual:+,.0f} $ (its own exits); {len(uniq)} other stocks skipped, {len(skip)} replayed; {len(real) - len(ok_r)} trades had no usable bars =====")
        print("TAKEN:")
        print("\n".join(summary(ok_r)))
        if ok_s:
            print("SKIPPED (random few):")
            print("\n".join(summary(ok_s)))
        if d == want[-1] or os.getenv("GATE_DETAIL"):
            print("\n".join(lines("TAKEN, one by one", real)))
            print("\n".join(lines("SKIPPED sample, one by one", skip)))
    print("\n===== ALL DAYS TOGETHER =====\nTAKEN:")
    print("\n".join(summary(all_real)))
    print("SKIPPED (random few):")
    print("\n".join(summary(all_skip)))
    exit_study(trades, book, frames, want)
    try:
        import scenario_search
        scenario_search.run(book, trades, frames, want)
    except Exception as e:                                   # the other studies stay in the report whatever happens here
        import traceback
        print(f"\n(scenario search failed: {e})\n{traceback.format_exc()}")
    print("\nHow to read: NOW = enter at the setup price. HOLD = a later finished 5-min bar closes at or above it with RSI and MACD rising and volume at least the recent average (cancel if a bar closes 0.5% under, or 30 min pass). "
          "HOLD2 = looser: close within 0.2% of the level, RSI or MACD rising, no volume test (cancel 1% under). PULLBACK = price dips 0.3% under the setup price, then a bar closes above the previous high (cancel if 1.5% under, or 30 min pass). "
          "Exit for all: stop 1.5% under entry, trail 1% under the peak once up 1%, out after 60 min without +0.5%, out at 15:55. The real Quick exits differ, so compare the rules with each other, not with the real number.")


if __name__ == "__main__":
    main()
