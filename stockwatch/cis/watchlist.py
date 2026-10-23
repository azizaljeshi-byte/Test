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

from datetime import datetime, timedelta

from .. import transitions
from . import candidates, decision, features, level_packet

AGREE = 0.005             # Yahoo and Finnhub prices within 0.5% agree


def finnhub_session(fq: dict | None, now: datetime) -> dict | None:
    """Today's Finnhub quote (price, session high/low, trade time) if it's from today's New York session and
    not from the future; None otherwise. A quote with a zero price means Finnhub has none."""
    if not fq or not fq.get("time") or not fq.get("price"):
        return None
    t = datetime.fromtimestamp(float(fq["time"]), tz=features.NY)
    if t.date() != now.astimezone(features.NY).date() or t > now + timedelta(minutes=2):
        return None
    if not all(isinstance(fq.get(k), (int, float)) and fq[k] > 0 for k in ("price", "high", "low")):
        return None
    if not fq["low"] <= fq["price"] <= fq["high"]:
        return None
    return {"price": float(fq["price"]), "low": float(fq["low"]), "high": float(fq["high"]), "time": t.isoformat()}


def second_source(yahoo_quote: dict | None, fq: dict | None, now: datetime) -> dict:
    """Cross-check today's price between Yahoo and Finnhub. Disagreement is reported, never averaged away."""
    y = transitions.current_quote(yahoo_quote, now)
    f = finnhub_session(fq, now)
    out = {"yahoo": None if y is None else y[0], "finnhub": None if f is None else f["price"],
           "session_low": None if f is None else f["low"], "session_high": None if f is None else f["high"]}
    if y is None or f is None:
        out["status"] = "not compared (" + ", ".join(n for n, v in (("no current Yahoo quote", y), ("no Finnhub quote today", f))
                                                     if v is None) + ")"
    else:
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
           "reasons": []}
    packet = packets.get(ticker)
    if packet is not None:
        inp = decision.live_inputs(packet, hist, yahoo_quote, now)
        if inp.quote is None and second["finnhub"] is not None:
            inp.quote = second["finnhub"]                     # Finnhub fills a missing Yahoo quote, labelled
            out["reasons"].append("Quote from Finnhub (no current Yahoo quote).")
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
    # automatic candidate levels: a diagnostic, never a call
    if hist is None or len(hist) == 0:
        out["data"] = "no daily bars cached yet"
        out["candidate"] = None
        return out
    boundary = features.default_boundary(hist.index, now)
    done = features.completed(hist, boundary) if boundary else hist.iloc[:0]
    q = features.check(done, ticker)
    out["data"] = "ok" if q.usable and len(done) else "; ".join(q.problems) or "no completed session"
    pk, diag = candidates.extract(done.iloc[-400:], ticker, "provider") if out["data"] == "ok" else (None, {"why": out["data"]})
    if pk is None:
        out["candidate"] = {"why": diag.get("why")}
    else:
        cp = level_packet.Packet(pk)
        st = decision.state.downside_state(pk["completed_close"], cp.downside)
        first = next((c for c in pk["upside"]["ceilings"] if c["zone"]["low"] > pk["completed_close"]), None)
        out["candidate"] = {"packet_id": cp.id, "stage": level_packet.stage(cp), "state": decision.DOWN_LABEL[st],
                            "floor": (pk["downside"]["zone"]["low"], pk["downside"]["zone"]["high"]),
                            "failure": pk["downside"]["failure"],
                            "first_ceiling": None if first is None else (first["zone"]["low"], first["zone"]["high"])}
        stop, target = legacy["stop"], legacy["target"]
        out["discrepancy"] = {
            "stop_vs_candidate_failure": None if not stop else stop / pk["downside"]["failure"] - 1,
            "target_vs_candidate_first_ceiling": None if not (target and first) else target / first["zone"]["low"] - 1,
            "legacy_target_is_measured_move": bool(legacy["target_label"] and "measured move" in legacy["target_label"])}
    # alert preview: would the Telegram decision class differ if CIS were active for this stock?
    if out["coverage"] == "unsupported":
        out["alert_preview"] = "no change (legacy kept)"
    elif out["cis_class"] is None:
        out["alert_preview"] = f"{legacy['class']} -> REVIEW (needs a new alert class; never shown as a sell)"
    else:
        out["alert_preview"] = ("same class" if out["cis_class"] == legacy["class"]
                                else f"{legacy['class']} -> {out['cis_class']} (re-baselined silently at activation)")
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
        rows.append(row(s, hist, yq, fq, now))
    return rows


def coverage(rows: list[dict]) -> dict:
    out = {"approved": 0, "proposed": 0, "unsupported": 0, "candidate available": 0, "no candidate": 0, "data problems": 0}
    for r in rows:
        out[r["coverage"]] += 1
        if r.get("data") != "ok":
            out["data problems"] += 1
        elif r.get("candidate") and "packet_id" in r["candidate"]:
            out["candidate available"] += 1
        else:
            out["no candidate"] += 1
    return out
