"""Read-only: how many stocks change their momentum word when "stabilising" must also mean the price has stopped falling.
Runs the OLD rule (MACD above its signal alone) and the NEW rule on the same daily bars for the whole S&P 500 plus your tracked stocks,
and lists every stock whose word changes, and which of your tracked stocks have a New call BUY or ADD that would now be held back
(momentum "weak" blocks a buy). Nothing is bought, saved or changed. Run: momentum.bat -> momentum_compare_output.txt"""
import json
import os
import sqlite3
import sys
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

from stockwatch import momentum  # noqa: E402
from stockwatch.config import load_portfolio  # noqa: E402
from stockwatch.data import get_provider  # noqa: E402
from stockwatch.market import load_universe  # noqa: E402


def main():
    db = sqlite3.connect(f"file:{here / 'data' / 'stockwatch.db'}?mode=ro", uri=True)
    calls, tracked = {}, set()
    for t, p in db.execute("SELECT ticker, payload FROM snapshots WHERE id IN (SELECT MAX(id) FROM snapshots GROUP BY ticker)"):
        tracked.add(t)
        try:
            calls[t] = (json.loads(p).get("technical") or {}).get("one_call", {}).get("call")
        except ValueError:
            continue
    tickers = sorted(set(load_universe()["ticker"]) | tracked)
    provider = get_provider(load_portfolio().settings.data_provider)
    print(f"Downloading daily bars for {len(tickers)} stocks (about a minute)...")
    hist = provider.bulk_history(tuple(tickers))
    rows, counts = [], {}
    for t, h in hist.items():
        try:
            momentum.STAB_CHECK = False
            old = momentum.assess(h, None, None)
            momentum.STAB_CHECK = True
            new = momentum.assess(h, None, None)
        except Exception:
            continue
        if not (old.get("known") and new.get("known")):
            continue
        counts[new["momentum"]] = counts.get(new["momentum"], 0) + 1
        if old["momentum"] != new["momentum"]:
            f = new["facts"]
            rows.append((t, old["momentum"], new["momentum"], f["ret20"], f["rsi"], calls.get(t), t in tracked))
    out = [f"{len(hist)} stocks read. Words under the NEW rule: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
           f"{len(rows)} stocks change their word (old -> new), {sum(1 for r in rows if r[1] == 'stabilising')} of them were 'stabilising'.", ""]
    out.append("Your tracked stocks whose word changes:")
    for t, o, n, r20, rsi, call, _ in sorted(r for r in rows if r[6]):
        held = " <- a BUY/ADD call that the weak-momentum block would now hold back" if call in ("BUY", "ADD") else ""
        out.append(f"  {t:<6} {o:>11} -> {n:<8} 20-session {r20:+.1%}, RSI {rsi:.0f}, New call {call or '-'}{held}")
    out.append("")
    out.append("Everything else in the S&P 500 whose word changes:")
    for t, o, n, r20, rsi, call, _ in sorted(r for r in rows if not r[6]):
        out.append(f"  {t:<6} {o:>11} -> {n:<8} 20-session {r20:+.1%}, RSI {rsi:.0f}")
    Path(here / "momentum_compare_output.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out[:30]))


if __name__ == "__main__":
    main()
