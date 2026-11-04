"""How is the New call paper account doing? Read only: loads its book from the app's database and prints the results, by day, by entry hour
and by exit reason, with the best and worst trades. Changes nothing."""
from __future__ import annotations

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


def main() -> None:
    from stockwatch import paper_newcall
    from stockwatch.store import Store
    book = paper_newcall.load_book(Store())
    trades = book.trades
    closed = [t for t in trades if t.get("status") == "CLOSED"]
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


if __name__ == "__main__":
    main()
