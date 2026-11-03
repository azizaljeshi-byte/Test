"""One short word for where a stock is in its move: RIDING, SLOWING, PULLING BACK, STABILISING or FALLING (owner, 2 Nov).
Display only: it changes no score, call, signal, alert or trade rule, and it fetches nothing.
A breakdown up at least 1 ATR today is labelled BOUNCING TODAY; its code remains FALLING.

It is built only from two reads the stock already carries, so it cannot disagree with them:
  the chart status (record high / strong uptrend / pullback / weakening / testing support / breakdown), and
  the momentum word (strong / building / stabilising / fading / weak / falling),
plus today's move in daily ranges when the market is live (a stock in an uptrend that has given back half a range today is SLOWING).

  RIDING        uptrend and momentum strong or building, not giving back today
  SLOWING       still above its floor, but momentum fading, or it is giving back today, or a weakening chart with some life left
  PULLING BACK  a dip inside an uptrend while momentum is still strong or building
  STABILISING   it was falling or weak and has turned up (never shown on a confirmed breakdown: the chart says falling there)
  FALLING       a confirmed breakdown, or a weak chart with weak or falling momentum

No word when either read is missing, or when the pair does not make a clear story, or when the word would contradict the New call
(RIDING on an EXIT or AVOID, FALLING on a BUY or ADD): never two answers. Unknown is unknown.
"""
from __future__ import annotations

BOUNCE_ATR = 1.0              # breakdown display only: up this many daily ranges = bouncing today
GIVEBACK_ATR = 0.5            # in an uptrend, down this many daily ranges today = slowing
COLORS = {"RIDING": "opp", "SLOWING": "warn", "PULLING BACK": "info", "STABILISING": "info", "FALLING": "risk"}
UP_TREND = ("record_high", "strong_uptrend")
BREAKDOWN = ("breakdown", "deep_breakdown")
GOOD, BAD = ("strong", "building"), ("weak", "falling")


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def _move_atr(p: dict) -> float | None:
    """Today's move in daily ranges, only while the regular session is live."""
    q, tech = p.get("quote") or {}, p.get("technical") or {}
    chg, price, atr = _num(q.get("live_change")), _num(q.get("live_price")), _num(tech.get("atr"))
    if q.get("market_state") != "REGULAR" or chg is None or not price or not atr or atr <= 0:
        return None
    prev = price / (1 + chg) if chg > -0.9 else None
    return (price - prev) / atr if prev else None


def phase(snap: dict) -> dict | None:
    """{"code", "label", "why", "color"} or None."""
    p = snap.get("payload") or {}
    tech = p.get("technical") or {}
    ps, mo = tech.get("price_status"), tech.get("momentum")
    if not isinstance(ps, dict) or not ps.get("code") or ps["code"] == "unknown":
        return None
    if not isinstance(mo, dict) or not mo.get("known") or not mo.get("momentum"):
        return None
    code, m = ps["code"], mo["momentum"]
    day = _move_atr(p)
    word, why = None, ""
    if code in UP_TREND:
        if m in GOOD:
            if day is not None and day <= -GIVEBACK_ATR:
                word, why = "SLOWING", f"uptrend, but down {abs(day):.1f} daily ranges today"
            else:
                word, why = "RIDING", f"{ps.get('label', 'uptrend').lower()}, momentum {m}"
        elif m in ("fading",) + BAD:
            word, why = "SLOWING", f"uptrend, but momentum is {m}"
    elif code == "pullback":
        if m in GOOD:
            word, why = "PULLING BACK", f"a dip inside an uptrend, momentum still {m}"
        elif m in ("fading", "weak"):
            word, why = "SLOWING", f"a dip, and momentum is {m}"
        elif m == "stabilising":
            word, why = "STABILISING", "a dip that has turned up"
        elif m == "falling":
            word, why = "FALLING", "a dip with falling momentum"
    elif code == "weakening":
        if m in GOOD + ("fading",):
            word, why = "SLOWING", f"chart weakening, momentum {m}"
        elif m == "stabilising":
            word, why = "STABILISING", "chart weakening but momentum has turned up"
        elif m in BAD:
            word, why = "FALLING", f"chart weakening, momentum {m}"
    elif code == "testing_support":
        if m in GOOD + ("stabilising",):
            word, why = "STABILISING", f"at support, momentum {m}"
        elif m == "fading":
            word, why = "SLOWING", "at support, momentum fading"
        elif m in BAD:
            word, why = "FALLING", f"at support, momentum {m}"
    elif code in BREAKDOWN:
        word, why = "FALLING", f"{ps.get('label', 'breakdown').lower()}" + (", momentum has turned up but the chart is still broken" if m == "stabilising" else f", momentum {m}")
    if not word:
        return None
    call = ((tech.get("one_call") or {}).get("call"))
    if (word in ("RIDING", "PULLING BACK") and call in ("EXIT", "AVOID")) or (word == "FALLING" and call in ("BUY", "ADD")):
        return None                                              # would contradict the New call: no signal rather than two answers
    label = word
    if code in BREAKDOWN and word == "FALLING" and day is not None and day >= BOUNCE_ATR:
        label, why = "BOUNCING TODAY", f"up {day:.1f} daily ranges today; daily chart still broken"
    return {"code": word, "label": label, "why": why, "color": COLORS[word]}
