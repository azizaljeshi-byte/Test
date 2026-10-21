"""Mission Control look for the dashboard: theme CSS and HTML builders for the cards."""
from __future__ import annotations

import math
from html import escape

OPP, RISK, WARN, INFO, MUTED, INK = "#3dffa8", "#ff4d7a", "#ffb020", "#36c5f0", "#5f8796", "#c9f5e4"

VERDICT_STYLE = {  # color, glyph
    "OPPORTUNITY - ADD": (OPP, "▲"), "BUY SETUP": (OPP, "▲"), "STRONG HOLD": (OPP, "●"),
    "HOLD": (INFO, "●"), "WATCH": (INFO, "◌"), "TRIM / REVIEW": (WARN, "◆"),
    "RISK - REVIEW": (RISK, "▼"), "AVOID": (RISK, "✕"), "ERROR": (MUTED, "?"),
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Share+Tech+Mono&display=swap');
:root { --bg:#05080d; --panel:#0a1119; --line:#173a44; --ink:#c9f5e4; --muted:#5f8796;
        --opp:#3dffa8; --risk:#ff4d7a; --warn:#ffb020; --info:#36c5f0; }
html, body, .stApp, .stMarkdown, button, input, textarea, [data-baseweb] { font-family: 'Share Tech Mono', monospace !important; }
.stApp { background: radial-gradient(ellipse at 50% -10%, #0e2630 0%, #05080d 55%) fixed; }
.stApp::after { content:''; position:fixed; inset:0; pointer-events:none; z-index:1000;
  background: repeating-linear-gradient(0deg, rgba(61,255,168,.03) 0 1px, transparent 1px 3px); }
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }
.block-container { padding: 1.2rem .9rem 4rem; max-width: 1180px; }
h1,h2,h3 { font-family: 'Orbitron', sans-serif !important; letter-spacing: .12em; }

.mc-head { display:flex; align-items:center; gap:.8rem; margin-bottom:.2rem; }
.mc-radar { width:42px; height:42px; border-radius:50%; flex:none; position:relative;
  border:1px solid rgba(61,255,168,.5); box-shadow: 0 0 14px rgba(61,255,168,.35), inset 0 0 10px rgba(61,255,168,.2);
  background: repeating-radial-gradient(circle, transparent 0 7px, rgba(61,255,168,.18) 7px 8px); overflow:hidden; }
.mc-radar::before { content:''; position:absolute; inset:0; border-radius:50%;
  background: conic-gradient(from 0deg, rgba(61,255,168,.65), rgba(61,255,168,0) 70deg, transparent 360deg);
  animation: sweep 3.2s linear infinite; }
@keyframes sweep { to { transform: rotate(360deg); } }
.mc-title { font-family:'Orbitron',sans-serif; font-weight:900; font-size:1.3rem; letter-spacing:.22em;
  color:var(--opp); text-shadow:0 0 14px rgba(61,255,168,.55); line-height:1.1; }
.mc-sub { color:var(--muted); font-size:.72rem; letter-spacing:.16em; text-transform:uppercase; }
.mc-blink { animation: blink 1.4s steps(2) infinite; color: var(--opp); }
@keyframes blink { 50% { opacity: 0; } }

.mc-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.55rem; margin:.7rem 0; }
@media (min-width: 820px) { .mc-grid { grid-template-columns:repeat(4,minmax(0,1fr)); } }
.mc-tile { border:1px solid var(--line); background:var(--panel); border-radius:10px; padding:.6rem .75rem; position:relative; overflow:hidden; }
.mc-tile::before { content:''; position:absolute; left:0; top:0; height:2px; width:100%; background:var(--c, var(--line)); opacity:.8; }
.mc-k { color:var(--muted); font-size:.66rem; letter-spacing:.16em; text-transform:uppercase; }
.mc-v { font-family:'Orbitron',sans-serif; font-size:1.25rem; color:var(--ink); margin-top:.15rem; white-space:nowrap; }
.mc-d { color:var(--muted); font-size:.72rem; }

.mc-cards { display:grid; grid-template-columns:minmax(0,1fr); gap:.6rem; }
@media (min-width: 760px) { .mc-cards { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (min-width: 1100px) { .mc-cards { grid-template-columns:repeat(3,minmax(0,1fr)); } }
.mc-card { border:1px solid var(--line); border-left:3px solid var(--c); border-radius:10px; padding:.65rem .8rem;
  background: linear-gradient(180deg, rgba(255,255,255,.025), transparent 40%), var(--panel);
  box-shadow: 0 0 22px -14px var(--c); }
.mc-card.urgent { animation: pulse 2.2s ease-in-out infinite; }
@keyframes pulse { 50% { box-shadow: 0 0 26px -6px var(--c); } }
.mc-row { display:flex; justify-content:space-between; align-items:center; gap:.5rem; }
.mc-tk { font-family:'Orbitron',sans-serif; font-weight:700; font-size:1.05rem; letter-spacing:.08em; color:var(--ink); }
.mc-tag { font-size:.62rem; color:var(--muted); border:1px solid var(--line); border-radius:4px; padding:0 .3rem; margin-left:.35rem; letter-spacing:.1em; vertical-align:middle; }
.mc-chip { font-size:.68rem; letter-spacing:.08em; border:1px solid var(--c); color:var(--ink); border-radius:999px; padding:.05rem .5rem; white-space:nowrap; }
.mc-chip b { color:var(--c); font-weight:400; }
.mc-px { font-size:.95rem; color:var(--ink); margin:.25rem 0 .35rem; }
.mc-px small { color:var(--muted); }
.mc-bar { display:grid; grid-template-columns:3.2rem 1fr 1.8rem; align-items:center; gap:.4rem; font-size:.68rem; color:var(--muted); margin:.12rem 0; }
.mc-bar i { display:block; height:4px; border-radius:2px; background:rgba(54,197,240,.13); overflow:hidden; }
.mc-bar i u { display:block; height:100%; border-radius:2px; background:var(--info); box-shadow:0 0 8px rgba(54,197,240,.6); }
.mc-bar span:last-child { text-align:right; color:var(--ink); }
.mc-meta { display:flex; flex-wrap:wrap; gap:.25rem .8rem; font-size:.68rem; color:var(--muted); margin-top:.35rem; }
.mc-meta b { color:var(--ink); font-weight:400; }
.mc-sig { font-size:.74rem; color:var(--ink); margin-top:.4rem; border-top:1px dashed var(--line); padding-top:.35rem; }
.mc-g { font-style:normal; margin-right:.3rem; }

.mc-log { font-size:.78rem; line-height:1.5; border-bottom:1px solid rgba(23,58,68,.6); padding:.35rem 0; color:var(--ink); }
.mc-log small { color:var(--muted); }
.mc-kv { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.3rem .9rem; font-size:.78rem; }
@media (min-width: 820px) { .mc-kv { grid-template-columns:repeat(4,minmax(0,1fr)); } }
.mc-kv div { border-bottom:1px solid rgba(23,58,68,.6); padding:.2rem 0; display:flex; justify-content:space-between; gap:.4rem; }
.mc-kv span { color:var(--muted); }
.mc-news a { color:var(--info); text-decoration:none; }
.mc-section { font-family:'Orbitron',sans-serif; font-size:.78rem; letter-spacing:.2em; color:var(--muted); margin:1rem 0 .4rem; text-transform:uppercase; }

.stButton > button, .stFormSubmitButton > button { border:1px solid var(--opp) !important; background:rgba(61,255,168,.06) !important;
  color:var(--opp) !important; letter-spacing:.14em; text-transform:uppercase; border-radius:8px; }
.stButton > button:hover { box-shadow:0 0 14px rgba(61,255,168,.4); }
.stTabs [data-baseweb="tab"] { letter-spacing:.14em; text-transform:uppercase; font-size:.8rem; }
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
    cells = "".join(f'<div class="mc-tile" style="--c:{c}"><div class="mc-k">{escape(k)}</div>'
                    f'<div class="mc-v">{escape(v)}</div><div class="mc-d">{escape(d)}</div></div>'
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
    return (f'<div class="mc-card{" urgent" if urgent else ""}" style="--c:{color}">'
            f'<div class="mc-row"><div><span class="mc-tk">{escape(snap["ticker"])}</span><span class="mc-tag">{tag}</span></div>'
            f'<span class="mc-chip" style="--c:{color}"><b>{glyph}</b> {escape(snap["verdict"])}</span></div>'
            f'<div class="mc-px">{num(snap["price"])}{day_html}</div>'
            f'{_bar("FUND", snap["fundamental_score"])}{_bar("TECH", snap["technical_score"])}{_bar("Σ ALL", snap["composite"])}'
            f'<div class="mc-meta">{"".join(f"<span>{m}</span>" for m in meta)}</div>{sig}</div>')


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
