"""Buy the pullback instead of the signal. For every stock Quick selected on a day (one "campaign" per stock and day, from its earliest signal) it keeps the stock on
watch for up to 2 hours and enters only after a pullback with a bounce: price dips at least 1% under the signal price (or retests the lowest low of the last 2 hours),
then a bar closes above the previous bar's high and above its own open. The stop goes just under the pullback low, so it is tight, and a second try is allowed after an exit.
Compared with buying at the signal. Read only. Limits: 5-minute bars, flat $2,500 a trade, stops and targets assumed filled at their price (stop first if both in one bar)."""
from __future__ import annotations

import pandas as pd

from rule_test import events, sim_exit

SIZE, WATCH_BARS, DIP_PCT, SUPPORT_BARS, CONFIRM_BARS, MAX_RISK, MIN_RISK, CHASE_PCT, CUTOFF_HOUR = 2500.0, 24, 1.0, 24, 4, 2.0, 0.3, 1.5, 15
TARGET_ALT, RIDE_TARGET, RIDE_TRAIL, RIDE_LOCK, NO_PROGRESS_BARS = 2.0, 1.0, 0.7, 0.2, 12


def find_entry(day: pd.DataFrame, i: int, p0: float, start: int, chase_cancel: bool = True):
    """Returns (bar index, entry price, stop price, risk %) or (None, reason)."""
    lo = max(0, i - SUPPORT_BARS + 1)
    support = float(day["Low"].iloc[lo:i + 1].min())
    pull = None
    end = min(i + WATCH_BARS, len(day) - 1)
    for k in range(start, end + 1):
        b = day.iloc[k]
        if b.name.hour >= CUTOFF_HOUR:
            return None, "too late in the day"
        if pull is None:
            if chase_cancel and float(b["Close"]) > p0 * (1 + CHASE_PCT / 100):
                return None, "ran away without a pullback"
            if float(b["Low"]) <= p0 * (1 - DIP_PCT / 100) or float(b["Low"]) <= support * 1.004:
                pull = k
            else:
                continue
        elif float(b["Low"]) < float(day["Low"].iloc[pull]):
            pull = k                                                     # a lower low: the pullback is still going
        if k > pull and k - pull <= CONFIRM_BARS:
            a = day.iloc[k - 1]
            if float(b["Close"]) > float(a["High"]) and float(b["Close"]) > float(b["Open"]):
                entry = float(b["Close"])
                stop = float(day["Low"].iloc[pull:k + 1].min()) * 0.998
                risk = (entry - stop) / entry * 100
                if risk > MAX_RISK:
                    return None, "stop too far from the entry"
                return (k, entry, stop, max(risk, MIN_RISK)), None
    return None, "no pullback and bounce" if pull is None else "no bounce confirmed"


def exit_struct(day: pd.DataFrame, k: int, entry: float, stop: float, mode: str) -> tuple[float, int, str]:
    """mode 'T2': fixed +2% target. mode 'RIDE': +1% target unless the bar closes near its high, then a 0.7% trail. Both keep the structural stop."""
    peak, riding = entry, False
    tgt = entry * (1 + (TARGET_ALT if mode == "T2" else RIDE_TARGET) / 100)
    for m in range(k + 1, len(day)):
        b = day.iloc[m]
        if float(b["Low"]) <= stop:
            return (min(float(b["Open"]), stop) / entry - 1) * 100, m, "stop"
        if not riding and float(b["High"]) >= tgt:
            rng = float(b["High"] - b["Low"])
            near = rng > 0 and (float(b["Close"]) - float(b["Low"])) / rng >= 0.7 and float(b["Close"]) >= tgt
            if mode == "RIDE" and near:
                riding, peak, stop = True, float(b["High"]), max(stop, entry * (1 + RIDE_LOCK / 100))
            else:
                return (tgt / entry - 1) * 100, m, "took the profit"
        if riding:
            peak = max(peak, float(b["High"]))
            stop = max(stop, peak * (1 - RIDE_TRAIL / 100))
        if (m - k) >= NO_PROGRESS_BARS and peak < entry * 1.005:
            return (float(b["Close"]) / entry - 1) * 100, m, "no progress"
        if day.index[m].hour == 15 and day.index[m].minute >= 55:
            return (float(b["Close"]) / entry - 1) * 100, m, "end of day"
    last = len(day) - 1
    return (float(day.iloc[last]["Close"]) / entry - 1) * 100, last, "end of data"


def campaigns(evs: list[dict]) -> list[dict]:
    first = {}
    for e in sorted(evs, key=lambda x: x["w"]):
        first.setdefault((e["d"], e["t"]), {**e, "any_took": False})
    for e in evs:
        first[(e["d"], e["t"])]["any_took"] |= e["took"]
    return sorted(first.values(), key=lambda x: (x["d"], x["w"]))


