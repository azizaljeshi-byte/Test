"""The Debt and cash flow card on Details: one headline, cash against debt, four tiles and eight quarters of cash flow.
Display only: it reads `research["debt_cash"]` (see `debtcash.build`) and changes no score, call, plan or alert.
A figure that was not found says "not available" and why; it is never shown as zero.
"""
from __future__ import annotations

from html import escape

from . import ui

LOW_DE, HIGH_DE = 0.5, 1.5
RUNWAY_WARN = 18          # months of cash at the recent burn below which the card turns red


def _m(v) -> str:
    return "not available" if v is None else ui.money(v)


def _band(v, cuts: list[tuple[float, str, str]], last: tuple[str, str]) -> tuple[str, str]:
    for limit, word, cls in cuts:
        if v < limit:
            return word, cls
    return last


def tiles(d: dict) -> list[tuple[str, str, str, str]]:
    """(label, value, class, note) four tiles: net cash or debt, debt to equity, current ratio, interest cover."""
    cash, debt = d.get("cash"), d.get("debt")
    if cash is not None and debt is not None:
        net = cash - debt
        t1 = ("Net cash" if net >= 0 else "Net debt", ("+" if net >= 0 else "−") + ui.money(abs(net)), "up" if net >= 0 else "dn", "cash minus debt")
    else:
        t1 = ("Net cash", "n/a", "mid", "cash or debt not available")
    de = d.get("debt_to_equity")
    if de is None:
        t2 = ("Debt to equity", "n/a", "mid", "not available")
    else:
        w, c = _band(de, [(LOW_DE, "low", "up"), (HIGH_DE, "moderate", "mid")], ("high", "dn"))
        t2 = ("Debt to equity", f"{de:.1f}", c, w)
    cr = d.get("current_ratio")
    if cr is None:
        t3 = ("Current ratio", "n/a", "mid", "not available")
    else:
        w, c = _band(cr, [(1.0, "weak", "dn"), (1.2, "thin", "mid"), (2.0, "fine", "up")], ("strong", "up"))
        t3 = ("Current ratio", f"{cr:.1f}", c, w)
    ebit, interest = d.get("ebit_ttm"), d.get("interest_ttm")
    if ebit is not None and ebit <= 0:
        t4 = ("Interest cover", "n/a", "mid", "no operating profit")
    elif ebit is None or interest is None or interest <= 0:
        t4 = ("Interest cover", "n/a", "mid", "interest not reported" if interest is None else "no interest cost")
    else:
        x = ebit / interest
        w, c = _band(x, [(1.5, "at risk", "dn"), (3.0, "thin", "mid"), (8.0, "fine", "up")], ("very safe", "up"))
        t4 = ("Interest cover", f"{x:.0f}x", c, w)
    return [t1, t2, t3, t4]


def quarters(d: dict) -> list[dict]:
    """[{end, cfo, capex, fcf}] oldest first, only quarters with an operating cash flow figure. A missing capex is 0 spent
    only when the company reports no capex line at all; the line says so."""
    capex = {q["end"]: abs(q["value"]) for q in d.get("capex_q") or []}
    rows = [{"end": q["end"], "cfo": q["value"], "capex": capex.get(q["end"], 0.0),
             "fcf": q["value"] - capex.get(q["end"], 0.0)} for q in (d.get("cfo_q") or [])]
    return rows[::-1]


def headline(d: dict, qs: list[dict]) -> tuple[str, str]:
    """(text, good|bad|careful) one sentence from cash, debt and free cash flow."""
    cash, debt, fcf = d.get("cash"), d.get("debt"), d.get("fcf_ttm")
    if cash is None and debt is None and fcf is None:
        return "Debt and cash figures are not available for this stock yet.", "careful"
    if fcf is not None and fcf < 0:
        if cash is not None:
            months = cash / (-fcf / 12)
            txt = f"Burning cash. Cash covers about {months:.0f} months at the recent pace"
            txt += ", and debt is larger than cash." if debt is not None and debt > cash else "."
            return txt, "bad" if months < RUNWAY_WARN else "careful"
        return "Burning cash, and the cash balance is not available.", "careful"
    makes = ""
    if len(qs) >= 4 and all(q["fcf"] > 0 for q in qs[-4:]):
        makes = ", and it made cash in each of the last 4 quarters"
    elif fcf is not None and fcf > 0:
        makes = ", and it makes cash over the year"
    if cash is not None and debt is not None:
        if debt <= 0:
            return f"No debt reported{makes}.", "good"
        x = cash / debt
        if x >= 1:
            return f"Cash covers its debt {x:.1f} times{makes}.", "good"
        return f"Cash covers {x * 100:.0f}% of its debt{makes}.", "good" if fcf and fcf > 0 else "careful"
    return f"Only part of the balance sheet is available{makes}.", "careful"


