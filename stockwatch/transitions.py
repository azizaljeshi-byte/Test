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
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import status

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


def effective_stance(verdict: str, plan: dict | None, watchlist: bool, price_status: dict | None = None,
                    technical: dict | None = None) -> str:
    """The plan's stance, or the verdict's when there's no plan. Nothing to sell on a watchlist name.

    A confirmed breakdown (`status.forces_exit`: a completed close below support, on a held stock) turns the call
    into REDUCE / EXIT whatever the verdict says, so the app never shows 'hold' under a broken support. A confirmed breakdown also turns any buy or add into
    HOLD (WAIT on a watchlist name), so the app never says 'buy more' under a broken support either."""
    if status.forces_exit(price_status, watchlist):
        return "REDUCE / EXIT"
    stance = (plan or {}).get("stance") or VERDICT_STANCE.get(verdict, "HOLD" if not watchlist else "WAIT FOR CONFIRMATION")
    if watchlist and stance in ("TRIM", "TRIM / PROTECT", "REDUCE / EXIT", "HOLD"):
        stance = "NO TRADE" if stance != "HOLD" else "WAIT FOR CONFIRMATION"
    if stance in status.BUY_STANCES and status.blocks_buy(price_status, technical):     # never 'buy more' over a broken support or a failed entry gate
        stance = "WAIT FOR CONFIRMATION" if watchlist else "HOLD"
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
    ps = (e.technical or {}).get("price_status")
    forced = status.forces_exit(ps, e.watchlist)
    stance = effective_stance(e.verdict, e.plan, e.watchlist, ps, e.technical)
    cls = STANCE_CLASS.get(stance)
    if cls is None:
        return None, "unknown stance"
    if (cls in ("BUY", "ADD") and e.verdict not in BUY_VERDICTS) or (
            cls in ("TRIM", "SELL") and e.verdict not in RISK_VERDICTS and not forced):
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


# ---- price status changes: a second, independent alert stream (see status.py and docs/PRICE_STATUS.md)

STATUS_KEY = "__price_status__"       # reserved entry in the alert memory: {ticker: last confirmed status}
STATUS_ICON = {"record_high": "🟢", "strong_uptrend": "🟢", "pullback": "🔵", "weakening": "🟠",
               "testing_support": "🟠", "breakdown": "🔴", "deep_breakdown": "🔴"}


def split_state(entries: dict) -> tuple[dict, dict]:
    """(call entries, status entries) from the saved alert memory. A memory saved before status alerts existed has
    no status entries, so every stock starts with a silent baseline."""
    calls = {k: v for k, v in entries.items() if k != STATUS_KEY}
    return calls, dict(entries.get(STATUS_KEY) or {})


def join_state(calls: dict, statuses: dict) -> dict:
    return {**calls, STATUS_KEY: statuses}


def status_reading(e, stale: bool) -> dict | None:
    """{code, held} for a valid status reading, or None. No data, no change: an analysis error, stale prices or a
    status that couldn't be read ("unknown") never counts as a status and never confirms or cancels a change."""
    if not status.ALERT_ON_CHANGE or e.error or stale:
        return None
    ps = (e.technical or {}).get("price_status")
    code = ps.get("code") if isinstance(ps, dict) else None
    return {"code": code, "held": not e.watchlist} if code in status.ORDER else None


def step_status(statuses: dict, current: dict[str, dict | None], now: str) -> tuple[dict, list[dict], dict]:
    """Advance the recorded statuses with this run's readings, like `step` does for calls.

    statuses: {ticker: {code, since, pending}} from the last run (modified in place). A first sight is a baseline
    (no message); a change is ready after CONFIRM_RUNS valid readings in a row; flipping back cancels it.
    A ready change isn't recorded until `status_delivered`, so a failed send is offered again next run."""
    counts = {"baseline": 0, "unchanged": 0, "pending": 0, "skipped": 0, "removed": 0}
    for gone in set(statuses) - set(current):
        del statuses[gone]
        counts["removed"] += 1
    ready = []
    for ticker, cur in sorted(current.items()):
        if cur is None:
            counts["skipped"] += 1
            continue
        prev = statuses.get(ticker)
        if prev is None:
            statuses[ticker] = {"code": cur["code"], "since": now, "pending": None}
            counts["baseline"] += 1
            continue
        if cur["code"] == prev["code"]:
            prev["pending"] = None
            counts["unchanged"] += 1
            continue
        pending = prev.get("pending")
        if pending and pending["code"] == cur["code"]:
            pending["count"] += 1
        else:
            pending = prev["pending"] = {"code": cur["code"], "count": 1, "first_seen": now}
        if pending["count"] >= CONFIRM_RUNS:
            ready.append({"ticker": ticker, "held": cur["held"], "from": prev["code"], "to": pending["code"],
                          "first_seen": pending["first_seen"]})
        else:
            counts["pending"] += 1
    return statuses, ready, counts


def status_delivered(statuses: dict, t: dict, now: str) -> None:
    """Record a status change as the new status, once its message went out."""
    statuses[t["ticker"]].update(code=t["to"], since=now, pending=None)


