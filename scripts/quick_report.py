"""How is the Quick paper account doing, and where did it go wrong? Read only: loads its book from the app's database and prints results by day,
setup kind, entry time, exit reason and sector, today's trades one by one, the worst trades, and what the open positions look like. Changes nothing."""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def pct(a, b):
    return f"{a / b * 100:.0f}%" if b else "-"


def block(title, groups):
    print(f"\n{title}")
    for k, ts in groups:
        res = [t["result"] for t in ts]
        w = [x for x in res if x > 0]
        print(f"  {str(k):<30} {len(ts):>3} trades  wins {pct(len(w), len(ts)):>4}  total {sum(res):>9,.2f}  avg {sum(res) / len(ts):>8,.2f}")


def line(t, sectors):
    return (f"  {t['ticker']:<6} {t['kind'][:9]:<9} in {str(t['opened'])[5:16]} at {t['entry']:>8,.2f} x{t['shares']:<5} out {str(t.get('closed') or '')[11:16]:<5} "
            f"{t['result']:>+9,.2f} ({t['pct'] if t.get('pct') is not None else 0:+.1f}%) best {t.get('best') or 0:+.1f}% held {t.get('minutes') if t.get('minutes') is not None else '-'}m "
            f"[{sectors.get(t['ticker'], '?')}] {str(t.get('exit_reason'))[:48]}")


def is_hand(t) -> bool:
    return str(t.get("exit_reason") or "").startswith("owner override")


SLOTS = [(0, 15, "09:30-09:45 (17:30-17:45 Riyadh)"), (15, 30, "09:45-10:00 (17:45-18:00)"), (30, 60, "10:00-10:30 (18:00-18:30)"), (60, 90, "10:30-11:00 (18:30-19:00)"),
         (90, 180, "11:00-12:30 (19:00-20:30)"), (180, 999, "12:30-close (20:30 on)")]


def minutes_after_open(t) -> int:
    hhmm = str(t["opened"])[11:16]
    return (int(hhmm[:2]) - 9) * 60 + int(hhmm[3:]) - 30


def kind_by_timing(closed) -> None:
    """Each setup kind, split by when it entered: trades, win rate, average win and loss, profit factor, how far it ran, how many hit the stop."""
    for kind in sorted({t["kind"] for t in closed}):
        ts = [t for t in closed if t["kind"] == kind]
        print(f"\nSETUP {kind.upper()} BY ENTRY TIME ({len(ts)} trades, all days; New York time, Riyadh in brackets)")
        print(f"  {'entered':<34}{'trades':>7}{'wins':>6}{'total $':>10}{'avg $':>8}{'avg win':>9}{'avg loss':>10}{'PF':>6}{'avg best':>10}{'stops':>7}")
        for lo, hi, lab in SLOTS + [(0, 999, "ALL DAY")]:
            g = [t for t in ts if lo <= minutes_after_open(t) < hi]
            if not g:
                continue
            w = [t["result"] for t in g if t["result"] > 0]
            lo_ = [t["result"] for t in g if t["result"] <= 0]
            stops = len([t for t in g if str(t.get("exit_reason") or "").startswith("stop hit")])
            pf = (sum(w) / -sum(lo_)) if lo_ and sum(lo_) else float("inf")
            print(f"  {lab:<34}{len(g):>7}{pct(len(w), len(g)):>6}{sum(t['result'] for t in g):>10,.0f}{sum(t['result'] for t in g) / len(g):>8,.1f}"
                  f"{(sum(w) / len(w) if w else 0):>9,.1f}{(sum(lo_) / len(lo_) if lo_ else 0):>10,.1f}{pf:>6.2f}{sum((t.get('best') or 0) for t in g) / len(g):>+9.1f}%{stops:>7}")


