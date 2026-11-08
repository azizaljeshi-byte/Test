"""Scenario test of the owner's proposed Quick rules (7 Nov): at most 3 entries in the opening, a 1.5% hard stop, take the profit at +1% unless the stock is riding.
Replays (1) the trades Quick took and (2) every candidate it selected (ranked best first), on 5-minute bars, with Quick's other limits kept: 15 open at most,
40 entries a day, no new entries after the day's closed loss reaches $500, and 3 new entries per 10 minutes after the opening. Read only: changes nothing.
Limits: 5-minute bars, flat $2,500 a trade, stops and targets assumed filled at their price (a stop and a target in one bar counts as the stop), losses on open trades are not part of the loss stop."""
from __future__ import annotations

import pandas as pd

from gate_replay import exit_run, ny
from selection_report import candidates

SIZE, OPEN_MAX, DAY_MAX, DAY_LOSS, PACE_N, PACE_MIN = 2500.0, 15, 40, 500.0, 3, 10
STOP, TARGET, RIDE_TRAIL, RIDE_LOCK, NO_PROGRESS_BARS = 1.5, 1.0, 0.7, 0.5, 12


def sim_exit(day: pd.DataFrame, i: int, p0: float, mode: str) -> tuple[float, int, str]:
    """Returns (result in percent, bar index of the exit, why)."""
    if mode == "A":                                                    # about Quick today: wide stop, late lock
        xp, why, held = exit_run(day, i, p0, 2.2, 2.0, 1.2)
        return (xp / p0 - 1) * 100, i + held, why
    if mode == "B":
        xp, why, held = exit_run(day, i, p0, 1.5, 1.0, 1.0)
        return (xp / p0 - 1) * 100, i + held, why
    stop, peak, riding, tgt = p0 * (1 - STOP / 100), p0, False, p0 * (1 + TARGET / 100)
    last = len(day) - 1
    for k in range(i + 1, len(day)):
        b = day.iloc[k]
        if b["Low"] <= stop:
            return (min(float(b["Open"]), stop) / p0 - 1) * 100, k, "stop"
        if not riding and b["High"] >= tgt:
            rng = float(b["High"] - b["Low"])
            near_high = rng > 0 and (float(b["Close"]) - float(b["Low"])) / rng >= 0.7 and float(b["Close"]) >= tgt
            if mode == "TP1_RIDE" and near_high:
                riding, peak = True, float(b["High"])
                stop = max(stop, p0 * (1 + RIDE_LOCK / 100))
            else:
                return TARGET, k, "took the profit"
        if riding:
            peak = max(peak, float(b["High"]))
            stop = max(stop, peak * (1 - RIDE_TRAIL / 100))
        if (k - i) >= NO_PROGRESS_BARS and peak < p0 * 1.005:
            return (float(b["Close"]) / p0 - 1) * 100, k, "no progress"
        if day.index[k].hour == 15 and day.index[k].minute >= 55:
            return (float(b["Close"]) / p0 - 1) * 100, k, "end of day"
    return (float(day.iloc[last]["Close"]) / p0 - 1) * 100, last, "end of data"


def events(book, trades, frames, days) -> list[dict]:
    out, seen = [], set()
    rk = {(r["day"], r["ticker"]): r.get("rank") for r in book.get("ranked", []) if r.get("taken")}
    for d in days:
        for c in candidates(book, d):
            out.append({"d": d, "t": c["t"], "w": pd.Timestamp(f"{d} {c['time']}").tz_localize("America/New_York"), "p0": c["p0"], "rank": c["rank"] or 99, "took": c["entered"]})
        for t in trades:
            if str(t["opened"])[:10] == d:
                out.append({"d": d, "t": t["ticker"], "w": ny(t["opened"]), "p0": float(t["entry"]), "rank": rk.get((d, t["ticker"])) or 99, "took": True})
    res = []
    for e in sorted(out, key=lambda x: (x["w"], x["rank"], not x["took"])):
        key = (e["d"], e["t"], e["w"].floor("5min"))
        f = frames.get(e["t"])
        if key in seen or f is None:
            continue
        seen.add(key)
        day = f[f.index.normalize() == pd.Timestamp(e["d"], tz="America/New_York")]
        idx = day.index[day.index <= e["w"]]
        if len(day) < 20 or not len(idx):
            continue
        e["day"], e["i"] = day, day.index.get_loc(idx[-1])
        res.append(e)
    return res


