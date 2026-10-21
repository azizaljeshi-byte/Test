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
.mc-bar { display:grid; grid-template-columns:4.2rem 1fr 1.8rem; align-items:center; gap:.45rem; font-size:.66rem;
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
.mc-tbl.wrap td:first-child { white-space:normal; font-family:var(--sans); }
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

/* ---- trade plan */
.mc-plan { font-family:var(--mono); font-size:.68rem; color:var(--soft); margin-top:.45rem; padding:.35rem .5rem;
  border:1px dashed rgba(61,255,168,.25); border-radius:10px; background:rgba(61,255,168,.03); }
.mc-plan b { color:var(--opp); font-weight:500; letter-spacing:.12em; margin-right:.35rem; }
.mc-tp { border:1px solid var(--line); border-radius:16px; padding:.9rem 1rem; margin:.6rem 0 .9rem;
  background: linear-gradient(160deg, rgba(54,197,240,.07), transparent 45%), var(--panel); }
.mc-tp .hd { display:flex; justify-content:space-between; align-items:center; gap:.5rem; flex-wrap:wrap; }
.mc-tp .lab { font-family:var(--mono); font-size:.62rem; letter-spacing:.2em; color:var(--opp); }
.mc-tp .stance { font-family:var(--head); font-weight:700; font-size:1.25rem; color:var(--ink); margin:.25rem 0 .1rem; }
.mc-tp p { font-size:.88rem; line-height:1.55; color:var(--ink); margin:.5rem 0; }
.mc-tp .note { color:var(--warn); font-size:.82rem; }
.mc-tp ol { margin:.2rem 0 0; padding-left:1.2rem; } .mc-tp li { font-size:.84rem; line-height:1.55; color:var(--ink); margin:.12rem 0; }
.mc-tp .mc-kv { grid-template-columns:minmax(0,1fr); }
@media (min-width: 760px) { .mc-tp .mc-kv { grid-template-columns:repeat(2,minmax(0,1fr)); } }
.mc-tp .fine { color:var(--muted); font-size:.72rem; margin-top:.6rem; }
.mc-lad { position:relative; height:64px; margin:.9rem .4rem .6rem; font-family:var(--mono); }
.mc-lad .track { position:absolute; left:0; right:0; top:28px; height:4px; border-radius:2px;
  background:linear-gradient(90deg, rgba(255,77,122,.35), rgba(108,138,151,.25) 35%, rgba(54,197,240,.35)); }
.mc-lad .zone { position:absolute; top:22px; height:16px; border-radius:5px; background:rgba(61,255,168,.22); border:1px solid var(--opp); }
.mc-lad .tick { position:absolute; top:20px; width:2px; height:20px; border-radius:1px; }
.mc-lad .lbl { position:absolute; font-size:.6rem; transform:translateX(-50%); white-space:nowrap; color:var(--soft); }
.mc-lad .lbl.top { top:2px; } .mc-lad .lbl.bot { top:44px; }

/* ---- outlook, history, news */
.mc-seg { display:flex; height:10px; border-radius:5px; overflow:hidden; margin:.4rem 0 .3rem; gap:2px; }
.mc-seg i { display:block; height:100%; }
.mc-legend { display:flex; flex-wrap:wrap; gap:.2rem .9rem; font-size:.74rem; color:var(--soft); font-family:var(--mono); }
.mc-legend b { font-weight:500; color:var(--ink); }
.mc-ev { border:1px solid var(--c); border-radius:12px; padding:.6rem .75rem; margin:.6rem 0;
  background:color-mix(in srgb, var(--c) 7%, transparent); }
.mc-ev .t { font-family:var(--head); font-weight:600; color:var(--ink); }
.mc-ev ul { margin:.25rem 0 0; padding-left:1.1rem; } .mc-ev li { font-size:.82rem; line-height:1.5; color:var(--ink); }
.mc-tone { font-family:var(--mono); font-size:.6rem; letter-spacing:.08em; border:1px solid var(--c); color:var(--c);
  border-radius:4px; padding:0 .25rem; margin-right:.35rem; vertical-align:middle; }

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


def _bar(label: str, v: float | None) -> str:
    if nan(v):
        return f'<div class="mc-bar"><span>{label}</span><i></i><span>—</span></div>'
    v = max(0, min(100, v))
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
    if q.get("market_state") in ("PRE", "POST") and (nan(q.get("ext_price")) or q.get("ext_stale")):
        day_html += (f' <small style="color:{MUTED}">· {"PRE" if q["market_state"] == "PRE" else "AH"} '
                     f'no trades yet</small>')
    if not nan(q.get("ext_price")) and not nan(q.get("ext_change")):
        ch = q["ext_change"]
        label = "PRE" if q.get("ext_session") == "pre" else ("AH (last night)" if q.get("ext_stale") else "AH")
        day_html += (f' <small style="color:{MUTED}">· {label}</small> '
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
        meta.append(f"EARNINGS <b>{'~' if ev.get('earnings_estimated') else ''}T-{ev['days_to_earnings']}D</b>")
    if ev.get("news_today"):
        meta.append(f"NEWS TODAY <b>{ev['news_today']}</b>")
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
            f'{_bar("FUND·SEC" if p.get("fundamental", {}).get("source") == "SEC filings" else "FUND", snap["fundamental_score"] if p.get("fundamental", {}).get("available", True) else None)}'
            f'{_bar("TECH", snap["technical_score"])}{_bar("Σ ALL", snap["composite"])}'
            f'<div class="mc-meta">{"".join(f"<span>{m}</span>" for m in meta)}</div>{sig}{plan_line(p.get("plan"))}</div></a>')


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
            f'<div style="margin-top:.4rem">{trig}{risks}</div>{plan_line(r.get("plan"))}</div></a>')


