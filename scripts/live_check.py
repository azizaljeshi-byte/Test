"""One-shot check of the LIVE path: takes real Yahoo 5-minute bars, builds the same intraday block the live agent gets (opening range, VWAP, volume against the same time slot)
as of a past minute, shows the numbers, and asks the agent (playbook v1.1) what it would instruct at that minute. Nothing is bought or saved.
Edit live_check_list.txt ("stocks:" and "at:" lines, New York time). Run: live_check.bat -> live_check_output.txt"""
import json
import os
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

LIST = here / "live_check_list.txt"
if not LIST.exists():
    LIST.write_text("stocks: TTAN, FDX, INTC, CRDO\nat: 2026-10-30 11:00, 2026-10-29 12:20\n", encoding="utf-8")
cfg = {}
for l in LIST.read_text(encoding="utf-8").splitlines():
    if ":" in l:
        k, v = l.split(":", 1)
        cfg[k.strip().lower()] = [x.strip() for x in v.split(",") if x.strip()]
TICKERS = [t.upper() for t in cfg.get("stocks", [])] or ["TTAN", "FDX", "INTC", "CRDO"]
TIMES = cfg.get("at") or ["2026-10-30 11:00"]


def daily_bits(t, day):
    import yfinance as yf
    d = yf.Ticker(t).history(period="1y", interval="1d")
    d = d[d.index.tz_localize(None).strftime("%Y-%m-%d") < day]
    c = d["Close"]
    delta = c.diff()
    up, dn = delta.clip(lower=0).tail(14).mean(), (-delta.clip(upper=0)).tail(14).mean()
    return {"prior_close": float(c.iloc[-1]), "atr": float((d["High"] - d["Low"]).tail(14).mean()), "rsi": round(float(100 - 100 / (1 + up / dn))) if dn else None,
            "vs_sma50_pct": round(float((c.iloc[-1] / c.tail(50).mean() - 1) * 100), 1) if len(c) >= 50 else None,
            "vs_sma200_pct": round(float((c.iloc[-1] / c.tail(200).mean() - 1) * 100), 1) if len(c) >= 200 else None}


def main():
    if not agent.has_key():
        sys.exit("No ANTHROPIC_API_KEY in my_settings.txt.bat")
    system = agent.playbook_text() + "\n" + agent.CONTRACT
    df = agent._download_5m(TICKERS)
    out = [f"Stocks: {', '.join(TICKERS)}", f"Moments: {', '.join(TIMES)}  (edit live_check_list.txt)"]
    for at in TIMES:
        when = datetime.fromisoformat(at.replace(" ", "T")).replace(tzinfo=NY)
        stocks, held = [], {"quick": set(), "newcall": set()}
        out.append(f"\n##### {at} New York")
        for t in TICKERS:
            f = agent.features_for(agent._bars_of(df, t, True), when)
            if not f:
                out.append(f"  {t}: no completed bars at that moment")
                continue
            last = f["last_bars"][-1]
            db = daily_bits(t, at[:10])
            price = last[4]
            out.append(f"  {t}: price {price}  opening range {f['opening_range']}  vwap {f['vwap']} ({f['close_vs_vwap_pct']}%)  crossings {f['vwap_crossings_last_12']}  "
                       f"above-vwap bars {f['bars_above_vwap_last_12']}/12  volume vs same time {f['cum_volume_vs_same_time']}x")
            stocks.append({"ticker": t, "price": price, "day_change_pct": round((price / db["prior_close"] - 1) * 100, 2), "atr_pct": round(db["atr"] / price * 100, 2),
                           "rsi": db["rsi"], "vs_sma50_pct": db["vs_sma50_pct"], "vs_sma200_pct": db["vs_sma200_pct"], "intraday": f})
        if not stocks:
            continue
        data = {"now_ny": at, "task": "review", "market": {"note": "breadth not available in this check"},
                "accounts": {"quick": {"open": [], "entries_today": 0, "day_result_usd": 0}, "newcall": {"open": [], "entries_today": 0}},
                "watching": [{"ticker": s["ticker"], "minutes_watched": 99, "last_state": "basing", "why": "check"} for s in stocks], "stocks": stocks}
        try:
            text, usage = agent.call_api(system, json.dumps(data, separators=(",", ":")))
            ans = agent.parse(text)
        except Exception as e:
            out.append(f"  ERROR: {type(e).__name__}: {e}")
            continue
        out.append(f"  market call: {ans.get('market')}")
        for ins in ans.get("instructions") or []:
            clean, why = agent.vet(ins, held, {s["ticker"] for s in stocks})
            out.append(f"  {ins.get('account')} {ins.get('action')} {ins.get('ticker')} [{ins.get('state')}, conf {ins.get('confidence')}]: {ins.get('reason')}"
                       + ("" if clean else f"   << code would throw this out: {why}"))
        out.append(f"  (tokens in/out: {usage.get('input_tokens')}+{usage.get('cache_creation_input_tokens') or 0} new, {usage.get('cache_read_input_tokens') or 0} cached / {usage.get('output_tokens')})")
    text = "\n".join(out)
    print(text)
    (here / "live_check_output.txt").write_text(text, encoding="utf-8")


main()
