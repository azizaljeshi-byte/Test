"""Decision-change alerts: tell the owner when a tracked stock's effective call moves from one class to
another (WAIT -> BUY, HOLD -> TRIM, HOLD -> SELL, BUY -> WAIT...), for held and watchlist stocks alike.

The call is the same reconciled verdict + trade-plan stance the dashboard shows (`effective_stance`), so a
message never says BUY while the app says WAIT. Individual signal codes don't trigger anything here.

Rules:
- A stock's first valid reading records a baseline and sends nothing.
- A new call must be seen on CONFIRM_RUNS valid readings in a row before it's sent, so a one-run flip doesn't
  alert. Flipping back cancels it; a run with no valid reading in between neither confirms nor cancels.
- A run with no valid reading for a stock (error, no plan, stale prices, a verdict/plan conflict) changes
  nothing: an outage is never read as HOLD or SELL.
- Buying or selling the whole position (watchlist <-> held) re-baselines silently.
- The recorded call advances only after the message is delivered, so a failed send is retried next run.
"""
from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

CONFIRM_RUNS = 2
NY = ZoneInfo("America/New_York")

# plan stance -> decision class; a move between classes is what's worth a message
STANCE_CLASS = {
    # BUY ON PULLBACK is a conditional entry (a limit order in the zone, below the price). The plan gives it
    # without the BUY SETUP verdict and the dashboard shows it as BUY ON DIP, so it's its own class.
    "BUY NOW": "BUY", "BUY THE BREAKOUT": "BUY", "BUY ON PULLBACK": "DIP", "ADD": "ADD",
    "WAIT FOR CONFIRMATION": "WAIT", "HOLD": "HOLD", "TRIM": "TRIM", "TRIM / PROTECT": "TRIM",
    "REDUCE / EXIT": "SELL", "NO TRADE": "PASS",
}
VERDICT_STANCE = {"OPPORTUNITY - ADD": "ADD", "BUY SETUP": "BUY NOW", "TRIM / REVIEW": "TRIM",
                  "RISK - REVIEW": "REDUCE / EXIT", "AVOID": "NO TRADE"}
BUY_VERDICTS = {"OPPORTUNITY - ADD", "BUY SETUP"}
RISK_VERDICTS = {"RISK - REVIEW", "TRIM / REVIEW", "AVOID"}
ICON = {"BUY": "🟢", "ADD": "🟢", "DIP": "🟢", "WAIT": "⚪", "HOLD": "🔵", "TRIM": "🟠", "SELL": "🔴", "PASS": "⚫"}


def effective_stance(verdict: str, plan: dict | None, watchlist: bool) -> str:
    """The plan's stance, or the verdict's when there's no plan. Nothing to sell on a watchlist name."""
    stance = (plan or {}).get("stance") or VERDICT_STANCE.get(verdict, "HOLD" if not watchlist else "WAIT FOR CONFIRMATION")
    if watchlist and stance in ("TRIM", "TRIM / PROTECT", "REDUCE / EXIT", "HOLD"):
        stance = "NO TRADE" if stance != "HOLD" else "WAIT FOR CONFIRMATION"
    return stance


