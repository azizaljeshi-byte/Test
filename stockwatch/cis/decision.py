"""CIS replacement decision adapter (shadow only): technical STATE -> trading ACTION.

Issue #29. A chart state is not an action: the action also depends on ownership, the position's mandate,
the setup, entry quality and risk. This adapter turns the fixed level packet's confirmed states into the
existing StockWatch decision categories, with the levels and reasons behind them.

Status: SHADOW. The switch `STOCKWATCH_CIS_DECISIONS` is off by default; `shadow` shows these calls beside
the existing ones, labelled. Nothing here feeds the verdict, the trade plan, the alert memory or Telegram,
and no setting activates it: activation needs Codex review, a methodology check and the owner's approval.

Rules (owner-approved mapping, 23 Oct 2026, Issue #29):
- No reviewed level packet, or no constructive floor: CIS UNSUPPORTED. The existing call stays, labelled
  legacy; it is never relabelled as CIS.
- Decisions use the completed close. The live quote and the session's low are shown as provisional or
  intraday facts and never change the action.
- TRADE INVALIDATED / TREND BREAKDOWN on a held stock: a long-term (Tier 1, "core") holding gets RISK —
  REVIEW REDUCTION/EXIT; a position with a precommitted tactical contract gets EXIT TACTICAL; anything else,
  including Tier 2 (no trade contract exists in the holding model), gets REVIEW REQUIRED. Never an
  unconditional liquidation. Watchlist: NO TRADE.
- SUPPORT BREAK: held -> TRIM / REDUCE REVIEW (stop adding); watchlist -> NO TRADE.
- SUPPORT HOLD while testing the floor: held -> HOLD; watchlist -> WAIT FOR SUPPORT CONFIRMATION.
- SUPPORT HOLD above the floor: held -> HOLD; watchlist -> WAIT unless a separate entry check passes.
- Upside: FAILED BREAKOUT -> held REDUCE/EXIT REVIEW by mandate, watchlist NO TRADE; BREAKOUT RETEST HELD ->
  WAIT until a newly reviewed floor version exists; BREAKOUT CONFIRMED -> SETUP CANDIDATE pending
  follow-through; RESISTANCE TEST -> WAIT (caution for a new entry).
- Entry check (watchlist, above the floor, first ceiling not reached): reward/risk from the WORST permitted
  entry (the floor zone's top) to the first ceiling's lower edge, against the fixed failure level, after an
  illustrative round-trip cost. RR_MIN = 1.5 is an UNVALIDATED screening filter, not a buy rule. A conditional
  BUY ON DIP proposal also needs: dated buyer defense of the floor, no verified event inside the horizon and
  usable data. Anything less is SETUP CANDIDATE or WAIT. No order is ever placed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import features, level_packet, state

FLAG = "STOCKWATCH_CIS_DECISIONS"
RR_MIN = 1.5                 # UNVALIDATED provisional screening minimum; sensitivity to be assessed
RR_ENV = "STOCKWATCH_CIS_RR_MIN"   # optional override, 1.0-5.0; its source is reported with every check
MAX_PACKET_SESSIONS = 20     # provisional: a packet is stale once this many completed sessions have passed
ANCHOR_TOLERANCE = 0.005     # the packet's as-of close must still match today's history within 0.5%
MAX_BAR_LAG = 1              # live bars may trail the expected last session by one weekday (a holiday)
MAX_MISSING = 1              # weekdays missing among the last 10 before the latest bar (a holiday)
COST_ROUND_TRIP = 0.002      # illustrative costs/slippage for the net reward/risk; gross is shown too
DEFENSE_LOOKBACK = 10        # completed sessions searched for a dated defense of the floor
HORIZON = 20                 # trading sessions, the packets' scenario horizon

DOWN_LABEL = {"above_floor": "SUPPORT HOLD", "testing_floor": "SUPPORT HOLD · TESTING",
              "warning": "SUPPORT BREAK", "failure": "TRADE INVALIDATED", "major_damage": "TREND BREAKDOWN",
              "undetermined": "NO REVIEWED FLOOR"}
UP_LABEL = {"pending": "NOT REACHED", "testing": "RESISTANCE TEST", "close_above": "BREAKOUT CONFIRMED",
            "retest_defended": "BREAKOUT RETEST HELD", "failed_breakout": "FAILED BREAKOUT"}
# action -> (category, the existing plan stance it corresponds to, or None when no existing label fits)
ACTIONS = {
    "BUY ON DIP (CONDITIONAL PROPOSAL)": ("BUY", "BUY ON PULLBACK"),
    "SETUP CANDIDATE": ("WAIT", "WAIT FOR CONFIRMATION"),
    "WAIT": ("WAIT", "WAIT FOR CONFIRMATION"),
    "WAIT FOR SUPPORT CONFIRMATION": ("WAIT", "WAIT FOR CONFIRMATION"),
    "WAIT — REVIEW NEW FLOOR": ("WAIT", "WAIT FOR CONFIRMATION"),
    "HOLD": ("HOLD", "HOLD"),
    "TRIM / REDUCE REVIEW": ("TRIM", "TRIM / PROTECT"),
    "RISK — REVIEW REDUCTION/EXIT": ("REVIEW", None),
    "REDUCE/EXIT REVIEW": ("REVIEW", None),
    "REVIEW REQUIRED": ("REVIEW", None),
    "EXIT TACTICAL": ("EXIT", "REDUCE / EXIT"),
    "NO TRADE": ("PASS", "NO TRADE"),
    "STALE LEVELS — REVIEW REQUIRED": ("REVIEW", None),
    "DATA REVIEW": (None, None),
    "CIS UNSUPPORTED": (None, None),
}
SEVERITY = ("above_floor", "testing_floor", "warning", "failure", "major_damage")


def mode() -> str:
    """'shadow' shows CIS calls beside the existing ones; anything else is 'off'. There is no active mode."""
    return "shadow" if (os.getenv(FLAG) or "").strip().lower() == "shadow" else "off"


def reviewed_packets() -> dict:
    """Analyst-reviewed level packets by symbol, for SHADOW evaluation. Only these four exist; nothing selects
    levels for other tickers. Reviewed is not approved: see `Packet.approved` and `activation_eligible`."""
    return {s: p for s, p in level_packet.load_acceptance()["packets"].items() if p.reviewed}


def rr_min() -> tuple[float, str]:
    """The screening minimum and where it came from. An invalid override is ignored and reported."""
    raw = (os.getenv(RR_ENV) or "").strip()
    if not raw:
        return RR_MIN, f"default {RR_MIN} (unvalidated)"
    try:
        v = float(raw)
    except ValueError:
        v = None
    if v is None or not 1.0 <= v <= 5.0:
        return RR_MIN, f"default {RR_MIN} (unvalidated; ignored invalid {RR_ENV}={raw!r})"
    return v, f"{RR_ENV}={v:g} (unvalidated)"


@dataclass
class Inputs:
    """What the adapter evaluates. Missing values stay None (unknown), never 0."""
    completed_close: float | None
    completed_session: str | None
    quote: float | None = None                 # a validated current quote, or None
    quote_time: str | None = None
    session_low: float | None = None
    session_high: float | None = None
    later_bars: list = field(default_factory=list)   # completed sessions after the packet's as-of, oldest first
    recent_bars: list = field(default_factory=list)  # the last completed sessions, for the floor-defense check
    data_ok: bool = True
    data_note: str | None = None
    event: dict | None = None                  # a verified scheduled event, e.g. earnings
    sessions_to_event: int | None = None
    as_of_close_now: float | None = None       # today's history's close on the packet's as-of session
    evaluated_on: str | None = None            # the New York date the evaluation is for
    historical: bool = False                   # True for a frozen snapshot: never eligible for activation


def weekdays_between(a: str | date, b: str | date) -> int:
    """Weekdays strictly after a and strictly before b. No exchange calendar: holidays count as sessions, so
    ages run slightly fast (the safe side for expiry) and the bar-lag check allows one holiday."""
    a, b = (date.fromisoformat(x) if isinstance(x, str) else x for x in (a, b))
    n, d = 0, a + timedelta(days=1)
    while d < b:
        n += d.weekday() < 5
        d += timedelta(days=1)
    return n


def inputs_from_packet(packet, recent_bars: list | None = None) -> Inputs:
    """The packet's own frozen snapshot as inputs (the reference shadow run)."""
    q, r = packet["quote"], packet["session_range"]
    event = packet["verified_event"] if "verified_event" in packet.data else None
    snap_day = str(datetime.fromisoformat(q["observed_at_utc"].replace("Z", "+00:00")).astimezone(features.NY).date())
    return Inputs(packet["completed_close"], packet["as_of_completed_session"], q["price"], q["observed_at_utc"],
                  r["low"], r["high"], [], recent_bars or [], True, None, level_packet.thaw(event) if event else None,
                  None, packet["completed_close"], snap_day, True)


