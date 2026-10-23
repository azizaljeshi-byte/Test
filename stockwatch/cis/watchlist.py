"""Whole-watchlist CIS shadow comparison (Issue #31, workstream B). Read-only, run on demand.

For every tracked stock: data quality, the CIS call where a reviewed packet exists (CIS UNSUPPORTED with the
legacy call kept otherwise), the automatic candidate levels and their state as a diagnostic only, how the
legacy stop/target compare with the candidate failure level and first ceiling, whether a Telegram decision
class would change, and a Finnhub second-source quote check when a key is configured.

Candidate levels never produce a call: the walk-forward check (docs/CIS_PHASE2.md) found their failure levels
no better than a level the same ATR distance below price. Nothing here feeds the verdict, plans, the alert
memory or Telegram; `run` is meant for a background job, never the page itself.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from .. import transitions
from . import candidates, decision, features, level_packet

AGREE = 0.005             # Yahoo and Finnhub prices within 0.5% agree


def finnhub_session(fq: dict | None, now: datetime) -> dict | None:
    """Today's Finnhub quote (price, session high/low, trade time) if it's from today's New York session and
    not from the future; None otherwise. A quote with a zero price means Finnhub has none."""
    if not fq or not fq.get("time") or not fq.get("price"):
        return None
    try:
        t = datetime.fromtimestamp(float(fq["time"]), tz=features.NY)
    except (TypeError, ValueError, OverflowError, OSError):
        return None                                   # a malformed timestamp: no Finnhub quote, never an error
    if t.date() != now.astimezone(features.NY).date() or t > now + timedelta(minutes=2):
        return None
    ok = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0  # noqa: E731
    if not all(ok(fq.get(k)) for k in ("price", "high", "low")):
        return None
    if not fq["low"] <= fq["price"] <= fq["high"]:
        return None
    # usable as today's price only under the same rule as a Yahoo quote: a regular-session trade at most an
    # hour old. Today's high/low stay valid facts after the close.
    current = transitions._in_session(t, "regular", now)
    return {"price": float(fq["price"]), "low": float(fq["low"]), "high": float(fq["high"]), "time": t.isoformat(),
            "current": current}


def second_source(yahoo_quote: dict | None, fq: dict | None, now: datetime) -> dict:
    """Cross-check today's price between Yahoo and Finnhub. Disagreement is reported, never averaged away."""
    y = transitions.current_quote(yahoo_quote, now)
    f = finnhub_session(fq, now)
    out = {"yahoo": None if y is None else y[0], "yahoo_session": None if y is None else y[1],
           "finnhub": None if f is None else f["price"], "finnhub_time": None if f is None else f["time"],
           "finnhub_current": bool(f and f["current"]),
           "session_low": None if f is None else f["low"], "session_high": None if f is None else f["high"]}
    # comparable only when both are current regular-session trades (same session, each at most an hour old)
    why = [n for n, bad in (("no current Yahoo quote", y is None),
                            ("Yahoo's quote is from the extended session", y is not None and y[1] != "regular"),
                            ("no Finnhub quote today", f is None),
                            ("Finnhub's quote isn't a current regular-session trade", f is not None and not f["current"]))
           if bad]
    if why:
        out["status"] = "not comparable (" + "; ".join(why) + ")"
        return out
    diff = f["price"] / y[0] - 1
    out["diff"] = diff
    out["status"] = "agree" if abs(diff) <= AGREE else f"DISAGREE by {diff:+.2%}"
    return out


def legacy_view(snap: dict) -> dict:
    p = snap["payload"]
    plan = p.get("plan") or {}
    stance = transitions.effective_stance(snap["verdict"], plan, p["watchlist"])
    t = next(iter(plan.get("targets") or []), None)
    return {"verdict": snap["verdict"], "stance": stance, "class": transitions.STANCE_CLASS.get(stance),
            "stop": plan.get("stop"), "target": None if t is None else t.get("price"),
            "target_label": None if t is None else t.get("label")}


