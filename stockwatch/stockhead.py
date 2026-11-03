"""The top of the Details page (owner, 30 Oct: "two cards, I want one extended card"): one card per stock with
  - the call, how many checks agree, and the New call beside it (a clash is said, never hidden),
  - the reading in plain words: falling, stalled or recovering, and why,
  - the price ladder: next resistance, price, exit line, next support, hard stop, each with the distance from now,
  - only the technicals and the fundamentals that matter for the decision,
  - the major news of the last day and the analyst moves.
Display only: it reads what is already on the snapshot and changes no score, call, signal or plan."""
from __future__ import annotations

from datetime import datetime
from html import escape

from . import dayboard, design, ui
from .data import NY
from .ui import nan

NEWS_HOURS = 36
NEWS_MAX = 4
SELL_WORDS = ("EXIT", "AVOID", "SELL")
BUY_WORDS = ("BUY", "ADD")


def _n(v) -> float | None:
    return None if v is None or isinstance(v, bool) or nan(v) else float(v)


def _usd(v) -> str:
    return "n/a" if _n(v) is None else f"${float(v):,.2f}"


def _pct(v, digits: int = 0, sign: bool = True) -> str:
    return "n/a" if _n(v) is None else f"{float(v) * 100:{'+' if sign else ''}.{digits}f}%"


def _big(v) -> str:
    v = _n(v)
    if v is None:
        return "n/a"
    a = abs(v)
    s = f"{a / 1e12:.1f}T" if a >= 1e12 else f"{a / 1e9:.1f}B" if a >= 1e9 else f"{a / 1e6:.0f}M" if a >= 1e6 else f"{a:,.0f}"
    return ("-" if v < 0 else "") + "$" + s


def _row(label: str, value: str, note: str = "", tone: str = "") -> str:
    cls = f" sh-{tone}" if tone else ""
    return (f'<div class="sh-r"><span class="sh-l">{escape(label)}</span><b class="sh-v{cls}">{escape(value)}</b>'
            + (f'<small>{escape(note)}</small>' if note else "") + "</div>")


# ---------------------------------------------------------------- the reading (falling, stalled, recovering)

def reading(snap: dict) -> tuple[str, str, str]:
    """(word, tone, why in plain English). The momentum read when it is known, else the trend from the indicators."""
    t = snap["payload"].get("technical") or {}
    m = t.get("momentum") or {}
    if m.get("known"):
        word = str(m.get("momentum_label") or m.get("momentum") or "").upper()
        cause = m.get("cause_label")
        why = (m.get("why") or "").strip()
        tone = "bad" if word in ("FALLING", "WEAKENING") else "good" if word in ("RISING", "STRENGTHENING", "RECOVERING") else "mid"
        return word.title() if word else "Unclear", tone, (f"{cause}. " if cause else "") + why
    trend = t.get("trend")
    if trend:
        return str(trend).title() + " trend", "bad" if trend == "down" else "good" if trend == "up" else "mid", "from the averages only; the momentum read is missing"
    return "Unclear", "mid", "not enough price history for a reading"


# ---------------------------------------------------------------- the price ladder

def _zone(snap: dict, kind: str, price: float) -> dict | None:
    zs = ((snap["payload"].get("technical") or {}).get("zones") or {}).get(kind) or []
    if kind == "support":
        ok = [z for z in zs if _n(z.get("high")) is not None and z["high"] <= price]
        return max(ok, key=lambda z: z["high"]) if ok else None
    ok = [z for z in zs if _n(z.get("low")) is not None and z["low"] >= price]
    return min(ok, key=lambda z: z["low"]) if ok else None


def ladder(snap: dict) -> list[dict]:
    """Rows highest price first: next resistance, now, exit line, next support, hard stop. Each: label, level, note, tone."""
    p = snap["payload"]
    price = _n(ui.price_parts(snap)["price"])
    if price is None:
        return []
    rows = []
    r = _zone(snap, "resistance", price)
    if r:
        words, tone = design.zone_words("resistance", r.get("grade"))
        rows.append({"label": "Next resistance", "level": r["low"], "note": words, "tone": tone})
    rows.append({"label": "Now", "level": price, "note": "", "tone": "now"})
    oc = (p.get("technical") or {}).get("one_call") or {}
    ps = ui.price_status(snap) or {}
    line = _n(oc.get("exit_line")) if oc.get("known") else None
    if line is None:
        line = _n((ps.get("levels") or {}).get("support_low")) if ps.get("floor_known") else None
    if line is not None:
        band = _n(oc.get("band_line")) if oc.get("known") else None
        note = "a daily close below it is the exit" if price > line else "the close is already under it"
        rows.append({"label": "Exit line", "level": line, "note": note + (f" (band down to {band:,.2f})" if band else ""), "tone": "exit"})
    s = _zone(snap, "support", price)
    if s:
        words, tone = design.zone_words("support", s.get("grade"))
        rows.append({"label": "Next support", "level": s["high"], "note": words, "tone": tone})
    stop = _n((p.get("plan") or {}).get("stop"))
    if stop is not None and stop < price:
        rows.append({"label": "Plan stop", "level": stop, "note": "hard stop: protects against a fall straight through", "tone": "exit"})
    return sorted(rows, key=lambda x: -x["level"])


