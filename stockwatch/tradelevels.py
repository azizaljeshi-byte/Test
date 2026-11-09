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
    if p is None:
        return None
    oc = oc if isinstance(oc, dict) else {}
    line = _num(oc.get("exit_line")) if oc.get("known") else None
    if line is None:                                   # no exit line: still draw the levels, say why
        z = zones if isinstance(zones, dict) and zones.get("known") else {}
        if not (z.get("resistance") or z.get("support")):
            return None
        why = str(oc.get("why") or "no exit line saved for this stock yet")
        return {"call": "", "price": p, "line": None, "atr": None, "mode": "noline", "why": why, "entry": None, "stop": None,
                "targets": [], "risk": None, "ratios": [],
                "res": sorted((x for x in (z.get("resistance") or []) if _num(x.get("low")) is not None and x["low"] > p), key=lambda x: x["low"])[:2],
                "sup": sorted((x for x in (z.get("support") or []) if _num(x.get("high")) is not None and x["high"] < p), key=lambda x: -x["high"])[:2]}
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


def _strength(z: dict) -> str:
    return {"HIGH": "strong", "MEDIUM": "medium"}.get(str(z.get("grade")).upper(), "weak")


def _row(cls: str, price: str, title: str, sub: str = "", chip: str = "", grade: str = "") -> str:
    g = f' <em class="tl-g tl-g-{grade}">{grade.upper()}</em>' if grade else ""
    chip_html = f'<em class="tl-chip tl-c-{chip.split()[0].lower()}">{escape(chip)}</em>' if chip else ""
    sub_html = f"<small>{escape(sub)}</small>" if sub else ""
    return (f'<div class="tl-row tl-{cls}"><i></i><b>{price}</b><span>{escape(title)}{g}{sub_html}</span>{chip_html}</div>')


def _zone_price(z: dict) -> str:
    lo, hi = z["low"], z["high"]
    return f"{lo:,.2f}" if abs(hi - lo) < 0.005 else f"{lo:,.2f}-{hi:,.2f}"


def html(plan: dict | None) -> str:
    """ONE ladder: resistance 2 and 1, price (entry), stop, support 1 and 2, top to bottom, with the trade marks on the rows
    they belong to (profit 1 and 2 sit on the resistance rows, the stop is the exit line)."""
    if not plan:
        return ""
    p, line, atr = plan["price"], plan["line"], plan["atr"]
    buy = plan["mode"] == "buy"

    def sub(z, edge):
        n = swings_away(p, z[edge], atr)
        return f"{n:.1f} swings" if n is not None else ""

    items = []          # (price, row): the ladder is sorted by price, so the exit line sits above the price when the price is under it
    for i, z in enumerate(plan["res"], 1):
        chip = f"Profit {i}" if buy and i <= len(plan["targets"]) else ""
        items.append((float(z["high"]), _row("res", _zone_price(z), f"Resistance {i}", sub(z, "low"), chip, _strength(z))))
    items.append((p, _row("now", f"{p:,.2f}", "Price now", "", "Entry" if buy else "")))
    if line is not None:
        n_line = swings_away(p, line, atr)
        stop_sub = (f"{n_line:.1f} swings " + ("below" if p > line else "above")) if n_line is not None else ""
        items.append((line, _row("stop" if buy else "exit", f"{line:,.2f}", "Exit line", stop_sub, "Stop loss" if buy else "")))
    for i, z in enumerate(plan["sup"], 1):
        items.append((float(z["low"]), _row("sup", _zone_price(z), f"Support {i}", sub(z, "high"), "", _strength(z))))
    rows = [r for _, r in sorted(items, key=lambda x: -x[0])]
    if buy:
        head = ("BUY ZONE", "buy", "Close to the exit line and turning up.")
        foot = [f"Risk ${plan['risk']:,.2f} a share ({plan['risk'] / p:.1%})."]
        if plan["ratios"]:
            foot.append("Gain for each $1 risked: " + " · ".join(f"${r:.1f} at profit {i}" for i, r in enumerate(plan["ratios"], 1)) + ".")
            if plan["ratios"][0] < 1:
                foot.append("Profit 1 is closer than the risk.")
        else:
            foot.append("No resistance above to use as a target.")
    elif plan["mode"] == "noline":
        head = ("NO EXIT LINE", "wait", "No exit line yet: " + plan["why"].rstrip(".") + ". The levels below still apply.")
        foot = []
    elif plan["mode"] == "under":
        head = ("NO ENTRY NOW", "avoid", f"Under its exit line {line:,.2f}. Would change if it closes back above it.")
        foot = []
    else:
        n = swings_away(p, line, atr)
        far = f"{n:.1f} normal swings above its exit line" if n is not None else "Above its exit line"
        head = ("NO ENTRY YET", "wait", f"{far[0].upper() + far[1:]}: not a low-risk entry.")
        foot = []
    word, cls, subtext = head
    foot_html = f'<div class="tl-foot">{" ".join(escape(x) for x in foot)}</div>' if foot else ""
    return (f'<div class="rd-h"><span>Price ladder</span></div><div class="tl"><div class="tl-v tl-{cls}">{word}<small>{escape(subtext)}</small></div>'
            f'<div class="tl-rows">{"".join(rows)}</div>{foot_html}</div>')


