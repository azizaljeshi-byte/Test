"""How is the New call paper account doing? Read only: loads its book from the app's database and prints the results, by day, by entry hour
and by exit reason, with the best and worst trades. Changes nothing."""
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
        print(f"  {k:<28} {len(ts):>3} trades  wins {pct(len(w), len(ts)):>4}  total {sum(res):>9,.2f}  avg {sum(res) / len(ts):>8,.2f}")


def is_test(t) -> bool:
    return str(t.get("exit_reason") or "").startswith("forced sell")


def main() -> None:
    from datetime import datetime
    from stockwatch import paper_newcall, rotation
    from stockwatch.data import NY
    from stockwatch.store import Store
    store = Store()
    book = paper_newcall.load_book(store)
    prices = {}
    try:
        for sn in store.latest_snapshots():
            px = rotation._price(sn)
            if px:
                prices[sn["ticker"]] = px
    except Exception as e:
        print(f"(latest prices not read: {e})")
    trades = book.trades
    test = [t for t in trades if t.get("status") == "CLOSED" and is_test(t)]
    print(f"Left out of every table below: {len(test)} 'forced sell (owner test)' trades ({sum(t['result'] for t in test):,.2f}), which test the buttons, not the rules.\n")
    closed = [t for t in trades if t.get("status") == "CLOSED" and not is_test(t)]
    openp = [t for t in trades if t.get("status") != "CLOSED"]
    res = [t["result"] for t in closed]
    wins, losses = [x for x in res if x > 0], [x for x in res if x < 0]
    print("NEW CALL PAPER ACCOUNT")
    print(f"Start {book.start:,.0f}, cash now {book.cash:,.2f}. {len(trades)} trades: {len(closed)} closed, {len(openp)} open.")
    print(f"Closed result {sum(res):,.2f} ({sum(res) / book.start * 100:+.2f}% of the account). Win rate {pct(len(wins), len(closed))}. "
          f"Average win {sum(wins) / len(wins) if wins else 0:,.2f}, average loss {sum(losses) / len(losses) if losses else 0:,.2f}. "
          f"Profit factor {(sum(wins) / -sum(losses)) if losses else float('inf'):.2f}.")
    if openp:
        print("Open now: " + ", ".join(f"{t['ticker']} (in at {t['entry']})" for t in openp))
    by_day, by_hour, by_reason = defaultdict(list), defaultdict(list), defaultdict(list)
    for t in closed:
        by_day[str(t["closed"])[:10]].append(t)
        by_hour[str(t["opened"])[11:13] + ":00 entry"].append(t)
        r = str(t.get("exit_reason") or "").split(":")[0].split(" (")[0][:28]
        by_reason[r].append(t)
    block("BY DAY (closed that day)", sorted(by_day.items()))
    block("BY ENTRY HOUR (New York)", sorted(by_hour.items()))
    block("BY EXIT REASON", sorted(by_reason.items(), key=lambda kv: sum(t["result"] for t in kv[1])))
    print("\nBEST 5")
    for t in sorted(closed, key=lambda t: -t["result"])[:5]:
        print(f"  {t['ticker']:<6} {t['result']:>9,.2f}  {str(t['opened'])[:16]} -> {str(t['closed'])[:16]}  {str(t.get('exit_reason'))[:60]}")
    print("WORST 5")
    for t in sorted(closed, key=lambda t: t["result"])[:5]:
        print(f"  {t['ticker']:<6} {t['result']:>9,.2f}  {str(t['opened'])[:16]} -> {str(t['closed'])[:16]}  {str(t.get('exit_reason'))[:60]}")
    top = sorted(res, reverse=True)[:3]
    print(f"\nShare of the total from the 3 best trades: {sum(top):,.2f} of {sum(res):,.2f}")

    # ---- money in use, what is open, what was held back, and why the rest of the cash is not used
    eq = book.equity(prices)
    inv = sum(p["shares"] * (prices.get(t) or p["entry"]) for t, p in book.positions.items())
    print(f"\nMONEY IN USE\n  Account value {eq:,.2f}. Invested {inv:,.2f} ({inv / eq * 100:.0f}%), cash {book.cash:,.2f} ({book.cash / eq * 100:.0f}%).")
    print("  Open positions (ticker, shares, in at, now, result, size, share of the account):")
    unreal = 0.0
    for t, p in sorted(book.positions.items()):
        now_px = prices.get(t)
        r = (now_px - p["entry"]) * p["shares"] if now_px else 0.0
        unreal += r
        print(f"    {t:<6} {p['shares']:>6g} {p['entry']:>9,.2f} {now_px or 0:>9,.2f} {r:>+9,.2f} ({(now_px / p['entry'] - 1) * 100 if now_px else 0:+.1f}%)  {p['shares'] * (now_px or p['entry']):>9,.2f}  {p['shares'] * (now_px or p['entry']) / eq * 100:>4.1f}%"
              f"  stop {p.get('trail') or p.get('stop') or 0:,.2f}")
    print(f"  Open result right now {unreal:+,.2f}. Closed (without tests) {sum(res):+,.2f}.")
    today = datetime.now(NY).date().isoformat()
    held = [b for b in book.blocked if b.get("day") == today]
    print(f"\nHELD BACK TODAY ({len(held)} stocks the rules wanted but did not buy; one line per stock)")
    by = defaultdict(list)
    for b in held:
        by[re.sub(r"[\d.]+%?", "#", str(b["reason"]))[:90]].append(b["ticker"])
    for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(v):>3}  {k}  ({', '.join(v[:8])}{'...' if len(v) > 8 else ''})")
    print("\nWHY THE REST OF THE CASH IS NOT USED")
    free = paper_newcall.MAX_POSITIONS - len(book.positions)
    print(f"  Rules: at most {paper_newcall.MAX_POSITIONS} positions at once ({len(book.positions)} open, {free} free), at most {paper_newcall.MAX_NEW} new entries per {paper_newcall.NEW_WINDOW_MIN} minutes,")
    print(f"  each position sized so a hit on its exit line costs about 1% of the account, never over {paper_newcall.SIZE_CAP_PCT:g}% of it.")
    print("  A stock is bought only when its call is BUY or ADD, it is not down on the day, its volume is normal, and it is not weak (a confirmed breakdown or a weakening chart).")
    print("  So cash stays unused when few stocks pass those checks, or when the positions are small because their exit lines are close.")


if __name__ == "__main__":
    main()