def main() -> None:
    from datetime import datetime
    from stockwatch import quick, rotation, sectors
    from stockwatch.data import NY
    from stockwatch.store import Store
    store = Store()
    book = quick.load_book(store, migrate=False)
    prices, secof = {}, {}
    try:
        for sn in store.latest_snapshots():
            px = rotation._price(sn)
            if px:
                prices[sn["ticker"]] = px
            secof[sn["ticker"]] = sectors.sector_of(sn) or "?"
    except Exception as e:
        print(f"(latest prices or sectors not read: {e})")
    trades = book["trades"]
    hand = [t for t in trades if t.get("status") == "CLOSED" and is_hand(t)]
    closed = [t for t in trades if t.get("status") == "CLOSED" and not is_hand(t)]
    openp = [t for t in trades if t.get("status") != "CLOSED"]
    res = [t["result"] for t in closed]
    wins, losses = [x for x in res if x > 0], [x for x in res if x < 0]
    eq = quick.equity(book, prices)
    print("QUICK PAPER ACCOUNT")
    print(f"Start {book['start']:,.0f}, cash now {book['cash']:,.2f}, account value {eq:,.2f}. {len(trades)} trades: {len(closed)} closed, {len(openp)} open.")
    print(f"Closed result {sum(res):,.2f}. Win rate {pct(len(wins), len(closed))}. Average win {sum(wins) / len(wins) if wins else 0:,.2f}, "
          f"average loss {sum(losses) / len(losses) if losses else 0:,.2f}. Profit factor {(sum(wins) / -sum(losses)) if losses else float('inf'):.2f}.")
    unreal = sum(((prices.get(tk) or p["entry"]) - p["entry"]) * p["shares"] for tk, p in book["positions"].items())
    print(f"Open positions now {len(book['positions'])}, open result {unreal:+,.2f}. Closed plus open {sum(res) + unreal:+,.2f}.")
    by_day, by_kind, by_when, by_reason, by_sec = (defaultdict(list) for _ in range(5))
    for t in closed:
        by_day[str(t["closed"])[:10]].append(t)
        by_kind[t["kind"]].append(t)
        hhmm = str(t["opened"])[11:16]
        mins = (int(hhmm[:2]) - 9) * 60 + int(hhmm[3:]) - 30
        by_when["first 30 min" if mins < 30 else "30-90 min" if mins < 90 else "after 90 min"].append(t)
        by_reason[re.sub(r"[\d.]+", "#", str(t.get("exit_reason") or "")).split(":")[0][:30]].append(t)
        by_sec[secof.get(t["ticker"], "?")].append(t)
    block("BY DAY (closed that day)", sorted(by_day.items()))
    block("BY SETUP", sorted(by_kind.items()))
    block("BY WHEN IT ENTERED (minutes after the open)", sorted(by_when.items()))
    kind_by_timing(closed)
    block("BY EXIT REASON", sorted(by_reason.items(), key=lambda kv: sum(t["result"] for t in kv[1])))
    block("BY SECTOR", sorted(by_sec.items(), key=lambda kv: sum(t["result"] for t in kv[1])))
    today = datetime.now(NY).date().isoformat()
    have = {str(t["opened"])[:10] for t in trades} | {str(t.get("closed") or "")[:10] for t in trades} | {str(x.get("day")) for x in book.get("ranked", [])}
    have.discard("")
    if today not in have and have:
        today = max(have)                  # weekend, holiday or before the first trade: report the last day that has records (owner, 7 Nov)
    print(f"\nREPORT DAY: {today} (the sections called TODAY below are for this day)")
    tt = [t for t in trades if str(t["opened"]).startswith(today) or str(t.get("closed") or "").startswith(today)]
    print(f"\nTODAY'S TRADES ({len(tt)}, in order)")
    for t in sorted(tt, key=lambda t: str(t["opened"])):
        print(line(t, secof) if t.get("status") == "CLOSED" else f"  {t['ticker']:<6} {t['kind'][:9]:<9} in {str(t['opened'])[5:16]} at {t['entry']:>8,.2f} x{t['shares']:<5} OPEN now {prices.get(t['ticker']) or t['entry']:,.2f} [{secof.get(t['ticker'], '?')}] {t.get('reason', '')[:50]}")
    print("\nWORST 8 EVER")
    for t in sorted(closed, key=lambda t: t["result"])[:8]:
        print(line(t, secof))
    gave = [t for t in closed if (t.get("best") or 0) >= 1 and t["result"] <= 0]
    print(f"\nWINNERS THAT TURNED INTO LOSSES ({len(gave)}: were up 1% or more, then closed at a loss or flat)")
    for t in sorted(gave, key=lambda t: t["result"])[:8]:
        print(line(t, secof))
    cut = [t for t in closed if t["result"] > 0 and (t.get("best") or 0) - (t.get("pct") or 0) >= 1.5]
    print(f"WINNERS THAT GAVE BACK 1.5% OR MORE OF THEIR PEAK: {len(cut)}, peak minus exit averaging {sum((t.get('best') or 0) - (t.get('pct') or 0) for t in cut) / len(cut) if cut else 0:.1f}%")
    print(f"\nSOLD BY HAND (owner override: {len(hand)}). Left out of every table above, so the rules are judged on their own.")
    for t in hand:
        now_px = prices.get(t["ticker"])
        after = f"; since the sale the price is {now_px:,.2f}, so keeping it would have made {(now_px - t['exit']) * t['shares']:+,.2f}" if now_px and t.get("exit") else ""
        print(f"  {t['ticker']:<6} {t['kind']} in {str(t['opened'])[:16]} at {t['entry']:,.2f}, sold {str(t['closed'])[:16]} at {t['exit']:,.2f}: {t['result']:+,.2f}{after}. Why it entered: {str(t.get('reason'))[:80]}")
    again = [t for t in closed if t.get("nth_today")]
    first = [t for t in closed if not t.get("nth_today")]
    print(f"\nRE-ENTRIES (same stock bought again the same day: {len(again)} closed; first tries: {len(first)})")
    for lab, grp in (("first tries", first), ("re-entries", again)):
        r = [t["result"] for t in grp]
        print(f"  {lab:<12} {len(grp):>4} trades  wins {pct(len([x for x in r if x > 0]), len(grp)):>4}  total {sum(r):>9,.2f}")
    for t in sorted(again, key=lambda t: t["result"])[:10]:
        print(f"  {t['ticker']:<6} try #{t['nth_today']} in {str(t['opened'])[5:16]}: {t['result']:+,.2f} ({str(t.get('exit_reason'))[:40]}); the try before ended {t.get('prev_result') if t.get('prev_result') is not None else '?'} ({str(t.get('prev_exit'))[:40]})")
    rk = [x for x in book.get("ranked", []) if x.get("day") == today]
    print(f"\nRANKING TODAY ({len(rk)} qualifying setups logged; the best-scored is entered first, the limits cut the rest)")
    for x in sorted(rk, key=lambda x: (x["time"], x["rank"]))[:60]:
        parts = " ".join(f"{k} {v:+.1f}" for k, v in (x.get("parts") or {}).items())
        print(f"  {x['time']} #{x['rank']} of {x['of']}  {x['ticker']:<6} {x['kind']:<8} grade {x['grade']} score {x['score']:>5}  {'TAKEN' if x['taken'] else 'passed over: ' + str(x['why_not'])[:60]}  [{parts}]")
    ranked_trades = [t for t in closed if t.get("rank")]
    if ranked_trades:
        print("RESULTS OF TRADES BY THEIR RANK WHEN ENTERED (rank 1 = the best-scored of that moment)")
        for lab, grp in (("rank 1", [t for t in ranked_trades if t["rank"] == 1]), ("rank 2 or lower", [t for t in ranked_trades if t["rank"] > 1])):
            r = [t["result"] for t in grp]
            print(f"  {lab:<16} {len(grp):>4} trades  wins {pct(len([x for x in r if x > 0]), len(grp)):>4}  total {sum(r):>9,.2f}")
    print("\nOPEN POSITIONS")
    for tk, p in sorted(book["positions"].items()):
        px = prices.get(tk) or p["entry"]
        print(f"  {tk:<6} {p['shares']:>6g} in {p['entry']:>9,.2f} now {px:>9,.2f} {(px - p['entry']) * p['shares']:>+9,.2f} ({(px / p['entry'] - 1) * 100:+.1f}%) stop {p['stop']:,.2f} [{secof.get(tk, '?')}]")
    sk = [s for s in book["skipped"] if s.get("day") == today]
    grp = defaultdict(list)
    for s in sk:
        grp[re.sub(r"[\d.]+%?", "#", str(s["reason"]))[:80]].append(s["ticker"])
    print(f"\nSKIPPED TODAY ({len(sk)})")
    for k, v in sorted(grp.items(), key=lambda kv: -len(kv[1]))[:12]:
        print(f"  {len(v):>3}  {k}  ({', '.join(sorted(set(v))[:8])})")


if __name__ == "__main__":
    main()
