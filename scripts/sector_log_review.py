"""Read-only: what the log-only sector check said at each entry of Quick and New call, and how those trades ended.
Run: sector_log.bat -> sector_log_output.txt"""
import json
import sqlite3
from pathlib import Path

here = Path(__file__).resolve().parent.parent
db = sqlite3.connect(f"file:{here / 'data' / 'stockwatch.db'}?mode=ro", uri=True)
out = []
for name, key in (("Quick", "quick_book"), ("New call", "paper_newcall_book")):
    r = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    trades = json.loads(r[0]).get("trades", []) if r and r[0] else []
    tagged = [t for t in trades if t.get("sector_gate") and t.get("status") == "CLOSED"]
    out.append(f"{name}: {len(tagged)} closed trades carry a sector note ({len(trades)} trades in all)")
    for label in ("healthy", "WOULD BLOCK", "no read"):
        g = [t for t in tagged if t["sector_gate"].startswith(label)]
        out.append(f"  {label:<12} {len(g):>3} trades  result {sum(float(t.get('result') or 0) for t in g):>9.2f}  wins {sum(float(t.get('result') or 0) > 0 for t in g)}")
    fun = [t for t in trades if t.get("funnel_gate") and t.get("status") == "CLOSED"]
    out.append(f"  Full-market funnel (market > sector > industry), {len(fun)} closed trades carry it:")
    for label in ("PASS", "WOULD BLOCK at market", "WOULD BLOCK at sector", "WOULD BLOCK at industry", "no read"):
        g = [t for t in fun if t["funnel_gate"].startswith(label)]
        out.append(f"    {label:<24} {len(g):>3} trades  result {sum(float(t.get('result') or 0) for t in g):>9.2f}  wins {sum(float(t.get('result') or 0) > 0 for t in g)}")
    for t in sorted(fun or tagged, key=lambda x: x.get("opened", "")):
        out.append(f"    {t['opened']}  {t['ticker']:<6} {float(t.get('result') or 0):>8.2f}  {t.get('funnel_gate') or t['sector_gate']}")
    out.append("")
Path(here / "sector_log_output.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out[:12]))
