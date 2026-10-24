"""The Fundamentals block on the Details page: a rating, the four pillars, each measure as one plain line with an icon and its
source, the last five quarters of revenue with margins, and expected against actual profit per share.

Display only. It reads the fundamental metrics, score and research already on the snapshot. The words (good, careful, bad) use
the same bands as the score in `fundamental.py` so a line never disagrees with the number above it; nothing here changes the
score. A missing figure is left out and counted, never shown as zero.
"""
from __future__ import annotations

from html import escape

from . import briefing, design, ui
from .ui import nan

MIN_COVERAGE = 30       # same as engine.MIN_FUND_COVERAGE: under this the score is unknown

# (key, label, bands [(upper limit, points)], plain words for good / careful / bad, format)
MEASURES = [
    ("revenue_growth", "Revenue growth", [(-0.05, 0), (0.0, 2), (0.05, 4), (0.10, 6), (0.20, 8), (1e9, 10)],
     ("Sales are growing fast", "Sales are growing slowly", "Sales are shrinking"), "pct"),
    ("earnings_growth", "Profit growth", [(-0.15, 0), (0.0, 3), (0.10, 6), (0.25, 8), (1e9, 10)],
     ("Profit is growing fast", "Profit is growing slowly", "Profit is falling"), "pct"),
    ("operating_margin", "Operating margin", [(0.0, 0), (0.08, 3), (0.15, 6), (0.25, 8), (1e9, 10)],
     ("Keeps a healthy share of each sale", "Thin profit on each sale", "Loses money on operations"), "pct1"),
    ("roe", "Return on equity", [(0.0, 0), (0.08, 3), (0.15, 6), (0.25, 8), (1e9, 10)],
     ("Uses owners' money well", "Average use of owners' money", "Poor use of owners' money"), "pct1"),
    ("debt_to_equity", "Debt to equity", [(0.3, 10), (0.8, 8), (1.5, 5), (2.5, 2), (1e9, 0)],
     ("Little debt", "Some debt", "Heavy debt"), "x"),
    ("current_ratio", "Current ratio", [(0.8, 0), (1.0, 3), (1.5, 7), (1e9, 10)],
     ("Can pay its near-term bills", "Near-term bills are covered, with little room", "May struggle with near-term bills"), "x"),
    ("pe", "P/E", [(12, 10), (18, 8), (25, 6), (35, 4), (50, 2), (1e9, 0)],
     ("Priced low for its earnings", "Priced fairly to high", "Priced high for its earnings"), "plain"),
    ("peg", "PEG", [(1.0, 10), (1.5, 7), (2.0, 5), (3.0, 2), (1e9, 0)],
     ("Growth at a fair price", "Growth is priced in", "Paying a lot for growth"), "plain"),
    ("analyst_upside", "Gap to analyst target", [(-0.10, 0), (0.0, 3), (0.10, 5), (0.20, 7), (1e9, 10)],
     ("Analysts see room to rise", "Analysts see little upside", "Trading above the analyst target"), "pct"),
]
PILLARS = (("growth", "Growth"), ("quality", "Quality"), ("balance", "Balance sheet"), ("valuation", "Valuation"))


def _points(value: float, bands) -> int:
    for limit, pts in bands:
        if value <= limit:
            return pts
    return bands[-1][1]


def _fmt(v: float, how: str) -> str:
    return {"pct": f"{v * 100:+.0f}%", "pct1": f"{v * 100:.0f}%", "x": f"{v:.1f}×", "plain": f"{v:.1f}"}[how]


def measure_lines(f: dict) -> tuple[list[tuple[str, str]], int]:
    """([(kind, text)], how many of the measures had a figure). A non-positive P/E or PEG is not scored, so it is left out."""
    out, got = [], 0
    for key, label, bands, words, how in MEASURES:
        v = f.get(key)
        if v is None or nan(v) or (key in ("pe", "peg") and v <= 0):
            continue
        got += 1
        pts = _points(v, bands)
        i = 0 if pts >= 7 else 1 if pts >= 4 else 2
        out.append((("good", "careful", "bad")[i], f"{label}: {_fmt(v, how)}. {words[i]}."))
    fcf = f.get("free_cash_flow")
    if fcf is not None and not nan(fcf):
        got += 1
        out.append(("good", "Free cash flow: positive. The business makes more cash than it spends.") if fcf > 0 else
                   ("bad", "Free cash flow: negative. The business is burning cash."))
    return out, got


