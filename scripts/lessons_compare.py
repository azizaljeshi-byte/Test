"""Run the agent on real 5-minute bars twice: WITHOUT and WITH the lessons in docs/LESSONS_TEST.md, to see what the lessons change.
Nothing is bought or saved. Edit lessons_list.txt for stocks and days. Run: lessons_test.bat -> lessons_compare_<first day>.txt
It sees the full days at once (hindsight); it is asked to use only what was visible by each entry bar. The bars include session VWAP, the opening range and volume against the same time slot on earlier days."""
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

LIST = here / "lessons_list.txt"
DEFAULT = "stocks: TTAN, GILD, FDX, NFLX\ndays: 2026-10-28, 2026-10-29, 2026-10-30\n"
if not LIST.exists():
    LIST.write_text(DEFAULT, encoding="utf-8")
_cfg = {}
for _l in LIST.read_text(encoding="utf-8").splitlines():
    if ":" in _l:
        _k, _v = _l.split(":", 1)
        _cfg[_k.strip().lower()] = [x.strip() for x in _v.replace(";", ",").split(",") if x.strip()]
TICKERS = [t.upper() for t in _cfg.get("stocks", [])] or ["TTAN", "GILD", "FDX", "NFLX"]
DAYS = _cfg.get("days") or ["2026-10-28", "2026-10-29", "2026-10-30"]
LESSONS = (here / "docs" / "LESSONS_TEST.md").read_text(encoding="utf-8") if (here / "docs" / "LESSONS_TEST.md").exists() else ""

TASK = """
HINDSIGHT EXERCISE (not live). You get the full 5-minute bars of several regular sessions for one stock, plus daily context.
Using the playbook, say where you WOULD have entered and exited:
- Quick: intraday, flat by the close, level 1 then level 2 only if riding and not flying, an add only on a pullback. No bounce entry in the first 15 minutes.
- New call: multi-day, nothing in the first hour, may hold overnight.
If there was no clean setup, say none. Name the traps too. Entry reasoning must use only what was visible up to the entry bar.
Bars: [time, open, high, low, close, volume_k, vwap, vol_vs_slot] where vol_vs_slot is this bar's volume divided by the average for the same time slot on earlier sessions (null if unknown). "opening_range" is the 09:30-09:45 high and low.
Keep every "why" under 20 words, at most 5 trades and 4 traps. Reply with the JSON object only:
{"read": {"<date>": "one sentence"},
 "trades": [{"account": "quick|newcall", "date": "YYYY-MM-DD", "pattern": "opening-range breakout|VWAP reclaim|trend pullback|base reversal|other", "label_at_entry": "forming|confirmed",
             "levels": [{"level": "L1|L2|ADD", "time": "HH:MM", "price": 0.0, "why": "what was visible by then"}],
             "exit": {"date": "YYYY-MM-DD", "time": "HH:MM", "price": 0.0, "why": "rule or sign"}}],
 "traps": [{"date": "YYYY-MM-DD", "time": "HH:MM", "pattern": "family", "why": "what looked like a buy but was not"}],
 "verdict": "one or two sentences"}
"""


def load(t):
    import yfinance as yf
    bars = yf.Ticker(t).history(period="15d", interval="5m", prepost=False)
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


def session(bars, day):
    b = bars[bars.index.strftime("%Y-%m-%d") == day]
    return b[(b.index.strftime("%H:%M") >= "09:30") & (b.index.strftime("%H:%M") < "16:00")]


def pack(t):
    bars, daily = load(t)
    out = {"ticker": t, "daily_context": context(daily, DAYS[0]), "sessions": {}}
    all_days = sorted(set(bars.index.strftime("%Y-%m-%d")))
    for day in DAYS:
        b = session(bars, day)
        if b.empty:
            out["sessions"][day] = "no bars"
            continue
        prior = [session(bars, d) for d in all_days if d < day]
        slot = {}
        for p in prior:
            for i, r in p.iterrows():
                slot.setdefault(i.strftime("%H:%M"), []).append(float(r.Volume))
        pv = (b["High"] + b["Low"] + b["Close"]) / 3 * b["Volume"]
        vwap = pv.cumsum() / b["Volume"].cumsum()
        rows = []
        for (i, r), vw in zip(b.iterrows(), vwap):
            hh = i.strftime("%H:%M")
            base = slot.get(hh)
            vs = round(float(r.Volume) / (sum(base) / len(base)), 2) if base and sum(base) > 0 else None
            rows.append([hh, round(float(r.Open), 2), round(float(r.High), 2), round(float(r.Low), 2), round(float(r.Close), 2), round(float(r.Volume) / 1000), round(float(vw), 2), vs])
        first = b[b.index.strftime("%H:%M") < "09:45"]
        out["sessions"][day] = {"opening_range": {"high": round(float(first.High.max()), 2), "low": round(float(first.Low.min()), 2)}, "bars": rows}
    return out