def _label(end: str) -> str:
    y, m = end[:4], int(end[5:7])
    return f"{('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec').split()[m - 1]} {y[2:]}"


def chart(qs: list[dict], w: int = 340, h: int = 120) -> str:
    vals = [v for q in qs for v in (q["cfo"], -q["capex"], q["fcf"])]
    top, bot = max(max(vals), 0) * 1.1, min(min(vals), 0) * 1.1
    span = (top - bot) or 1
    y = lambda v: 8 + (top - v) / span * (h - 24)
    zero = y(0)
    gw = w / len(qs)
    bw = gw / 4.2
    out = [f'<svg viewBox="0 0 {w} {h + 14}" width="100%" role="img" aria-label="Cash flow by quarter">',
           f'<line x1="0" x2="{w}" y1="{zero:.1f}" y2="{zero:.1f}" stroke="var(--dz-line)"/>']
    for i, q in enumerate(qs):
        for j, (v, col) in enumerate(((q["cfo"], "var(--dz-calm)"), (-q["capex"], "var(--dz-watch)"), (q["fcf"], "var(--dz-buy)" if q["fcf"] >= 0 else "var(--dz-act)"))):
            x = i * gw + bw * 0.6 + j * bw
            top_y = y(max(v, 0))
            out.append(f'<rect x="{x:.1f}" y="{(top_y if v >= 0 else zero):.1f}" width="{bw * 0.9:.1f}" '
                       f'height="{max(abs(y(v) - zero), 1):.1f}" rx="2" fill="{col}"/>')
        out.append(f'<text x="{i * gw + gw / 2:.1f}" y="{h + 10}" text-anchor="middle" font-size="8" fill="var(--dz-muted)">{_label(q["end"])}</text>')
    return "".join(out) + "</svg>"


def html(snap: dict) -> str:
    d = ((snap.get("payload") or {}).get("research") or {}).get("debt_cash")
    if not d:
        return (f'<style>{CSS}</style><div class="dc"><div class="dc-h">Debt and cash flow</div>'
                '<p class="dc-ft">Not read yet. It appears after the next full scan.</p></div>')
    qs = quarters(d)
    text, kind = headline(d, qs)
    icon = {"good": "▲", "bad": "▼", "careful": "!"}[kind]
    cash, debt = d.get("cash"), d.get("debt")
    mx = max(cash or 0, debt or 0) or 1
    bars = "".join(f'<div class="dc-pr"><span>{lab}</span><div>{f"<i class={cls} style=width:{v / mx * 100:.0f}%></i>" if v is not None else ""}</div>'
                   f'<b>{_m(v)}</b></div>' for lab, v, cls in (("Cash", cash, "c"), ("Debt", debt, "d")))
    tl = "".join(f'<div class="dc-tl"><small>{escape(a)}</small><b>{escape(b)}</b><em class="{c}">{escape(n)}</em></div>' for a, b, c, n in tiles(d))
    run = ""
    fcf = d.get("fcf_ttm")
    if fcf is not None and fcf < 0 and cash is not None:
        run = (f'<div class="dc-run"><small>Cash runway at the recent burn</small><b>about {cash / (-fcf / 12):.0f} months</b></div>')
    cf = ""
    if len(qs) >= 2:
        pos = sum(1 for q in qs if q["fcf"] > 0)
        cf = (f'<div class="dc-sec">Cash flow, last {len(qs)} quarters</div>{chart(qs)}'
              '<div class="dc-lg"><span><i style="background:var(--dz-calm)"></i>Operating</span>'
              '<span><i style="background:var(--dz-watch)"></i>Capex</span><span><i style="background:var(--dz-buy)"></i>Free cash flow</span></div>'
              f'<p class="dc-ft">Free cash flow was positive in {pos} of {len(qs)} quarters.</p>')
    else:
        cf = '<p class="dc-ft">Quarter-by-quarter cash flow is not available for this stock.</p>'
    src = f'Source: {escape(d["source"])}' + (f", as of {escape(d['as_of'])}" if d.get("as_of") else "") + "." if d.get("source") else ""
    return (f'<style>{CSS}</style><div class="dc"><div class="dc-h">Debt and cash flow</div>'
            f'<div class="dc-hl {kind}"><i>{icon}</i><p>{escape(text)}</p></div>{bars}<div class="dc-tls">{tl}</div>{run}{cf}'
            f'<p class="dc-src">{src}</p></div>')


