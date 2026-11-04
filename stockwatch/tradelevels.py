"""Trade levels on the stock page: price, exit line (the stop), the nearest resistance zones (the profit targets) and the
support zones, drawn to scale. DISPLAY ONLY: it reads the one-call result (`onecall.assess`) and the graded zones
(`zones.assess`) that the engine already saved, changes no score, call, plan, alert or paper rule, and places no order.

Entry is the price now, and only while the one-call says BUY or ADD. The stop is the exit line. Profit 1 and 2 are the low edges
of the two nearest resistance zones above the price. Under the exit line, or not yet near it, nothing is drawn as an entry.
"""
from __future__ import annotations

from html import escape

H = 300                      # chart height in px
MIN_GAP = 24                 # label spacing in px
BUY_CALLS = ("BUY", "ADD")
UNDER_CALLS = ("ON THE LINE", "EXIT", "AVOID")


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def swings_away(price, level, atr) -> float | None:
    """Distance from the price to a level in normal daily swings (always positive), or None when unknown."""
    p, lv, a = _num(price), _num(level), _num(atr)
    if p is None or lv is None or not a or a <= 0:
        return None
    return abs(lv - p) / a


def atr_of(oc: dict | None) -> float | None:
    """A normal daily swing from the one-call result: stored directly, else back out of the distance to the exit line."""
    if not isinstance(oc, dict):
        return None
    a = _num(oc.get("atr"))
    if a and a > 0:
        return a
    d, c, ln = _num(oc.get("distance_swings")), _num(oc.get("close")), _num(oc.get("exit_line"))
    if d and c is not None and ln is not None and abs(d) > 1e-9:
        v = (c - ln) / d
        return v if v > 0 else None
    return None


def build(oc: dict | None, zones: dict | None, price) -> dict | None:
    """The plan to draw, or None when there is nothing honest to draw (no exit line, no price)."""
    p = _num(price)
    if not isinstance(oc, dict) or not oc.get("known") or p is None:
        return None
    line = _num(oc.get("exit_line"))
    if line is None:
        return None
    z = zones if isinstance(zones, dict) and zones.get("known") else {}
    res = sorted((x for x in (z.get("resistance") or []) if _num(x.get("low")) is not None and x["low"] > p), key=lambda x: x["low"])[:2]
    sup = sorted((x for x in (z.get("support") or []) if _num(x.get("high")) is not None and x["high"] < p), key=lambda x: -x["high"])[:2]
    call = str(oc.get("call") or "")
    out = {"call": call, "price": p, "line": line, "atr": atr_of(oc), "res": res, "sup": sup, "why": oc.get("why") or "",
           "mode": "buy" if (call in BUY_CALLS and p > line) else "under" if (call in UNDER_CALLS or p <= line) else "wait",
           "entry": None, "stop": None, "targets": [], "risk": None, "ratios": []}
    if out["mode"] == "buy":
        out["entry"], out["stop"] = p, line
        out["risk"] = p - line
        out["targets"] = [float(x["low"]) for x in res]
        out["ratios"] = [(t - p) / out["risk"] for t in out["targets"]]
    return out


def _layout(marks: list, price_to_y) -> list:
    """(mark, y) with labels pushed apart so none overlap."""
    out, last = [], -999.0
    for m in sorted(marks, key=lambda m: -m["price"]):
        y = max(price_to_y(m["price"]), last + MIN_GAP)
        out.append((m, y))
        last = y
    return out


