"""Versioned, immutable level packets: the analyst-selected floors and ceilings a state is judged against.

A packet's levels were chosen by an analyst from dated chart evidence; nothing here selects them. A code
proposal would carry level_selection/review_status `code_candidate_unreviewed` and is never treated as
reviewed. Quotes are evaluated against a packet (see `state`); they can't change it. A new analysis is a new
packet version with a reason, and the old version stays as it was. A new version starts unapproved: the
owner's acceptance is bound to one packet ID and content hash and never carries over to a revision.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import date
from pathlib import Path
from types import MappingProxyType

FIXTURES = Path(__file__).with_name("fixtures")
ACCEPTANCE = FIXTURES / "CIS-chart-framework-v1-acceptance.json"
SELECTIONS = ("analyst_selected", "code_candidate_unreviewed")
REVIEWS = ("analyst_proposed", "user_accepted_in_chat", "code_candidate_unreviewed")
REVIEW_LABEL = {"analyst_proposed": "analyst proposed, not yet accepted",
                "user_accepted_in_chat": "accepted by the owner in chat",
                "code_candidate_unreviewed": "code candidate, NOT reviewed"}
QUOTE_SESSIONS = ("pre", "regular", "post", "closed", "unknown")
REQUIRED = ("contract_version", "method_id", "packet_id", "symbol", "currency", "timeframe", "level_selection",
            "review_status", "action_mode", "as_of_completed_session", "completed_close", "quote", "session_range",
            "downside", "upside", "scenarios", "provenance", "expected")


class PacketError(ValueError):
    pass


def _freeze(v):
    if isinstance(v, dict):
        return MappingProxyType({k: _freeze(x) for k, x in v.items()})
    if isinstance(v, list):
        return tuple(_freeze(x) for x in v)
    return v


def thaw(v):
    """A plain, mutable deep copy (for JSON output or for drafting a new version)."""
    if isinstance(v, MappingProxyType | dict):
        return {k: thaw(x) for k, x in v.items()}
    if isinstance(v, tuple | list):
        return [thaw(x) for x in v]
    return v


def fingerprint(d) -> str:
    return hashlib.sha256(json.dumps(thaw(d), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def content_hash(d) -> str:
    """The hash an owner acceptance is bound to: everything except the review status and the acceptance itself."""
    return fingerprint({k: v for k, v in thaw(d).items() if k not in ("review_status", "acceptance")})


def _pos(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


def _zone_ok(z) -> bool:
    return isinstance(z, dict) and _pos(z.get("low")) and _pos(z.get("high")) and z["low"] < z["high"]


def problems(d: dict) -> list[str]:
    """Everything wrong with a packet: the schema's required shape plus the cross-field rules JSON Schema
    can't express (level order, ceiling order, weights summing to 100, scenario band arithmetic)."""
    out = [f"missing {k}" for k in REQUIRED if k not in d]
    if out:
        return out
    if d["contract_version"] != "1.0" or d["method_id"] != "independent_chart_judgment_v1":
        out.append("unknown contract version or method")
    if d["timeframe"] != "daily":
        out.append("timeframe must be daily")
    if d["action_mode"] != "explain_only":
        out.append("action_mode must be explain_only (no orders or notifications)")
    if d["level_selection"] not in SELECTIONS or d["review_status"] not in REVIEWS:
        out.append("unknown level_selection or review_status")
    if (d["level_selection"] == "code_candidate_unreviewed") != (d["review_status"] == "code_candidate_unreviewed"):
        out.append("a code candidate must stay marked code_candidate_unreviewed in both fields")
    try:
        date.fromisoformat(d["as_of_completed_session"])
    except (TypeError, ValueError):
        out.append("as_of_completed_session must be a date")
    if not _pos(d["completed_close"]):
        out.append("completed_close must be a positive number")
    q = d["quote"]
    if not (isinstance(q, dict) and _pos(q.get("price")) and q.get("session") in QUOTE_SESSIONS
            and isinstance(q.get("is_partial"), bool) and q.get("observed_at_utc")):
        out.append("quote needs price, observed_at_utc, session and is_partial")
    r = d["session_range"]
    if not (isinstance(r, dict) and _pos(r.get("low")) and _pos(r.get("high")) and r["low"] <= r["high"]):
        out.append("session_range needs low <= high")
    dn = d["downside"]
    if dn is not None:
        if not _zone_ok(dn.get("zone")) or not all(_pos(dn.get(k)) for k in ("warning", "failure", "major_damage")):
            out.append("downside needs a zone and positive warning, failure and major_damage")
        elif not dn["major_damage"] < dn["failure"] < dn["warning"] == dn["zone"]["low"] < dn["zone"]["high"]:
            out.append("downside must be ordered major_damage < failure < warning = floor low < floor high")
    ceilings = (d["upside"] or {}).get("ceilings", [])
    if not all(_zone_ok(c.get("zone")) for c in ceilings):
        out.append("every ceiling needs a zone with low < high")
    elif any(a["zone"]["high"] > b["zone"]["low"] for a, b in zip(ceilings, ceilings[1:])):
        out.append("ceilings must be ascending and not overlap")
    s = d["scenarios"]
    w = s.get("weights_pct") or {}
    if s.get("method") != "subjective_not_calibrated":
        out.append("scenario weights must be labelled subjective_not_calibrated")
    if set(w) != {"up", "sideways", "down"} or not all(isinstance(v, int) and 0 <= v <= 100 and v % 5 == 0
                                                       for v in w.values()):
        out.append("scenario weights are up/sideways/down in 5-point steps")
    elif sum(w.values()) != 100:
        out.append("scenario weights must sum to 100")
    if all(_pos(s.get(k)) for k in ("anchor", "neutral_band")):
        if abs(s["lower"] - (s["anchor"] - s["neutral_band"])) > 1e-6 or abs(s["upper"] - (s["anchor"] + s["neutral_band"])) > 1e-6:
            out.append("scenario lower/upper must be anchor -/+ neutral band")
    else:
        out.append("scenario anchor and neutral band must be positive")
    if not isinstance(s.get("horizon_trading_sessions"), int) or s["horizon_trading_sessions"] < 1:
        out.append("scenario horizon must be a positive number of sessions")
    return out


