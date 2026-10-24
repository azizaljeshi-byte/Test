"""The top of the Details page: one decision block, and the WHY, CHANGED and WATCH NEXT lines with an icon on each.
Display only: it reads the call, the chart status, the plan and the score that are already on the snapshot, and changes none.

The decision block puts the call first and then every source that bears on it, each labelled with its job, so two numbers
never read as two answers:
  - the call (from the Day Board) and how many checks agree;
  - the quality score (fundamentals and technicals) and its label, shown as a rating, not as an action;
  - the chart status and its levels (daily closes only);
  - the exit ladder for a stock you own: the chart's warning exit (a daily close below the support floor) and the plan's hard
    stop, in the order price would reach them.
"""
from __future__ import annotations

from html import escape

from . import dayboard, design, ui
from .ui import nan

BAD_CHART = ("weakening", "testing_support", "breakdown", "deep_breakdown")
GOOD_SCORE = ("STRONG HOLD", "HOLD", "OPPORTUNITY - ADD", "BUY SETUP")


def _usd(v) -> str:
    return "n/a" if v is None or nan(v) else f"${v:,.2f}"


def exit_ladder(snap: dict) -> list[tuple[str, float, str]]:
    """(label, price, what it does) for an owned stock, highest price first (the one price reaches first when falling)."""
    p = snap["payload"]
    if p.get("watchlist"):
        return []
    rows = []
    ps = ui.price_status(snap) or {}
    lv = ps.get("levels") or {}
    code = ps.get("code")
    if ps.get("floor_known") and lv.get("support_low") and code in BAD_CHART + ("pullback", "strong_uptrend", "record_high"):
        if code in ("breakdown", "deep_breakdown"):
            rows.append(("Chart exit", float(lv["support_low"]), "already closed below it"))
        else:
            rows.append(("Chart exit", float(lv["support_low"]), "a daily close below it is the exit"))
    stop = (p.get("plan") or {}).get("stop")
    if stop is not None and not nan(stop):
        rows.append(("Plan stop", float(stop), "protects against a fall straight through"))
    return sorted(rows, key=lambda r: -r[1])


def decision(snap: dict) -> str:
    a = dayboard.assess(snap)
    cls = dayboard.SPOT[a["word"]]
    price, _ = ui._price(snap)
    ps = ui.price_status(snap) or {}
    sure = f'<span class="dt-sure">{a["sure"][0]} of {a["sure"][1]} checks agree</span>' if a["sure"] else \
        f'<span class="dt-sure">{escape(a["why"] or "no usable signal")}</span>'
    verdict = snap["verdict"].title()
    lines = [f'<div class="dt-k">Score</div><div class="dt-v">{snap["composite"]:.0f} · {escape(verdict)}'
             f'<small>quality rating, not the decision</small></div>']
    if ps.get("code") and ps["code"] != "unknown":
        lines.append(f'<div class="dt-k">Chart</div><div class="dt-v">{escape(ps.get("label") or ps["code"]).title()}'
                     f'<small>judged on daily closes</small></div>')
    ladder = exit_ladder(snap)
    for label, level, note in ladder:
        gap = (level / price - 1) * 100 if price and not nan(price) else None
        gap_txt = f" ({gap:+.1f}%)" if gap is not None else ""
        lines.append(f'<div class="dt-k">{escape(label)}</div><div class="dt-v">{_usd(level)}{gap_txt}<small>{escape(note)}</small></div>')
    clash = ""
    if snap["verdict"] in GOOD_SCORE and ps.get("code") in BAD_CHART:
        clash = design.icon_line("careful", f'The score is {snap["composite"]:.0f} ({verdict}), but the chart reads '
                                 f'{(ps.get("label") or ps["code"]).lower()}. Both are shown; watch the exit lines.')
    return (f'<style>{CSS}</style><div class="dt dz-{cls}"><div class="dt-top"><div><b class="dt-tk">{escape(snap["ticker"])}</b>'
            f'<span class="dt-px">{_usd(price)}</span></div>'
            f'<span class="dz-call dz-{cls}">{escape(dayboard._words(snap, a))}</span></div>{sure}'
            f'<div class="dt-grid">{"".join(lines)}</div>{clash}</div>')


# ---------------------------------------------------------------- icons on the WHY, CHANGED and WATCH NEXT lines

def line_kind(section: str, text: str) -> str:
    """good, bad, careful or info for one line. A line that mixes good and bad takes the worse side."""
    t = text.lower()
    if t.startswith("risk:"):
        return "bad"
    if t.startswith("opportunity:"):
        return "good"
    if section == "why":
        if t.startswith("fundamentals are"):
            head = t.split(":")[0]
            return "bad" if "weak" in head else "careful" if ("mixed" in head or "unavailable" in head) else "good"
        if t.startswith("price trend is"):
            kind = "bad" if "trend is down" in t else "careful" if "mixed" in t else "good"
            if kind == "good" and ("overbought" in t or "oversold" in t):
                kind = "careful"
            return kind
        if "underperformed" in t:
            return "bad"
        if "outperformed" in t:
            return "good"
    if section == "changed":
        if t.startswith(("first scan", "no meaningful", "cleared:", "new:")):
            return "info"
        if "fell" in t or "price down" in t:
            return "bad"
        if "rose" in t or "price up" in t:
            return "good"
        if "verdict moved" in t:
            return "careful"
    if section == "watch":
        if "has been hit" in t:
            return "bad"
        if t.startswith(("earnings", "losing the 200-day")) or "sold short" in t:
            return "careful"
    return "info"


def brief_html(b: dict) -> str:
    """The headline and the three lists, one icon per line, with the key."""
    def block(title: str, key: str) -> str:
        items = b.get(key) or []
        if not items:
            return ""
        return f'<div class="dt-h">{title}</div>' + "".join(design.icon_line(line_kind(key, x), x) for x in items)
    return (f'<style>{CSS}</style><div class="dt-brief"><div class="dt-hl">{escape(b["headline"])}</div>{design.icon_key()}'
            f'{block("Why", "why")}{block("Changed", "changed")}{block("Watch next", "watch")}</div>')


CSS = """
.dt{border-radius:16px;padding:14px;margin:6px 0 12px;background:color-mix(in srgb,var(--dz-c) 9%,var(--dz-surface,#121a25));
  border:1px solid color-mix(in srgb,var(--dz-c) 32%,var(--dz-line,#243041));border-left:5px solid var(--dz-c);color:var(--dz-ink,#e9eef5)}
.dt-top{display:flex;justify-content:space-between;align-items:center;gap:10px}
.dt-tk{font-size:1.3rem;margin-right:10px}.dt-px{font-size:1.05rem;font-variant-numeric:tabular-nums}
.dt-sure{display:block;font-size:.78rem;color:var(--dz-muted,#8b95a7);margin:8px 0 2px}
.dt-grid{display:grid;grid-template-columns:78px 1fr;gap:8px 10px;margin-top:10px;padding-top:10px;border-top:1px solid var(--dz-line,#243041)}
.dt-k{font-size:.72rem;color:var(--dz-muted,#8b95a7);text-transform:uppercase;letter-spacing:.05em;padding-top:2px}
.dt-v{font-weight:700}.dt-v small{display:block;font-weight:400;font-size:.72rem;color:var(--dz-muted,#8b95a7)}
.dt .dz-li{margin:12px 0 0}
.dt-brief{margin:8px 0}.dt-hl{font-size:1.02rem;font-weight:700;margin:4px 2px 8px;color:var(--dz-ink,#e9eef5)}
.dt-h{font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;color:var(--dz-muted,#8b95a7);margin:14px 2px 6px}
"""