CSS = """
.dc{background:var(--dz-surface,#121a25);border:1px solid var(--dz-line,#243041);border-radius:16px;padding:14px;margin:12px 0;color:var(--dz-ink,#e9eef5)}
.dc-h{font-size:1.1rem;font-weight:800}
.dc-hl{display:flex;gap:10px;margin:10px 0;padding:10px;border-radius:12px;border:1px solid var(--dz-line,#243041)}.dc-hl p{margin:0;font-size:.88rem;line-height:1.4}
.dc-hl i{font-style:normal;flex:none;width:22px;height:22px;border-radius:6px;display:grid;place-items:center;font-weight:800;color:#111;font-size:.8rem}
.dc-hl.good{border-color:var(--dz-buy,#7be3a8);background:color-mix(in srgb,var(--dz-buy,#7be3a8) 12%,transparent)}.dc-hl.good i{background:var(--dz-buy,#7be3a8)}
.dc-hl.bad{border-color:var(--dz-act,#ff7a7a);background:color-mix(in srgb,var(--dz-act,#ff7a7a) 12%,transparent)}.dc-hl.bad i{background:var(--dz-act,#ff7a7a)}
.dc-hl.careful{border-color:var(--dz-watch,#ffc267);background:color-mix(in srgb,var(--dz-watch,#ffc267) 12%,transparent)}.dc-hl.careful i{background:var(--dz-watch,#ffc267)}
.dc-pr{display:grid;grid-template-columns:44px 1fr 86px;gap:8px;align-items:center;margin:6px 0;font-size:.82rem}
.dc-pr>div{height:12px;background:color-mix(in srgb,var(--dz-ink,#e9eef5) 8%,transparent);border-radius:6px;overflow:hidden}.dc-pr i{display:block;height:100%;border-radius:6px}
.dc-pr .c{background:var(--dz-buy,#7be3a8)}.dc-pr .d{background:var(--dz-act,#ff7a7a)}.dc-pr b{text-align:right;font-size:.8rem}
.dc-tls{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px}.dc-tl{background:color-mix(in srgb,var(--dz-ink,#e9eef5) 6%,transparent);border-radius:10px;padding:8px}
.dc-tl small{display:block;font-size:.64rem;color:var(--dz-muted,#8b95a7);text-transform:uppercase;letter-spacing:.04em}.dc-tl b{font-size:1.05rem}
.dc-tl em{font-style:normal;font-size:.7rem;display:block;color:var(--dz-muted,#8b95a7)}.dc-tl em.up{color:var(--dz-buy,#7be3a8)}.dc-tl em.dn{color:var(--dz-act,#ff7a7a)}.dc-tl em.mid{color:var(--dz-watch,#ffc267)}
.dc-run{margin-top:8px;padding:8px 10px;border-radius:10px;background:color-mix(in srgb,var(--dz-watch,#ffc267) 14%,transparent);border:1px solid var(--dz-watch,#ffc267)}
.dc-run small{display:block;font-size:.66rem;color:var(--dz-muted,#8b95a7)}.dc-run b{font-size:1.1rem}
.dc-sec{font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;color:var(--dz-soft,#9aa4b2);font-weight:800;margin:14px 0 4px}
.dc-lg{display:flex;gap:12px;font-size:.68rem;color:var(--dz-muted,#8b95a7);margin-top:2px}.dc-lg i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:4px}
.dc-ft{font-size:.76rem;color:var(--dz-muted,#8b95a7);margin:8px 0 0}.dc-src{font-size:.66rem;color:var(--dz-muted,#8b95a7);margin:6px 0 0}
"""