def _revenue(rq: list[dict]) -> str:
    rows = [r for r in reversed(rq[:5]) if r.get("revenue")]
    if len(rows) < 2:
        return ""
    top = max(r["revenue"] for r in rows)
    bars = ""
    for k, r in enumerate(rows):
        chg = f'{(r["revenue"] / rows[k - 1]["revenue"] - 1) * 100:+.0f}%' if k else ""
        bars += (f'<div><b>{ui.money(r["revenue"])}</b><i style="height:{r["revenue"] / top * 110:.0f}px"></i>'
                 f'<em>{escape(str(r["period"])[:7])}</em><small>{chg}</small></div>')
    def margins(key, label):
        cells = "".join(f'<u style="--h:{max(0, min(100, (r.get(key) or 0) * 100)):.0f}">'
                        f'{"n/a" if r.get(key) is None else f"{r[key] * 100:.0f}%"}</u>' for r in rows)
        return f'<div class="fv-mr"><span>{label}</span>{cells}</div>'
    return (f'<div class="fv-k">Revenue, last {len(rows)} quarters</div><div class="fv-rv">{bars}</div>'
            + margins("gross_margin", "Gross margin") + margins("op_margin", "Operating margin"))


def _usd(v: float) -> str:
    return f"-${abs(v):.2f}" if v < 0 else f"${v:.2f}"


def _eps(quarters: list[dict]) -> str:
    rows = [q for q in quarters[:4] if q.get("eps_actual") is not None and q.get("eps_estimate") is not None][::-1]
    if not rows:
        return ""
    top = max(max(abs(q["eps_actual"]), abs(q["eps_estimate"])) for q in rows) or 1
    out = ""
    for q in rows:
        e, a = q["eps_estimate"], q["eps_actual"]
        res = "BEAT" if (a - e) / (abs(e) or 1) > 0.02 else "MISS" if (a - e) / (abs(e) or 1) < -0.02 else "IN LINE"
        cls = {"BEAT": "b", "MISS": "m"}.get(res, "l")
        mv = q.get("reaction")
        move = "" if mv is None or nan(mv) else f'<em class="{"up" if mv >= 0 else "dn"}">{mv * 100:+.0f}%</em>'
        out += (f'<div class="fv-eq"><span>{escape(str(q["quarter"])[:7])}</span><div class="fv-pair">'
                f'<i class="e" style="width:{max(abs(e) / top * 100, 3):.0f}%"></i><i class="a" style="width:{max(abs(a) / top * 100, 3):.0f}%"></i></div>'
                f'<b class="fv-tag {cls}">{res}</b><small>{_usd(e)} → {_usd(a)}</small>{move}</div>')
    return ('<div class="fv-k">Profit per share: expected vs actual</div><div class="fv-lg"><span><u class="e"></u>Expected</span>'
            f'<span><u class="a"></u>Actual</span><span class="mv">Share move on report day</span></div>{out}')


AREA_OF = {"growth": "Growth", "quality": "Profitability", "balance": "Balance sheet", "valuation": "Valuation"}
SHORT = {"Profitability": "Profit", "Balance sheet": "Balance", "Momentum": "Chart", "Earnings delivery": "Earnings", "Smart money": "Insiders"}
TONE = {"A": "good", "B": "good", "C": "neutral", "D": "weak", "F": "bad"}


def _company(o: dict) -> str:
    site = f' · <a href="{escape(o["website"])}" target="_blank">website</a>' if o.get("website") else ""
    about = ""
    summary = o.get("summary") or ""
    if summary:
        about = f'<details class="fv-about"><summary>About the company</summary><p>{escape(summary)}</p></details>'
    return f'<div class="fv-co"><b>{escape(o["name"])}</b><small>{escape(o["intro"])}{site}</small>{about}</div>'


def _chips(grades: list[dict]) -> str:
    chips = "".join(f'<span class="fv-ch"><b class="{TONE.get(g["grade"], "neutral")}">{escape(g["grade"])}</b>'
                    f'{escape(SHORT.get(g["area"], g["area"]))}</span>' for g in grades)
    return ('<div class="fv-k">Report card</div>' f'<div class="fv-chs">{chips}</div>'
            '<small class="fv-ft">Chart and Insiders come from other pages; they are not part of the fundamentals rating.</small>')


def _delivery(earn: dict) -> str:
    qs = [q for q in (earn.get("quarters") or [])[:4] if q.get("eps_actual") is not None and q.get("eps_estimate") is not None]
    if not qs:
        return ""
    beats = [q["eps_actual"] > q["eps_estimate"] for q in qs][::-1]
    dots = "".join(f'<i class="{"y" if b else "m"}"></i>' for b in beats)
    n = sum(beats)
    move = (f'Shares moved about {earn["avg_move"] * 100:.0f}% on report days.'
            if earn.get("avg_move") is not None and not nan(earn["avg_move"]) else "")
    return (f'<div class="fv-k">Earnings delivery</div><div class="fv-bt"><div class="fv-dots">{dots}</div>'
            f'<b class="{"up" if n == len(qs) else "dn" if n == 0 else ""}">Beat {n} of the last {len(qs)}</b></div>'
            + (f'<small class="fv-ft">{move}</small>' if move else ""))