def live_inputs(packet, hist, quote: dict | None, now: datetime) -> Inputs:
    """Inputs from the app's cached daily bars and quote. Only completed sessions count as closes; the quote
    is used only if it passes the same 'current trade' check as Telegram (`transitions.current_quote`)."""
    from .. import transitions                      # shared quote validation; imported late to keep this light
    today = now.astimezone(features.NY).date()
    if hist is None or len(hist) == 0:
        return Inputs(None, None, data_ok=False, data_note="no daily bars cached yet", evaluated_on=str(today))
    q = features.check(hist, packet.symbol)
    boundary = features.default_boundary(hist.index, now)
    done = features.completed(hist, boundary) if boundary else hist.iloc[:0]
    if not q.usable or done.empty:
        return Inputs(None, None, data_ok=False, data_note="; ".join(q.problems) or "no completed session",
                      evaluated_on=str(today))
    last = done.index[-1].date()
    expected = today - timedelta(days=1)
    while expected.weekday() >= 5:
        expected -= timedelta(days=1)
    lag = weekdays_between(last, expected) + (last < expected)
    if lag > MAX_BAR_LAG:
        return Inputs(None, str(last), data_ok=False, evaluated_on=str(today),
                      data_note=f"the latest completed bar is {last}, {lag} weekdays behind the expected {expected}")
    have = {d.date() for d in done.index[-15:]}
    checked = [d for d in (last - timedelta(days=i) for i in range(1, 15)) if d.weekday() < 5][:10]
    gaps = [d for d in checked if d not in have and d > done.index[0].date()]
    if len(gaps) > MAX_MISSING:
        return Inputs(None, str(last), data_ok=False, evaluated_on=str(today),
                      data_note=f"{len(gaps)} weekday sessions missing before {last} ({', '.join(map(str, sorted(gaps)))})")
    rows = [{"session": str(i.date()), "high": float(r.High), "low": float(r.Low), "close": float(r.Close),
             "completed": True} for i, r in done.iterrows()]
    later = [b for b in rows if b["session"] > packet["as_of_completed_session"]]
    anchor = next((b["close"] for b in rows if b["session"] == packet["as_of_completed_session"]), None)
    cur = transitions.current_quote(quote, now)
    event = level_packet.thaw(packet["verified_event"]) if "verified_event" in packet.data else None
    if event and event["date"] < str(now.astimezone(features.NY).date()):
        event = None                                # already happened
    # the app has no intraday low/high for the session: those stay None ("not available"), never "no breach"
    return Inputs(rows[-1]["close"], rows[-1]["session"], None if cur is None else cur[0],
                  None if cur is None else cur[2].isoformat(), None, None, later, rows[-DEFENSE_LOOKBACK:],
                  True, None, event, None, anchor, str(today), False)