def _ladder_html(rows: list[dict], price: float | None) -> str:
    out = []
    for r in rows:
        gap = "" if r["tone"] == "now" or not price else f'{(r["level"] / price - 1) * 100:+.1f}%'
        out.append(f'<div class="sh-lad sh-t-{r["tone"]}"><span class="sh-l">{escape(r["label"])}</span>'
                   f'<b>{_usd(r["level"])}</b><em>{gap}</em><small>{escape(r["note"])}</small></div>')
    return "".join(out)


# ---------------------------------------------------------------- technicals and fundamentals that matter

def technicals(snap: dict) -> list[str]:
    t = snap["payload"].get("technical") or {}
    price = _n(snap.get("price"))
    rows = []
    trend = t.get("trend")
    if trend:        # the long-term rule only: price against the 200-day and the 50-day against the 200-day (it can read Up while the price is under the 50-day)
        note = {"up": "price above the 200-day, 50-day above the 200-day", "down": "price below the 200-day, 50-day below the 200-day"}.get(trend, "the averages disagree")
        rows.append(_row("Long-term trend", str(trend).title(), note, "bad" if trend == "down" else "good" if trend == "up" else ""))
    for key, name in (("sma50", "50-day average"), ("sma200", "200-day average")):
        v = _n(t.get(key))
        if v and price:
            gap = price / v - 1
            rows.append(_row(f"vs {name}", f"{abs(gap) * 100:.0f}% {'below' if gap < 0 else 'above'}", f"{v:,.2f}", "bad" if gap < 0 else "good"))
    rsi = _n(t.get("rsi"))
    if rsi is not None:
        word = "oversold" if rsi < 30 else "overbought" if rsi > 70 else "normal"
        rows.append(_row("RSI", f"{rsi:.0f}", word, "mid" if word != "normal" else ""))
    vr, day = _n(t.get("volume_ratio")), _n(t.get("day_change"))
    if vr is not None:
        rows.append(_row("Volume", f"{vr:.1f}x normal", "heavy" if vr >= 1.5 else "", "mid" if vr >= 1.5 else ""))
    dd = _n(t.get("drawdown_52w"))
    if dd is not None:
        rows.append(_row("From the 52-week high", _pct(dd), "", "bad" if dd < -0.2 else ""))
    rs = _n(t.get("rs_spy_3m"))
    if rs is not None:
        rows.append(_row("Against the market, 3 months", _pct(rs), "", "bad" if rs < -0.05 else "good" if rs > 0.05 else ""))
    atr = _n(t.get("atr"))
    if atr and price:
        rows.append(_row("Normal daily swing", f"{atr / price * 100:.1f}%", f"{atr:,.2f}"))
    del day
    return rows


def fundamentals(snap: dict) -> list[str]:
    f = snap["payload"].get("fundamental") or {}
    rows = [_row("Fundamentals score", f'{snap.get("fundamental_score", 0):.0f} / 100', "", "good" if snap.get("fundamental_score", 0) >= 70 else "bad" if snap.get("fundamental_score", 0) < 40 else "")]
    if not f.get("available", True):
        return rows + [_row("Detail", "unavailable", "no fundamentals data came back", "mid")]
    for key, name in (("pillar_valuation", "Valuation"), ("pillar_growth", "Growth"), ("pillar_quality", "Quality"), ("pillar_balance", "Balance sheet")):
        v = _n(f.get(key))
        if v is not None:
            rows.append(_row(name, f"{v:.0f}", "", "good" if v >= 70 else "bad" if v < 40 else ""))
    for key, name, fmt in (("pe", "P/E", lambda v: f"{v:.1f}"), ("revenue_growth", "Revenue growth", _pct),
                           ("operating_margin", "Operating margin", _pct), ("free_cash_flow", "Free cash flow", _big),
                           ("analyst_upside", "Analyst target", lambda v: f"{v * 100:+.0f}% upside")):
        v = _n(f.get(key))
        if v is not None:
            rows.append(_row(name, fmt(v)))
    return rows


# ---------------------------------------------------------------- news and analyst moves