def run_campaign(c: dict, mode: str, tries: int = 2) -> list[dict]:
    day, i, p0, out, start, chase = c["day"], c["i"], c["p0"], [], c["i"] + 1, True
    for n in range(tries):
        got, why = find_entry(day, i, p0, start, chase)
        if got is None:
            if not out:
                out.append({"d": c["d"], "t": c["t"], "in": False, "why": why})
            break
        k, entry, stop, risk = got
        pct, kx, xwhy = exit_struct(day, k, entry, stop, mode)
        out.append({"d": c["d"], "t": c["t"], "in": True, "at": day.index[k], "entry": entry, "pct": pct, "risk": risk, "r": pct / risk, "why": xwhy, "n": n + 1})
        start, chase = kx + 1, False
    return out


def stat(label: str, rows: list[dict], camps: int) -> str:
    inn = [r for r in rows if r["in"]]
    if not inn:
        return f"  {label:<52} {camps:>4} campaigns, no entries"
    v = [r["pct"] for r in inn]
    w = [x for x in v if x > 0]
    return (f"  {label:<52}{camps:>4} camp. {len(inn):>4} trades  wins {100 * len(w) / len(inn):>3.0f}%  avg {sum(v) / len(v):+5.2f}%  total ${sum(SIZE * x / 100 for x in v):>+7,.0f}  "
            f"avg risk {sum(r['risk'] for r in inn) / len(inn):.2f}%  avg R {sum(r['r'] for r in inn) / len(inn):+.2f}  avg win {(sum(w) / len(w)) if w else 0:+.2f}%  worst {min(v):+.2f}%")


def baseline(c: dict, mode: str) -> dict:
    pct, _, why = sim_exit(c["day"], c["i"], c["p0"], mode)
    return {"d": c["d"], "t": c["t"], "in": True, "pct": pct, "risk": 1.5, "r": pct / 1.5, "why": why}


def run(book, trades, frames, days) -> None:
    evs = events(book, trades, frames, days)
    camps = campaigns(evs)
    print(f"\n===== PULLBACK TEST: {len(camps)} campaigns (one per stock and day) on {len(days)} days; {len([c for c in camps if c['any_took']])} are stocks Quick traded =====")
    friday = days[-1]
    for title, sel in (("ALL SELECTED STOCKS", camps), ("ONLY THE STOCKS QUICK TRADED", [c for c in camps if c["any_took"]])):
        print(f"\n{title}")
        for lab, fn in (("buy at the signal, exit about as Quick today", lambda c: [baseline(c, "A")]),
                        ("buy at the signal, 1.5% stop, +1% unless riding", lambda c: [baseline(c, "TP1_RIDE")]),
                        ("PULLBACK entry, tight stop, +2% target", lambda c: run_campaign(c, "T2")),
                        ("PULLBACK entry, tight stop, +1% unless riding", lambda c: run_campaign(c, "RIDE")),
                        ("PULLBACK entry, one try only, +2% target", lambda c: run_campaign(c, "T2", 1))):
            rows = [r for c in sel for r in fn(c)]
            print(stat(lab + " [all days]", rows, len(sel)))
            fr = [c for c in sel if c["d"] == friday]
            print(stat(lab + f" [{friday}]", [r for c in fr for r in fn(c)], len(fr)))
    print("\nWhy campaigns did not enter (pullback, +2% target):")
    why = {}
    for c in camps:
        for r in run_campaign(c, "T2"):
            if not r["in"]:
                why[r["why"]] = why.get(r["why"], 0) + 1
    for k, v in sorted(why.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<40}{v:>5}")
    print("\nBy day (pullback entry, +2% target, all selected stocks) against buying at the signal with today's exit:")
    for d in days:
        cs = [c for c in camps if c["d"] == d]
        pb = [r for c in cs for r in run_campaign(c, "T2") if r["in"]]
        bl = [baseline(c, "A") for c in cs]
        print(f"  {d}  signal {len(bl):>3} trades ${sum(SIZE * r['pct'] / 100 for r in bl):>+6,.0f}   pullback {len(pb):>3} trades ${sum(SIZE * r['pct'] / 100 for r in pb):>+6,.0f}")
    print(f"\nThe pullback trades on {friday} (+2% target):")
    for c in [c for c in camps if c["d"] == friday][:60]:
        for r in run_campaign(c, "T2"):
            if r["in"]:
                print(f"  {r['at'].strftime('%H:%M')} {r['t']:<6} entry {r['entry']:>8.2f} risk {r['risk']:.2f}%  result {r['pct']:+5.2f}%  {r['why']:<16} try {r['n']}  {'(Quick traded it)' if c['any_took'] else ''}")
