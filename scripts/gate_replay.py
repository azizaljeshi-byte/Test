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


def exit_run(f: pd.DataFrame, i0: int, entry: float) -> tuple[float, str, int]:
    """Walks bars after i0. Returns (exit price, reason, bars held)."""
    stop, peak = entry * (1 - STOP_PCT / 100), entry
    for k in range(i0 + 1, len(f)):
        b = f.iloc[k]
        if b["Low"] <= stop:
            return min(float(b["Open"]), stop), "stop", k - i0
        peak = max(peak, float(b["High"]))
        if peak >= entry * (1 + TRAIL_ARM / 100):
            stop = max(stop, peak * (1 - TRAIL_PCT / 100))
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


RULES = {"NOW": entry_now, "HOLD": entry_hold, "PULLBACK": entry_pullback}


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


def main() -> None:
    from stockwatch import quick, rising
    from stockwatch.store import Store
    book = quick.load_book(Store(), migrate=False)
    trades = [t for t in book["trades"] if t.get("opened")]
    days = sorted({str(t["opened"])[:10] for t in trades})
    want = os.getenv("GATE_DAY") or days[-1]
    todays = [t for t in trades if str(t["opened"])[:10] == want]
    skipped = [s for s in book.get("skipped", []) if s.get("day") == want and s.get("price")]
    taken = {t["ticker"] for t in todays}
    pool = [s for s in skipped if s["ticker"] not in taken]
    seen, uniq = set(), []
    for s in pool:
        if s["ticker"] not in seen:
            seen.add(s["ticker"])
            uniq.append(s)
    random.seed(7)
    pick = random.sample(uniq, min(SAMPLE, len(uniq)))
    names = sorted({t["ticker"] for t in todays} | {s["ticker"] for s in pick})
    print(f"GATE REPLAY for {want}: {len(todays)} trades Quick took, {len(uniq)} different stocks it skipped (random {len(pick)} replayed). Downloading {len(names)} stocks, 5-minute bars...")
    frames = rising.fetch(names, "5d", "5m")
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
    ok_real = [x["r"] for x in real if "err" not in x["r"]]
    ok_skip = [x["r"] for x in skip if "err" not in x["r"]]
    actual = sum(t.get("result", 0) for t in todays if t.get("status") == "CLOSED")
    print(f"\nWhat Quick really made on {want}: {actual:+,.0f} $ on {len(todays)} trades (its own exits, sizes differ).")
    print("\nTHE TRADES QUICK TOOK, replayed (all three rules use the same simple exit, so compare them with each other, not with the real number):")
    print("\n".join(summary(ok_real)))
    print("\nA RANDOM FEW OF THE SKIPPED SETUPS (what it could have done):")
    print("\n".join(summary(ok_skip)))
    print("\nBOTH TOGETHER (if the loss stop had not blocked the later setups):")
    print("\n".join(summary(ok_real + ok_skip)))
    print("\n".join(lines("TAKEN, one by one", real)))
    print("\n".join(lines("SKIPPED sample, one by one", skip)))
    print("\nHow to read: NOW = enter at the setup price. HOLD = a later finished 5-min bar closes at or above it with RSI and MACD rising and volume at least the recent average (cancel if a bar closes 0.5% under, or 30 min pass). "
          "PULLBACK = price dips 0.3% under the setup price, then a bar closes above the previous high (cancel if 1.5% under, or 30 min pass). Exit for all: stop 1.5% under entry, trail 1% under the peak once up 1%, out after 60 min without +0.5%, out at 15:55.")


if __name__ == "__main__":
    main()
