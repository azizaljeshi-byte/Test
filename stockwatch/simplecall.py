"""One call per stock (owner, 9 Nov): the technical-first New call, in plain words. Display only.

The call comes from `onecall` alone (the exit line, the band under it, the fall stopping). The fundamentals number is shown beside it as guidance
and never changes it. "x of 6 checks agree" says how sure the call is; it is not a second call. Nothing here is read by scoring, alerts or paper rules."""
from __future__ import annotations

from . import dayboard, design

WORDS = {"EXIT": ("Sell", "sell"), "AVOID": ("Avoid", "sell"), "ON THE LINE": ("On the line", "watch"), "WAIT FOR TURN": ("Watch", "watch"),
         "BUY": ("Buy", "buy"), "ADD": ("Add", "buy"), "HOLD": ("Hold", "hold"), "WAIT": ("Wait", "hold")}
CLS = {"sell": "act", "buy": "buy", "watch": "watch", "hold": "calm", "unknown": "calm"}


def of(snap: dict) -> dict:
    """{word, group (sell|buy|watch|hold|unknown), cls, why, sure ((agree, known) or None), fund (score or None), fund_word, line}. Never raises."""
    p = snap.get("payload") or {}
    oc = ((p.get("technical") or {}).get("one_call")) or {}
    score = snap.get("fundamental_score")
    score = score if isinstance(score, (int, float)) and not isinstance(score, bool) and score == score else None
    rated = design.fundamentals_rating(score)
    base = {"fund": score, "fund_word": rated[0] if rated else None, "line": oc.get("exit_line") if oc.get("known") else None}
    word_group = WORDS.get(oc.get("call")) if oc.get("known") else None
    if p.get("error") or not word_group:
        why = p.get("error") or oc.get("why") or "no usable chart reading"
        return {**base, "word": "No call", "group": "unknown", "cls": "calm", "why": str(why), "sure": None}
    word, group = word_group
    sure = None
    if group in ("sell", "buy"):
        want = dayboard.BEAR if group == "sell" else dayboard.BULL
        known = [c for c in dayboard.checks(snap) if c["state"] is not None]
        if len(known) >= dayboard.MIN_KNOWN:
            sure = (sum(1 for c in known if c["state"] == want or c["state"] == "ok"), len(known))
    return {**base, "word": word, "group": group, "cls": CLS[group], "why": oc.get("why") or "", "sure": sure}


def fund_line(c: dict) -> str:
    """The fundamentals number as guidance, plainly labelled; unknown stays unknown."""
    if c["fund"] is None:
        return "Fundamentals: unknown (guidance only)"
    return f"Fundamentals {c['fund']:.0f}/100 · {c['fund_word']} (guidance only, not part of the call)"