def simulate(evs: list[dict], mode: str, cap_window: int | None, only_took: bool = False, portfolio: bool = True) -> list[dict]:
    """cap_window: minutes after the open in which at most 3 entries are allowed (None = Quick today: no limit in the first 30 minutes)."""
    done = []
    for d in sorted({e["d"] for e in evs}):
        taken, closed_pnl, open_pos = [], [], []                     # open_pos: (ticker, exit time)
        for e in [x for x in evs if x["d"] == d and (x["took"] or not only_took)]:
            w, mins = e["w"], e["w"].hour * 60 + e["w"].minute - 570
            open_pos = [(t, x) for t, x in open_pos if x > w]
            if portfolio:
                if any(t == e["t"] for t, _ in open_pos) or len(open_pos) >= OPEN_MAX or len(taken) >= DAY_MAX:
                    continue
                if -sum(p for p, x in closed_pnl if x <= w) >= DAY_LOSS:
                    continue
            elif any(t == e["t"] for t, _ in open_pos):
                continue
            window = cap_window if cap_window is not None else 30
            if mins < window:
                if cap_window is not None and len([x for x in taken if x["mins"] < window]) >= 3:
                    continue
            elif portfolio and len([x for x in taken if (w - x["w"]).total_seconds() < PACE_MIN * 60]) >= PACE_N:
                continue
            pct, k, why = sim_exit(e["day"], e["i"], e["p0"], mode)
            xt = e["day"].index[min(k, len(e["day"]) - 1)]
            taken.append({"d": d, "t": e["t"], "w": w, "mins": mins, "pct": pct, "why": why, "took": e["took"]})
            closed_pnl.append((SIZE * pct / 100, xt))
            open_pos.append((e["t"], xt))
        done += taken
    return done


def row(label: str, rs: list[dict]) -> str:
    if not rs:
        return f"  {label:<46} no trades"
    v = [r["pct"] for r in rs]
    w = [x for x in v if x > 0]
    return (f"  {label:<46}{len(v):>5} trades  wins {100 * len(w) / len(v):>3.0f}%  avg {sum(v) / len(v):+5.2f}%  total ${sum(SIZE * x / 100 for x in v):>+7,.0f}  "
            f"worst {min(v):+5.2f}%  avg win {(sum(w) / len(w)) if w else 0:+.2f}%  avg loss {(sum(x for x in v if x <= 0) / max(len(v) - len(w), 1)):+.2f}%")


SETS = [("Quick today (exit about as now, no opening cap)", "A", None), ("exit B only (stop 1.5, lock +1, trail 1)", "B", None),
        ("take +1% (no riding), no opening cap", "TP1", None), ("take +1% unless riding, no opening cap", "TP1_RIDE", None),
        ("cap 3 in 15 min + take +1%", "TP1", 15), ("cap 3 in 15 min + take +1% unless riding", "TP1_RIDE", 15),
        ("cap 3 in 30 min + take +1% unless riding", "TP1_RIDE", 30), ("cap 3 in 30 min + exit B", "B", 30),
        ("cap 3 in 30 min only (exit A)", "A", 30)]


def run(book, trades, frames, days) -> None:
    evs = events(book, trades, frames, days)
    print(f"\n===== RULE TEST: {len(evs)} candidate events on {len({e['d'] for e in evs})} days ({len([e for e in evs if e['took']])} are trades Quick took) =====")
    friday = days[-1]
    for title, only, port in (("A. THE TRADES QUICK TOOK, replayed with each rule set (no other limits)", True, False),
                              ("B. EVERY CANDIDATE QUICK SELECTED, best rank first, with 15 open / 40 a day / $500 loss stop / pace limit kept", False, True)):
        print(f"\n{title}")
        for lab, mode, cap in SETS:
            rs = simulate(evs, mode, cap, only_took=only, portfolio=port)
            print(row(lab + " [all days]", rs))
            print(row(lab + f" [{friday}]", [r for r in rs if r["d"] == friday]))
    print("\nC. By day: the proposed rules (cap 3 in 30 min + take +1% unless riding) against Quick today, every candidate, other limits kept")
    base, new = simulate(evs, "A", None), simulate(evs, "TP1_RIDE", 30)
    for d in days:
        b, n = [r for r in base if r["d"] == d], [r for r in new if r["d"] == d]
        if b or n:
            print(f"  {d}  today: {len(b):>3} trades ${sum(SIZE * r['pct'] / 100 for r in b):>+6,.0f}   proposed: {len(n):>3} trades ${sum(SIZE * r['pct'] / 100 for r in n):>+6,.0f}")
    print(f"\nD. {friday}, the trades the proposed rules would take (cap 3 in 30 min + take +1% unless riding):")
    for r in [r for r in new if r["d"] == friday][:40]:
        print(f"  {r['w'].strftime('%H:%M')} {r['t']:<6} {r['pct']:+5.2f}%  {r['why']:<16} {'(Quick took it)' if r['took'] else '(Quick passed)'}")