def row(snap: dict, hist, yahoo_quote: dict | None, fq: dict | None, now: datetime,
        packets: dict | None = None) -> dict:
    """One watchlist line. `hist`: the provider's daily bars (may be None); `fq`: Finnhub quote or None."""
    ticker, held = snap["ticker"], not snap["payload"]["watchlist"]
    packets = decision.reviewed_packets() if packets is None else packets
    legacy = legacy_view(snap)
    second = second_source(yahoo_quote, fq, now)
    out = {"ticker": ticker, "held": held, "tier": snap.get("tier"), "legacy": legacy, "second_source": second,
           "reasons": [], "data": None, "data_as_of": None, "candidate": None, "discrepancy": {}, "alert_preview": None}
    packet = packets.get(ticker)
    if packet is not None:
        inp = decision.live_inputs(packet, hist, yahoo_quote, now)
        if inp.quote is None and second["finnhub_current"]:
            inp.quote = second["finnhub"]                     # Finnhub fills a missing Yahoo quote, labelled
            out["reasons"].append("Quote from Finnhub (no current Yahoo quote); today's high/low not used "
                                  "without a second source to agree with.")
        if second["session_low"] is not None and second["status"] == "agree":
            inp.session_low, inp.session_high = second["session_low"], second["session_high"]
        d = decision.decide(packet, inp, held, snap.get("tier"))
        out.update(coverage="approved" if packet.approved else "proposed", action=d["action"],
                   cis_class=transitions.STANCE_CLASS.get(d["stance"]) if d.get("stance") else None,
                   packet_id=packet.id)
        out["reasons"] += d["reasons"]
    else:
        out.update(coverage="unsupported", action="CIS UNSUPPORTED", cis_class=None, packet_id=None)
        out["reasons"].append("No reviewed level packet: the legacy call stays, labelled legacy.")
    # alert preview: would the Telegram decision class differ if CIS were active for this stock?
    if out["coverage"] == "unsupported":
        out["alert_preview"] = "no change (legacy kept)"
    elif out["cis_class"] is None:
        out["alert_preview"] = (f"{legacy['class']} -> no CIS call ({out['action']})"
                                if out["action"] in ("DATA REVIEW", "CIS UNSUPPORTED")
                                else f"{legacy['class']} -> REVIEW (needs a new alert class; never shown as a sell)")
    else:
        out["alert_preview"] = ("same class" if out["cis_class"] == legacy["class"]
                                else f"{legacy['class']} -> {out['cis_class']} (re-baselined silently at activation)")
    # automatic candidate levels: a diagnostic, never a call
    done, note, last = decision.current_bars(hist, now, ticker)   # the same freshness policy as reviewed packets
    out["data_as_of"] = last
    if done is None:
        out["data"] = note
        return out
    out["data"] = "ok"
    pk, diag = candidates.extract(done.iloc[-400:], ticker, "provider")
    if pk is None:
        out["candidate"] = {"why": diag.get("why")}
    else:
        cp = level_packet.Packet(pk)
        st = decision.state.downside_state(pk["completed_close"], cp.downside)
        first = next((c for c in pk["upside"]["ceilings"] if c["zone"]["low"] > pk["completed_close"]), None)
        out["candidate"] = {"packet_id": cp.id, "stage": level_packet.stage(cp), "state": decision.DOWN_LABEL[st],
                            "as_of": pk["as_of_completed_session"],
                            "floor": (pk["downside"]["zone"]["low"], pk["downside"]["zone"]["high"]),
                            "failure": pk["downside"]["failure"],
                            "first_ceiling": None if first is None else (first["zone"]["low"], first["zone"]["high"])}
        stop, target = legacy["stop"], legacy["target"]
        out["discrepancy"] = {
            "stop_vs_candidate_failure": None if not stop else stop / pk["downside"]["failure"] - 1,
            "target_vs_candidate_first_ceiling": None if not (target and first) else target / first["zone"]["low"] - 1,
            "legacy_target_is_measured_move": bool(legacy["target_label"] and "measured move" in legacy["target_label"])}
    return out


