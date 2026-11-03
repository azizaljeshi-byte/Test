"""Read-only look at the New call account's closed trades: when each was bought, where its stop was, how far it went against and for
the trade, how it ended and why. Nothing is bought or saved; the database is opened read-only.
Run: newcall_review.bat -> newcall_review_output.txt"""
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

here = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(here))
db = sqlite3.connect(f"file:{here / 'data' / 'stockwatch.db'}?mode=ro", uri=True)


def book():
    r = db.execute("SELECT value FROM settings WHERE key='paper_newcall_book'").fetchone()
    return json.loads(r[0]) if r and r[0] else {}


def when(s):
    try:
        return datetime.fromisoformat(str(s).replace(" ", "T"))
    except (TypeError, ValueError):
        return None


def snap_at(ticker, when):
    """The last saved scan of the stock at or before the moment it was bought (scans are stored in UTC; trade times are New York)."""
    from zoneinfo import ZoneInfo
    if when is None:
        return None
    w = when.replace(tzinfo=ZoneInfo("America/New_York")) if when.tzinfo is None else when
    lo = (w - timedelta(days=3)).astimezone(timezone.utc).isoformat()
    hi = (w + timedelta(minutes=2)).astimezone(timezone.utc).isoformat()
    best = None
    for r in db.execute("SELECT id FROM snapshots WHERE ticker=? AND scanned_at>=? AND scanned_at<=? ORDER BY scanned_at", (ticker, lo, hi)):
        best = r[0]
    if best is None:
        return None
    r = db.execute("SELECT payload FROM snapshots WHERE id=?", (best,)).fetchone()
    return {"ticker": ticker, "payload": json.loads(r[0])}


def main():
    b = book()
    trades = [t for t in b.get("trades", []) if t.get("status") == "CLOSED"]
    out = [f"New call account: cash {b.get('cash')}, start {b.get('start')}, {len(trades)} closed trades, {len(b.get('positions', {}))} still open", ""]
    out.append("id  ticker  opened            entry     stop    closed            exit     result    R     worst%  best%  held   how it ended")
    kind = defaultdict(lambda: [0, 0.0])
    beyond = []
    for t in sorted(trades, key=lambda x: x.get("id", 0)):
        o, c = when(t.get("opened")), when(t.get("closed"))
        held = f"{(c - o).total_seconds() / 3600:.1f}h" if o and c else "?"
        why = str(t.get("exit_reason") or "")
        k = "forced sell (owner test)" if "forced" in why else ("call turned EXIT/AVOID" if "turned" in why else ("stop / exit line" if ("stop" in why.lower() or "line" in why.lower()) else (why[:40] or "other")))
        kind[k][0] += 1
        kind[k][1] += float(t.get("result") or 0)
        r = t.get("r")
        if isinstance(r, (int, float)) and r <= -1.05:
            beyond.append(f"{t['ticker']} {r:+.1f}R")
        out.append(f"{t.get('id'):<3} {t.get('ticker'):<7} {str(t.get('opened'))[:16]:<17} {t.get('entry'):<9} {t.get('stop'):<7} {str(t.get('closed'))[:16]:<17} {t.get('exit')!s:<8} "
                   f"{float(t.get('result') or 0):>8.2f} {r if r is not None else '':>5} {t.get('worst')!s:>7} {t.get('best')!s:>6} {held:>6}  {why[:60]}")
    out.append("")
    out.append("By how it ended:")
    for k, (n, usd) in sorted(kind.items(), key=lambda x: x[1][1]):
        out.append(f"  {k:<28} {n:>3} trades  {usd:>9.2f}")
    out.append(f"Total result: {sum(float(t.get('result') or 0) for t in trades):.2f}   wins {sum(1 for t in trades if (t.get('result') or 0) > 0)}   losses {sum(1 for t in trades if (t.get('result') or 0) < 0)}")
    out.append("R of -1.05 or worse (risk is counted to the exit line; the real stop is the lower band line, so this is NOT a stop failure): " + (", ".join(beyond) or "none"))
    out.append("")
    out.append("Would the new weak-stock rule have blocked it? (price status and momentum as saved at the minute of the buy)")
    try:
        from stockwatch import paper_newcall
        blocked, allowed = [0, 0.0], [0, 0.0]
        for t in sorted(trades, key=lambda x: x.get("id", 0)):
            if not t.get("result"):
                continue                                         # the zero-result re-buys of the forced sale add nothing
            sn = snap_at(t["ticker"], when(t.get("opened")))
            if sn is None:
                out.append(f"  {t['ticker']:<6} {float(t['result']):>9.2f}  no saved scan near the buy")
                continue
            tech = (sn["payload"].get("technical") or {})
            ps = tech.get("price_status") or {}
            mo = (tech.get("momentum") or {}).get("momentum")
            why = paper_newcall.weak_reason(sn)
            bucket = blocked if why else allowed
            bucket[0] += 1
            bucket[1] += float(t["result"])
            out.append(f"  {t['ticker']:<6} {float(t['result']):>9.2f}  status {ps.get('code')}, momentum {mo}  ->  " + (f"BLOCKED ({why})" if why else "allowed"))
        out.append(f"  Blocked: {blocked[0]} trades, {blocked[1]:.2f}.  Allowed: {allowed[0]} trades, {allowed[1]:.2f}.")
    except Exception as e:
        out.append(f"  (could not run this check: {type(e).__name__}: {e})")
    out.append("")
    out.append("Why each was bought (first 140 characters):")
    for t in sorted(trades, key=lambda x: x.get("id", 0)):
        out.append(f"  {t.get('ticker')}: {str(t.get('reason'))[:140]}")
    text = "\n".join(out)
    (here / "newcall_review_output.txt").write_text(text, encoding="utf-8")
    print(text)


main()