def table(headers: list[str], rows: list[list], highlight: int | None = None, wrap: bool = False) -> str:
    """wrap=True lets the first column wrap, for tables with long labels on a phone."""
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(f'<tr{" class=me" if i == highlight else ""}>' + "".join(f"<td>{escape(str(c))}</td>" for c in r) + "</tr>"
                   for i, r in enumerate(rows))
    return (f'<div class="mc-tbl{" wrap" if wrap else ""}"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


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


STANCE_COLOR = {"BUY NOW": OPP, "BUY ON PULLBACK": OPP, "BUY THE BREAKOUT": OPP, "ADD": OPP,
                "WAIT FOR CONFIRMATION": INFO, "HOLD": INFO, "TRIM": WARN, "REDUCE / EXIT": RISK, "NO TRADE": RISK}
BIAS_GLYPH = {"bullish": ("▲ bullish", OPP), "bearish": ("▼ bearish", RISK), "neutral": ("◆ neutral", INFO)}


def plan_line(plan: dict | None) -> str:
    from .tradeplan import summary
    return f'<div class="mc-plan"><b>PLAN</b>{escape(summary(plan))}</div>' if plan else ""


def _ladder(plan: dict) -> str:
    exit_only = plan["stance"] in ("REDUCE / EXIT", "NO TRADE")
    points = [plan["stop"], plan["entry_low"], plan["entry_high"], plan["price"]]
    if not exit_only:
        points += [t["price"] for t in plan["targets"]]
    lo, hi = min(points), max(points)
    pad = (hi - lo) * 0.06 or hi * 0.02
    lo, hi = lo - pad, hi + pad
    x = lambda v: (v - lo) / (hi - lo) * 100  # noqa: E731
    out = ['<div class="mc-lad"><div class="track"></div>',
           "" if exit_only else
           f'<div class="zone" style="left:{x(plan["entry_low"]):.1f}%;width:{max(x(plan["entry_high"]) - x(plan["entry_low"]), 1):.1f}%"></div>',
           f'<div class="tick" style="left:{x(plan["stop"]):.1f}%;background:{RISK}"></div>',
           f'<div class="tick" style="left:{x(plan["price"]):.1f}%;background:{INK};box-shadow:0 0 8px {INK};height:28px;top:16px"></div>',
           f'<div class="lbl top" style="left:{x(plan["price"]):.1f}%;color:{INK}">NOW {plan["price"]:.2f}</div>',
           f'<div class="lbl bot" style="left:{x(plan["stop"]):.1f}%;color:{RISK}">STOP {plan["stop"]:.2f}</div>']
    zone_mid = x((plan["entry_low"] + plan["entry_high"]) / 2)
    if not exit_only and abs(zone_mid - x(plan["price"])) >= 18:
        out.append(f'<div class="lbl top" style="left:{zone_mid:.1f}%;color:{OPP}">ZONE</div>')
    if not exit_only:
        for i, t in enumerate(plan["targets"]):
            out.append(f'<div class="tick" style="left:{x(t["price"]):.1f}%;background:{INFO}"></div>')
            if abs(x(t["price"]) - x(plan["stop"])) >= 16 and (i == 0 or abs(x(t["price"]) - x(plan["targets"][0]["price"])) >= 16):
                out.append(f'<div class="lbl bot" style="left:{x(t["price"]):.1f}%;color:{INFO}">T{i + 1} {t["price"]:.2f}</div>')
    return "".join(out) + "</div>"


def trade_plan(plan: dict, sizing: dict | None, risk_pct: float, portfolio_value: float) -> str:
    if not plan:
        return ""
    color = STANCE_COLOR.get(plan["stance"], INFO)
    bias, bias_color = BIAS_GLYPH.get(plan["bias"], ("◆ neutral", INFO))
    price = plan["price"]
    exit_only = plan["stance"] in ("REDUCE / EXIT", "NO TRADE")

    def rel(v):
        return f"{v:.2f} <small style='color:{MUTED}'>({(v / price - 1) * 100:+.1f}%)</small>"

    zone_label = {"ADD": "Add zone", "HOLD": "Add on dips", "TRIM": "Re-buy zone", "WAIT FOR CONFIRMATION": "Entry zone",
                  "REDUCE / EXIT": "Support zone", "NO TRADE": "Support zone"}.get(plan["stance"], "Entry zone")
    rows = [] if exit_only else [(zone_label, f"{plan['entry_low']:.2f} - {plan['entry_high']:.2f}")]
    if plan.get("trigger"):
        rows.append(("Trigger", escape(plan["trigger"])))
    rows.append(("Stop", rel(plan["stop"]) + f"<br><small style='color:{MUTED}'>{escape(plan['stop_basis'])}</small>"))
    if not exit_only:
        for i, t in enumerate(plan["targets"]):
            r = f" · {t['r']:.1f}R" if t.get("r") else ""
            rows.append((f"Target {i + 1}", rel(t["price"]) + f"<br><small style='color:{MUTED}'>{escape(t['label'])}{r}</small>"))
        rows.append(("Reward / risk", f"{plan['rr']:.1f} : 1"))
    rows.append(("Horizon", escape(plan["horizon"])))
    if plan.get("timeframe") and not exit_only:
        rows.append(("Timeframe", escape(plan["timeframe"])))
    grid = "".join(f"<div><span>{k}</span><em style='font-style:normal;text-align:right'>{v}</em></div>" for k, v in rows)

    size_html = ""
    if sizing and not exit_only:
        size_html = (f"<p style='font-size:.82rem;color:var(--soft)'>Sizing: risking {risk_pct:g}% of your "
                     f"{money(portfolio_value)} portfolio ({money(sizing['budget'])}) means about "
                     f"<b style='color:var(--ink)'>{sizing['shares']:.1f} shares</b> ({money(sizing['value'])})"
                     + (" — capped by the tier's maximum position size" if sizing["capped"] else "") + ".</p>")
    notes = "".join(f"<p class='note'>⚠ {escape(n)}</p>" for n in plan.get("notes", []))
    hist_html = history_check(plan.get("history")) if not exit_only else ""
    fwd = plan.get("forward") or []
    fwd_html = (f'<div class="lab" style="margin-top:.7rem">WHERE THE COMPANY IS HEADING</div>'
                f'<p style="margin-top:.25rem">{escape(" ".join(fwd))}</p>') if fwd else ""
    exits = "".join(f"<li>{escape(e)}</li>" for e in plan["exits"])
    return (f'<div class="mc-tp"><div class="hd"><div><div class="lab">TRADE PLAN</div>'
            f'<div class="stance" style="color:{color}">{escape(plan["stance"])}</div></div>'
            f'<span class="mc-chip" style="--c:{bias_color}">{bias}</span></div>'
            f'{_ladder(plan)}<div class="mc-kv" style="margin-top:.2rem">{grid}</div>'
            f'<p>{escape(plan["outlook"])}</p>{fwd_html}{hist_html}{notes}{size_html}'
            f'<div class="lab" style="margin-top:.7rem">{"WHAT WOULD CHANGE THE PLAN" if plan["stance"] == "NO TRADE" else "WHEN TO SELL"}</div><ol>{exits}</ol>'
            f'<div class="fine">Rule-based levels from price structure and volatility, not a forecast or financial advice. '
            f'Check them against the chart before placing an order.</div></div>')


def _segbar(parts: list[tuple[str, float, str]]) -> str:
    """Stacked bar with a text legend, so the split is readable without relying on color."""
    total = sum(v for _, v, _ in parts) or 1
    bar = "".join(f'<i style="width:{v / total * 100:.1f}%;background:{c}"></i>' for _, v, c in parts if v > 0)
    legend = "".join(f'<span><span style="color:{c}">■</span> {escape(l)} <b>{v / total * 100:.0f}%</b></span>'
                     for l, v, c in parts)
    return f'<div class="mc-seg">{bar}</div><div class="mc-legend">{legend}</div>'


def history_check(h: dict | None) -> str:
    if not h:
        return ""
    when = h.get("median_days_to_target")
    detail = (f"Median {when:.0f} trading days to the target; median return after {h['horizon_days']} days "
              f"{h['median_return'] * 100:+.1f}%." if when else
              f"Median return after {h['horizon_days']} days {h['median_return'] * 100:+.1f}%.")
    return (f'<div class="lab" style="margin-top:.7rem">OLDER SCENARIOS · {h["n"]} SIMILAR SETUPS</div>'
            f'<p style="margin:.2rem 0;font-size:.8rem;color:var(--soft)">Matched on {escape(h["match"])}'
            + (" (loosened to find enough cases)" if h.get("loose") else "") + "; replaying this plan's stop and target.</p>"
            + _segbar([("target first", h["win_rate"], OPP), ("stop first", h["loss_rate"], RISK),
                       ("neither", h["neither_rate"], MUTED)])
            + f'<p style="font-size:.8rem;color:var(--soft);margin-top:.35rem">{escape(detail)}</p>')


def outlook(st: dict, price: float) -> str:
    """Street view, forward estimates, 3-12 month scenarios and the earnings setup."""
    if not st:
        return ""
    out = ['<div class="mc-tp">']
    c = st.get("consensus")
    if c:
        out.append(f'<div class="lab">STREET VIEW · {c["analysts"]} ANALYSTS</div>'
                   f'<div class="stance">{escape(c["label"])}</div>'
                   + _segbar([("buy", c["buy"], OPP), ("hold", c["hold"], INFO), ("sell", c["sell"], RISK)]))
        if c.get("change_3m") is not None and abs(c["change_3m"]) >= 0.15:
            out.append(f'<p style="font-size:.8rem;color:var(--soft)">'
                       f'{"More bullish" if c["change_3m"] < 0 else "More cautious"} than three months ago.</p>')
    tg = st.get("targets") or {}
    if all(tg.get(k) for k in ("low", "median", "high")):
        out.append('<div class="lab" style="margin-top:.8rem">PRICE TARGETS (12 MONTHS)</div>'
                   + fair_value_bar({"low": tg["low"], "mid": tg["median"], "high": tg["high"]}, price)
                   .replace("fair ", "median "))
    g = st.get("growth") or {}
    names = {"0q": "This quarter", "+1q": "Next quarter", "0y": "This year", "+1y": "Next year"}
    rows = [[names.get(k, k), pct((v or {}).get("eps")), pct((v or {}).get("revenue")),
             str(int(v["analysts"])) if (v or {}).get("analysts") else "—"] for k, v in g.items()]
    if rows:
        out.append('<div class="lab" style="margin-top:.4rem">EXPECTED GROWTH</div>'
                   + table(["Period", "EPS growth", "Revenue growth", "Analysts"], rows))
    r = st.get("revisions") or {}
    if r.get("eps_30d") is not None or r.get("up30") is not None:
        bits = []
        if r.get("eps_30d") is not None:
            bits.append(f"EPS estimate {pct(r['eps_30d'], digits=1)} in 30 days")
        if r.get("eps_90d") is not None:
            bits.append(f"{pct(r['eps_90d'], digits=1)} in 90 days")
        if r.get("up30") is not None:
            bits.append(f"{r['up30']} raised / {r.get('down30') or 0} cut this month")
        out.append(f'<p style="font-size:.84rem"><b>Estimate revisions:</b> {escape(", ".join(bits))}.</p>')
    sc = st.get("scenarios") or []
    if sc:
        out.append('<div class="lab" style="margin-top:.6rem">WHERE IT COULD BE</div>'
                   + table(["", "Bear", "Base", "Bull", "P(up)"],
                           [[f"{x['months']}m", num(x["bear"]), num(x["base"]), num(x["bull"]), f"{x['p_up']:.0%}"]
                            for x in sc])
                   + f'<p style="font-size:.74rem;color:var(--muted)">Bear and bull are the 16th and 84th percentiles '
                     f'using {escape(st.get("sigma_source") or "price history")} volatility '
                     f'({(st.get("sigma") or 0) * 100:.0f}% a year). The base case blends the median target with a '
                     f'market-average return, because targets tend to run optimistic.</p>')
    if st.get("implied_move_1m"):
        out.append(f'<p style="font-size:.84rem"><b>Options market:</b> expects about ±{st["implied_move_1m"] * 100:.0f}% '
                   f'over the next month.</p>')
    e = st.get("earnings_setup")
    if e:
        col = {"favourable": OPP, "unfavourable": RISK}.get(e["verdict"], INFO)
        items = "".join(f"<li>▲ {escape(x)}</li>" for x in e["for"]) + "".join(f"<li>▼ {escape(x)}</li>" for x in e["against"])
        imp = (f" Options price a ±{e['implied_move'] * 100:.0f}% move on the report." if e.get("implied_move") else "")
        out.append(f'<div class="mc-ev" style="--c:{col}"><div class="t">Next earnings in {e["days"]} days: '
                   f'setup looks {escape(e["verdict"])}</div><ul>{items or "<li>No strong signals either way.</li>"}</ul>'
                   + (f'<p style="font-size:.8rem;color:var(--soft);margin:.3rem 0 0">{escape(e["note"])}</p>' if e.get("note") else "")
                   + (f'<p style="font-size:.8rem;color:var(--soft);margin:.3rem 0 0">{escape(imp.strip())}</p>'
                      if imp and not e.get("note") else "")
                   + "</div>")
    out.append("</div>")
    return "".join(out)


TONE = {"positive": ("POS", OPP), "negative": ("NEG", RISK), "neutral": ("NEW", INFO)}


def news_list(items: list[dict], limit: int = 8) -> str:
    rows = []
    for n in items[:limit]:
        tag, col = TONE.get(n.get("tone"), TONE["neutral"])
        title = (f'<a href="{escape(n["url"])}" target="_blank">{escape(n["title"])}</a>' if n.get("url")
                 else escape(n["title"]))
        rows.append(f'<div class="mc-log mc-news"><span class="mc-tone" style="--c:{col}">{tag}</span>{title}<br>'
                    f'<small>{escape(n["published"][5:16].replace("T", " "))} · {escape(n.get("publisher") or "")}</small></div>')
    return "".join(rows)
