"""The read for one reference snapshot, built only from structured evidence.

Every sentence comes from a dated number in the packet, the completed bars or the history policy. Nothing
here infers news, intent or future prices, and nothing turns "above the floor" into a buy. Scenario weights
are shown as the analyst entered them (subjective, not calibrated); they are never computed here.
"""
from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache

from . import features, history, level_packet, state

NY = features.NY
BOUNDARY = "2026-10-22"

# The frozen 23 October 2026 inputs for each reference stock: its bars, SPY on the same boundary, and a
# sector ETF labelled as a proxy (None when the round didn't capture one).
REFERENCE = {
    "ISRG": {"bars": "ISRG-adjusted-daily.csv", "spy": "SPY-adjusted-daily.csv", "sector": None,
             "lesson": "Constructive recovery, but the entry is stretched.",
             "upside_extra": None},
    "FICO": {"bars": "FICO-20261023-adjusted.csv", "spy": "SPY-20261023-adjusted.csv",
             "sector": ("XLK", "XLK-20261023-adjusted.csv"),
             "lesson": "A rebound above a local floor inside broader bearish damage.",
             "upside_extra": None},
    "CRDO": {"bars": "CRDO-CRDO-20261023-adjusted.csv", "spy": "CRDO-SPY-20261023-adjusted.csv",
             "sector": ("XLK", "CRDO-XLK-20261023-adjusted.csv"),
             "lesson": "The floor is lost; a deeper support is not moved up to look healthy.",
             "upside_extra": "CRDO-upside-evidence.json"},
    "PODD": {"bars": "PODD-PODD-20261023-adjusted.csv", "spy": "PODD-SPY-20261023-adjusted.csv",
             "sector": ("XLV", "PODD-XLV-20261023-adjusted.csv"),
             "lesson": "A daily recovery with little room to the first ceiling and earnings ahead.",
             "upside_extra": None},
}
STATE_LABEL = {"above_floor": "Above the floor", "testing_floor": "Testing the floor", "warning": "Warning",
               "failure": "Tactical failure", "major_damage": "Major damage", "undetermined": "Undetermined"}
STATE_MEANING = {
    "above_floor": "above this setup's floor; entry quality and the longer trend are separate questions",
    "testing_floor": "inside the floor zone; buyers need to defend it. Falling into support is not a buy signal",
    "warning": "the constructive floor is lost: stop adding and review a reduction under the plan",
    "failure": "the tactical thesis is invalidated: its exit rule applies",
    "major_damage": "the broader base is compromised; tactical failure has already happened",
    "undetermined": "there's no defensible floor to judge against",
}
CEILING_LABEL = {"pending": "not reached", "testing": "being tested", "close_above": "closed above",
                 "retest_defended": "retest defended", "failed_breakout": "failed breakout"}


def money(v) -> str:
    return "unknown" if v is None else f"{v:,.2f}"


def pct(v, signed=True) -> str:
    return "unknown" if v is None else (f"{v:+.1%}" if signed else f"{v:.1%}")


def ny_time(iso: str) -> str:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(NY)
    return f"{t:%a %d %b %Y %H:%M} New York"


def _zone(z) -> str:
    return f"{z['low']:g}–{z['high']:g}"


def _anchor(a) -> str:
    return f"{a['field']} {a['value']:,.2f} on {a['session_date']}"


@lru_cache(maxsize=None)
def report(symbol: str) -> dict:
    """Everything the six tabs show for one reference stock, as plain data."""
    ref = REFERENCE[symbol]
    fx = level_packet.FIXTURES
    packet = level_packet.load_acceptance()["packets"][symbol]
    raw = features.read_csv(fx / ref["bars"])
    quality = features.check(raw, symbol, features.sha256_file(fx / ref["bars"]))
    bars = features.completed(raw, packet["as_of_completed_session"])
    m = features.metrics(bars)
    spy = features.completed(features.read_csv(fx / ref["spy"]), BOUNDARY)
    rel = {"SPY": {n: features.relative_return(bars, spy, n) for n in (21, 63)}}
    if ref["sector"]:
        name, f = ref["sector"]
        rel[name] = {n: features.relative_return(bars, features.completed(features.read_csv(fx / f), BOUNDARY), n)
                     for n in (21, 63)}
    wk = features.weekly(bars)
    done_wk = wk[~wk["incomplete"]]
    hist = history.analogues(bars, history.POLICIES[symbol])
    ev = state.evaluate(packet)
    ladder = state.ladder(packet)
    extra = None
    if ref["upside_extra"]:
        extra = json.loads((fx / ref["upside_extra"]).read_text())
    r = {"symbol": symbol, "packet": packet, "quality": quality, "bars": bars, "metrics": m, "relative": rel,
         "sector": ref["sector"][0] if ref["sector"] else None, "weekly": done_wk, "history": hist,
         "evaluation": ev, "ladder": ladder, "lesson": ref["lesson"], "upside_extra": extra}
    r["room"] = room(packet, ladder)
    r["takeaway"] = takeaway(r)
    r["why_down"] = why_downside(r)
    r["why_up"] = why_upside(r)
    r["what_changes"] = what_changes(r)
    return r