def staleness(packet, inp: Inputs) -> str | None:
    """Why the packet's levels can't be relied on today, or None. A stale packet stays useful for shadow
    analysis, but its states are no longer a basis for a call until a new version is reviewed."""
    on = inp.evaluated_on or inp.completed_session
    age = weekdays_between(packet["as_of_completed_session"], on) if on else None
    if age is None:
        return "the evaluation date is unknown, so the levels' age can't be checked"
    if age > MAX_PACKET_SESSIONS:                 # elapsed time, not how many rows the provider returned
        return (f"the levels are about {age} sessions old on {on} (as of {packet['as_of_completed_session']}; "
                f"limit {MAX_PACKET_SESSIONS}, provisional)")
    if inp.as_of_close_now is None:
        return f"today's history has no {packet['as_of_completed_session']} session to check the packet against"
    drift = inp.as_of_close_now / packet["completed_close"] - 1
    if abs(drift) > ANCHOR_TOLERANCE:
        return (f"the {packet['as_of_completed_session']} close is now {inp.as_of_close_now:,.2f} vs "
                f"{packet['completed_close']:,.2f} in the packet ({drift:+.1%}): a corporate action or an adjustment "
                "change; the levels need re-review")
    return None


def _mandate(held: bool, tier: int | None, tactical_contract: bool) -> str:
    if not held:
        return "watchlist"
    if tactical_contract:
        return "tactical_contract"
    return "long_term" if tier == 1 else "unknown"