def check(ans, data):
    lines = []
    bars = {d: {r[0]: r for r in v["bars"]} for d, v in data["sessions"].items() if isinstance(v, dict)}
    for tr in ans.get("trades") or []:
        try:
            lv, e = tr["levels"], tr["exit"]
            avg = sum(float(x["price"]) for x in lv) / len(lv)
            res = (float(e["price"]) / avg - 1) * 100
            warn = []
            for x in lv:
                bar = bars.get(tr["date"], {}).get(x["time"])
                if not bar or not (bar[3] - 0.02 <= float(x["price"]) <= bar[2] + 0.02):
                    warn.append(f"{x['time']} price {x['price']} outside that bar")
            bar = bars.get(e.get("date", tr["date"]), {}).get(e["time"])
            if not bar or not (bar[3] - 0.02 <= float(e["price"]) <= bar[2] + 0.02):
                warn.append(f"exit {e['time']} price {e['price']} outside that bar")
            lines.append(f"    {tr['account']} {tr['date']} [{tr.get('pattern')}, {tr.get('label_at_entry')}]: " + " + ".join(f"{x['level']} {x['time']}@{x['price']}" for x in lv)
                         + f" -> exit {e.get('date', tr['date'])} {e['time']}@{e['price']} = {res:+.2f}%" + (f"   !! {'; '.join(warn)}" if warn else ""))
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            lines.append(f"    (could not read one trade: {tr})")
    return lines


def run(system, data, out, tag):
    try:
        text, usage = agent.call_api(system, json.dumps(data, separators=(",", ":")), max_tokens=10000, timeout=240)
    except Exception as e:
        out.append(f"  [{tag}] ERROR: {type(e).__name__}: {e}")
        return
    try:
        ans = agent.parse(text)
    except Exception as e:
        out.append(f"  [{tag}] ERROR: {type(e).__name__}: {e}. Tokens out: {usage.get('output_tokens')}. First 500: {text[:500]!r}")
        return
    out.append(f"  --- {tag} ---")
    for d, s in (ans.get("read") or {}).items():
        out.append(f"  {d}: {s}")
    out.extend(check(ans, data) or ["    no trade"])
    for tr in ans.get("trades") or []:
        for x in tr.get("levels") or []:
            out.append(f"      why {x.get('level')} {x.get('time')}: {x.get('why')}")
        out.append(f"      why exit: {(tr.get('exit') or {}).get('why')}")
    for tp in ans.get("traps") or []:
        out.append(f"    trap {tp.get('date')} {tp.get('time')} [{tp.get('pattern')}]: {tp.get('why')}")
    out.append(f"  verdict: {ans.get('verdict')}")
    out.append(f"  (tokens in/out: {usage.get('input_tokens')}+{usage.get('cache_creation_input_tokens') or 0} new, {usage.get('cache_read_input_tokens') or 0} cached / {usage.get('output_tokens')})")


def main():
    if not agent.has_key():
        sys.exit("No ANTHROPIC_API_KEY in my_settings.txt.bat")
    base = agent.playbook_text()
    out = [f"Stocks: {', '.join(TICKERS)}", f"Days:   {', '.join(DAYS)}   (edit lessons_list.txt to change)", "Each stock is run twice: WITHOUT the lessons, then WITH them."]
    print("\n".join(out), flush=True)
    for t in TICKERS:
        out.append(f"\n=== {t}")
        try:
            data = pack(t)
        except Exception as e:
            out.append(f"  ERROR loading data: {type(e).__name__}: {e}")
            continue
        run(base + "\n" + TASK, data, out, "WITHOUT lessons")
        run(base + "\n\n" + LESSONS + "\n" + TASK, data, out, "WITH lessons")
        print("\n".join(out[-1:]), flush=True)
    text = "\n".join(out)
    print(text)
    (here / f"lessons_compare_{DAYS[0]}.txt").write_text(text, encoding="utf-8")


main()
