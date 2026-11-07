"""Which scenario turns Quick's setups into profitable trades? Builds the setups of the replay days (the trades Quick took plus the ranked ones it passed over),
measures what each looked like at the moment of the signal and what happened next on 5-minute bars, then:
  1. shows what exit structure (stop / target) would have paid, and how far the trades ran in their favour and against them;
  2. looks for entry conditions that separate winners from losers, and checks them honestly: a rule is chosen on four days and scored on the fifth (walk-forward).
Read only. Limits: few days, 5-minute bars, and any rule found on this little data may be luck; the walk-forward score is the one to trust."""
from __future__ import annotations

import itertools
import math

import pandas as pd

from gate_replay import exit_run, indicators, ny

FEATS = ["mins", "ext_open", "ext_vwap", "from_hi", "rsi", "rsi_d", "hist_d", "vol_x", "gap", "rank", "score"]
LOOK = 12                                   # bars (60 minutes) of path to measure
GRID = [(1.0, 1.0), (1.5, 1.0), (1.5, 1.5), (1.5, 2.0), (1.5, 3.0), (2.0, 3.0), (1.0, 2.0)]


def features(full: pd.DataFrame, when: pd.Timestamp, p0: float) -> dict | None:
    f = indicators(full)
    day = f[f.index.normalize() == when.normalize()]
    before = f[f.index.normalize() < when.normalize()]
    idx = day.index[day.index <= when]
    if len(day) < 20 or not len(idx):
        return None
    i = day.index.get_loc(idx[-1])
    fin = day.iloc[:i]                                       # finished bars only: nothing from the future
    if len(fin) < 2 or before.empty:
        return None
    typ = (fin["High"] + fin["Low"] + fin["Close"]) / 3
    vw = float((typ * fin["Volume"]).sum() / max(fin["Volume"].sum(), 1))
    past = [d for _, d in before.groupby(before.index.normalize()) if len(d) >= len(fin)]
    pv = [float(d["Volume"].iloc[:len(fin)].sum()) for d in past]
    if not pv or sum(pv) == 0:
        return None
    last, prev = fin.iloc[-1], fin.iloc[-2]
    return {"i": i, "day": day, "mins": when.hour * 60 + when.minute - 570, "ext_open": (p0 / float(day.iloc[0]["Open"]) - 1) * 100,
            "ext_vwap": (p0 / vw - 1) * 100, "from_hi": (p0 / float(fin["High"].max()) - 1) * 100, "rsi": float(last["rsi"]),
            "rsi_d": float(last["rsi"] - prev["rsi"]), "hist_d": float(last["hist"] - prev["hist"]),
            "vol_x": float(fin["Volume"].sum()) / (sum(pv) / len(pv)), "gap": (float(day.iloc[0]["Open"]) / float(before.iloc[-1]["Close"]) - 1) * 100}


def path(day: pd.DataFrame, i: int, p0: float) -> dict:
    nxt = day.iloc[i + 1:i + 1 + LOOK]
    return {"mfe": (float(nxt["High"].max()) / p0 - 1) * 100 if len(nxt) else 0.0, "mae": (float(nxt["Low"].min()) / p0 - 1) * 100 if len(nxt) else 0.0}


def first_touch(day: pd.DataFrame, i: int, p0: float, stop: float, target: float) -> float:
    for k in range(i + 1, min(i + 1 + LOOK, len(day))):
        b = day.iloc[k]
        if b["Low"] <= p0 * (1 - stop / 100):
            return -stop
        if b["High"] >= p0 * (1 + target / 100):
            return target
    last = day.iloc[min(i + LOOK, len(day) - 1)]
    return (float(last["Close"]) / p0 - 1) * 100


def setups(book, trades, frames, days) -> list[dict]:
    cand, seen = [], set()
    for t in trades:
        d = str(t["opened"])[:10]
        if d in days:
            cand.append({"d": d, "t": t["ticker"], "w": ny(t["opened"]), "p0": float(t["entry"]), "rank": 99, "score": 0.0, "took": True, "kind": t.get("kind", "")})
    for r in book.get("ranked", []):
        if r.get("day") in days and not r.get("taken") and r.get("price"):
            cand.append({"d": r["day"], "t": r["ticker"], "w": pd.Timestamp(f"{r['day']} {r['time']}").tz_localize("America/New_York"), "p0": float(r["price"]),
                         "rank": r.get("rank", 99), "score": float(r.get("score") or 0), "took": False, "kind": r.get("kind", "")})
    rk = {(r["day"], r["ticker"]): (r.get("rank", 99), float(r.get("score") or 0)) for r in book.get("ranked", []) if r.get("taken")}
    out = []
    for c in cand:
        key = (c["d"], c["t"], c["w"].floor("5min"))
        f = frames.get(c["t"])
        if key in seen or f is None:
            continue
        seen.add(key)
        ft = features(f, c["w"], c["p0"])
        if ft is None:
            continue
        if c["took"]:
            c["rank"], c["score"] = rk.get((c["d"], c["t"]), (99, 0.0))
        day, i = ft.pop("day"), ft.pop("i")
        c.update(ft)
        c["pct"] = (exit_run(day, i, c["p0"], 1.5, 0.7, 0.7)[0] / c["p0"] - 1) * 100
        c.update(path(day, i, c["p0"]))
        c["grid"] = {g: first_touch(day, i, c["p0"], g[0], g[1]) for g in GRID}
        out.append(c)
    return out