def _risk_action(mandate: str) -> str:
    return {"tactical_contract": "EXIT TACTICAL", "long_term": "RISK — REVIEW REDUCTION/EXIT"}.get(mandate, "REVIEW REQUIRED")


def entry_check(packet, inp: Inputs, ceilings: list[dict]) -> dict:
    """Reward/risk at the worst permitted entry and the other conditions a conditional proposal needs."""
    dn = packet["downside"]
    entry, stop = dn["zone"]["high"], dn["failure"]
    first = next((c for c in ceilings if c["low"] > entry), None)
    out = {"entry_zone": (dn["zone"]["low"], entry), "worst_entry": entry, "invalidation": stop,
           "first_ceiling": None if first is None else (first["low"], first["high"]),
           "rr_gross": None, "rr_net": None, "rr_min": rr_min()[0], "rr_min_source": rr_min()[1], "rr_validated": False,
           "cost_round_trip": COST_ROUND_TRIP,
           "passes_filter": False, "defense": None, "event_inside_horizon": None, "blocks": []}
    if first is None:
        out["blocks"].append("no ceiling above the floor in the packet")
        return out
    target = first["low"]                       # the lower edge: the first place price has to prove itself
    out["rr_gross"] = (target - entry) / (entry - stop)
    half = COST_ROUND_TRIP / 2
    out["rr_net"] = (target * (1 - half) - entry * (1 + half)) / (entry * (1 + half) - stop * (1 - half))
    out["passes_filter"] = out["rr_net"] >= out["rr_min"]
    if not out["passes_filter"]:
        out["blocks"].append(f"reward/risk {out['rr_net']:.2f} (net) is below the {out['rr_min']:g} screening minimum")
    out["defense"] = defense(packet, inp)
    if out["defense"] is None:
        out["blocks"].append("no dated defense of the floor since the levels were set (a session that traded into "
                             "the zone and closed above it, followed only by closes above it)")
    if first["state"] != "pending":
        out["blocks"].append(f"the first ceiling is already at {UP_LABEL[first['state']]}")
    if inp.event:
        inside = inp.sessions_to_event is None or inp.sessions_to_event <= HORIZON
        out["event_inside_horizon"] = inside
        if inside:
            out["blocks"].append(f"verified {inp.event.get('type', 'event')} on {inp.event.get('date')} inside the "
                                 f"{HORIZON}-session horizon")
    return out