CSS = """
.tl{background:var(--dz-surface);border:1px solid var(--dz-line);border-radius:14px;padding:12px;margin-bottom:10px}
.tl-v{border-left:4px solid var(--c);padding:7px 11px;border-radius:8px;background:var(--dz-raised);font-weight:800;color:var(--c);margin-bottom:6px}
.tl-v small{display:block;font-weight:400;color:var(--dz-soft);font-size:.78rem;margin-top:1px}
.tl-buy{--c:var(--dz-buy,#3dffa8)}.tl-wait{--c:var(--dz-watch,#ffb020)}.tl-avoid{--c:var(--dz-act,#ff697b)}
.tl-rows{position:relative;padding-left:16px}.tl-rows:before{content:'';position:absolute;left:4px;top:18px;bottom:18px;border-left:1px solid var(--dz-line)}
.tl-row{position:relative;display:grid;grid-template-columns:116px minmax(0,1fr) auto;gap:10px;align-items:center;padding:9px 0;border-bottom:1px dotted var(--dz-line);color:var(--c)}
.tl-row:last-child{border-bottom:0}.tl-row i{position:absolute;left:-15px;top:50%;width:7px;height:7px;margin-top:-4px;border-radius:50%;background:var(--c)}
.tl-row b{font-variant-numeric:tabular-nums;font-size:.9rem;white-space:nowrap}
.tl-row span{color:var(--dz-ink);font-size:.86rem;line-height:1.25;min-width:0}.tl-row span small{display:block;color:var(--dz-muted);font-size:.72rem}
.tl-res{--c:var(--dz-act,#ff697b)}.tl-sup{--c:var(--dz-buy,#3dffa8)}.tl-now{--c:#70b8ff;border-top:1px solid #70b8ff;border-bottom:1px solid #70b8ff}
.tl-stop,.tl-exit{--c:var(--dz-watch,#ffb020);border-bottom:1px dashed var(--dz-watch,#ffb020)}
.tl-chip{font-style:normal;font-size:.7rem;font-weight:800;padding:2px 8px;border-radius:999px;white-space:nowrap;color:var(--dz-on-c,#0b1118);background:var(--c)}
.tl-c-profit{background:var(--dz-buy,#3dffa8)}.tl-c-entry{background:#70b8ff}.tl-c-stop{background:var(--dz-act,#ff697b)}
.tl-g{font-style:normal;font-size:.62rem;font-weight:800;letter-spacing:.04em;padding:1px 6px;margin-left:6px;border-radius:999px;vertical-align:1px;border:1px solid var(--dz-muted);color:var(--dz-soft)}
.tl-g-strong{background:var(--dz-ink);color:var(--dz-bg,#0b1118);border-color:var(--dz-ink)}.tl-g-medium{border-color:var(--dz-ink);color:var(--dz-ink)}.tl-g-weak{opacity:.75}
.tl-foot{margin-top:8px;border-top:1px solid var(--dz-line);padding-top:8px;font-size:.78rem;color:var(--dz-soft)}
"""


