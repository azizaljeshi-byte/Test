"""Why the paper rules do not buy a stock (owner, 2026-10-26: "study the behaviour of the entire system").

Read-only. For every tracked stock it asks the paper decision (`decision.decide`, the same rules the Paper account follows) whether it
would enter now and, when it would not, which checks stand in the way. It changes no card, score, call, plan, alert or account.

Checks, in the paper rules' own words:
  chart        the daily chart reads weakening or testing support
  momentum     momentum is falling, weak or fading
  second view  TradingView or Finnhub says SELL, or another price source disagrees
  earnings     a report is within the paper rules' blackout days
  zone         the price is outside the plan's entry zone
  call         the plan itself is not a buy (checked only when no gate above already blocks it)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from html import escape

from . import decision, status, ui
from .data import NY

CHECKS = [("chart", "Chart reads weakening"), ("momentum", "Momentum falling or fading"), ("second", "Second opinion says no"),
          ("earnings", "Earnings too close"), ("zone", "Price outside the entry zone"), ("call", "Plan is not a buy"),
          ("price", "No fresh price")]
BUY_CALLS = ("BUY NOW", "BUY ON DIP", "BUY ON BREAKOUT", "BUY MORE")


def session_time(now: datetime | None = None) -> datetime:
    """`now` when the regular session is open, else 11:00 New York on the latest weekday, so the paper rules can be asked
    outside the session too."""
    now = (now or datetime.now(NY)).astimezone(NY)
    if decision.minutes_into_session(now) is not None:
        return now
    d = now.date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return datetime(d.year, d.month, d.day, 11, 0, tzinfo=NY)


def diagnose(snap: dict, price: float | None, now: datetime, cfg: decision.Config = decision.Config(blackout_min=0)) -> dict:
    p = snap["payload"]
    plan = p.get("plan") or {}
    ps = ui.price_status(snap) or {}
    real = decision.decide(snap, None, price, now, cfg)
    flags: list[str] = []
    if price is None or price != price or price <= 0:
        flags.append("price")
    else:
        blockers = status.entry_blockers(ps, p.get("technical"))
        text = " ".join(blockers) + " " + str(plan.get("status_exit") or "")
        if "chart reads" in text:
            flags.append("chart")
        if "momentum is" in text:
            flags.append("momentum")
        if "says SELL" in text or "another source disagrees" in text:
            flags.append("second")
        days = (p.get("events") or {}).get("days_to_earnings")
        if days is not None and days <= cfg.earnings_block_days:
            flags.append("earnings")
        lo, hi = plan.get("entry_low"), plan.get("entry_high")
        if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo <= price <= hi):
            flags.append("zone")
        if not any(f in flags for f in ("chart", "momentum", "second")) and ui.action(snap)[0] not in BUY_CALLS:
            flags.append("call")
    return {"ticker": snap["ticker"], "price": price, "call": ui.action(snap)[0], "chart": ps.get("code"), "flags": flags,
            "action": real["action"], "reason": real["reason"]}


def study(snaps: list[dict], now: datetime | None = None) -> dict:
    """{rows, would_enter, counts, only}: `counts[check]` stocks that fail it, `only[check]` stocks it alone blocks."""
    t = session_time(now)
    rows = []
    for s in snaps:
        px = ui._now(s)[0]
        rows.append(diagnose(s, float(px) if px is not None and px == px else None, t))
    rows.sort(key=lambda r: (r["action"] != "ENTER", len(r["flags"]), r["ticker"]))
    counts = {k: sum(k in r["flags"] for r in rows) for k, _ in CHECKS}
    only = {k: sum(r["flags"] == [k] for r in rows) for k, _ in CHECKS}
    return {"rows": rows, "would_enter": [r["ticker"] for r in rows if r["action"] == "ENTER"], "counts": counts, "only": only, "at": t}


def html(res: dict) -> str:
    rows, label = res["rows"], dict(CHECKS)
    n = len(rows)
    tab = "".join(f'<div class="pp-row"><span><b>{escape(label[k])}</b></span><span>{res["counts"][k]} of {n} · alone: {res["only"][k]}</span></div>'
                  for k, _ in CHECKS if res["counts"][k])
    lst = "".join(
        f'<div class="pp-row"><span><b>{escape(r["ticker"])}</b> <small>{escape(str(r["call"]).lower())} · chart {escape(str(r["chart"] or "unknown").replace("_", " "))}</small><br>'
        f'<small>{"would enter now" if r["action"] == "ENTER" else escape(", ".join(label[f].lower() for f in r["flags"]) or r["reason"])}</small></span>'
        f'<span class="{"up" if r["action"] == "ENTER" else ""}">{"ENTER" if r["action"] == "ENTER" else "no"}</span></div>' for r in rows)
    return (f'<div class="pp-c"><div class="pp-h">Why stocks are not bought</div>'
            f'<div class="pp-m">The paper rules asked about all {n} tracked stocks. Nothing here trades.</div>'
            f'<div class="pp-k2"><div><small>Would enter now</small><b>{len(res["would_enter"])}</b></div><div><small>Blocked</small><b>{n - len(res["would_enter"])}</b></div></div>'
            f'<div class="pp-hd">What blocks them ("alone" = the only thing in the way)</div>{tab or "<div class=pp-m>Nothing blocks.</div>"}'
            f'<div class="pp-hd">Stock by stock</div>{lst}</div>')
