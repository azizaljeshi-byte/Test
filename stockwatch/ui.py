"""Mission Control look for the dashboard: theme CSS and HTML builders for the cards."""
from __future__ import annotations

import math
import re
from html import escape

OPP, RISK, WARN, INFO, MUTED, INK = "#3dffa8", "#ff4d7a", "#ffb020", "#36c5f0", "#5f8796", "#c9f5e4"

VERDICT_STYLE = {  # color, glyph
    "OPPORTUNITY - ADD": (OPP, "▲"), "BUY SETUP": (OPP, "▲"), "STRONG HOLD": (OPP, "●"),
    "HOLD": (INFO, "●"), "WATCH": (INFO, "◌"), "TRIM / REVIEW": (WARN, "◆"),
    "RISK - REVIEW": (RISK, "▼"), "AVOID": (RISK, "✕"), "ERROR": (MUTED, "?"),
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;500&family=Orbitron:wght@700;900&display=swap');
:root { --bg:#060a10; --panel:#0c141d; --panel2:#101b26; --line:#1b3442; --ink:#e4f1ec; --soft:#a9c2c9; --muted:#6c8a97;
        --opp:#3dffa8; --risk:#ff4d7a; --warn:#ffb020; --info:#36c5f0;
        --sans:'Inter',system-ui,sans-serif; --head:'Space Grotesk','Inter',sans-serif; --mono:'JetBrains Mono',ui-monospace,monospace; }
html, body, .stApp, .stMarkdown, button, input, textarea, [data-baseweb] { font-family: var(--sans) !important; }
.stApp { background:
  radial-gradient(1200px 500px at 85% -10%, rgba(54,197,240,.10), transparent 60%),
  radial-gradient(900px 500px at -10% 0%, rgba(61,255,168,.07), transparent 55%), var(--bg) fixed; }
.stApp::after { content:''; position:fixed; inset:0; pointer-events:none; z-index:1000;
  background: repeating-linear-gradient(0deg, rgba(255,255,255,.012) 0 1px, transparent 1px 4px); }
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }
.block-container { padding: 1.1rem 1rem 4rem; max-width: 1180px; }
h1,h2,h3 { font-family: var(--head) !important; }
a { color: var(--info); }
.mc-mono { font-family: var(--mono); }

/* ---- header & hero */
.mc-head { display:flex; align-items:center; gap:.75rem; }
.mc-radar { width:38px; height:38px; border-radius:50%; flex:none; position:relative;
  border:1px solid rgba(61,255,168,.45); box-shadow: 0 0 18px rgba(61,255,168,.25), inset 0 0 10px rgba(61,255,168,.15);
  background: repeating-radial-gradient(circle, transparent 0 6px, rgba(61,255,168,.16) 6px 7px); overflow:hidden; }
.mc-radar::before { content:''; position:absolute; inset:0; border-radius:50%;
  background: conic-gradient(from 0deg, rgba(61,255,168,.6), rgba(61,255,168,0) 70deg, transparent 360deg);
  animation: sweep 3.6s linear infinite; }
@keyframes sweep { to { transform: rotate(360deg); } }
.mc-title { font-family:'Orbitron',sans-serif; font-weight:900; font-size:1.05rem; letter-spacing:.24em; color:var(--opp);
  text-shadow:0 0 14px rgba(61,255,168,.45); line-height:1.1; }
.mc-sub { color:var(--muted); font-family:var(--mono); font-size:.68rem; letter-spacing:.08em; text-transform:uppercase; margin-top:.15rem; }
.mc-blink { animation: blink 1.6s steps(2) infinite; color: var(--opp); }
@keyframes blink { 50% { opacity: 0; } }
.mc-hero { margin:.9rem 0 .2rem; }
.mc-hero .h1 { font-family:var(--head) !important; font-weight:600; font-size:1.55rem; line-height:1.2; color:var(--ink);
  margin:0; padding:0; letter-spacing:-.01em; }
.mc-hero p { color:var(--soft); font-size:.95rem; line-height:1.5; margin:.35rem 0 0; }
.mc-hero p b { color:var(--ink); font-weight:600; }