def stats(rows: list[dict], key="pct") -> str:
    if not rows:
        return "n=0"
    v = [r[key] for r in rows]
    return f"n={len(v):>3} wins {100 * len([x for x in v if x > 0]) / len(v):>3.0f}% avg {sum(v) / len(v):>+5.2f}% total ${sum(2500 * x / 100 for x in v):>+6,.0f}"


def conds(train: list[dict]) -> list[tuple]:
    out = []
    for ft in FEATS:
        vals = sorted(r[ft] for r in train if r.get(ft) is not None and not math.isnan(r[ft]))
        if len(vals) < 20 or len(set(vals)) < 4:
            continue
        for q in (0.33, 0.5, 0.67):
            cut = vals[int(q * (len(vals) - 1))]
            out += [(ft, ">=", cut), (ft, "<=", cut)]
    return out


def ok(r: dict, c: tuple) -> bool:
    v = r.get(c[0])
    return v is not None and not math.isnan(v) and (v >= c[2] if c[1] == ">=" else v <= c[2])


def best_rule(train: list[dict], min_n: int = 12):
    cs = conds(train)
    best = None
    for combo in itertools.chain(((c,) for c in cs), itertools.combinations(cs, 2)):
        if len({c[0] for c in combo}) < len(combo):
            continue
        sel = [r for r in train if all(ok(r, c) for c in combo)]
        if len(sel) < min_n:
            continue
        v = [r["pct"] for r in sel]
        m = sum(v) / len(v)
        sd = (sum((x - m) ** 2 for x in v) / max(len(v) - 1, 1)) ** 0.5 or 1
        score = m / sd * math.sqrt(len(v))
        if best is None or score > best[0]:
            best = (score, combo, sel)
    return best


def name(combo) -> str:
    return " and ".join(f"{c[0]} {c[1]} {c[2]:.2f}" for c in combo)


def run(book, trades, frames, days) -> None:
    rows = setups(book, trades, frames, days)
    print(f"\n===== SCENARIO SEARCH: {len(rows)} setups with usable bars ({len([r for r in rows if r['took']])} Quick took, {len([r for r in rows if not r['took']])} it passed over) =====")
    if len(rows) < 30:
        print("  too few setups to say anything")
        return
    print("\n1. What the trades did in the 60 minutes after the signal (price path, before any exit):")
    for lab, sel in (("all", rows), ("Quick took", [r for r in rows if r["took"]]), ("passed over", [r for r in rows if not r["took"]])):
        if sel:
            print(f"  {lab:<12} n={len(sel):>3}  average best point {sum(r['mfe'] for r in sel) / len(sel):+.2f}%  average worst point {sum(r['mae'] for r in sel) / len(sel):+.2f}%  "
                  f"reached +1% {100 * len([r for r in sel if r['mfe'] >= 1]) / len(sel):.0f}%  +2% {100 * len([r for r in sel if r['mfe'] >= 2]) / len(sel):.0f}%  fell -1.5% {100 * len([r for r in sel if r['mae'] <= -1.5]) / len(sel):.0f}%")
    print("\n2. Fixed stop and target on every setup (60 minutes, then out at the close of that bar):")
    for g in GRID:
        v = [r["grid"][g] for r in rows]
        print(f"  stop {g[0]:.1f}% target {g[1]:.1f}%   wins {100 * len([x for x in v if x > 0]) / len(v):>3.0f}%  avg {sum(v) / len(v):+.2f}%  total ${sum(2500 * x / 100 for x in v):>+7,.0f}")
    print(f"\n3. Exit C (stop 1.5, lock at +0.7, trail 0.7) on all setups: {stats(rows)}")
    print("\n4. One feature at a time (exit C), split in thirds of the values:")
    for ft in FEATS:
        vals = sorted(r[ft] for r in rows if not math.isnan(r[ft]))
        if len(vals) < 30 or len(set(vals)) < 4:
            continue
        a, b = vals[len(vals) // 3], vals[2 * len(vals) // 3]
        low, mid, high = [r for r in rows if r[ft] <= a], [r for r in rows if a < r[ft] <= b], [r for r in rows if r[ft] > b]
        print(f"  {ft:<9} low (<= {a:+.2f}) {stats(low)}\n  {'':<9} mid               {stats(mid)}\n  {'':<9} high (> {b:+.2f})  {stats(high)}")
    print("\n5. Walk-forward: pick the best rule on four days, score it on the fifth (this is the honest number):")
    oos_all, base_all = [], []
    for d in days:
        train, test = [r for r in rows if r["d"] != d], [r for r in rows if r["d"] == d]
        best = best_rule(train)
        if not best or not test:
            print(f"  {d}: no rule found")
            continue
        sel = [r for r in test if all(ok(r, c) for c in best[1])]
        oos_all += sel
        base_all += test
        print(f"  {d}: rule [{name(best[1])}]  trained on {stats(best[2])}  |  on the held-out day: {stats(sel)}  (every setup that day: {stats(test)})")
    print(f"  ALL held-out days together: rule picks {stats(oos_all)}   versus every setup {stats(base_all)}")
    best = best_rule(rows)
    if best:
        print(f"\n6. Best rule on all days (in-sample, expect it to look better than it is): [{name(best[1])}]  {stats(best[2])}")