def defense(packet, inp: Inputs) -> str | None:
    """The latest dated buyer defense AFTER the packet's as-of session: a completed session that traded into the
    floor zone and closed at or above its top, followed by at least one more completed session, all closing at
    or above the top. Defense before the levels were set doesn't count."""
    top = packet["downside"]["zone"]["high"]
    after = [b for b in inp.recent_bars[-DEFENSE_LOOKBACK:] if b["session"] > packet["as_of_completed_session"]]
    found = None
    for i, b in enumerate(after[:-1]):
        if b["low"] <= top <= b["close"] and all(x["close"] >= top for x in after[i + 1:]):
            found = b["session"]
    return found


def decide(packet, inp: Inputs, held: bool, tier: int | None = None, tactical_contract: bool = False) -> dict:
    """The CIS shadow decision for one stock. `packet` None means no reviewed levels: CIS UNSUPPORTED."""
    mandate = _mandate(held, tier, tactical_contract)
    base = {"mode": "shadow", "no_order_placed": True, "mandate": mandate, "held": held}
    if packet is None or not packet.reviewed or packet["downside"] is None:
        why = ("no reviewed level packet for this stock" if packet is None or not packet.reviewed
               else "the packet has no defensible constructive floor")
        return {**base, "supported": False, "action": "CIS UNSUPPORTED", "category": None, "stance": None,
                "reasons": [why + "; the existing call is shown, labelled legacy"]}
    if inp is None or inp.completed_close is None or not inp.data_ok:
        note = (inp.data_note if inp is not None and inp.data_note else "no completed close to evaluate")
        return {**base, "supported": False, "action": "DATA REVIEW", "category": None, "stance": None,
                "packet_id": packet.id, "reasons": [f"Data can't be used ({note}); no CIS call. The existing call is "
                                                    "shown, labelled legacy."]}
    ev = state.evaluate(packet, inp.completed_close, inp.quote, inp.session_low)
    conf, prov = ev["confirmed_state"], ev["quote_state"]
    ceilings = []
    for c in packet.ceilings:
        bars = list(inp.later_bars)
        if inp.quote is not None:
            bars.append({"session": "today (forming)", "high": inp.session_high if inp.session_high is not None else inp.quote,
                         "low": inp.session_low if inp.session_low is not None else inp.quote, "close": inp.quote,
                         "completed": False})
        cs = state.ceiling_state(c["zone"], bars, c["confirmation"])
        ceilings.append({"id": c["id"], "low": c["zone"]["low"], "high": c["zone"]["high"], "state": cs["state"],
                         "label": UP_LABEL[cs["state"]], "provisional_test": cs["partial_attempt"],
                         "events": cs["events"]})
    reasons = [f"{DOWN_LABEL[conf]} on the {inp.completed_session} close {inp.completed_close:,.2f} "
               f"(levels {packet.id}, {level_packet.REVIEW_LABEL[packet['review_status']]})."]
    if inp.quote is not None and prov != conf:
        worse = SEVERITY.index(prov) > SEVERITY.index(conf)
        reasons.append(f"Provisional: the quote {inp.quote:,.2f} reads {DOWN_LABEL[prov]}"
                       + (" — confirmed only if a session closes there." if worse else "; not a close."))
    if inp.session_low is None:
        reasons.append("Intraday low/high: not available, so nothing is claimed about intraday breaches.")
    for b in ev["session_extreme_breaches"]:
        if b["crossed_below"] and SEVERITY.index(b["threshold"]) > SEVERITY.index(conf):
            reasons.append(f"Intraday: today's low went below {b['level']:g}"
                           + ("; the quote has recovered above it." if b["quote_recovered_at_or_above"] else "."))
    check = None
    failed = [c for c in ceilings if c["state"] == "failed_breakout"]
    if conf in ("failure", "major_damage"):
        action = _risk_action(mandate) if held else "NO TRADE"
        if held and mandate == "unknown":
            reasons.append("The holding model has no trade contract tying this position to these levels "
                           "(Tier 2 or unknown mandate), so it needs your review rather than an automatic exit.")
    elif failed:
        action = ("REDUCE/EXIT REVIEW" if mandate != "tactical_contract" else "EXIT TACTICAL") if held else "NO TRADE"
        reasons.append(f"FAILED BREAKOUT at {failed[-1]['low']:g}–{failed[-1]['high']:g}.")
    elif conf == "warning":
        action = "TRIM / REDUCE REVIEW" if held else "NO TRADE"
        reasons.append("The constructive floor is lost: stop adding" + ("; review a reduction." if held else "."))
    elif conf == "testing_floor":
        action = "HOLD" if held else "WAIT FOR SUPPORT CONFIRMATION"
        reasons.append("Inside the floor zone without a proven defense yet; falling into support is not a buy.")
    else:
        retest = [c for c in ceilings if c["state"] == "retest_defended"]
        broken = [c for c in ceilings if c["state"] == "close_above"]
        testing = [c for c in ceilings if c["state"] == "testing" or c["provisional_test"]]
        if held:
            action = "HOLD"
        elif retest:
            action = "WAIT — REVIEW NEW FLOOR"
            reasons.append(f"BREAKOUT RETEST HELD at {retest[-1]['low']:g}–{retest[-1]['high']:g}: eligible for entry "
                           "reassessment once a new floor version is reviewed; not installed automatically.")
        elif broken:
            action = "SETUP CANDIDATE"
            reasons.append(f"BREAKOUT CONFIRMED above {broken[-1]['high']:g}: a candidate pending follow-through and "
                           "a retest.")
        else:
            check = entry_check(packet, inp, ceilings)
            if testing:
                action = "WAIT"
                reasons.append(f"RESISTANCE TEST at {testing[0]['low']:g}–{testing[0]['high']:g}: wait for a new entry.")
            elif check["passes_filter"] and not check["blocks"]:
                action = "BUY ON DIP (CONDITIONAL PROPOSAL)"
                reasons.append(f"A limit inside {check['entry_zone'][0]:g}–{check['entry_zone'][1]:g} only; invalid on a "
                               f"close below {check['invalidation']:g}; first ceiling {check['first_ceiling'][0]:g}. "
                               "No order is placed.")
            else:
                action = "SETUP CANDIDATE" if check["passes_filter"] else "WAIT"
                reasons += [f"Not a buy: {b}." for b in check["blocks"]]
        if held:
            for c in testing[:1]:
                reasons.append(f"RESISTANCE TEST at {c['low']:g}–{c['high']:g}.")
            reasons.append("Above the floor; adding needs a separate entry check.")
    stale = staleness(packet, inp)
    if stale:
        reasons.insert(0, f"Stale levels: {stale}. The states are shown for information only; no call until a new "
                          f"packet version is reviewed (would have been: {action}).")
        action, check = "STALE LEVELS — REVIEW REQUIRED", None
    if not packet.approved:
        reasons.append("These levels are proposed by the analyst, not accepted by the owner: shadow evaluation only, "
                       "not eligible for an active decision.")
    if inp.historical:
        reasons.append(f"Historical snapshot as of {inp.completed_session}: a record of that day, not a current call.")
    category, stance = ACTIONS[action]
    return {**base, "supported": True, "packet_id": packet.id, "review_status": packet["review_status"],
            "approval": "owner-accepted" if packet.approved else "proposed (not owner-accepted)",
            "evaluation": "historical snapshot" if inp.historical else "live",
            "activation_eligible": packet.approved and stale is None and not inp.historical, "stale": stale,
            "intraday_available": inp.session_low is not None,
            "action": action, "category": category, "stance": stance,
            "downside": {"confirmed": DOWN_LABEL[conf], "confirmed_state": conf,
                         "provisional": DOWN_LABEL[prov] if inp.quote is not None else "NO CURRENT QUOTE",
                         "provisional_state": prov if inp.quote is not None else None,
                         "intraday": ev["session_extreme_breaches"]},
            "upside": ceilings, "entry_check": check,
            "levels": {"floor": (packet["downside"]["zone"]["low"], packet["downside"]["zone"]["high"]),
                       "warning": packet["downside"]["warning"], "failure": packet["downside"]["failure"],
                       "major_damage": packet["downside"]["major_damage"]},
            "reasons": reasons}
