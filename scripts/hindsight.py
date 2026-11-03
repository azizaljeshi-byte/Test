"""Hindsight exercise: the agent sees two FULL sessions of 5-minute bars for six stocks and says where it would have entered and exited, following the playbook.
Nothing is bought or saved. Needs internet (Yahoo, through the app's own yfinance). Run: hindsight.bat -> hindsight_output_<first day>.txt
Honest limit: it sees the whole two days at once, so this tests whether it can *name* good setups and exits, not whether it would have found them live.
Change the stocks or days by editing hindsight_list.txt (it is created on the first run)."""
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

LIST = here / "hindsight_list.txt"        # the owner edits this file: two lines, "stocks: ..." and "days: ..."
DEFAULT = "stocks: PODD, ISRG, FDX, INTC, NVDA, CRDO\ndays: 2026-10-29, 2026-10-30\n"
if not LIST.exists():
    LIST.write_text(DEFAULT, encoding="utf-8")
_cfg = {}
for _l in LIST.read_text(encoding="utf-8").splitlines():
    if ":" in _l:
        _k, _v = _l.split(":", 1)
        _cfg[_k.strip().lower()] = [x.strip() for x in _v.replace(";", ",").split(",") if x.strip()]
TICKERS = [t.upper() for t in _cfg.get("stocks", [])] or ["PODD", "ISRG", "FDX", "INTC", "NVDA", "CRDO"]
DAYS = _cfg.get("days") or ["2026-10-29", "2026-10-30"]

TASK = """
HINDSIGHT EXERCISE (not live). You are given the full 5-minute bars of two regular sessions for one stock, plus its daily context.
Using this playbook, say where you WOULD have entered and exited, as the rules allow:
- Quick: intraday, flat by the close, level 1 then level 2 only if riding and not flying, an add only on a pullback. No bounce entry in the first 15 minutes.
- New call: multi-day, nothing in the first hour, may hold overnight; use the daily context.
Be honest: if there was no clean setup, say none. Name the traps too (a bounce that failed, a spike you would not chase).
Entry reasoning must use only what was visible up to the entry bar; say what you saw by then.
Keep every "why" under 20 words, give at most 4 trades and 3 traps, and reply with the JSON object only: no text before or after it.
OUTPUT one JSON object, nothing else:
{"read": {"<date>": "one sentence on how the day developed"},
 "trades": [{"account": "quick|newcall", "date": "YYYY-MM-DD", "levels": [{"level": "L1|L2|ADD", "time": "HH:MM", "price": 0.0, "state": "turning|riding", "why": "what was visible by then"}],
             "exit": {"date": "YYYY-MM-DD", "time": "HH:MM", "price": 0.0, "why": "which rule or sign"}}],
 "traps": [{"date": "YYYY-MM-DD", "time": "HH:MM", "why": "what looked like a buy but was not"}],
 "verdict": "one or two sentences: how clean were these two days for this stock"}
"""


def load(t):
    import yfinance as yf
    bars = yf.Ticker(t).history(period="10d", interval="5m", prepost=False)
    daily = yf.Ticker(t).history(period="1y", interval="1d")
    bars.index = bars.index.tz_convert("America/New_York")
    return bars, daily


def context(daily, upto):
    d = daily[daily.index.tz_localize(None).strftime("%Y-%m-%d") < upto]
    c = d["Close"]
    tr = (d["High"] - d["Low"]).tail(14).mean()
    delta = c.diff()
    up, dn = delta.clip(lower=0).tail(14).mean(), (-delta.clip(upper=0)).tail(14).mean()
    return {"prior_close": round(float(c.iloc[-1]), 2), "atr14": round(float(tr), 2), "rsi14": round(float(100 - 100 / (1 + up / dn)), 0) if dn else None,
            "vs_sma50_pct": round(float((c.iloc[-1] / c.tail(50).mean() - 1) * 100), 1) if len(c) >= 50 else None,
            "vs_sma200_pct": round(float((c.iloc[-1] / c.tail(200).mean() - 1) * 100), 1) if len(c) >= 200 else None,
            "last_5_closes": [round(float(x), 2) for x in c.tail(5)]}