def news(snap: dict, now: datetime | None = None) -> list[dict]:
    """The last day's headlines, the ones with a clear tone first, newest first within each."""
    now = now or datetime.now(NY)
    out = []
    for n in (snap["payload"].get("events") or {}).get("news") or []:
        try:
            age = (now - datetime.fromisoformat(n["published"])).total_seconds() / 3600
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= age <= NEWS_HOURS:
            out.append({**n, "age": age})
    out.sort(key=lambda n: (n.get("tone", "neutral") == "neutral", n["age"]))
    return out[:NEWS_MAX]


def analyst_moves(snap: dict) -> list[str]:
    return [s["message"] for s in snap["payload"].get("signals") or [] if s.get("source") == "analyst"][:2]


def _news_html(snap: dict, now: datetime | None) -> str:
    items = news(snap, now)
    moves = analyst_moves(snap)
    rows = []
    for n in items:
        tag, col = ui.TONE.get(n.get("tone"), ui.TONE["neutral"])
        title = (f'<a href="{escape(n["url"])}" target="_blank">{escape(n["title"])}</a>' if n.get("url") else escape(n["title"]))
        hrs = n["age"]
        when = f"{hrs:.0f} h ago" if hrs >= 1 else "just now"
        rows.append(f'<div class="sh-n"><span class="mc-tone" style="--c:{col}">{tag}</span>{title}<small>{escape(n.get("publisher") or "")} · {when}</small></div>')
    for m in moves:
        rows.append(f'<div class="sh-n"><span class="mc-tone" style="--c:{ui.WARN}">ANALYST</span>{escape(m)}</div>')
    ev = snap["payload"].get("events") or {}
    if ev.get("days_to_earnings") is not None and ev.get("earnings_date"):
        d = ev["days_to_earnings"]
        rows.append(f'<div class="sh-n sh-q">Next earnings {escape(str(ev["earnings_date"]))} · in {d} day{"s" if d != 1 else ""}</div>')
    return "".join(rows) or '<div class="sh-n sh-q">No headlines in the last day.</div>'


# ---------------------------------------------------------------- the card

def calls(snap: dict) -> tuple[str, str, str | None, str | None]:
    """(main call text, its class, New call word or None, a clash note or None). One answer: a clash is stated, not shown twice."""
    a = dayboard.assess(snap)
    text, cls = dayboard._words(snap, a), dayboard.SPOT[a["word"]]
    oc = (snap["payload"].get("technical") or {}).get("one_call") or {}
    nc = oc.get("call") if oc.get("known") else None
    clash = None
    if nc and ((a["word"] == "ACT" and a.get("sell_side") and nc in BUY_WORDS) or (a["word"] == "BUY" and nc in SELL_WORDS)):
        clash = f"The two calls disagree (main: {text.lower()}, New call: {nc}). Do not buy; wait for the next close."
    return text, cls, nc, clash


def html(snap: dict, now: datetime | None = None) -> str:
    p = snap["payload"]
    pp = ui.price_parts(snap)
    text, cls, nc, clash = calls(snap)
    a = dayboard.assess(snap)
    sure = f'{a["sure"][0]} of {a["sure"][1]} checks agree' if a["sure"] else (a["why"] or "no usable signal")
    word, rtone, rwhy = reading(snap)
    price = _n(pp["price"])
    px = f'<b class="sh-px">{_usd(price)}</b>' + (design.change_pill(pp["day"]) if pp["day"] is not None else "")
    if pp["ext"]:
        label, eprice, echg = pp["ext"]
        px += f'<span class="sh-ext">{escape(label)} <b>{eprice:.2f}</b> {design.change_pill(echg)}</span>'
    elif pp["note"]:
        px += f'<span class="sh-ext">{escape(pp["note"])}</span>'
    nc_chip = f'<span class="sh-chip">New call <b>{escape(nc)}</b></span>' if nc else ""
    tier = snap.get("tier")
    owned = "owned" if not p.get("watchlist") else "watching"
    sub = " · ".join(x for x in (escape(p.get("name") or ""), f"T{tier}" if tier else "", owned) if x)
    lad = ladder(snap)
    as_of = ((p.get("technical") or {}).get("one_call") or {}).get("as_of") or (ui.price_status(snap) or {}).get("levels", {}).get("as_of")
    foot = f'<div class="sh-foot">Chart read on the daily close of {escape(str(as_of))}.</div>' if as_of else ""
    clash_html = design.icon_line("careful", clash) if clash else ""
    return (f'<style>{CSS}</style><div class="sh dz-{cls}">'
            f'<div class="sh-top"><div><b class="sh-tk">{escape(snap["ticker"])}</b><span class="sh-sub">{sub}</span></div>'
            f'<span class="dz-call dz-{cls}">{escape(text)}</span></div>'
            f'<div class="sh-pxrow">{px}</div>'
            f'<div class="sh-agree">{escape(sure)}{nc_chip}</div>{clash_html}'
            f'<div class="sh-read sh-{rtone}"><span class="sh-l">Reading</span><b>{escape(word)}</b><span>{escape(rwhy)}</span></div>'
            f'<div class="sh-h">Price ladder</div><div class="sh-ladder">{_ladder_html(lad, price)}</div>'
            f'<div class="sh-cols"><div><div class="sh-h">Technicals</div>{"".join(technicals(snap))}</div>'
            f'<div><div class="sh-h">Fundamentals</div>{"".join(fundamentals(snap))}</div></div>'
            f'<div class="sh-h">Major news</div>{_news_html(snap, now)}{foot}</div>')


