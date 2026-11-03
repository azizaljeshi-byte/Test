"""Try the agent on made-up setups, with the real API and the real playbook. Nothing is bought; nothing is saved.
Run: try_agent.bat   (reads the key from my_settings.txt.bat, prints the agent's answer for each setup, and writes try_agent_output.txt)."""
import json
import os
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

from stockwatch import agent  # noqa: E402

MKT = {"stocks_read": 480, "share_down_pct": 35, "median_change_pct": 0.2, "up_over_1pct": 90, "down_over_1pct": 40, "market_gate": "open", "minutes_into_session": 95}
BAD = {**MKT, "share_down_pct": 78, "median_change_pct": -1.4, "up_over_1pct": 8, "down_over_1pct": 210, "market_gate": "weak market"}


def stock(t, price, chg, pace, **kw):
    d = {"ticker": t, "name": t + " Inc", "sector": "Technology", "price": price, "day_change_pct": chg, "volume_pace": pace, "atr_pct": 2.0,
         "rsi": 50, "trend": "up", "vs_sma50_pct": 2.0, "vs_sma200_pct": 8.0, "zones": {}, "earnings_in_days": None, "headlines": []}
    d["daily_call"] = {"call": "BUY", "exit_line": round(price * 0.93, 2), "swings_above_line": 2.5}
    d.update(kw)
    return d


def chart(drop, off_low, rising, held, low_age, new_high=False):
    return {"drop_ranges": drop, "off_low_ranges": off_low, "rising_now": rising, "low_held": held, "minutes_since_low": low_age, "new_high": new_high}


NONE = {"quick": {"open": [], "entries_today": 0, "day_result_usd": 0}, "newcall": {"open": [], "entries_today": 0}}


def held(entry, now, stop, mins=60):
    return {"quick": {"open": [{"ticker": "HLD", "entry": entry, "now": now, "pct": round((now / entry - 1) * 100, 2), "stop": stop, "minutes_held": mins}],
                      "entries_today": 1, "day_result_usd": 0}, "newcall": {"open": [], "entries_today": 0}}


SETUPS = [
    ("1 Falling knife: down hard, lower lows, no base", MKT, NONE, [],
     [stock("KNF", 48.2, -4.1, 1.8, chart=chart(3.4, 0.2, False, False, 4), path=[[0, 0], [30, -1.5], [60, -2.8], [90, -4.0]])]),
    ("2 True turn: sold off, low held 45 min, higher low, volume back", MKT, NONE, [{"ticker": "TRN", "minutes_watched": 35, "last_state": "basing", "why": "holding the low"}],
     [stock("TRN", 51.9, -0.8, 1.4, chart=chart(2.6, 1.3, True, True, 45), path=[[0, 0], [30, -2.5], [60, -2.4], [90, -1.2]])]),
    ("3 Same turn but the whole market is a falling-knife day", BAD, NONE, [{"ticker": "TRN", "minutes_watched": 35, "last_state": "basing", "why": "holding the low"}],
     [stock("TRN", 51.9, -0.8, 1.4, chart=chart(2.6, 1.3, True, True, 45), path=[[0, 0], [30, -2.5], [60, -2.4], [90, -1.2]])]),
    ("4 Held and riding but FLYING at the peak: should level 2 wait?", MKT, held(100.0, 101.3, 98.5), [],
     [stock("HLD", 101.3, 2.6, 1.6, chart=chart(0.2, 2.8, True, True, 70, True), path=[[0, 0], [30, 0.4], [60, 1.0], [90, 1.3]])]),
    ("5 Held, riding, then a small pullback from the peak: add?", MKT, held(100.0, 101.0, 98.5), [],
     [stock("HLD", 101.0, 1.0, 1.3, chart=chart(0.5, 2.2, True, True, 70, False), path=[[0, 0], [30, 0.6], [60, 1.9], [75, 1.5], [90, 1.0]])]),
    ("7 Borderline turn: clear higher low, up 1 range off it, volume only average", MKT, NONE, [{"ticker": "BRD", "minutes_watched": 40, "last_state": "basing", "why": "bounced off support"}],
     [stock("BRD", 52.4, -0.3, 1.0, chart=chart(2.4, 1.0, True, True, 50), path=[[0, 0], [30, -2.4], [50, -2.0], [70, -1.6], [90, -0.3]])]),
    ("8 Strong turn: higher low, reclaimed a level, volume 2x, new high of the afternoon", MKT, NONE, [{"ticker": "STR", "minutes_watched": 40, "last_state": "turning", "why": "reclaiming"}],
     [stock("STR", 55.8, 0.9, 2.1, chart=chart(2.2, 2.4, True, True, 55, True), path=[[0, 0], [30, -2.2], [50, -1.8], [70, -0.5], [90, 0.9]])]),
    ("9 Up big on the day, just ran 4 ranges in 20 minutes, never watched before", MKT, NONE, [],
     [stock("RUN", 63.0, 5.5, 2.5, chart=chart(0.0, 4.0, True, True, 80, True), path=[[0, 0], [60, 1.0], [80, 3.5], [90, 5.5]])]),
    ("6 Held, green on the day but rolling over on weak volume: sell?", MKT, held(100.0, 100.4, 98.5), [],
     [stock("HLD", 100.4, 1.1, 0.5, chart=chart(1.6, 0.5, False, False, 12, False), path=[[0, 0], [30, 1.9], [60, 1.3], [90, 0.4]])]),
]


def main():
    if not agent.has_key():
        sys.exit("No ANTHROPIC_API_KEY in my_settings.txt.bat")
    system = agent.playbook_text() + "\n" + agent.CONTRACT
    out = []
    for title, mkt, accts, watching, stocks in SETUPS:
        data = {"now_ny": "2026-11-02 11:05", "task": "review", "market": mkt, "accounts": accts, "watching": watching, "stocks": stocks}
        try:
            text, usage = agent.call_api(system, json.dumps(data, separators=(",", ":")))
            ans = agent.parse(text)
        except agent.AgentError as e:
            out.append(f"\n=== {title}\n  ERROR: {e}")
            continue
        heldmap = {"quick": {x["ticker"] for x in accts["quick"]["open"]}, "newcall": set()}
        out.append(f"\n=== {title}\n  market: {ans.get('market')}")
        for ins in ans.get("instructions") or []:
            clean, why = agent.vet(ins, heldmap, {s["ticker"] for s in stocks})
            out.append(f"  {ins.get('account')} {ins.get('action')} {ins.get('ticker')} [{ins.get('state')}, conf {ins.get('confidence')}]: {ins.get('reason')}"
                       + ("" if clean else f"   << code would throw this out: {why}"))
        out.append(f"  (tokens in/out: {usage.get('input_tokens')}+{usage.get('cache_creation_input_tokens') or 0} new, {usage.get('cache_read_input_tokens') or 0} cached / {usage.get('output_tokens')})")
    text = "\n".join(out)
    print(text)
    (here / "try_agent_output.txt").write_text(text, encoding="utf-8")


main()