def pack(t):
    bars, daily = load(t)
    out = {"ticker": t, "daily_context": context(daily, DAYS[0]), "sessions": {}}
    for day in DAYS:
        b = bars[bars.index.strftime("%Y-%m-%d") == day]
        b = b[(b.index.strftime("%H:%M") >= "09:30") & (b.index.strftime("%H:%M") < "16:00")]
        if b.empty:
            out["sessions"][day] = "no bars"
            continue
        out["sessions"][day] = {"columns": "time, open, high, low, close, volume_k",
                                "bars": [[i.strftime("%H:%M"), round(float(r.Open), 2), round(float(r.High), 2), round(float(r.Low), 2), round(float(r.Close), 2),
                                          round(float(r.Volume) / 1000)] for i, r in b.iterrows()]}
    return out


def check(ans, data):
    """Compare the agent's quoted prices with the real bars and work out each trade's result."""
    lines = []
    close = {d: {r[0]: r for r in v["bars"]} for d, v in data["sessions"].items() if isinstance(v, dict)}
    for tr in ans.get("trades") or []:
        try:
            lv = tr["levels"]
            e = tr["exit"]
            px = [float(x["price"]) for x in lv]
            avg = sum(px) / len(px)
            res = (float(e["price"]) / avg - 1) * 100
            warn = []
            for x in lv:
                bar = close.get(tr["date"], {}).get(x["time"])
                if not bar or not (bar[3] - 0.02 <= float(x["price"]) <= bar[2] + 0.02):
                    warn.append(f"{x['time']} price {x['price']} is outside that bar")
            bar = close.get(e.get("date", tr["date"]), {}).get(e["time"])
            if not bar or not (bar[3] - 0.02 <= float(e["price"]) <= bar[2] + 0.02):
                warn.append(f"exit {e['time']} price {e['price']} is outside that bar")
            lines.append(f"    {tr['account']} {tr['date']}: " + " + ".join(f"{x['level']} {x['time']}@{x['price']}" for x in lv)
                         + f" -> exit {e.get('date', tr['date'])} {e['time']}@{e['price']} = {res:+.2f}%" + (f"   !! {'; '.join(warn)}" if warn else ""))
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            lines.append(f"    (could not read one trade: {tr})")
    return lines


def main():
    if not agent.has_key():
        sys.exit("No ANTHROPIC_API_KEY in my_settings.txt.bat")
    system = agent.playbook_text() + "\n" + TASK
    out = [f"Stocks: {', '.join(TICKERS)}", f"Days:   {', '.join(DAYS)}   (edit hindsight_list.txt to change)"]
    print("\n".join(out), flush=True)
    for t in TICKERS:
        out.append(f"\n=== {t}  ({', '.join(DAYS)})")
        try:
            data = pack(t)
            text, usage = agent.call_api(system, json.dumps(data, separators=(",", ":")), max_tokens=8000, timeout=180)
        except Exception as e:
            out.append(f"  ERROR: {type(e).__name__}: {e}")
            continue
        try:
            ans = agent.parse(text)
        except Exception as e:
            out.append(f"  ERROR: {type(e).__name__}: {e}. Tokens out: {usage.get('output_tokens')}. What came back ({len(text)} characters), first 700:\n    {text[:700]!r}")
            continue
        for d, s in (ans.get("read") or {}).items():
            out.append(f"  {d}: {s}")
        out.extend(check(ans, data) or ["    no trade: the agent found no clean setup"])
        for tp in ans.get("traps") or []:
            out.append(f"    trap {tp.get('date')} {tp.get('time')}: {tp.get('why')}")
        for tr in ans.get("trades") or []:
            for x in tr.get("levels") or []:
                out.append(f"      why {x.get('level')} {x.get('time')}: {x.get('why')}")
            out.append(f"      why exit: {(tr.get('exit') or {}).get('why')}")
        out.append(f"  verdict: {ans.get('verdict')}")
        out.append(f"  (tokens in/out: {usage.get('input_tokens')}+{usage.get('cache_creation_input_tokens') or 0} new, {usage.get('cache_read_input_tokens') or 0} cached / {usage.get('output_tokens')})")
    text = "\n".join(out)
    print(text)
    (here / f"hindsight_output_{DAYS[0]}.txt").write_text(text, encoding="utf-8")


main()