CSS = """
.sh{border-radius:16px;padding:14px;margin:6px 0 12px;background:color-mix(in srgb,var(--dz-c) 8%,var(--dz-surface,#121a25));
  border:1px solid color-mix(in srgb,var(--dz-c) 30%,var(--dz-line,#243041));border-left:5px solid var(--dz-c);color:var(--dz-ink,#e9eef5)}
.sh-top{display:flex;justify-content:space-between;align-items:center;gap:10px}
.sh-tk{font-size:1.3rem;margin-right:8px}.sh-sub{font-size:.76rem;color:var(--dz-muted,#8b95a7)}
.sh-pxrow{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;margin-top:4px}
.sh-px{font-size:1.25rem;font-variant-numeric:tabular-nums}.sh-ext{font-size:.78rem;color:var(--dz-muted,#8b95a7)}
.sh-agree{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;font-size:.78rem;color:var(--dz-muted,#8b95a7);margin-top:6px}
.sh-chip{border:1px solid var(--dz-line,#243041);border-radius:999px;padding:1px 9px;font-size:.74rem}
.sh-chip b{color:var(--dz-ink,#e9eef5)}
.sh .dz-li{margin:10px 0 0}
.sh-read{display:grid;grid-template-columns:auto auto 1fr;gap:2px 10px;align-items:baseline;margin-top:10px;padding:8px 10px;border-radius:10px;
  background:color-mix(in srgb,var(--dz-line,#243041) 40%,transparent);font-size:.82rem}
.sh-read b{font-size:.95rem}.sh-read.sh-bad b{color:#ff6b6b}.sh-read.sh-good b{color:#3dffa8}.sh-read.sh-mid b{color:#ffc857}
.sh-h{font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;color:var(--dz-muted,#8b95a7);margin:14px 0 6px}
.sh-l{font-size:.72rem;color:var(--dz-muted,#8b95a7);text-transform:uppercase;letter-spacing:.04em}
.sh-lad{display:grid;grid-template-columns:122px 84px 52px 1fr;gap:2px 8px;align-items:baseline;padding:4px 6px;border-radius:8px;font-size:.84rem}
.sh-lad .sh-l{font-size:.68rem;white-space:nowrap}.sh-lad b{font-variant-numeric:tabular-nums}.sh-lad em{font-style:normal;color:var(--dz-muted,#8b95a7);font-size:.76rem}
.sh-lad small{color:var(--dz-muted,#8b95a7);font-size:.72rem}
.sh-lad.sh-t-now{background:color-mix(in srgb,var(--dz-c) 18%,transparent);font-weight:700}
.sh-lad.sh-t-exit b{color:#ff8a8a}
.sh-cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:0 18px}
.sh-r{display:grid;grid-template-columns:1fr auto;gap:0 8px;padding:5px 0;border-bottom:1px solid color-mix(in srgb,var(--dz-line,#243041) 60%,transparent);font-size:.84rem}
.sh-r small{grid-column:1 / -1;color:var(--dz-muted,#8b95a7);font-size:.72rem}
.sh-v.sh-bad{color:#ff8a8a}.sh-v.sh-good{color:#3dffa8}.sh-v.sh-mid{color:#ffc857}
.sh-n{padding:6px 0;border-bottom:1px solid color-mix(in srgb,var(--dz-line,#243041) 60%,transparent);font-size:.86rem;line-height:1.35}
.sh-n small{display:block;color:var(--dz-muted,#8b95a7);font-size:.72rem}.sh-n a{color:inherit}
.sh-q{color:var(--dz-muted,#8b95a7)}.sh-foot{margin-top:10px;font-size:.72rem;color:var(--dz-muted,#8b95a7)}
@media(max-width:560px){.sh-lad{grid-template-columns:118px 80px 48px 1fr}.sh-lad small{grid-column:1 / -1}.sh-read{grid-template-columns:auto 1fr}.sh-read span:last-child{grid-column:1 / -1}}
"""