def html(plan: dict | None) -> str:
    if not plan:
        return ""
    p, line, atr = plan["price"], plan["line"], plan["atr"]
    marks = []
    if plan["mode"] == "buy":
        for i, t in reversed(list(enumerate(plan["targets"], 1))):
            marks.append({"label": f"Profit {i}", "price": t, "cls": "tp"})
        marks.append({"label": "Entry · price now", "price": p, "cls": "now"})
        marks.append({"label": "Stop loss (exit line)", "price": line, "cls": "stop"})
    else:
        marks.append({"label": "Price now", "price": p, "cls": "now"})
        marks.append({"label": "Exit line", "price": line, "cls": "exit"})
    bands = [("res", x["low"], x["high"], x) for x in plan["res"]] + [("sup", x["low"], x["high"], x) for x in plan["sup"]]
    prices = [m["price"] for m in marks] + [b[1] for b in bands] + [b[2] for b in bands]
    span = (max(prices) - min(prices)) or 1.0
    lo, hi = min(prices) - span * 0.06, max(prices) + span * 0.06
    y = lambda v: (hi - v) / (hi - lo) * H  # noqa: E731
    parts = []
    for kind, a, b, x in bands:
        top, ht = y(b), max(y(a) - y(b), 24)
        top -= (ht - (y(a) - y(b))) / 2
        word = "Resistance" if kind == "res" else "Support"
        strength = {"HIGH": "strong", "MEDIUM": "medium"}.get(str(x.get("grade")).upper(), "weak")
        cls = "tl-w" if strength == "weak" else ""
        parts.append(f'<div class="tl-band tl-{kind} {cls}" style="top:{top:.0f}px;height:{ht:.0f}px"><span>{word} · {strength}</span></div>')
    for m, yy in _layout(marks, y):
        parts.append(f'<div class="tl-ln tl-{m["cls"]}" style="top:{y(m["price"]):.0f}px"></div>'
                     f'<div class="tl-lb tl-{m["cls"]}" style="top:{yy - 10:.0f}px"><b>{escape(m["label"])}</b><i>{m["price"]:,.2f}</i></div>')
    chart = f'<div class="tl-chart" style="height:{H}px">{"".join(parts)}</div>'
    if plan["mode"] == "buy":
        head = ("BUY ZONE", "buy", "Close to the exit line and turning up.")
        notes = [f"Risk ${plan['risk']:,.2f} a share ({plan['risk'] / p:.1%}) if it falls to the exit line."]
        if plan["targets"]:
            gains = " · ".join(f"profit {i} +${t - p:,.2f}" for i, t in enumerate(plan["targets"], 1))
            notes.append(f"Gain: {gains}.")
            notes.append("Gain for each $1 risked: " + ", ".join(f"${r:.1f} at profit {i}" for i, r in enumerate(plan["ratios"], 1)) + ".")
            if plan["ratios"][0] < 1:
                notes.append("Profit 1 is closer than the risk: the first target pays less than the stop can cost.")
        else:
            notes.append("No resistance zone above to use as a target.")
        notes.append("Stop = the exit line. Targets = the low edge of the nearest resistance zones. Advice only: nothing is placed.")
    elif plan["mode"] == "under":
        head = ("NO ENTRY NOW", "avoid", f"Under its exit line {line:,.2f}. Would change if it closes back above it.")
        notes = ["No entry, stop or targets are drawn until it is back above the exit line."]
    else:
        n = swings_away(p, line, atr)
        far = f"{n:.1f} normal swings above its exit line" if n is not None else "above its exit line"
        head = ("NO ENTRY YET", "wait", f"{far.capitalize()}: not a low-risk entry.")
        notes = ["The exit line is shown as the level that would end the trade. No entry or targets are drawn."]
    word, cls, sub = head
    return (f'<div class="rd-h"><span>Trade levels</span></div><div class="tl"><div class="tl-v tl-{cls}">{word}<small>{escape(sub)}</small></div>'
            f'{chart}<div class="tl-notes">{"".join(f"<div>{escape(n)}</div>" for n in notes)}</div></div>')


CSS = """
.tl{background:var(--dz-surface);border:1px solid var(--dz-line);border-radius:14px;padding:12px;margin-bottom:10px}
.tl-v{border-left:4px solid var(--c);padding:7px 11px;border-radius:8px;background:var(--dz-raised);font-weight:800;color:var(--c);margin-bottom:10px}
.tl-v small{display:block;font-weight:400;color:var(--dz-soft);font-size:.78rem;margin-top:1px}
.tl-buy{--c:var(--dz-buy,#3dffa8)}.tl-wait{--c:var(--dz-watch,#ffb020)}.tl-avoid{--c:var(--dz-act,#ff697b)}
.tl-chart{position:relative;margin:4px 2px}
.tl-band{position:absolute;left:0;width:52%;border-radius:4px;font-size:.68rem;color:var(--dz-soft)}
.tl-band span{position:absolute;left:5px;top:50%;transform:translateY(-50%);white-space:nowrap;background:var(--dz-raised);padding:0 5px;border-radius:4px;z-index:3}
.tl-band.tl-res{background:color-mix(in srgb,var(--dz-act,#ff697b) 16%,transparent);border:1px solid color-mix(in srgb,var(--dz-act,#ff697b) 45%,transparent)}
.tl-band.tl-sup{background:color-mix(in srgb,var(--dz-buy,#3dffa8) 14%,transparent);border:1px solid color-mix(in srgb,var(--dz-buy,#3dffa8) 40%,transparent)}
.tl-band.tl-w{opacity:.65}
.tl-ln{position:absolute;left:0;width:60%;height:0;border-top:2px solid var(--c)}
.tl-lb{position:absolute;left:62%;right:0;font-size:.8rem;white-space:nowrap;color:var(--c)}.tl-lb i{font-style:normal;float:right;font-variant-numeric:tabular-nums}
.tl-now{--c:#70b8ff}.tl-stop{--c:var(--dz-act,#ff697b)}.tl-stop.tl-ln,.tl-tp.tl-ln,.tl-exit.tl-ln{border-top-style:dashed}
.tl-tp{--c:var(--dz-buy,#3dffa8)}.tl-exit{--c:var(--dz-watch,#ffb020)}
.tl-notes{margin-top:10px;border-top:1px solid var(--dz-line);padding-top:8px;font-size:.78rem;color:var(--dz-soft)}.tl-notes div{padding:2px 0}
"""