def _smart(sm: dict) -> str:
    if not sm:
        return ""
    out = []
    if sm.get("buyers_90d"):
        out.append(("good", f"Insiders: {sm['buyers_90d']} buyer{'s' if sm['buyers_90d'] != 1 else ''} in 90 days."))
    elif sm.get("sellers_90d", 0) >= 3:
        out.append(("bad", f"Insiders: {sm['sellers_90d']} sold in 90 days, no buying."))
    sp = sm.get("short_pct_float")
    if sp is not None and not nan(sp):
        out.append(("bad" if sp >= 0.15 else "careful" if sp >= 0.08 else "info",
                    f"{sp * 100:.0f}% of shares are sold short." + (" Expect sharp moves both ways." if sp >= 0.15 else "")))
    ip = sm.get("institution_pct")
    if ip is not None and not nan(ip):
        out.append(("info", f"Institutions own {ip * 100:.0f}%."))
    return ('<div class="fv-k">Insiders and short sellers</div>' + "".join(design.icon_line(k, t) for k, t in out)) if out else ""


def fundamentals(snap: dict) -> str:
    p = snap["payload"]
    f = p.get("fundamental") or {}
    research = p.get("research") or {}
    earn = research.get("earnings") or {}
    lines, got = measure_lines(f)
    try:
        o = briefing.overview(snap)
    except (KeyError, TypeError, ValueError):
        o = None
    letter = {g["area"]: g["grade"] for g in (o or {}).get("grades", [])}
    total = len(MEASURES) + 1
    source = f.get("source") or "Yahoo"
    if f.get("available") is False or (f.get("coverage") or 0) < MIN_COVERAGE:
        head = (f'<div class="fv-hd">{design.rating("Fundamentals", None)}<small>unknown: only {got} of {total} measures could be read '
                f'(Yahoo and the SEC filings did not return enough). Never counted as zero.</small></div>')
        pillars = ""
    else:
        head = (f'<div class="fv-hd">{design.rating("Fundamentals", design.fundamentals_rating(snap.get("fundamental_score")))}'
                f'<small>based on {got} of {total} measures · {escape(source)}</small></div>')
        tiles = ""
        for key, name in PILLARS:
            v = f.get(f"pillar_{key}")
            r = design.fundamentals_rating(v)
            lt = letter.get(AREA_OF[key])
            badge = f'<u class="g {TONE.get(lt, "neutral")}">{lt}</u>' if lt and lt != "?" else ""
            tiles += (f'<div class="fv-pl"><em>{name}</em>{badge}' + (
                f'<b>{v:.0f}</b><span style="color:var(--dz-{design.STEP_KEYS[r[1]]})">{r[0]}</span>{design.pips(r[1])}'
                if r else '<b>n/a</b><span>not enough data</span>') + '</div>')
        pillars = f'<div class="fv-pls">{tiles}</div>'
    body = (_chips(o["grades"]) if o and o.get("grades") else "") + design.icon_key() + "".join(design.icon_line(k, t) for k, t in lines)
    rq = (earn.get("revenue_q") or [])
    gm = rq[0].get("gross_margin") if rq else None
    body += (design.icon_line("info", f"Gross margin: {gm * 100:.0f}% in the last quarter.") if gm is not None and not nan(gm) else "")
    body += _revenue(rq) + _delivery(earn) + _eps(earn.get("quarters") or []) + _smart(research.get("smart_money") or {})
    if not (lines or rq or earn.get("quarters")):
        body = '<div class="fv-note">No fundamentals could be read for this stock right now.</div>'
    return f'<style>{CSS}</style><div class="fv"><div class="fv-card">{_company(o) if o else ""}{head}{pillars}{body}</div></div>'