def status_message(t: dict, e, bar_date: str | None, now: datetime) -> str:
    """The Telegram text for one status change: the move, the price and when it traded, why, what it means, the
    levels. Built from this run's evaluation, so it never states a status the run didn't read."""
    ps = (e.technical or {}).get("price_status") or {}
    now_ok = ps.get("code") == t["to"]
    lv = ps.get("levels") or {}
    held = "held" if t["held"] else "watchlist"
    head = [f"{STATUS_ICON.get(t['to'], '•')} {e.ticker} ({held}): {status.LABEL[t['from']]} → {status.LABEL[t['to']]}",
            price_line(e, bar_date, now)]
    lines = []
    if now_ok and ps.get("action"):
        lines.append(ps["action"])
    if now_ok and ps.get("floor_known") and lv:
        lines.append(f"Support {lv['support_low']:.2f} to {lv['support_high']:.2f} · exit below {lv['exit_below']:.2f} · "
                     f"deeper level {lv['deep_below']:.2f} · high {lv['high']:.2f} (daily close {lv['close']:.2f}, {lv['as_of']}).")
    elif now_ok and lv:
        lines.append(f"Daily close {lv['close']:.2f} ({lv['as_of']}); the high is {lv['high']:.2f}.")
    prov = ps.get("provisional") if now_ok else None
    if prov:
        lines.append(prov["note"])
    mo = (e.technical or {}).get("momentum")
    if now_ok and isinstance(mo, dict) and mo.get("known"):
        lines.append(f"Flow: {mo['momentum_label'].title()} ({mo['tone']}), {mo['cause_label']}.")
    lines.append("Automatic levels, not reviewed. Model levels from StockWatch's rules, not orders or predictions.")
    essentials = len("\n".join(head + lines)) + 1
    if essentials > LIMIT:
        raise ValueError("the status, levels and warnings alone exceed Telegram's limit; not sent")
    why = f"Why: {ps['why']}" if now_ok and ps.get("why") else ""
    return "\n".join(head + ([_short(why, LIMIT - essentials)] if why else []) + lines)


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


# A quote counts as current only if it traded in its own session, on the run's New York day, no later than the
# run (plus clock skew) and at most QUOTE_MAX_AGE before it. Anything else falls back to the dated daily bar.
QUOTE_MAX_AGE = timedelta(minutes=60)
CLOCK_SKEW = timedelta(minutes=2)
SESSIONS = {"regular": (time(9, 30), time(16, 0)), "pre": (time(4, 0), time(9, 30)), "post": (time(16, 0), time(20, 0))}
SESSION_LABEL = {"regular": "regular session", "pre": "pre-market", "post": "after hours"}


def _in_session(t: datetime, session: str, now: datetime) -> bool:
    start, end = SESSIONS[session]
    local = t.astimezone(NY)
    return (local.date() == now.astimezone(NY).date() and start <= local.time() <= end
            and now - QUOTE_MAX_AGE <= t <= now + CLOCK_SKEW)


def current_quote(q: dict | None, now: datetime) -> tuple[float, str, datetime] | None:
    """(price, session, trade time) for a quote that is current at `now`, or None.

    `now` is the run's clock (timezone-aware). A regular-session price needs a trade between 09:30 and 16:00
    New York today; a pre-market or after-hours one a trade inside that session today and not last night's.
    Old, future, wrong-session, missing or naive times are all refused."""
    q = q or {}
    live, t = q.get("live_price"), _when(q.get("live_time"))
    if q.get("market_state") == "REGULAR" and _ok(live) and t and _in_session(t, "regular", now):
        return live, "regular", t
    ext, t, sess = q.get("ext_price"), _when(q.get("ext_time")), q.get("ext_session")
    if sess in ("pre", "post") and _ok(ext) and t and not q.get("ext_stale") and _in_session(t, sess, now):
        return ext, sess, t
    return None


def price_line(e, bar_date: str | None, now: datetime) -> str:
    """The price with when it actually traded: a current quote (see `current_quote`) with its trade date and
    time, otherwise the last completed daily bar with its date. The fetch time is never shown as a trade time."""
    cur = current_quote(e.quote, now)
    if cur:
        price, sess, t = cur
        return f"Price {price:.2f} (Yahoo, {SESSION_LABEL[sess]}, last trade {t.astimezone(NY):%a %d %b %H:%M} New York)"
    return f"Price {e.price:.2f} (Yahoo, last daily bar{f' {bar_date}' if bar_date else ', date unknown'})"


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def message(t: dict, e, bar_date: str | None, now: datetime) -> str:
    """The Telegram text for one transition. Levels come from the existing plan; missing ones say so.

    The call, price, levels, warnings and disclaimer are always sent in full; only the "why" is shortened
    to fit Telegram's limit (marked with …). A message whose essentials alone don't fit raises ValueError
    rather than being cut."""
    from . import ui                              # labels and the reassess rule, shared with the dashboard
    label = lambda stance: ui.ACTIONS.get(stance, (stance,))[0]
    plan = e.plan or {}
    ps = (e.technical or {}).get("price_status")
    forced = status.forces_exit(ps, not t["held"])
    held = "held" if t["held"] else "watchlist"
    head = [f"{ICON.get(t['to'], '•')} {e.ticker} ({held}): {label(t['from_stance'])} → {label(t['to_stance'])}",
            price_line(e, bar_date, now)]
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
    elif to == "SELL" and forced:
        lines.append(ps["action"])
    elif to == "SELL":
        lines.append("Reduce or exit." + (f" If you keep part, sell on a close below {stop}." if stop else " Stop unavailable."))
    elif to == "PASS":
        lines.append("No trade" + (f": {trigger}." if trigger else "."))
    if ps and ps.get("code") in ("testing_support", "breakdown", "deep_breakdown"):
        lines.append(f"Price status: {ps['label']} (daily close {ps['levels']['close']:.2f}, {ps['levels']['as_of']}).")
    wait = ui.reassess(_snap(e)) if to in ("TRIM", "SELL") else None
    if wait:
        lines.append(f"Don't rush: {wait}")
    lines.append("Model levels from StockWatch's rules, not orders or predictions.")

    essentials = len("\n".join(head + lines)) + 1          # +1: the newline before "why"
    if essentials > LIMIT:
        raise ValueError("the call, levels and warnings alone exceed Telegram's limit; not sent")
    return "\n".join(head + [_short(why, LIMIT - essentials)] + lines)
