"""Deterministic floor and ceiling states against a fixed level packet. Pure functions, no I/O.

Downside: the most severe strict-below condition wins (a gap can skip stages). Three separate facts are
reported and never merged: the confirmed state from the last completed close, a provisional state from the
current quote, and which thresholds today's session low crossed (and whether the quote has recovered).

Upside: a ceiling is `pending` (not reached), `testing` (traded into it, or a close back inside after a
breakout), `close_above` (a completed close above its upper edge), `retest_defended` (a later completed
session traded back into the zone and closed above it) or `failed_breakout` (after a close above, a
completed close below the zone's lower edge). A failed breakout stands until a completed close back above
the zone; wicks into it or closes inside it are reported only as a test from below. Partial bars can flag a
test but never confirm anything.
"""
from __future__ import annotations

DOWNSIDE_STATES = ("above_floor", "testing_floor", "warning", "failure", "major_damage", "undetermined")
THRESHOLDS = ("warning", "failure", "major_damage")
CEILING_STATES = ("pending", "testing", "close_above", "retest_defended", "failed_breakout")


def downside_state(price: float | None, downside) -> str:
    """One price against the packet's floor ladder. Equal to a threshold is not below it."""
    if downside is None or price is None:
        return "undetermined"
    if price < downside["major_damage"]:
        return "major_damage"
    if price < downside["failure"]:
        return "failure"
    if price < downside["warning"]:
        return "warning"
    if price < downside["zone"]["high"]:
        return "testing_floor"
    return "above_floor"


SNAPSHOT = object()     # "use the packet's own snapshot value"; None always means unknown


def evaluate(packet, completed_close=SNAPSHOT, quote=SNAPSHOT, session_low=SNAPSHOT) -> dict:
    """Confirmed, provisional and intraday facts for one packet.

    An argument left out uses the packet's own snapshot. Passing None means unknown: the state is undetermined
    and intraday crossings are None, never "not crossed". A different quote re-evaluates the same fixed
    levels and can't change them."""
    dn = packet["downside"]
    close = packet["completed_close"] if completed_close is SNAPSHOT else completed_close
    px = packet["quote"]["price"] if quote is SNAPSHOT else quote
    low = packet["session_range"]["low"] if session_low is SNAPSHOT else session_low
    breaches = []
    if dn is not None:
        for name in THRESHOLDS:
            level = dn[name]
            breaches.append({"threshold": name, "level": level,
                             "crossed_below": None if low is None else low < level,
                             "quote_recovered_at_or_above": None if px is None else px >= level})
    return {"confirmed_state": downside_state(close, dn), "quote_state": downside_state(px, dn),
            "quote_is_provisional": True, "session_extreme_breaches": breaches}


def location(price: float | None, zone) -> str | None:
    """Where a price sits relative to a zone; the edges count as inside."""
    if price is None:
        return None
    return "below" if price < zone["low"] else "above" if price > zone["high"] else "inside"


def ceiling_state(zone, bars, start: str = "pending") -> dict:
    """Walk dated bars in order. Each bar: {session, high, low, close, completed}.

    `start` is the state recorded in the packet at its as-of session; the bars are the sessions after it.
    Returns the state, whether a retest has been confirmed, the dated events behind it, and whether the
    latest partial bar is attempting the zone."""
    lo, hi = zone["low"], zone["high"]
    state, events, attempt, touched = start, [], False, False
    broke = start in ("close_above", "retest_defended")
    for b in bars:
        if not b.get("completed"):
            attempt = b["high"] >= lo                 # a wick or forming bar is a test, never a confirmation
            if attempt and state == "pending":
                state = "testing"
            continue
        attempt = False
        c = b["close"]
        if not broke:
            if c > hi:                                 # a completed close above the zone: a (new) clearance
                state, broke, touched = "close_above", True, False
                events.append((b["session"], "close_above"))
            elif state == "failed_breakout":
                # a failed breakout stands until a completed close back above the zone; a wick into it, or a
                # close inside it, is only a provisional test from below
                touched = touched or b["high"] >= lo
            elif b["high"] >= lo:
                state = "testing"
            elif state == "testing":
                state = "pending"
            continue
        if c < lo:
            state, broke = "failed_breakout", False
            events.append((b["session"], "failed_breakout"))
        elif c <= hi:
            state = "testing"                          # back inside the zone: unresolved, not yet a failure
        elif b["low"] <= hi and state != "retest_defended":
            state = "retest_defended"
            events.append((b["session"], "retest_defended"))
        elif state == "testing":
            state = "close_above"
            events.append((b["session"], "close_above"))
    return {"state": state, "retest_confirmed": broke and (state == "retest_defended" or any(e == "retest_defended" for _, e in events)),
            "events": events, "partial_attempt": attempt,
            "tested_after_failure": state == "failed_breakout" and (touched or attempt)}


def ladder(packet, quote: float | None = None) -> list[dict]:
    """Each ceiling with the quote's location and its distance from the quote (a distance, not a forecast)."""
    px = packet["quote"]["price"] if quote is None else quote
    out = []
    for c in packet.ceilings:
        z = c["zone"]
        out.append({"id": c["id"], "low": z["low"], "high": z["high"], "location": location(px, z),
                    "confirmation": c["confirmation"],
                    "distance_to_low": None if px is None else z["low"] / px - 1,
                    "distance_to_high": None if px is None else z["high"] / px - 1})
    return out