def run(snaps: list[dict], provider, now: datetime, finnhub_quote=None) -> list[dict]:
    """The whole table, for a background job. `finnhub_quote(ticker)` is optional (no key: skipped)."""
    rows = []
    for s in snaps:
        t = s["ticker"]
        try:
            hist = provider.history(t)
        except Exception:
            hist = None
        try:
            yq = provider.quote(t)
        except Exception:
            yq = None
        fq = None
        if finnhub_quote:
            try:
                fq = finnhub_quote(t)
            except Exception:
                fq = None
        try:
            rows.append(row(s, hist, yq, fq, now))
        except Exception as e:                        # one bad stock never stops the comparison
            rows.append(error_row(s, f"{type(e).__name__}: {e}"))
    return rows


def error_row(snap: dict, why: str) -> dict:
    """A row with the full shape for a stock that couldn't be compared at all."""
    return {"ticker": snap.get("ticker", "?"), "held": not (snap.get("payload") or {}).get("watchlist", True),
            "tier": snap.get("tier"), "legacy": {"stance": None, "class": None}, "second_source": {"status": "not compared"},
            "reasons": [f"Couldn't compare: {why[:200]}"], "data": "comparison failed", "data_as_of": None, "candidate": None,
            "discrepancy": {}, "alert_preview": "no change (legacy kept)", "coverage": "unsupported",
            "action": "CIS UNSUPPORTED", "cis_class": None, "packet_id": None}


def table_rows(rows: list[dict]) -> list[list[str]]:
    """Stock | CIS | Legacy | Candidate, for the page. Works for any row, however incomplete."""
    out = []
    for r in rows:
        c = r.get("candidate") or {}
        cand = c.get("state") or ("data problem" if r.get("data") not in (None, "ok") else "none")
        out.append([r["ticker"] + (" (held)" if r.get("held") else ""), r.get("action") or "—",
                    (r.get("legacy") or {}).get("stance") or "—", cand])
    return out


def details(r: dict) -> tuple[str, str]:
    """(facts line, reasons line) for one stock's 'why' entry."""
    d, c = r.get("discrepancy") or {}, r.get("candidate") or {}
    bits = [f"alerts: {r.get('alert_preview') or 'unknown'}",
            f"price check: {(r.get('second_source') or {}).get('status', 'not compared')}"]
    if r.get("data") not in (None, "ok"):
        bits.append(f"data: {r['data']}")
    elif r.get("data_as_of"):
        bits.append(f"bars to {r['data_as_of']}")
    elif c.get("why"):
        bits.append(f"no candidate: {c['why']}")
    if c.get("floor"):
        bits.append(f"candidate (as of {c.get('as_of')}) floor {c['floor'][0]:g}–{c['floor'][1]:g}, failure {c['failure']:g}")
    if d.get("stop_vs_candidate_failure") is not None:
        bits.append(f"legacy stop {d['stop_vs_candidate_failure']:+.1%} vs candidate failure")
    if d.get("legacy_target_is_measured_move"):
        bits.append("legacy target is a measured move (no chart level)")
    return " · ".join(bits), " ".join((r.get("reasons") or [])[:3])


def coverage(rows: list[dict]) -> dict:
    out = {"approved": 0, "proposed": 0, "unsupported": 0, "candidate available": 0, "no candidate": 0, "data problems": 0}
    for r in rows:
        out[r.get("coverage", "unsupported")] += 1
        if r.get("data") != "ok":
            out["data problems"] += 1
        elif r.get("candidate") and "packet_id" in r["candidate"]:
            out["candidate available"] += 1
        else:
            out["no candidate"] += 1
    return out
