"""Show the agent a few real past trades (best and worst) from Quick and New call, as they looked when the old rules bought, and see what it says.
Read-only: the database is opened read-only, nothing is bought, nothing is saved. Run: replay_trades.bat -> replay_trades_output.txt
Limit: the saved scans have no minute-by-minute chart, so the agent sees the daily picture and the day's numbers, not the intraday path."""
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

here = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(here))
for name in ("my_settings.txt.bat", "my_settings.txt"):
    f = here / name
    if f.exists():
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.lower().startswith("set "):
                line = line[4:].strip()
            if len(line) > 1 and line[0] == '"' and line[-1] == '"':
                line = line[1:-1]
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        break

from stockwatch import agent  # noqa: E402
from stockwatch.data import NY  # noqa: E402

PER_SIDE = int(os.getenv("REPLAY_PER_SIDE", "2"))      # this many best and this many worst per account
db = sqlite3.connect(f"file:{here / 'data' / 'stockwatch.db'}?mode=ro", uri=True)
db.row_factory = sqlite3.Row


def setting(k):
    r = db.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
    return json.loads(r[0]) if r and r[0] else {}


def snap_at(ticker, when_ny):
    """The last saved scan at or before the moment (scans are stored in UTC)."""
    from datetime import timedelta, timezone
    lo = (when_ny - timedelta(days=3)).astimezone(timezone.utc).isoformat()
    hi = (when_ny + timedelta(minutes=2)).astimezone(timezone.utc).isoformat()
    best = None
    for r in db.execute("SELECT id, scanned_at FROM snapshots WHERE ticker=? AND scanned_at>=? AND scanned_at<=? ORDER BY scanned_at", (ticker, lo, hi)):
        best = r["id"]
    if best is None:
        return None
    r = db.execute("SELECT * FROM snapshots WHERE id=?", (best,)).fetchone()
    return {**dict(r), "payload": json.loads(r["payload"])}


def pick(trades):
    done = [t for t in trades if t.get("status") == "CLOSED" and t.get("pct") is not None]
    done.sort(key=lambda t: t["pct"])
    return (done[-PER_SIDE:][::-1] + done[:PER_SIDE]) if done else []


def main():
    if not agent.has_key():
        sys.exit("No ANTHROPIC_API_KEY in my_settings.txt.bat")
    cases = [("quick", t) for t in pick(setting("quick_book").get("trades", []))] + \
            [("newcall", t) for t in pick(setting("paper_newcall_book").get("trades", []))]
    if not cases:
        sys.exit("No closed trades found yet.")
    system = agent.playbook_text() + "\n" + agent.CONTRACT
    out = []
    for acct, t in cases:
        opened = str(t["opened"])[:16]
        when = datetime.fromisoformat(opened.replace(" ", "T")).replace(tzinfo=NY)
        sn = snap_at(t["ticker"], when)
        head = (f"\n=== {acct.upper()} {t['ticker']} opened {opened} at {t['entry']:.2f}  ->  actual: {t.get('pct')}% ({t.get('result')} USD), "
                f"exit '{t.get('exit_reason')}' after {t.get('minutes')} min\n  old rule's reason: {str(t.get('reason'))[:160]}")
        out.append(head)
        if not sn:
            out.append("  (no saved scan near that time: skipped)")
            continue
        try:
            mins = max(0.0, (when - when.replace(hour=9, minute=30)).total_seconds() / 60)
            stock = agent.pack(sn, None, mins, float(t["entry"]))
            data = {"now_ny": opened, "task": "replay of a past moment: decide as in a normal review. The watch time is already done.", "market": {"note": "market breadth not saved for this moment"},
                    "accounts": {acct: {"open": [], "entries_today": 0}}, "watching": [{"ticker": t["ticker"], "minutes_watched": 99, "last_state": "basing", "why": "replay"}],
                    "stocks": [stock]}
            text, usage = agent.call_api(system, json.dumps(data, default=str, separators=(",", ":")))
            ans = agent.parse(text)
        except Exception as e:
            out.append(f"  ERROR: {type(e).__name__}: {e}")
            continue
        got = [i for i in ans.get("instructions") or [] if str(i.get("ticker", "")).upper() == t["ticker"].upper() and i.get("account") == acct] or (ans.get("instructions") or [])
        for ins in got[:2]:
            out.append(f"  agent: {ins.get('action')} [{ins.get('state')}, conf {ins.get('confidence')}]: {ins.get('reason')}")
        if not got:
            out.append("  agent: no instruction")
    text = "\n".join(out)
    print(text)
    (here / "replay_trades_output.txt").write_text(text, encoding="utf-8")


main()