class Packet:
    """A validated, read-only level packet. Attribute access is to frozen mappings and tuples."""

    def __init__(self, d: dict):
        d = thaw(d)                                   # a private deep copy, whether given plain or frozen parts
        bad = problems(d)
        if bad:
            raise PacketError(f"{d.get('packet_id', 'packet')}: " + "; ".join(bad))
        object.__setattr__(self, "data", _freeze(d))
        object.__setattr__(self, "fingerprint", fingerprint(d))

    def __setattr__(self, *_):
        raise AttributeError("level packets are immutable; publish a new version instead")

    def __getitem__(self, k):
        return self.data[k]

    @property
    def id(self) -> str:
        return self.data["packet_id"]

    @property
    def symbol(self) -> str:
        return self.data["symbol"]

    @property
    def downside(self):
        return self.data["downside"]

    @property
    def ceilings(self) -> tuple:
        return (self.data["upside"] or {}).get("ceilings", ())

    @property
    def reviewed(self) -> bool:
        """Analyst-reviewed (proposed or accepted): usable for shadow evaluation. Not the same as approved."""
        return self.data["review_status"] != "code_candidate_unreviewed"

    @property
    def approved(self) -> bool:
        """Accepted by the owner for exactly this version. Only an approved packet could ever be eligible for an
        active decision.

        The four reference packets carry the acceptance recorded in the hash-checked handoff. Any revision must
        carry its own acceptance bound to its packet ID and content hash (`accept`); acceptance of an earlier
        version never carries over."""
        d = self.data
        if d["review_status"] != "user_accepted_in_chat":
            return False
        if "revision" not in d:
            return True
        a = d.get("acceptance") or {}
        return a.get("packet_id") == d["packet_id"] and a.get("content_sha256") == content_hash(d)


def new_version(old: Packet, changes: dict, reason: str, packet_id: str) -> Packet:
    """An explicit revision: a new packet with its own ID, a link to the version it replaces and why.

    The old packet is untouched. Loosening an existing failure level is refused. The revision starts as
    analyst-proposed: it needs its own owner acceptance (`accept`), whatever the old version's status was."""
    if not reason.strip():
        raise PacketError("a new level version needs a reason")
    if packet_id == old.id:
        raise PacketError("a new level version needs a new packet ID")
    d = thaw(old.data)
    d.update(copy.deepcopy(changes))
    if old.downside and d.get("downside") and d["downside"]["failure"] < old.downside["failure"]:
        raise PacketError("the failure level can't be lowered because price fell; start a new analysis instead")
    d["packet_id"] = packet_id
    if d["review_status"] != "code_candidate_unreviewed":
        d["review_status"] = "analyst_proposed"
    d.pop("acceptance", None)
    d["revision"] = {"supersedes": old.id, "supersedes_content_sha256": content_hash(old.data), "reason": reason}
    d.setdefault("provenance", {})
    d["provenance"] = {**d["provenance"], "level_rationale": f"{reason} (replaces {old.id})"}
    return Packet(d)


def accept(packet: Packet, note: str) -> Packet:
    """Record the owner's acceptance of exactly this packet version (ID and content hash). A code candidate
    can't be accepted directly; it has to be reviewed into an analyst packet first."""
    if not packet.reviewed:
        raise PacketError("a code candidate can't be accepted; review it into an analyst packet first")
    if not note.strip():
        raise PacketError("an acceptance needs a note saying who accepted it and where")
    d = thaw(packet.data)
    d["review_status"] = "user_accepted_in_chat"
    d["acceptance"] = {"packet_id": d["packet_id"], "content_sha256": content_hash(d), "note": note}
    return Packet(d)


def load_acceptance(path: Path = ACCEPTANCE) -> dict:
    raw = json.loads(Path(path).read_text())
    return {**raw, "packets": {p["symbol"]: Packet(p) for p in raw["packets"]}}