def _ok(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def reading(e, stale: bool) -> tuple[dict | None, str]:
    """(state, "") for a valid reading, or (None, why not)."""
    if e.error:
        return None, "analysis failed"
    if not _ok(e.price):
        return None, "no price"
    if stale:
        return None, "stale prices"
    if not (e.plan or {}).get("stance"):
        return None, "no trade plan"
    stance = effective_stance(e.verdict, e.plan, e.watchlist)
    cls = STANCE_CLASS.get(stance)
    if cls is None:
        return None, "unknown stance"
    if (cls in ("BUY", "ADD") and e.verdict not in BUY_VERDICTS) or (cls in ("TRIM", "SELL") and e.verdict not in RISK_VERDICTS):
        return None, "verdict and plan disagree"
    return {"held": not e.watchlist, "state": cls, "stance": stance, "verdict": e.verdict}, ""


def step(entries: dict, current: dict[str, dict | None], now: str) -> tuple[dict, list[dict], dict]:
    """Advance the recorded calls with this run's readings.

    entries: {ticker: {held, state, stance, verdict, since, pending}} from the last run (modified in place).
    current: {ticker: reading or None} for every tracked stock this run.
    Returns (entries, transitions ready to send, counts). A ready transition isn't recorded until `delivered`."""
    counts = {"baseline": 0, "unchanged": 0, "pending": 0, "skipped": 0, "removed": 0}
    for gone in set(entries) - set(current):
        del entries[gone]
        counts["removed"] += 1
    ready = []
    for ticker, cur in sorted(current.items()):
        prev = entries.get(ticker)
        if cur is None:
            counts["skipped"] += 1
            continue
        if prev is None or prev["held"] != cur["held"]:
            entries[ticker] = {**cur, "since": now, "pending": None}
            counts["baseline"] += 1
            continue
        if cur["state"] == prev["state"]:
            prev.update(stance=cur["stance"], verdict=cur["verdict"], pending=None)
            counts["unchanged"] += 1
            continue
        pending = prev.get("pending")
        if pending and pending["state"] == cur["state"]:
            pending.update(count=pending["count"] + 1, stance=cur["stance"], verdict=cur["verdict"])
        else:
            pending = prev["pending"] = {"state": cur["state"], "stance": cur["stance"], "verdict": cur["verdict"],
                                         "count": 1, "first_seen": now}
        if pending["count"] >= CONFIRM_RUNS:
            ready.append({"ticker": ticker, "held": cur["held"], "from": prev["state"], "from_stance": prev["stance"],
                          "from_verdict": prev["verdict"], "to": pending["state"], "to_stance": pending["stance"],
                          "to_verdict": pending["verdict"], "first_seen": pending["first_seen"]})
        else:
            counts["pending"] += 1
    return entries, ready, counts


def delivered(entries: dict, t: dict, now: str) -> None:
    """Record a transition as the new call, once its message went out."""
    entries[t["ticker"]].update(state=t["to"], stance=t["to_stance"], verdict=t["to_verdict"], since=now, pending=None)


def _px(v) -> str | None:
    return f"{v:.2f}" if _ok(v) else None


def _snap(e) -> dict:
    """The dashboard's snapshot shape, for the shared `ui.reassess` rule."""
    return {"ticker": e.ticker, "price": e.price, "verdict": e.verdict,
            "payload": {"quote": e.quote, "technical": e.technical, "plan": e.plan, "watchlist": e.watchlist,
                        "error": e.error, "signals": [{"code": s.code, "kind": s.kind} for s in e.signals]}}


LIMIT = 4096          # Telegram's maximum message length
REASON_CHARS = 200    # each "why" reason is shortened to this; the levels never are


def _when(v):
    """A trade timestamp as an aware datetime, or None (never assume 'now' for a missing or naive time)."""
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return v if isinstance(v, datetime) and v.tzinfo is not None else None


def price_line(e, bar_date: str | None) -> str:
    """The price with when it actually traded. A live or extended-hours quote needs its own trade time;
    last night's after-hours price seen before today's open, or any quote without a valid time, falls back
    to the last completed daily bar."""
    q = e.quote or {}
    ny = lambda t: t.astimezone(NY).strftime("%a %H:%M")
    live, t = q.get("live_price"), _when(q.get("live_time"))
    if q.get("market_state") == "REGULAR" and _ok(live) and t:
        return f"Price {live:.2f} (Yahoo, regular session, last trade {ny(t)} New York)"
    ext, t = q.get("ext_price"), _when(q.get("ext_time"))
    if _ok(ext) and t and not q.get("ext_stale") and q.get("ext_session") in ("pre", "post"):
        return f"Price {ext:.2f} (Yahoo, {'pre-market' if q['ext_session'] == 'pre' else 'after hours'}, last trade {ny(t)} New York)"
    return f"Price {e.price:.2f} (Yahoo, last daily bar{f' {bar_date}' if bar_date else ', date unknown'})"


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def message(t: dict, e, bar_date: str | None = None) -> str:
    """The Telegram text for one transition. Levels come from the existing plan; missing ones say so.

    The call, price, levels, warnings and disclaimer are always sent in full; only the "why" is shortened
    to fit Telegram's limit (marked with …). A message whose essentials alone don't fit raises ValueError
    rather than being cut."""
    from . import ui                              # labels and the reassess rule, shared with the dashboard
    label = lambda stance: ui.ACTIONS.get(stance, (stance,))[0]
    plan = e.plan or {}
    held = "held" if t["held"] else "watchlist"
    head = [f"{ICON.get(t['to'], '•')} {e.ticker} ({held}): {label(t['from_stance'])} → {label(t['to_stance'])}",
            price_line(e, bar_date)]
    reasons = [_short(s.message, REASON_CHARS) for s in e.signals[:2]]
    verdicts = f"{t['from_verdict']} → {t['to_verdict']}" if t["from_verdict"] != t["to_verdict"] else t["to_verdict"]
    why = f"Why: {verdicts}" + (f". {'; '.join(reasons)}" if reasons else "")

    lines = []
    lo, hi, stop, trigger = _px(plan.get("entry_low")), _px(plan.get("entry_high")), _px(plan.get("stop")), plan.get("trigger")
    target = next((x for x in plan.get("targets") or [] if _ok(x.get("price"))), None)
    stop_text = f"Stop: {stop} ({plan.get('stop_basis', 'plan stop')})" if stop else "Stop: unavailable"
    target_text = f"Target: {target['price']:.2f} ({target['label']})" if target else "Target: unavailable"
    zone = f"{lo}–{hi}" if lo and hi else None
    to = t["to"]
    if to == "DIP":
        lines.append("Conditional entry: a limit order inside the zone, not a buy at the current price.")
    if to in ("BUY", "ADD", "DIP"):
        lines += [f"Entry zone: {zone}" if zone else "Entry zone: unavailable"]
        if trigger:
            lines.append(f"Trigger: {trigger}")
        lines += [stop_text, target_text]
    elif to == "WAIT":
        lines.append("Not a buy yet." + (f" Wait for {trigger}." if trigger else " No trigger level available."))
        if zone:
            lines.append(f"Watch zone: {zone} (not an active buy)")
    elif to == "HOLD":
        lines += [stop_text, target_text]
    elif to == "TRIM":
        lines.append("Trim: take some profit at the current price (the plan has no separate trim zone), keep the rest"
                     + (f" above {stop}." if stop else "; stop unavailable."))
        lines.append(target_text)
    elif to == "SELL":
        lines.append("Reduce or exit." + (f" If you keep part, sell on a close below {stop}." if stop else " Stop unavailable."))
    elif to == "PASS":
        lines.append("No trade" + (f": {trigger}." if trigger else "."))
    wait = ui.reassess(_snap(e)) if to in ("TRIM", "SELL") else None
    if wait:
        lines.append(f"Don't rush: {wait}")
    lines.append("Model levels from StockWatch's rules, not orders or predictions.")

    essentials = len("\n".join(head + lines)) + 1          # +1: the newline before "why"
    if essentials > LIMIT:
        raise ValueError("the call, levels and warnings alone exceed Telegram's limit; not sent")
    return "\n".join(head + [_short(why, LIMIT - essentials)] + lines)