def scaled_layout(rows: list[dict], height: int = 360) -> list[dict]:
    """Price positions and separate label slots, without moving the data marks.

    Equal prices share a y coordinate. Labels use ordered slots connected by
    leaders so tight/coincident levels remain readable at phone width.
    """
    import math
    valid=[]
    for row in rows:
        value=row.get('level')
        if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>0:
            valid.append(dict(row))
    valid.sort(key=lambda row:-row['level'])
    if not valid:
        return []
    low,high=valid[-1]['level'],valid[0]['level']
    for i,row in enumerate(valid):
        row['y']=height/2 if high==low else 20+(high-row['level'])/(high-low)*(height-40)
        row['label_y']=height/2 if len(valid)==1 else 20+i/(len(valid)-1)*(height-40)
    return valid


def scaled_html(rows: list[dict], price=None) -> str:
    """Tape ladder: the exact existing levels on a proportional price axis."""
    height=max(180,len(rows)*76)
    layout=scaled_layout(rows,height)
    if not layout:
        return '<div class="ts"><h3>Price ladder</h3><small>Levels unknown: no usable price levels were saved.</small></div>'
    lines=[];labels=[]
    for row in layout:
        val=row['level'];now=row.get('tone')=='now'
        tone='now' if now else 'exit' if row.get('tone')=='exit' else 'level'
        gap=f'{(val/price-1)*100:+.1f}%' if isinstance(price,(int,float)) and price>0 and not now else ''
        label='Chart exit (Exit line)' if row['label']=='Exit line' else row['label']
        lines.append(f'<path d="M 144 {row["y"]:.2f} L 208 {row["label_y"]:.2f}" class="tsl-{tone}"/>'
                     f'<circle cx="144" cy="{row["y"]:.2f}" r="3" class="tsl-{tone}"/>')
        labels.append(f'<div class="tsl-label tsl-{tone}" style="top:{row["label_y"]/height*100:.3f}%" data-price="{val:g}" data-y="{row["y"]:.3f}">'
                      f'<div><b>{escape(label)}</b><strong>{val:,.2f} <small>{gap}</small></strong></div><small>{escape(row.get("note") or "")}</small></div>')
    return (f'<style>{TAPE_CSS}</style><div class="ts"><h3>Price ladder</h3><div class="tsl" style="height:{height}px">'
            f'<svg viewBox="0 0 320 {height}" role="img" aria-label="Saved price levels drawn to scale"><title>Dots follow the price scale; labels are staggered for readability.</title>'
            f'<line x1="144" x2="144" y1="20" y2="{height-20}"/>{"".join(lines)}</svg><div>{"".join(labels)}</div></div></div>')


TAPE_CSS='''
.tsl{position:relative;margin:24px 0;min-width:0}
.tsl svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible;pointer-events:none}.tsl svg line,.tsl svg path{stroke:var(--dz-line);stroke-width:1;fill:none}.tsl svg circle{fill:var(--dz-soft)}
.tsl svg .tsl-now{stroke:var(--dz-ink);fill:var(--dz-ink)}.tsl svg .tsl-exit{stroke:var(--dz-loss);fill:var(--dz-loss)}
.tsl>div{position:relative;height:100%;min-width:0}.tsl-label{position:absolute;left:0;right:0;transform:translateY(-50%);border-top:1px solid var(--dz-line);padding:4px 0;font-size:12px}
.tsl-label>div{display:flex;justify-content:space-between;gap:8px}.tsl-label b{font-weight:500;max-width:40%}.tsl-label strong{font-size:14px;white-space:nowrap}
.tsl-label>small{display:block;max-width:40%;color:var(--dz-soft);font-size:11px;line-height:1.25}.tsl-label strong small{font-size:11px;font-weight:400;color:var(--dz-soft)}
.tsl-label.tsl-now{border-top:2px solid var(--dz-ink)}.tsl-label.tsl-exit{border-top:1px dashed var(--dz-loss)}
'''