def room(packet, ladder) -> dict | None:
    """Distances from the quote to the first ceiling above and down to the failure level. A description of
    location, not a signal; None when the quote is already below the failure level."""
    px, dn = packet["quote"]["price"], packet["downside"]
    nxt = next((c for c in ladder if c["location"] in ("below", "inside")), None)
    if dn is None or px < dn["failure"]:
        return None
    up = None if nxt is None else max(nxt["low"] / px - 1, 0.0)
    down = dn["failure"] / px - 1
    return {"to_ceiling": up, "ceiling": nxt, "to_failure": down,
            "limited": up is not None and up < abs(down)}


def takeaway(r) -> str:
    p, ev, rm = r["packet"], r["evaluation"], r["room"]
    dn = p["downside"]
    conf = ev["confirmed_state"]
    parts = [f"{STATE_LABEL[conf]} on the {p['as_of_completed_session']} close ({money(p['completed_close'])}) "
             f"against the {_zone(dn['zone'])} floor."]
    if ev["quote_state"] != conf:
        parts.append(f"The live quote reads {STATE_LABEL[ev['quote_state']].lower()}, provisionally, until a "
                     "session closes there.")
    if rm and rm["ceiling"]:
        parts.append(f"The first ceiling ({rm['ceiling']['low']:g}–{rm['ceiling']['high']:g}) is "
                     f"{pct(rm['to_ceiling'], False)} above the quote; the failure level is "
                     f"{pct(-rm['to_failure'], False)} below."
                     + (" Room to the first ceiling is limited." if rm["limited"] else ""))
    if conf in ("above_floor", "testing_floor"):
        parts.append("Above or at the floor is not a buy signal.")
    return " ".join(parts)


def _obs(evidence: str, meaning: str, consequence: str) -> dict:
    return {"evidence": evidence, "meaning": meaning, "consequence": consequence}


def why_downside(r) -> dict:
    p, ev, m = r["packet"], r["evaluation"], r["metrics"]
    dn = p["downside"]
    obs, against = [], []
    q = p["quote"]
    conf = ev["confirmed_state"]
    obs.append(_obs(f"Completed close {money(p['completed_close'])} on {p['as_of_completed_session']}; floor "
                    f"{_zone(dn['zone'])}, warning below {dn['warning']:g}, failure below {dn['failure']:g}, "
                    f"major damage below {dn['major_damage']:g}.",
                    f"Confirmed state: {STATE_LABEL[conf].lower()} — {STATE_MEANING[conf]}.",
                    "Daily-close rule: only a completed session changes this."))
    if ev["quote_state"] != conf:
        obs.append(_obs(f"Quote {money(q['price'])} at {ny_time(q['observed_at_utc'])} (partial session).",
                        f"Provisionally {STATE_LABEL[ev['quote_state']].lower()}.",
                        "Not confirmed until a session closes below that level."))
    for b in ev["session_extreme_breaches"]:
        if b["crossed_below"]:
            rec = "and the quote has recovered above it" if b["quote_recovered_at_or_above"] else "and the quote is still below it"
            obs.append(_obs(f"Today's low {money(p['session_range']['low'])} went below the {b['threshold'].replace('_', ' ')} "
                            f"level {b['level']:g}, {rec}.",
                            "An intraday breach, not a closing one.",
                            "It is an early warning; it does not confirm the state."))
    for a in dn.get("anchor_evidence") or ():
        obs.append(_obs(f"{a['role'].replace('_', ' ').capitalize()} anchor: {_anchor(a)}.", a["reason"],
                        "Analyst-selected from this dated evidence; not generated by code."))
    if m["ma200"] is not None:
        (against if m["Close"] < m["ma200"] else obs).append(_obs(
            f"Close {money(m['Close'])} vs 200-day average {money(m['ma200'])} ({pct(m['dist200'])}).",
            "The longer trend is " + ("still bearish." if m["Close"] < m["ma200"] else "supportive."),
            "A daily recovery can sit inside a bearish longer structure." if m["Close"] < m["ma200"] else
            "Supports the floor, but doesn't make the entry attractive by itself."))
    if m["rv"] is not None:
        (obs if m["rv"] >= 1 else against).append(_obs(
            f"Volume {m['Volume']:,.0f} vs the prior 20-session average {m['volavg20']:,.0f} ({m['rv']:.2f}×).",
            "Participation was " + ("above" if m["rv"] >= 1 else "below") + " normal on the last close.",
            "Volume qualifies the move; it isn't a signal on its own."))
    spy63 = r["relative"]["SPY"][63]
    if spy63 is not None:
        (obs if spy63 >= 0 else against).append(_obs(
            f"Return vs SPY over 63 sessions: {pct(spy63)}.",
            "Relative strength is " + ("positive." if spy63 >= 0 else "negative."), "Context for how much to trust the floor."))
    return {"for": obs, "against": against}


