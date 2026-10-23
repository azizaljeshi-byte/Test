"""Mission Control look for the dashboard: theme CSS and HTML builders for the cards."""
from __future__ import annotations

import math
import re
from html import escape

from . import status
from .transitions import effective_stance

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

/* ---- radar scope */
.mc-scope { position:relative; width:100%; max-width:440px; aspect-ratio:1; margin:.4rem auto .2rem; }
.mc-scope .disc { position:absolute; inset:3.5%; border-radius:50%; border:1px solid var(--line); overflow:hidden; }
.mc-scope .sw { position:absolute; inset:0; border-radius:50%; animation: sweep 4s linear infinite;
  background: conic-gradient(from 0deg, rgba(61,255,168,.26), rgba(61,255,168,0) 60deg, transparent 360deg); }
.mc-scope .ring { position:absolute; border-radius:50%; box-sizing:border-box; pointer-events:none; }
.mc-scope .r2 { inset:14%; border:1px dashed var(--line); }
.mc-scope .r1 { inset:26%; border:1px solid rgba(61,255,168,.35); background:rgba(61,255,168,.04); }
.mc-scope .spoke { position:absolute; left:50%; top:50%; width:1px; height:46.5%; background:var(--line); transform-origin:top center; }
.mc-scope .sec { position:absolute; font-family:var(--mono); font-size:.62rem; letter-spacing:.1em; }
.mc-scope .blip { position:absolute; width:32px; height:30px; margin:-8px 0 0 -16px; display:flex; flex-direction:column;
  align-items:center; gap:1px; z-index:2; cursor:pointer; -webkit-tap-highlight-color:transparent; }