/* ---- status tiles */
.mc-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.6rem; margin:.9rem 0; }
@media (min-width: 820px) { .mc-grid { grid-template-columns:repeat(4,minmax(0,1fr)); } }
.mc-tile { border:1px solid var(--line); background:linear-gradient(180deg, var(--panel2), var(--panel)); border-radius:14px;
  padding:.7rem .85rem; position:relative; overflow:hidden; }
.mc-tile::before { content:''; position:absolute; left:.85rem; right:.85rem; top:0; height:2px; border-radius:0 0 2px 2px;
  background:var(--c, var(--line)); box-shadow:0 0 10px var(--c, transparent); }
.mc-k { color:var(--muted); font-family:var(--mono); font-size:.62rem; letter-spacing:.14em; text-transform:uppercase; }
.mc-v { font-family:var(--head); font-weight:600; font-size:1.35rem; color:var(--ink); margin-top:.1rem; white-space:nowrap; }
.mc-d { color:var(--soft); font-size:.74rem; line-height:1.4; }
.mc-d a { color:var(--soft); text-decoration:none; border-bottom:1px dotted var(--muted); }

/* ---- stock cards */
.mc-cards { display:grid; grid-template-columns:minmax(0,1fr); gap:.7rem; }
@media (min-width: 760px) { .mc-cards { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (min-width: 1100px) { .mc-cards { grid-template-columns:repeat(3,minmax(0,1fr)); } }
a.mc-a { text-decoration:none !important; color:inherit !important; display:block; }
.mc-card { border:1px solid var(--line); border-radius:16px; padding:.8rem .9rem; position:relative; overflow:hidden;
  background: linear-gradient(180deg, rgba(255,255,255,.03), transparent 45%), var(--panel);
  transition: border-color .15s, transform .15s, box-shadow .15s; }
.mc-card::before { content:''; position:absolute; left:0; top:12px; bottom:12px; width:3px; border-radius:0 3px 3px 0;
  background:var(--c); box-shadow:0 0 10px var(--c); }
a.mc-a:hover .mc-card { border-color:var(--c); transform:translateY(-1px); box-shadow:0 8px 28px -18px var(--c); }
.mc-card.urgent { animation: pulse 2.4s ease-in-out infinite; }
@keyframes pulse { 50% { box-shadow: 0 0 24px -8px var(--c); } }
.mc-row { display:flex; justify-content:space-between; align-items:flex-start; gap:.5rem; }
.mc-tk { font-family:var(--head); font-weight:700; font-size:1.12rem; letter-spacing:.02em; color:var(--ink); }
.mc-name { display:block; color:var(--soft); font-size:.74rem; margin-top:.05rem; max-width:13rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.mc-tag { font-family:var(--mono); font-size:.58rem; color:var(--muted); border:1px solid var(--line); border-radius:5px;
  padding:.05rem .3rem; margin-left:.4rem; letter-spacing:.08em; vertical-align:middle; }
.mc-chip { font-size:.68rem; font-weight:600; letter-spacing:.03em; border:1px solid var(--c); color:var(--ink); border-radius:999px;
  padding:.12rem .55rem; white-space:nowrap; background:color-mix(in srgb, var(--c) 10%, transparent); }
.mc-chip b { color:var(--c); font-weight:600; }
.mc-px { font-family:var(--mono); font-size:.92rem; color:var(--ink); margin:.45rem 0 .45rem; }
.mc-px small { color:var(--muted); font-size:.74rem; }
.mc-bar { display:grid; grid-template-columns:3.4rem 1fr 1.8rem; align-items:center; gap:.45rem; font-size:.66rem;
  color:var(--muted); margin:.16rem 0; font-family:var(--mono); }
.mc-bar i { display:block; height:5px; border-radius:3px; background:rgba(54,197,240,.12); overflow:hidden; }
.mc-bar i u { display:block; height:100%; border-radius:3px; background:linear-gradient(90deg, rgba(54,197,240,.55), var(--info)); }
.mc-bar span:last-child { text-align:right; color:var(--ink); }
.mc-meta { display:flex; flex-wrap:wrap; gap:.3rem .85rem; font-size:.68rem; color:var(--muted); margin-top:.45rem; font-family:var(--mono); }
.mc-meta b { color:var(--ink); font-weight:400; }
.mc-sig { font-size:.8rem; line-height:1.45; color:var(--ink); margin-top:.5rem; border-top:1px solid rgba(27,52,66,.8); padding-top:.45rem; }
.mc-g { font-style:normal; margin-right:.35rem; }

/* ---- lists, logs, tables */
.mc-log { font-size:.84rem; line-height:1.5; border-bottom:1px solid rgba(27,52,66,.7); padding:.45rem 0; color:var(--ink); }
.mc-log small { color:var(--muted); font-family:var(--mono); font-size:.68rem; }
.mc-log a { color:var(--ink); text-decoration:none; font-weight:600; }
.mc-kv { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.3rem .9rem; font-size:.8rem; }
@media (min-width: 820px) { .mc-kv { grid-template-columns:repeat(4,minmax(0,1fr)); } }
.mc-kv div { border-bottom:1px solid rgba(27,52,66,.7); padding:.25rem 0; display:flex; justify-content:space-between; gap:.4rem; font-family:var(--mono); }
.mc-kv span { color:var(--muted); font-family:var(--sans); }
.mc-news a { color:var(--info); text-decoration:none; font-weight:500; }
.mc-section { font-family:var(--mono); font-size:.68rem; letter-spacing:.18em; color:var(--muted); margin:1.2rem 0 .45rem; text-transform:uppercase; }
.mc-section::before { content:'◆ '; color:var(--opp); }
.mc-brief { border:1px solid var(--line); border-radius:16px; padding:.85rem 1rem; margin:.6rem 0 .9rem;
  background: linear-gradient(120deg, rgba(61,255,168,.06), rgba(54,197,240,.04) 40%, transparent 70%), var(--panel); }
.mc-brief .hl { font-family:var(--head); font-size:1.02rem; font-weight:500; color:var(--ink); line-height:1.45; }
.mc-brief .h4 { font-family:var(--mono) !important; font-size:.62rem; letter-spacing:.2em; color:var(--opp); margin:.75rem 0 .2rem; padding:0; font-weight:500; }
.mc-brief ul { margin:0; padding-left:1.1rem; }
.mc-brief li { font-size:.86rem; line-height:1.55; color:var(--ink); margin:.12rem 0; }
.mc-brief li::marker { color:var(--muted); }
.mc-brief a { color:var(--opp); text-decoration:none; font-weight:600; border-bottom:1px solid rgba(61,255,168,.35); }
.mc-tbl { overflow-x:auto; margin:.3rem 0 .6rem; }
.mc-tbl table { width:100%; border-collapse:collapse; font-size:.76rem; }
.mc-tbl th { color:var(--muted); font-weight:500; text-align:right; padding:.3rem .45rem; border-bottom:1px solid var(--line); white-space:nowrap; font-size:.7rem; }
.mc-tbl td { text-align:right; padding:.3rem .45rem; border-bottom:1px solid rgba(27,52,66,.6); color:var(--ink); white-space:nowrap; font-family:var(--mono); }
.mc-tbl th:first-child, .mc-tbl td:first-child { text-align:left; }
.mc-tbl tr.me td { color:var(--opp); }
.mc-fv { position:relative; height:44px; margin:.7rem .3rem 1.4rem; font-family:var(--mono); }
.mc-fv .track { position:absolute; left:0; right:0; top:16px; height:6px; border-radius:3px; background:rgba(108,138,151,.2); }
.mc-fv .band { position:absolute; top:12px; height:14px; border-radius:5px; background:rgba(54,197,240,.2); border:1px solid var(--info); }
.mc-fv .mid { position:absolute; top:8px; width:2px; height:22px; background:var(--info); }
.mc-fv .now { position:absolute; top:4px; width:2px; height:30px; background:var(--ink); box-shadow:0 0 8px var(--ink); }
.mc-fv .lbl { position:absolute; top:34px; font-size:.64rem; color:var(--muted); transform:translateX(-50%); white-space:nowrap; }
.mc-fv .lbl.now-l { top:-14px; color:var(--ink); }

/* ---- company overview */
.mc-ov { border:1px solid var(--line); border-radius:16px; padding:.9rem 1rem; margin:.4rem 0 .9rem;
  background: radial-gradient(ellipse at 100% 0%, rgba(54,197,240,.10), transparent 55%), var(--panel); }
.mc-ov .top { display:flex; justify-content:space-between; align-items:flex-start; gap:.6rem; }
.mc-ov .nm { font-family:var(--head); font-weight:600; font-size:1.08rem; color:var(--ink); }
.mc-ov .acq { font-family:var(--mono); font-size:.6rem; letter-spacing:.2em; color:var(--opp); margin-bottom:.2rem; }
.mc-ov .big { flex:none; width:60px; height:60px; border-radius:14px; border:1px solid var(--c); display:flex; flex-direction:column;
  align-items:center; justify-content:center; font-family:var(--head); font-weight:700; font-size:1.6rem; line-height:1;
  color:var(--ink); box-shadow:0 0 18px -6px var(--c); }
.mc-ov .big small { font-family:var(--mono); font-weight:400; font-size:.45rem; letter-spacing:.14em; color:var(--muted); margin-top:.3rem; }
.mc-ov p { font-size:.86rem; line-height:1.55; color:var(--ink); margin:.5rem 0; }
.mc-ov details { font-size:.84rem; color:var(--soft); line-height:1.55; margin:.2rem 0 .5rem; }
.mc-ov details summary { cursor:pointer; color:var(--soft); list-style:none; }
.mc-ov details summary::-webkit-details-marker { display:none; }
.mc-ov details summary span { color:var(--info); }
.mc-ov details[open] summary span { display:none; }
.mc-gr { display:grid; grid-template-columns:minmax(0,1fr); gap:.3rem; margin:.5rem 0; }
@media (min-width: 760px) { .mc-gr { grid-template-columns:repeat(2,minmax(0,1fr)); } }
.mc-gr div { display:grid; grid-template-columns:1.8rem 1fr; gap:.6rem; align-items:center; font-size:.84rem;
  border-bottom:1px solid rgba(27,52,66,.6); padding:.3rem 0; }
.mc-gr b { width:1.8rem; height:1.8rem; border-radius:8px; border:1px solid var(--c); display:grid; place-items:center;
  font-family:var(--head); font-weight:700; color:var(--ink); background:color-mix(in srgb, var(--c) 10%, transparent); }
.mc-gr span { color:var(--ink); }
.mc-gr em { font-style:normal; color:var(--muted); display:block; font-size:.74rem; }
.mc-ov .h4 { font-family:var(--mono) !important; font-size:.6rem; letter-spacing:.2em; margin:.7rem 0 .15rem; padding:0; font-weight:500; }
.mc-ov ul { margin:0; padding-left:1.1rem; } .mc-ov li { font-size:.84rem; line-height:1.55; }

/* ---- streamlit widgets */
.stButton > button, .stFormSubmitButton > button { border:1px solid rgba(61,255,168,.6) !important; background:rgba(61,255,168,.07) !important;
  color:var(--opp) !important; font-weight:600; border-radius:12px; }
.stButton > button:hover { box-shadow:0 0 16px rgba(61,255,168,.3); }
.stExpander { border-radius:14px !important; }
.stExpander summary p { font-weight:500; font-size:.9rem; }
[data-testid="stSegmentedControl"] button { border-radius:10px !important; }
</style>
"""


def nan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def pct(v, signed=True, digits=0) -> str:
    if nan(v):
        return "—"
    return f"{v * 100:{'+' if signed else ''}.{digits}f}%"


def num(v, fmt=".2f") -> str:
    return "—" if nan(v) else format(v, fmt)


def header(subtitle: str) -> str:
    return (f'<div class="mc-head"><div class="mc-radar"></div><div>'
            f'<div class="mc-title">STOCKWATCH</div>'
            f'<div class="mc-sub">mission control <span class="mc-blink">▮</span> {escape(subtitle)}</div></div></div>')


def tiles(items: list[tuple[str, str, str, str]]) -> str:
    """items: (label, value, detail, accent color)"""
    # detail is HTML (callers escape it), so it can carry ticker links
    cells = "".join(f'<div class="mc-tile" style="--c:{c}"><div class="mc-k">{escape(k)}</div>'
                    f'<div class="mc-v">{escape(v)}</div><div class="mc-d">{d}</div></div>'
                    for k, v, d, c in items)
    return f'<div class="mc-grid">{cells}</div>'


def signal_glyph(kind: str) -> str:
    return f'<i class="mc-g" style="color:{OPP if kind == "opportunity" else RISK}">{"▲" if kind == "opportunity" else "▼"}</i>'


def _bar(label: str, v: float) -> str:
    v = 0 if nan(v) else max(0, min(100, v))
    return f'<div class="mc-bar"><span>{label}</span><i><u style="width:{v:.0f}%"></u></i><span>{v:.0f}</span></div>'


def card(snap: dict) -> str:
    p = snap["payload"]
    t, ev = p.get("technical", {}), p.get("events") or {}
    color, glyph = VERDICT_STYLE.get(snap["verdict"], (MUTED, "●"))
    urgent = any(s["kind"] == "risk" and s["severity"] >= 3 for s in p["signals"])
    tag = "WATCH" if p["watchlist"] else f"T{snap['tier']}"
    day = t.get("day_change")
    day_html = "" if nan(day) else (
        f' <small><i class="mc-g" style="color:{OPP if day >= 0 else RISK}">{"▲" if day >= 0 else "▼"}</i>{pct(day, digits=1)}</small>')
    q = p.get("quote") or {}
    if not nan(q.get("ext_price")) and not nan(q.get("ext_change")):
        ch = q["ext_change"]
        day_html += (f' <small style="color:{MUTED}">· {"PRE" if q.get("ext_session") == "pre" else "AH"}</small> '
                     f'{q["ext_price"]:.2f} <small><i class="mc-g" style="color:{OPP if ch >= 0 else RISK}">'
                     f'{"▲" if ch >= 0 else "▼"}</i>{pct(ch, digits=1)}</small>')
    meta = []
    trend = t.get("trend")
    if trend:
        meta.append(f'TREND <b>{ {"up": "↗ UP", "down": "↘ DOWN"}.get(trend, "→ MIXED") }</b>')
    if not nan(t.get("rs_spy_3m")):
        meta.append(f"VS SPY 3M <b>{pct(t['rs_spy_3m'])}</b>")
    if not nan(t.get("rsi")):
        meta.append(f"RSI <b>{t['rsi']:.0f}</b>")
    if ev.get("days_to_earnings") is not None:
        meta.append(f"EARNINGS <b>T-{ev['days_to_earnings']}D</b>")
    if p["position"].get("weight_pct"):
        meta.append(f"WEIGHT <b>{p['position']['weight_pct']:.1f}%</b>")
    top = p["signals"][0] if p["signals"] else None
    sig = (f'<div class="mc-sig">{signal_glyph(top["kind"])}{escape(top["message"])}'
           + (f' <small style="color:{MUTED}">+{len(p["signals"]) - 1} more</small>' if len(p["signals"]) > 1 else "")
           + "</div>") if top else f'<div class="mc-sig" style="color:{MUTED}">◌ no signals</div>'
    if p.get("error"):
        sig = f'<div class="mc-sig" style="color:{MUTED}">signal lost: {escape(p["error"][:90])}</div>'
    name = (p.get("profile") or {}).get("name") or p.get("name") or ""
    name = "" if name.upper() == snap["ticker"] else name
    return (f'<a class="mc-a" href="?view=target&t={escape(snap["ticker"])}" target="_self">'
            f'<div class="mc-card{" urgent" if urgent else ""}" style="--c:{color}">'
            f'<div class="mc-row"><div><span class="mc-tk">{escape(snap["ticker"])}</span><span class="mc-tag">{tag}</span>'
            f'<span class="mc-name">{escape(name)}</span></div>'
            f'<span class="mc-chip" style="--c:{color}"><b>{glyph}</b> {escape(snap["verdict"])}</span></div>'
            f'<div class="mc-px">{num(snap["price"])}{day_html}</div>'
            f'{_bar("FUND", snap["fundamental_score"])}{_bar("TECH", snap["technical_score"])}{_bar("Σ ALL", snap["composite"])}'
            f'<div class="mc-meta">{"".join(f"<span>{m}</span>" for m in meta)}</div>{sig}</div></a>')


def cards(snaps: list[dict]) -> str:
    return f'<div class="mc-cards">{"".join(card(s) for s in snaps)}</div>'


def urgency(snap: dict) -> tuple:
    sigs = snap["payload"]["signals"]
    if any(s["kind"] == "risk" and s["severity"] >= 3 for s in sigs):
        rank = 0
    elif snap["verdict"] in ("OPPORTUNITY - ADD", "BUY SETUP"):
        rank = 1
    elif snap["verdict"] in ("TRIM / REVIEW", "AVOID"):
        rank = 2
    else:
        rank = 3
    return rank, -sum(s["severity"] for s in sigs), snap["ticker"]


def money(v) -> str:
    if nan(v):
        return "—"
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{'-' if v < 0 else ''}${a / div:.1f}{suf}"
    return f"${v:,.0f}"


def brief(b: dict) -> str:
    def section(title, items):
        return f"<div class='h4'>{title}</div><ul>{''.join(f'<li>{escape(i)}</li>' for i in items)}</ul>" if items else ""
    return (f'<div class="mc-brief"><div class="hl">{escape(b["headline"])}</div>'
            f'{section("WHY", b["why"])}{section("CHANGED", b["changed"])}{section("WATCH NEXT", b["watch"])}</div>')


def link_tickers(text: str, tickers) -> str:
    """Escape text and turn known ticker symbols into links to their detail page."""
    html = escape(text)
    if not tickers:
        return html
    pattern = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(sorted(map(re.escape, tickers), key=len, reverse=True))
                         + r")(?![A-Za-z0-9])")
    return pattern.sub(lambda m: f'<a href="?view=target&t={m.group(1)}" target="_self">{m.group(1)}</a>', html)


def mission_brief(lines: list[str], tickers=()) -> str:
    return (f'<div class="mc-brief"><div class="h4" style="margin-top:0">MISSION BRIEF</div><ul>'
            f'{"".join(f"<li>{link_tickers(l, tickers)}</li>" for l in lines)}</ul></div>')


def hero(greeting: str, summary: str) -> str:
    return f'<div class="mc-hero"><div class="h1">{escape(greeting)}</div><p>{summary}</p></div>'


def market_card(r: dict) -> str:
    color, glyph = VERDICT_STYLE.get(r["verdict"], (MUTED, "●"))
    trig = "".join(f'<div class="mc-sig" style="border:0;padding-top:.1rem;margin-top:.1rem">'
                   f'{signal_glyph("opportunity")}{escape(t)}</div>' for t in r["triggers"][:2])
    risks = "".join(f'<div class="mc-sig" style="border:0;padding-top:.1rem;margin-top:.1rem;color:var(--soft)">'
                    f'{signal_glyph("risk")}{escape(t)}</div>' for t in r.get("top_risks", [])[:1])
    meta = [f"{escape(r.get('sector') or '')}"]
    if not nan(r.get("rs_spy_3m")):
        meta.append(f"VS SPY 3M <b>{pct(r['rs_spy_3m'])}</b>")
    if r.get("earnings_days") is not None:
        meta.append(f"EARNINGS <b>T-{r['earnings_days']}D</b>")
    return (f'<a class="mc-a" href="?view=target&t={escape(r["ticker"])}" target="_self">'
            f'<div class="mc-card" style="--c:{color}"><div class="mc-row"><div><span class="mc-tk">{escape(r["ticker"])}</span>'
            f'<span class="mc-name">{escape(r.get("name") or "")}</span></div>'
            f'<span class="mc-chip" style="--c:{color}"><b>{glyph}</b> {escape(r["verdict"])}</span></div>'
            f'<div class="mc-px">{num(r["price"])}</div>'
            f'{_bar("FUND", r["fundamental"])}{_bar("TECH", r["technical"])}{_bar("Σ ALL", r["composite"])}'
            f'<div class="mc-meta">{"".join(f"<span>{m}</span>" for m in meta)}</div>'
            f'<div style="margin-top:.4rem">{trig}{risks}</div></div></a>')


def table(headers: list[str], rows: list[list], highlight: int | None = None) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(f'<tr{" class=me" if i == highlight else ""}>' + "".join(f"<td>{escape(str(c))}</td>" for c in r) + "</tr>"
                   for i, r in enumerate(rows))
    return f'<div class="mc-tbl"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def fair_value_bar(fv: dict, price: float) -> str:
    lo = min(fv["low"], price) * 0.92
    hi = max(fv["high"], price) * 1.08
    x = lambda v: (v - lo) / (hi - lo) * 100  # noqa: E731
    return (f'<div class="mc-fv"><div class="track"></div>'
            f'<div class="band" style="left:{x(fv["low"]):.1f}%;width:{max(x(fv["high"]) - x(fv["low"]), 0.8):.1f}%"></div>'
            f'<div class="mid" style="left:{x(fv["mid"]):.1f}%"></div><div class="now" style="left:{x(price):.1f}%"></div>'
            f'<div class="lbl now-l" style="left:{x(price):.1f}%">NOW {price:.2f}</div>'
            f'<div class="lbl" style="left:{x(fv["mid"]):.1f}%">fair {fv["mid"]:.0f}</div>'
            # range-end labels only where they won't collide with the midpoint label
            + "".join(f'<div class="lbl" style="left:{x(v):.1f}%">{v:.0f}</div>'
                      for v in (fv["low"], fv["high"]) if abs(x(v) - x(fv["mid"])) >= 16)
            + "</div>")


GRADE_COLOR = {"A": OPP, "B": OPP, "C": INFO, "D": WARN, "F": RISK, "?": MUTED}


def overview_card(o: dict, ticker: str, acquired: bool = False) -> str:
    summary = o.get("summary") or ""
    if len(summary) > 260:
        cut = summary.rfind(". ", 0, 260)
        cut = cut + 1 if cut > 80 else 260
        about = (f"<details><summary>{escape(summary[:cut])} <span>more ▾</span></summary>"
                 f"{escape(summary[cut:])}</details>")
    else:
        about = f'<p style="color:{MUTED}">{escape(summary)}</p>' if summary else ""
    grades = "".join(
        f'<div><b style="--c:{GRADE_COLOR[g["grade"]]}">{g["grade"]}</b><span>{escape(g["area"])}'
        f'<em>{escape(g["note"])}</em></span></div>' for g in o["grades"])
    lists = ""
    for title, items, color in (("STRENGTHS", o["strengths"], OPP), ("CONCERNS", o["concerns"], RISK)):
        if items:
            lists += (f'<div class="h4" style="color:{color}">{title}</div><ul>'
                      + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>")
    site = (f' · <a href="{escape(o["website"])}" target="_blank" style="color:{INFO}">website</a>'
            if o.get("website") else "")
    return ('<div class="mc-ov"><div class="top"><div>'
            + ('<div class="acq">◉ NEW TARGET ACQUIRED</div>' if acquired else "")
            + f'<div class="nm">{escape(ticker)} · {escape(o["name"])}</div></div>'
            f'<div class="big" style="--c:{GRADE_COLOR[o["overall"]]}">{o["overall"]}<small>OVERALL</small></div></div>'
            f'<p>{escape(o["intro"])}{site}</p>{about}<div class="mc-gr">{grades}</div>{lists}'
            f'<p style="color:{MUTED};margin-bottom:0">{escape(o["standing"])}</p></div>')


SESSION_LABEL = {"REGULAR": "market open", "PRE": "pre-market", "POST": "after hours", "CLOSED": "market closed"}