def why_upside(r) -> dict:
    p, ladder = r["packet"], r["ladder"]
    obs, against = [], []
    q = p["quote"]["price"]
    for c, raw in zip(ladder, p.ceilings):
        anchors = "; ".join(_anchor(a) for a in raw.get("anchor_evidence") or ()) or "no anchors recorded"
        obs.append(_obs(f"Ceiling {c['low']:g}–{c['high']:g} ({pct(c['distance_to_low'])} to its lower edge). "
                        f"Anchors: {anchors}.",
                        f"Status: {CEILING_LABEL[c['confirmation']]}; the quote is {c['location']} it.",
                        f"A completed close above {c['high']:g} would be the first clearance; a later defended retest "
                        "is the stronger confirmation."))
    extra = r["upside_extra"]
    if extra:
        for e in extra.get("ceiling_events", []):
            obs.append(_obs(f"{e['date']}: high {money(e['high'])}, close {money(e['close'])}, volume "
                            f"{e['relative_volume']:.2f}× its prior 20-session average.",
                            "A dated reaction at this ladder's levels.", "Evidence for the zone, not a forecast."))
    rm = r["room"]
    if rm and rm["limited"]:
        against.append(_obs(f"The first ceiling is {pct(rm['to_ceiling'], False)} above the quote; the failure "
                            f"level is {pct(-rm['to_failure'], False)} below.", "Little room before the first test.",
                            "Entry quality is limited even though the state may be constructive."))
    if q < p["downside"]["warning"]:
        against.append(_obs(f"Quote {money(q)} is below the lost floor {_zone(p['downside']['zone'])}.",
                            "Recovery isn't confirmed; this ladder maps where price must prove itself.",
                            "No ceiling clearance is implied."))
    return {"for": obs, "against": against}


def what_changes(r) -> list[dict]:
    """The explicit fixed thresholds that would change each read, nearest first."""
    p = r["packet"]
    dn = p["downside"]
    rows = [{"if": f"a completed close below {dn['major_damage']:g}", "then": "major damage"},
            {"if": f"a completed close below {dn['failure']:g}", "then": "tactical failure (exit rule applies)"},
            {"if": f"a completed close below {dn['warning']:g}", "then": "warning (stop adding, review)"},
            {"if": f"a completed close from {dn['zone']['low']:g} up to {dn['zone']['high']:g}", "then": "testing the floor"},
            {"if": f"a completed close at or above {dn['zone']['high']:g}", "then": "above the floor"}]
    for c in r["ladder"]:
        rows.append({"if": f"a completed close above {c['high']:g}",
                     "then": f"ceiling {c['low']:g}–{c['high']:g} closed above (retest still pending)"})
    if "verified_event" in p.data:
        e = p["verified_event"]
        rows.append({"if": f"earnings on {e['date']} ({e['session'].replace('_', ' ')})",
                     "then": "a scheduled event inside the 20-session horizon; the scenario weights don't model it"})
    rows.append({"if": "a new analysis version", "then": "new levels with a change log; quotes alone never move them"})
    return rows