.mc-pvr { position:absolute; width:1px; height:1px; opacity:0; pointer-events:none; }
.mc-pvs .hint { text-align:center; color:var(--muted); font-size:.78rem; margin:.1rem 0 .6rem; }
.mc-pvr:not(#pv-none):checked ~ .mc-pvs .hint { display:none; }
.mc-pv { display:none; margin:.2rem 0 .9rem; animation: pv-in .18s ease-out; }
.mc-pv .mc-li { border-color:var(--a); box-shadow:0 10px 30px -18px var(--a); border-radius:16px 16px 0 0; }
.mc-pv .foot { display:flex; justify-content:space-between; align-items:center; border:1px solid var(--a); border-top:0;
  border-radius:0 0 16px 16px; background:var(--panel2); }
.mc-pv .foot label, .mc-pv .foot a { min-height:44px; display:flex; align-items:center; padding:0 .95rem; font-size:.86rem;
  cursor:pointer; text-decoration:none; }
.mc-pv .foot label { color:var(--muted); }
.mc-pv .foot a { color:var(--info); font-weight:600; }
@keyframes pv-in { from { opacity:0; transform:translateY(-4px); } }
.mc-scope .blip b { width:9px; height:9px; border-radius:50%; box-sizing:border-box; border:2px solid var(--c); color:var(--c); }
.mc-scope .blip.own b { background:var(--c); }
.mc-scope .blip span { font-family:var(--mono); font-size:.55rem; line-height:1; color:var(--soft); white-space:nowrap; }
.mc-scope .blip.far span { display:none; }
.mc-scope .blip.urgent b { animation: ping 1.6s ease-out infinite; }
.mc-scope .blip.dim { opacity:.14; }
.mc-scope .blip:hover span { color:var(--ink); }
@keyframes ping { 0% { box-shadow:0 0 0 0 var(--c); } 100% { box-shadow:0 0 0 7px transparent; } }
.mc-rl { justify-content:center; font-family:var(--sans); font-size:.7rem; margin-bottom:.5rem; }
.mc-rl span, .mc-li .mc-row > div { display:inline-flex; align-items:center; gap:.35rem; }
.mc-rl .k, .mc-li .k { width:9px; height:9px; border-radius:50%; box-sizing:border-box; border:2px solid var(--c, var(--soft)); flex:none; }
.mc-rl .k.own, .mc-li.own .k { background:var(--c, var(--soft)); }

/* ---- radar list (compact cards) */
.mc-list { display:grid; grid-template-columns:minmax(0,1fr); gap:.6rem; }
@media (min-width: 900px) { .mc-list { grid-template-columns:repeat(2,minmax(0,1fr)); } }
.mc-li { border:1px solid var(--line); border-radius:16px; padding:.8rem .95rem .85rem; background:var(--panel); transition:border-color .15s;
  position:relative; overflow:hidden; }
.mc-li::before { content:''; position:absolute; left:0; top:0; right:0; height:3px; background:var(--a); box-shadow:0 0 12px var(--a); }
a.mc-a:hover .mc-li { border-color:var(--a); }
.mc-li .call { display:flex; align-items:center; gap:.5rem; flex-wrap:wrap; margin-bottom:.35rem; }
.mc-li .act { font-family:var(--head); font-weight:700; font-size:1.15rem; letter-spacing:.04em; color:var(--a); }
.mc-li .call .mc-tag { margin-left:auto; }
.mc-li .new { font-family:var(--mono); font-size:.66rem; font-weight:600; }
.mc-li .new small { color:var(--muted); font-weight:400; }
.mc-li .id { min-width:0; }
.mc-li .mc-tk { font-size:1.2rem; }
.mc-li .nm { color:var(--soft); font-size:.8rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.mc-li .px { font-family:var(--mono); font-size:.92rem; color:var(--ink); margin:.35rem 0 .3rem; }
.mc-li .px small { color:var(--muted); font-size:.76rem; }
.mc-li .why { font-size:.9rem; line-height:1.45; color:var(--ink); display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
.mc-li .rg { font-family:var(--mono); font-size:.64rem; letter-spacing:.1em; font-weight:500; margin-right:.3rem; }
.mc-li .rg.r1 { color:var(--c); } .mc-li .rg.r2 { color:var(--soft); } .mc-li .rg.r3 { color:var(--muted); }
.mc-li .pl { font-family:var(--mono); font-size:.74rem; line-height:1.5; color:var(--soft); margin-top:.5rem; padding-top:.45rem;
  border-top:1px solid rgba(27,52,66,.8); }
.mc-li .pl b { color:var(--opp); font-weight:500; letter-spacing:.12em; margin-right:.35rem; }

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
/* ---- research lab: status flags and the synthetic-example marker */
.mc-flag { border:1px solid var(--line); border-left:4px solid var(--c); border-radius:10px; padding:.5rem .75rem;
  margin:.35rem 0 .6rem; color:var(--soft); font-size:.8rem; line-height:1.45; }
.mc-flag b { color:var(--c); font-family:var(--mono); letter-spacing:.05em; }
.mc-synth { color:var(--warn); font-family:var(--mono); font-size:.72rem; letter-spacing:.14em; text-transform:uppercase;
  border:1px dashed var(--warn); border-radius:8px; padding:.3rem .6rem; margin-bottom:.4rem; display:inline-block; }
.mc-tbl { overflow-x:auto; margin:.3rem 0 .6rem; }
.mc-tbl table { width:100%; border-collapse:collapse; font-size:.76rem; }
.mc-tbl th { color:var(--muted); font-weight:500; text-align:right; padding:.3rem .45rem; border-bottom:1px solid var(--line); white-space:nowrap; font-size:.7rem; }
.mc-tbl td { text-align:right; padding:.3rem .45rem; border-bottom:1px solid rgba(27,52,66,.6); color:var(--ink); white-space:nowrap; font-family:var(--mono); }
.mc-tbl th:first-child, .mc-tbl td:first-child { text-align:left; }
.mc-tbl tr.me td { color:var(--opp); }
.mc-tbl.wrap td:first-child { white-space:normal; font-family:var(--sans); }
.mc-tbl.wrapall td { white-space:normal; text-align:left; font-family:var(--sans); }
.mc-tbl.wrapall th { text-align:left; }
ul.cis-why { padding-left:1.1rem; margin:.2rem 0 .6rem; font-size:.85rem; }
ul.cis-why li { margin-bottom:.45rem; line-height:1.35; }
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

/* ---- turbo */
.mc-turbo { border:1px solid var(--c); border-radius:18px; padding:1rem 1.05rem; margin:.6rem 0 .9rem; position:relative; overflow:hidden;
  background: radial-gradient(ellipse at 0% 0%, color-mix(in srgb, var(--c) 16%, transparent), transparent 60%), var(--panel);
  box-shadow: 0 0 32px -16px var(--c); }
.mc-turbo .dec { font-family:var(--head); font-weight:700; font-size:1.9rem; line-height:1.05; color:var(--c); margin:.2rem 0; }
.mc-turbo .conf { font-family:var(--mono); font-size:.7rem; letter-spacing:.14em; color:var(--soft); }
.mc-turbo .line { font-family:var(--mono); font-size:.82rem; color:var(--ink); margin:.5rem 0 .2rem; }
.mc-turbo .cols { display:grid; grid-template-columns:minmax(0,1fr); gap:.4rem .9rem; margin-top:.6rem; }
@media (min-width: 760px) { .mc-turbo .cols { grid-template-columns:repeat(2,minmax(0,1fr)); } }
.mc-turbo .cols div { font-size:.84rem; line-height:1.5; }

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


def _price(snap: dict) -> tuple[float | None, str]:
    """The price to show (live during regular hours) and its change line, with any pre/after-hours trade."""
    p = snap["payload"]
    t = p.get("technical", {})
    day = t.get("day_change")
    q = p.get("quote") or {}
    live = q.get("market_state") == "REGULAR" and not nan(q.get("live_price"))
    price_now = q["live_price"] if live else snap["price"]
    if live and not nan(q.get("live_change")):
        day = q["live_change"]
    day_html = "" if nan(day) else (
        f' <small><i class="mc-g" style="color:{OPP if day >= 0 else RISK}">{"▲" if day >= 0 else "▼"}</i>{pct(day, digits=1)}</small>')
    if live and q.get("fetched_at"):
        day_html += f' <small style="color:{OPP}">· LIVE {q["fetched_at"][11:16]}</small>'
    if q.get("market_state") in ("PRE", "POST") and (nan(q.get("ext_price")) or q.get("ext_stale")):
        day_html += (f' <small style="color:{MUTED}">· {"PRE" if q["market_state"] == "PRE" else "AH"} '
                     f'no trades yet</small>')
    if not nan(q.get("ext_price")) and not nan(q.get("ext_change")):
        ch = q["ext_change"]
        label = "PRE" if q.get("ext_session") == "pre" else ("AH (last night)" if q.get("ext_stale") else "AH")
        day_html += (f' <small style="color:{MUTED}">· {label}</small> '
                     f'{q["ext_price"]:.2f} <small><i class="mc-g" style="color:{OPP if ch >= 0 else RISK}">'
                     f'{"▲" if ch >= 0 else "▼"}</i>{pct(ch, digits=1)}</small>')
    return price_now, day_html


def card(snap: dict, was: str | None = None) -> str:
    p = snap["payload"]
    t, ev = p.get("technical", {}), p.get("events") or {}
    color, glyph = VERDICT_STYLE.get(snap["verdict"], (MUTED, "●"))
    urgent = any(s["kind"] == "risk" and s["severity"] >= 3 for s in p["signals"])
    tag = "WATCH" if p["watchlist"] else f"T{snap['tier']}"
    price_now, day_html = _price(snap)
    meta = []
    if was:
        meta.append(f'<b style="color:{color}">● NEW</b> was {escape(was)}')
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
            f'<div class="mc-px">{num(price_now)}{day_html}</div>'
            f'{_bar({"SEC filings": "FUND·SEC", "Finnhub": "FUND·FH"}.get(p.get("fundamental", {}).get("source"), "FUND"), snap["fundamental_score"] if p.get("fundamental", {}).get("available", True) else None)}'
            f'{_bar("TECH", snap["technical_score"])}{_bar("Σ ALL", snap["composite"])}'
            f'<div class="mc-meta">{"".join(f"<span>{m}</span>" for m in meta)}</div>{sig}{plan_line(p.get("plan"))}</div></a>')


def cards(snaps: list[dict], changed: dict[str, str] | None = None) -> str:
    changed = changed or {}
    return f'<div class="mc-cards">{"".join(card(s, changed.get(s["ticker"])) for s in snaps)}</div>'


# ---- radar scope: direction is the verdict, distance from the middle is how soon the stock needs you
BUY_VERDICTS = ("OPPORTUNITY - ADD", "BUY SETUP")
RISK_VERDICTS = ("RISK - REVIEW", "TRIM / REVIEW", "AVOID")
# % of the scope's width from the centre, by ring and by how many lanes a crowded group is staggered over
LANES = {1: ([15], [12, 18], [9, 15, 21]), 2: ([30], [28, 32], [27, 30, 33]), 3: ([41.5], [39.5, 43.5], [38.5, 41.5, 44.5])}
RING_LABEL = {1: "ACT NOW", 2: "GETTING CLOSE", 3: "NOTHING TO DO"}
CLOSE = 0.03                                                           # "getting close" = within 3%


def sector(verdict: str) -> str:
    return "opp" if verdict in BUY_VERDICTS else "risk" if verdict in RISK_VERDICTS else "hold"


def ring(snap: dict) -> tuple[int, str]:
    """(1 act now | 2 getting close | 3 nothing to do, the reason in plain English).
    Reasons only ever back the card's verdict (a buy zone on a buy, an exit on a risk), never contradict it."""
    p = snap["payload"]
    side, plan = sector(snap["verdict"]), p.get("plan") or {}
    sigs = p.get("signals") or []
    days = (p.get("events") or {}).get("days_to_earnings")
    price, _ = _price(snap)
    stance = plan.get("stance")
    urgent = next((s for s in sigs if s["kind"] == "risk" and s["severity"] >= 3), None)
    if urgent:
        return 1, urgent["message"]
    if status.forces_exit(price_status(snap), p["watchlist"]):
        return 1, "support broke: exit the trade"
    if side == "risk" and stance == "REDUCE / EXIT":
        return 1, "the plan says reduce or exit"
    buying = side == "opp" and stance in ("BUY NOW", "BUY ON PULLBACK", "BUY THE BREAKOUT", "ADD")
    lo, hi = plan.get("entry_low"), plan.get("entry_high")
    in_reach = not (nan(price) or nan(lo) or nan(hi)) and lo > 0
    if buying and in_reach and lo <= price <= hi:
        return 1, "in the entry zone now"
    if days is not None and days <= 2:
        return 1, f"earnings in {days} day{'s' if days != 1 else ''}"
    if side == "opp" and in_reach and stance != "NO TRADE":
        gap = (price - hi) / hi if price > hi else (lo - price) / lo
        if gap <= CLOSE:
            return 2, f"{gap * 100:.1f}% from the entry zone"
    stop = plan.get("stop")
    if (not p["watchlist"] and side != "opp" and not (nan(price) or nan(stop)) and stop > 0
            and 0 <= (price - stop) / price <= CLOSE):
        return 2, f"{(price - stop) / price * 100:.1f}% above the stop"
    if side == "risk" and stance in ("TRIM", "TRIM / PROTECT"):
        return 2, "the plan says trim"
    if days is not None and days <= 7:
        return 2, f"earnings in {days} days"
    return 3, "nothing to do"


def _ring_sort(snap: dict) -> tuple:
    return (ring(snap)[0],) + urgency(snap)


def sectors(snaps: list[dict]) -> dict[str, tuple[float, float]]:
    """(start angle, width) per verdict wedge, 0 = top and clockwise. Buys sit at the top; wedges widen with their count."""
    n = {k: sum(1 for s in snaps if sector(s["verdict"]) == k) for k in ("opp", "hold", "risk")}
    width = {k: 60 + 180 * v / max(len(snaps), 1) for k, v in n.items()}
    opp = -width["opp"] / 2
    return {"opp": (opp, width["opp"]), "hold": (opp + width["opp"], width["hold"]),
            "risk": (opp + width["opp"] + width["hold"], width["risk"])}


def radar(snaps: list[dict], shown: set[str] | None = None) -> str:
    """The scope: one dot per stock. Tapping a dot previews it under the scope (hidden radios + CSS, no reload);
    the preview links to Details. Stocks outside the filter fade instead of vanishing."""
    groups: dict[tuple[str, int], list[dict]] = {}
    for s in sorted(snaps, key=lambda x: x["ticker"]):
        groups.setdefault((sector(s["verdict"]), ring(s)[0]), []).append(s)
    wedges = sectors(snaps)
    dots = []
    for (side, r), group in groups.items():
        start, width = wedges[side]
        pad = min(8, width / 8)
        lanes = LANES[r][0 if len(group) < 3 else 1 if len(group) <= 8 else 2]
        for i, s in enumerate(group):
            ang = math.radians(start + pad + (i + 0.5) * (width - 2 * pad) / len(group))
            dist = lanes[i % len(lanes)]
            x, y = 50 + dist * math.sin(ang), 50 - dist * math.cos(ang)
            color, _ = VERDICT_STYLE.get(s["verdict"], (MUTED, "●"))
            urgent = r == 1 and side != "hold"
            cls = "blip" + (" own" if not s["payload"]["watchlist"] else "") + (" urgent" if urgent else "") \
                + (" far" if r == 3 else "") + (" dim" if shown is not None and s["ticker"] not in shown else "")
            tk = escape(s["ticker"])
            dots.append(f'<label class="{cls}" for="pv-{_slug(s["ticker"])}" style="left:{x:.1f}%;top:{y:.1f}%;--c:{color}" '
                        f'title="{tk}: {escape(s["verdict"].lower())}, {escape(ring(s)[1])}"><b></b><span>{tk}</span></label>')
    spokes = "".join(f'<i class="spoke" style="transform:rotate({a + 180:.1f}deg)"></i>' for a, _ in wedges.values())
    o, h = wedges["opp"][1], wedges["hold"][1]
    tint = (f"conic-gradient(from {wedges['opp'][0]:.1f}deg, rgba(61,255,168,.07) 0 {o:.1f}deg, "
            f"rgba(54,197,240,.045) {o:.1f}deg {o + h:.1f}deg, rgba(255,77,122,.08) {o + h:.1f}deg 360deg)")
    ids = [_slug(x["ticker"]) for x in snaps]
    # no `checked` attribute: Streamlit renders through React, which locks a radio that has one
    radios = '<input type="radio" name="mc-pv" id="pv-none" class="mc-pvr" aria-label="Close preview">' + "".join(
        f'<input type="radio" name="mc-pv" id="pv-{i}" class="mc-pvr" aria-label="Preview {escape(x["ticker"])}">'
        for i, x in zip(ids, snaps))
    rules = "".join(f"#pv-{i}:checked~.mc-pvs #pvc-{i}{{display:block}}#pv-{i}:checked~.mc-scope label[for=pv-{i}]{{z-index:3}}"
                    f"#pv-{i}:checked~.mc-scope label[for=pv-{i}] b{{outline:2px solid var(--ink);outline-offset:3px}}"
                    f"#pv-{i}:checked~.mc-scope label[for=pv-{i}] span{{display:block;color:var(--ink);margin-top:5px}}" for i in ids)
    previews = "".join(
        f'<div class="mc-pv" id="pvc-{i}">{row(x)}<div class="foot"><label for="pv-none">✕ Close</label>'
        f'<a href="?view=target&t={escape(x["ticker"])}" target="_self">Open full details →</a></div></div>'
        for i, x in zip(ids, snaps))
    return (f'<div class="mc-radar-wrap"><style>{rules}</style>{radios}'
            f'<div class="mc-scope"><div class="disc" style="background:{tint}"><div class="sw"></div></div>'
            '<div class="ring r2"></div><div class="ring r1"></div>'
            f'{spokes}<span class="sec" style="left:50%;top:0;transform:translateX(-50%);color:{OPP}">▲ BUY ZONE</span>'
            f'<span class="sec" style="left:0;bottom:0;color:{RISK}">▼ RISK</span>'
            f'<span class="sec" style="right:0;bottom:0;color:{INFO}">● HOLD / WATCH</span>{"".join(dots)}</div>'
            '<div class="mc-legend mc-rl"><span><b class="k own"></b>Owned</span><span><b class="k"></b>Watchlist</span>'
            '<span>Middle: act now</span><span>Dashed ring: getting close</span><span>Edge: nothing to do</span></div>'
            f'<div class="mc-pvs"><div class="hint">Tap a dot for a quick look.</div>{previews}</div></div>')


def _slug(ticker: str) -> str:
    """A ticker as a safe HTML id (BRK.B -> BRK_B)."""
    return re.sub(r"[^A-Za-z0-9]", "_", ticker)


ACTIONS = {  # plan stance -> the plain call at the top of a list row, its glyph and color
    "BUY NOW": ("BUY NOW", "▲", OPP), "BUY ON PULLBACK": ("BUY ON DIP", "▲", OPP),
    "BUY THE BREAKOUT": ("BUY ON BREAKOUT", "▲", OPP), "ADD": ("BUY MORE", "▲", OPP),
    "WAIT FOR CONFIRMATION": ("WAIT", "◌", INFO), "HOLD": ("HOLD", "●", INFO), "NO TRADE": ("PASS", "✕", MUTED),
    "TRIM": ("SELL SOME", "◆", WARN), "TRIM / PROTECT": ("SELL SOME", "◆", WARN), "REDUCE / EXIT": ("SELL", "▼", RISK),
}


REBOUND = 0.03   # a sell call on a stock up this much today waits for the close instead of selling into the bounce


def _now(snap: dict) -> tuple[float | None, float | None, bool]:
    """(latest price including pre/after-hours, today's move, whether that's a live session)."""
    p = snap["payload"]
    q, day = p.get("quote") or {}, (p.get("technical") or {}).get("day_change")
    state = q.get("market_state")
    if state == "REGULAR" and not nan(q.get("live_price")):
        return q["live_price"], q.get("live_change"), True
    if state in ("PRE", "POST") and not nan(q.get("ext_price")) and not q.get("ext_stale"):
        ch = q.get("ext_change")
        if state == "POST" and not (nan(ch) or nan(day)):
            ch = (1 + day) * (1 + ch) - 1          # the regular session's move plus the after-hours one
        return q["ext_price"], ch, True
    return snap["price"], day, False


def reassess(snap: dict) -> str | None:
    """Why a sell call should wait, or None. Two cases: the trailing stop that triggered the sell has been
    retaken, or the stock is bouncing hard today. Either way the decision moves to the close, with one level."""
    if _action(snap)[0] not in ("SELL", "SELL SOME"):
        return None
    price, move, live = _now(snap)
    if nan(price):
        return None
    p = snap["payload"]
    trail = (p.get("technical") or {}).get("trailing_stop")
    tripped = not nan(trail) and any(x.get("code") == "atr_trailing_stop" for x in p.get("signals") or [])
    moved = "" if nan(move) else f", {pct(move, digits=1)} {'today' if live else 'in the last session'}"
    close = "near the close" if live else "at the next close"
    if tripped and price >= trail:
        return (f"Back above its trailing stop ({trail:.2f}) at {price:.2f}{moved}. Re-check {close} "
                f"and sell only if it closes below {trail:.2f}.")
    if not nan(move) and move >= REBOUND:
        rule = f" and sell if it closes below the trailing stop ({trail:.2f})" if tripped else " before acting"
        return f"Up {move * 100:.1f}% {'today' if live else 'in the last session'}. Re-check {close}{rule}."
    return None


def action(snap: dict) -> tuple[str, str, str]:
    """(call, glyph, color) for the list and preview: the plan's call, except that a sell on a stock that is
    recovering right now reads REASSESS (see `reassess`), so the app never says 'sell now' into a bounce."""
    if reassess(snap):
        return "REASSESS", "↻", WARN
    return _action(snap)


def _action(snap: dict) -> tuple[str, str, str]:
    """(call, glyph, color): buy / wait / hold / sell in plain words, from the same plan the verdict produced.
    Nothing to sell on a watchlist name, so a sell there reads PASS."""
    p = snap["payload"]
    if p.get("error") or snap["verdict"] == "ERROR":
        return "NO SIGNAL", "?", MUTED
    # the same reconciliation the Telegram decision-change alerts use
    stance = effective_stance(snap["verdict"], p.get("plan"), p["watchlist"], price_status(snap))
    return ACTIONS.get(stance, (stance, "●", INFO))


def row(snap: dict, was: str | None = None) -> str:
    """One list entry: the buy/sell call on top, then price, why it sits where it does on the radar, and the plan."""
    p = snap["payload"]
    color, _ = VERDICT_STYLE.get(snap["verdict"], (MUTED, "●"))
    call, glyph, acolor = action(snap)
    tag = f'<span class="mc-tag">OWNED · T{snap["tier"]}</span>' if not p["watchlist"] else ""
    price_now, day_html = _price(snap)
    r, why = ring(snap)
    top = p["signals"][0] if p["signals"] else None
    wait = reassess(snap)
    if p.get("error"):
        why_html = f'<span style="color:{MUTED}">signal lost: {escape(p["error"][:90])}</span>'
    elif wait:
        why_html = f'<b class="rg" style="color:{WARN}">DON\'T RUSH</b> {escape(wait)}'
    elif r < 3 or not top:
        why_html = f'<b class="rg r{r}">{RING_LABEL[r]}</b> {escape(why) if r < 3 else ""}'
    else:
        why_html = f'{signal_glyph(top["kind"])}{escape(top["message"])}'
    new = f'<span class="new" style="color:{color}">● NEW <small>was {escape(was)}</small></span>' if was else ""
    name = (p.get("profile") or {}).get("name") or p.get("name") or ""
    name = "" if name.upper() == snap["ticker"] else name
    from .tradeplan import summary
    plan = summary(p.get("plan"))
    return (f'<a class="mc-a" href="?view=target&t={escape(snap["ticker"])}" target="_self">'
            f'<div class="mc-li{" own" if not p["watchlist"] else ""}" style="--c:{color};--a:{acolor}">'
            f'<div class="call"><span class="act">{glyph} {escape(call)}</span>{new}{status_chip(snap)}{tag}</div>'
            f'<div class="mc-row"><div class="id"><b class="k"></b><span class="mc-tk">{escape(snap["ticker"])}</span>'
            f'<span class="nm">{escape(name)}</span></div></div>'
            f'<div class="px">{num(price_now)}{day_html}</div><div class="why">{why_html}</div>'
            + (f'<div class="pl"><b>{"IF IT FAILS" if wait else "PLAN"}</b>{escape(plan)}</div>' if plan else "") + '</div></a>')


STATUS_STYLE = {"record_high": (OPP, "★"), "strong_uptrend": (OPP, "↗"), "pullback": (INFO, "↘"),
                "weakening": (WARN, "▾"), "testing_support": (WARN, "◎"), "breakdown": (RISK, "✕"),
                "deep_breakdown": (RISK, "✕✕"), "unknown": (MUTED, "?")}


def price_status(snap: dict) -> dict | None:
    """The stored price status (see status.py), or None for a snapshot saved before it existed."""
    ps = ((snap.get("payload") or {}).get("technical") or {}).get("price_status")
    return ps if isinstance(ps, dict) and ps.get("code") else None


def status_chip(snap: dict) -> str:
    """A small chip with the status for the list. An unknown status stays off the list (Details says why)."""
    ps = price_status(snap)
    if not ps or ps["code"] == "unknown":
        return ""
    color, glyph = STATUS_STYLE.get(ps["code"], (MUTED, "●"))
    return f'<span class="mc-chip" style="--c:{color}"><b>{glyph}</b> {escape(ps.get("label") or ps["code"])}</span>'


def status_note(snap: dict) -> str:
    """The Details page's statement: where the price stands, what to do, and the levels behind it."""
    ps = price_status(snap)
    if not ps:
        return ""
    color, glyph = STATUS_STYLE.get(ps["code"], (MUTED, "●"))
    lv = ps.get("levels") or {}
    parts = [f'<div class="t">{glyph} {escape(ps.get("label") or ps["code"])}</div>',
             f'<div style="font-size:.86rem;line-height:1.5;margin-top:.2rem;color:var(--ink)">{escape(ps.get("why") or "")}'
             + ("" if ps["code"] == "unknown" else f' <b>{escape(ps.get("action") or "")}</b>') + "</div>"]
    prov = ps.get("provisional")
    if prov:
        parts.append(f'<div style="font-size:.8rem;margin-top:.3rem;color:{WARN}">{escape(prov["note"])}</div>')
    if ps.get("floor_known") and lv:
        parts.append(f'<div style="font-size:.76rem;margin-top:.35rem;color:{MUTED}">'
                     f'Support {lv["support_low"]:.2f} to {lv["support_high"]:.2f} · exit below {lv["exit_below"]:.2f} · '
                     f'deeper level {lv["deep_below"]:.2f} · high {lv["high"]:.2f} · {lv["years_of_data"]:g}y of data · '
                     f'as of {escape(str(lv["as_of"]))} close. Automatic levels, not reviewed.</div>')
    return f'<div class="mc-ev" style="--c:{color}">{"".join(parts)}</div>'


def reassess_note(snap: dict) -> str:
    """The Details page's version: a banner above the plan, so Details and the radar give the same answer."""
    wait = reassess(snap)
    return (f'<div class="mc-ev" style="--c:{WARN}"><div class="t">↻ Reassess before selling</div>'
            f'<div style="font-size:.86rem;line-height:1.5;margin-top:.2rem;color:var(--ink)">{escape(wait)} The sell plan below '
            f'still applies if it fails.</div></div>') if wait else ""


def rows(snaps: list[dict], changed: dict[str, str] | None = None) -> str:
    changed = changed or {}
    return f'<div class="mc-list">{"".join(row(s, changed.get(s["ticker"])) for s in sorted(snaps, key=_ring_sort))}</div>'


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


def market_card(r: dict, new: bool = False) -> str:
    color, glyph = VERDICT_STYLE.get(r["verdict"], (MUTED, "●"))
    trig = "".join(f'<div class="mc-sig" style="border:0;padding-top:.1rem;margin-top:.1rem">'
                   f'{signal_glyph("opportunity")}{escape(t)}</div>' for t in r["triggers"][:2])
    risks = "".join(f'<div class="mc-sig" style="border:0;padding-top:.1rem;margin-top:.1rem;color:var(--soft)">'
                    f'{signal_glyph("risk")}{escape(t)}</div>' for t in r.get("top_risks", [])[:1])
    meta = [f"{escape(r.get('sector') or '')}"]
    if new:
        meta.insert(0, f'<b style="color:{OPP}">● NEW SETUP</b>')
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


def table(headers: list[str], rows: list[list], highlight: int | None = None, wrap: bool = False,
          wrap_all: bool = False) -> str:
    """wrap=True lets the first column wrap, for tables with long labels on a phone; wrap_all=True lets every
    column wrap, for tables of sentences."""
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(f'<tr{" class=me" if i == highlight else ""}>' + "".join(f"<td>{escape(str(c))}</td>" for c in r) + "</tr>"
                   for i, r in enumerate(rows))
    cls = " wrap" * wrap + " wrapall" * wrap_all
    return (f'<div class="mc-tbl{cls}"><table><thead><tr>{head}</tr></thead>'
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
                "WAIT FOR CONFIRMATION": INFO, "HOLD": INFO, "TRIM": WARN, "TRIM / PROTECT": WARN,
                "REDUCE / EXIT": RISK, "NO TRADE": RISK}
BIAS_GLYPH = {"bullish": ("▲ bullish", OPP), "bearish": ("▼ bearish", RISK), "neutral": ("◆ neutral", INFO),
              "mixed": ("◆ short-term down · long-term up", WARN)}


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

    zone_label = {"ADD": "Add zone", "HOLD": "Add on dips", "TRIM": "Re-buy zone", "TRIM / PROTECT": "Re-buy zone", "WAIT FOR CONFIRMATION": "Entry zone",
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


DECISION_COLOR = {"BUY": OPP, "WAIT FOR PULLBACK": WARN, "WAIT FOR TRIGGER": INFO, "PASS": RISK}


def turbo_card(d: dict, deep: bool) -> str:
    col = DECISION_COLOR.get(d["decision"], INFO)
    m = d["momentum"]
    tape = []
    if not nan(m.get("price")):
        tape.append(f"<b>{m['price']:.2f}</b>")
    if not nan(m.get("day_change")):
        tape.append(f'<span style="color:{OPP if m["day_change"] >= 0 else RISK}">'
                    f'{"▲" if m["day_change"] >= 0 else "▼"} {m["day_change"] * 100:+.1f}% today</span>')
    if not nan(m.get("vwap")):
        tape.append(f"VWAP {m['vwap']:.2f}")
    if not nan(m.get("rel_volume")):
        tape.append(f"rel. volume {m['rel_volume']:.1f}x")
    if not nan(m.get("extension_atr")):
        tape.append(f"{m['extension_atr']:+.1f} ATR vs 20-day")
    pros = "".join(f"<li>{escape(x)}</li>" for x in d["pros"]) or "<li>none stand out</li>"
    cons = "".join(f"<li>{escape(x)}</li>" for x in d["cons"]) or "<li>none stand out</li>"
    notes = "".join(f'<p style="font-size:.82rem;color:var(--soft);margin:.3rem 0">{escape(n)}</p>' for n in d["notes"])
    return (f'<div class="mc-turbo" style="--c:{col}">'
            f'<div class="mc-row"><div><span class="mc-tk">{escape(d["ticker"])}</span>'
            f'<span class="mc-name">{escape(d.get("name") or "")}</span></div>'
            f'<span class="mc-chip" style="--c:{col}">⚡ TURBO{"" if deep else " · quick read"}</span></div>'
            f'<div class="dec">{escape(d["decision"])}</div>'
            f'<div class="conf">CONFIDENCE {escape(d["confidence"].upper())} · VERDICT {escape(d["verdict"])} · '
            f'SCORE {d["composite"]:.0f}</div>'
            f'<div class="line">{escape(d["line"])}</div>'
            f'<div class="mc-meta" style="font-size:.74rem">{" · ".join(tape)}</div>{notes}'
            f'<div class="cols"><div><div class="lab" style="font-family:var(--mono);font-size:.62rem;letter-spacing:.2em;color:{OPP}">FOR</div><ul style="margin:.2rem 0 0;padding-left:1.1rem">{pros}</ul></div>'
            f'<div><div class="lab" style="font-family:var(--mono);font-size:.62rem;letter-spacing:.2em;color:{RISK}">AGAINST</div><ul style="margin:.2rem 0 0;padding-left:1.1rem">{cons}</ul></div></div>'
            f'</div>')


RESEARCH_STATUS = {"INSUFFICIENT EVIDENCE": WARN, "computed research scenarios": INFO, "ASSUMPTIONS REQUIRED": WARN,
                   "UNAVAILABLE": MUTED, "INCOMPLETE": WARN, "READY TO CHECK": INFO}


def flag(status: str, text: str, color: str | None = None) -> str:
    """A research status line: the status in its color, then the plain-English reason (already escaped)."""
    c = color or RESEARCH_STATUS.get(status, MUTED)
    return f'<div class="mc-flag" style="--c:{c}"><b>{escape(status)}</b> · {text}</div>'