CSS = """
.fv{color:var(--dz-ink,#e9eef5)}.fv-card{background:var(--dz-surface,#121a25);border:1px solid var(--dz-line,#243041);border-radius:16px;padding:14px}
.fv-hd .dz-rate b{font-size:1.1rem}.fv-hd small{display:block;color:var(--dz-muted,#8b95a7);font-size:.72rem;margin-top:6px}
.fv-pls{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}
.fv-pl{background:color-mix(in srgb,var(--dz-ink,#e9eef5) 5%,transparent);border-radius:12px;padding:9px 10px}
.fv-pl em{display:block;font-size:.66rem;color:var(--dz-muted,#8b95a7);font-style:normal}.fv-pl b{font-size:1.2rem;margin-right:8px}.fv-pl span{font-size:.74rem}
.fv-pl .dz-pips{display:flex;margin-top:6px}
.fv-k{font-size:.66rem;letter-spacing:.08em;text-transform:uppercase;color:var(--dz-muted,#8b95a7);margin:20px 0 8px}
.fv-rv{display:flex;gap:8px;align-items:flex-end;height:178px}.fv-rv div{flex:1;text-align:center;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:3px}
.fv-rv i{display:block;width:100%;background:var(--dz-calm,#8da2d6);border-radius:6px 6px 0 0}.fv-rv b{font-size:.7rem}
.fv-rv em{font-size:.64rem;color:var(--dz-muted,#8b95a7);font-style:normal}.fv-rv small{font-size:.64rem;color:var(--dz-buy,#3fd08d);height:12px}
.fv-mr{display:flex;align-items:center;gap:6px;margin-top:8px}.fv-mr span{width:96px;font-size:.7rem;color:var(--dz-muted,#8b95a7)}
.fv-mr u{flex:1;text-align:center;text-decoration:none;font-size:.72rem;padding:3px 0;border-radius:6px;
  background:color-mix(in srgb,var(--dz-buy,#3fd08d) calc(var(--h)*1%),var(--dz-surface,#121a25))}
.fv-lg{display:flex;gap:14px;font-size:.7rem;color:var(--dz-muted,#8b95a7);margin-bottom:6px}.fv-lg u{display:inline-block;width:10px;height:6px;border-radius:3px;margin-right:5px}
.fv .e{background:var(--dz-line,#243041)}.fv .a{background:var(--dz-buy,#3fd08d)}.fv-lg .mv{margin-left:auto}
.fv-eq{display:grid;grid-template-columns:54px 1fr 52px 76px 38px;gap:6px;align-items:center;margin-top:8px;font-size:.72rem}.fv-eq span{color:var(--dz-muted,#8b95a7)}
.fv-pair{display:grid;gap:3px}.fv-pair i{display:block;height:6px;border-radius:3px}
.fv-tag{font-size:.6rem;padding:2px 5px;border-radius:5px;text-align:center;color:#0b1118}.fv-tag.b{background:var(--dz-buy,#3fd08d)}
.fv-tag.m{background:var(--dz-act,#ff7b78)}.fv-tag.l{background:var(--dz-line,#243041);color:var(--dz-soft,#aab3c3)}
.fv-eq small{color:var(--dz-soft,#aab3c3)}.fv-eq em{font-style:normal;text-align:right;font-weight:700}.fv .up{color:var(--dz-buy,#3fd08d)}.fv .dn{color:var(--dz-act,#ff7b78)}
.fv-co b{font-size:1.02rem}.fv-co small{display:block;color:var(--dz-muted,#8b95a7);font-size:.72rem;margin-top:4px;line-height:1.4}
.fv-co a{color:var(--dz-calm,#8da2d6)}.fv-about{margin-top:6px;font-size:.78rem;color:var(--dz-soft,#aab3c3)}.fv-about summary{cursor:pointer;color:var(--dz-calm,#8da2d6)}
.fv-hd{margin-top:12px}
.fv-pl u{text-decoration:none;display:inline-grid;place-items:center;width:28px;height:28px;border-radius:8px;font-weight:800;color:#0b1118;margin-right:8px;vertical-align:middle}
.fv .g.good,.fv-ch b.good{background:var(--dz-good,#a6e08a)}.fv .g.neutral,.fv-ch b.neutral{background:var(--dz-neutral,#9aa6b8)}
.fv .g.weak,.fv-ch b.weak{background:var(--dz-weak,#ffa566)}.fv .g.bad,.fv-ch b.bad{background:var(--dz-bad,#ff6b6b)}
.fv-chs{display:flex;flex-wrap:wrap;gap:6px}.fv-ch{display:flex;gap:6px;align-items:center;font-size:.7rem;color:var(--dz-soft,#aab3c3);
  background:color-mix(in srgb,var(--dz-ink,#e9eef5) 5%,transparent);border-radius:9px;padding:4px 8px 4px 4px}
.fv-ch b{display:grid;place-items:center;width:20px;height:20px;border-radius:6px;color:#0b1118;font-size:.72rem}
.fv-ft{display:block;color:var(--dz-muted,#8b95a7);font-size:.68rem;margin:8px 0 10px}
.fv-bt{display:flex;align-items:center;gap:12px}.fv-dots{display:flex;gap:5px}.fv-dots i{width:22px;height:22px;border-radius:50%;background:var(--dz-line,#243041)}
.fv-dots i.y{background:var(--dz-buy,#3fd08d)}.fv-dots i.m{background:var(--dz-act,#ff7b78)}
.fv-note{font-size:.84rem;color:var(--dz-muted,#8b95a7)}
"""
