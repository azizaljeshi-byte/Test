"""StockWatch Mission Control: streamlit run dashboard.py"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from html import escape

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from stockwatch import technical, ui
from stockwatch.config import load_portfolio, to_yaml
from stockwatch.data import get_provider
from stockwatch.engine import evaluate
from stockwatch.relative import market_regime
from stockwatch.scanner import run_once
from stockwatch.store import Store

st.set_page_config(page_title="StockWatch · Mission Control", page_icon="🛸", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)


@st.cache_resource
def get_store() -> Store:
    return Store()


@st.cache_resource
def provider(name: str):
    return get_provider(name)


base = load_portfolio()
store = get_store()
data = provider("demo" if os.getenv("STOCKWATCH_DEMO") else base.settings.data_provider)
portfolio = store.apply_overrides(base)
tickers = {h.ticker for h in portfolio.holdings}


def scan_now():
    run_once(portfolio, data, store)
    st.session_state.last_auto = time.time()


snaps = [s for s in store.latest_snapshots() if s["ticker"] in tickers]
last_scan = max((s["scanned_at"] for s in snaps), default=None)
st.markdown(ui.header(f"{len(tickers)} targets · last sweep {last_scan[5:16].replace('T', ' ') + ' UTC' if last_scan else 'never'}"),
            unsafe_allow_html=True)

# ---------------------------------------------------------------- controls
c1, c2, c3 = st.columns([1.2, 1.3, 1])
if c1.button("⟳ Sweep now", use_container_width=True):
    with st.spinner("Sweeping targets..."):
        scan_now()
    st.rerun()
auto = c2.toggle("Auto-sweep", value=False, help="Re-scans on an interval while this page is open.")
interval = c3.selectbox("Every", [5, 15, 30, 60], index=1, format_func=lambda m: f"{m} min", label_visibility="collapsed")

if auto:
    @st.fragment(run_every="60s")
    def _auto():
        if time.time() - st.session_state.get("last_auto", 0) >= interval * 60:
            scan_now()
            st.rerun()
    _auto()

if not snaps:
    st.info("No telemetry yet. Hit **⟳ Sweep now** to run the first scan.")
    st.stop()

# ---------------------------------------------------------------- status tiles
try:
    reg = market_regime(data.history(portfolio.settings.benchmark))
    reg_color = {"RISK-ON": ui.OPP, "RISK-OFF": ui.RISK}.get(reg["state"], ui.WARN)
    market_tile = ("Market", reg["state"], f"SPY {ui.pct(reg['day_change'], digits=1)} today · {ui.pct(reg['vs_200d'])} vs 200d", reg_color)
except Exception:
    market_tile = ("Market", "NO SIGNAL", "benchmark unavailable", ui.MUTED)

urgent = [s for s in snaps if any(x["kind"] == "risk" and x["severity"] >= 3 for x in s["payload"]["signals"])]
opps = [s for s in snaps if s["verdict"] in ("OPPORTUNITY - ADD", "BUY SETUP")]
soon = [s for s in snaps if (s["payload"].get("events") or {}).get("days_to_earnings") is not None
        and s["payload"]["events"]["days_to_earnings"] <= 7]
held = [s for s in snaps if not s["payload"]["watchlist"]]
st.markdown(ui.tiles([
    market_tile,
    ("Red alerts", str(len(urgent)), " ".join(s["ticker"] for s in urgent[:4]) or "all clear", ui.RISK if urgent else ui.MUTED),
    ("Opportunities", str(len(opps)), " ".join(s["ticker"] for s in opps[:4]) or "none in range", ui.OPP if opps else ui.MUTED),
    ("Earnings ≤7d", str(len(soon)), " ".join(s["ticker"] for s in soon[:4]) or "quiet week", ui.WARN if soon else ui.MUTED),
]), unsafe_allow_html=True)

radar, target, log, fleet = st.tabs(["◉ Radar", "◎ Target", "≡ Log", "⊕ Fleet"])

# ---------------------------------------------------------------- radar
with radar:
    view = st.pills("Filter", ["All", "▼ Risk", "▲ Opportunity", "Held", "Watch"], default="All",
                    label_visibility="collapsed")
    shown = sorted(snaps, key=ui.urgency)
    if view == "▼ Risk":
        shown = [s for s in shown if any(x["kind"] == "risk" and x["severity"] >= 2 for x in s["payload"]["signals"])]
    elif view == "▲ Opportunity":
        shown = [s for s in shown if any(x["kind"] == "opportunity" and x["severity"] >= 2 for x in s["payload"]["signals"])]
    elif view == "Held":
        shown = [s for s in shown if not s["payload"]["watchlist"]]
    elif view == "Watch":
        shown = [s for s in shown if s["payload"]["watchlist"]]
    st.markdown(ui.cards(shown) if shown else f'<div class="mc-d">no targets match</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------- target detail
with target:
    order = [s["ticker"] for s in sorted(snaps, key=ui.urgency)]
    ticker = st.selectbox("Lock target", order)
    snap = next(s for s in snaps if s["ticker"] == ticker)
    p = snap["payload"]
    t, f, ev = p["technical"], p["fundamental"], p.get("events") or {}
    st.markdown(ui.cards([snap]), unsafe_allow_html=True)
    if p.get("name"):
        st.caption(p["name"])

    try:
        ind = technical.indicators(data.history(ticker)).iloc[-180:]
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.74, 0.26], vertical_spacing=0.04)
        fig.add_trace(go.Candlestick(x=ind.index, open=ind.Open, high=ind.High, low=ind.Low, close=ind.Close,
                                     name="Price", increasing_line_color=ui.OPP, decreasing_line_color=ui.RISK,
                                     increasing_fillcolor=ui.OPP, decreasing_fillcolor=ui.RISK), 1, 1)
        fig.add_trace(go.Scatter(x=ind.index, y=ind.SMA50, name="50-day", line=dict(width=2, color=ui.INFO)), 1, 1)
        fig.add_trace(go.Scatter(x=ind.index, y=ind.SMA200, name="200-day", line=dict(width=2, color=ui.WARN)), 1, 1)
        fig.add_trace(go.Scatter(x=ind.index, y=ind.RSI, name="RSI", line=dict(width=2, color=ui.INFO),
                                 showlegend=False), 2, 1)
        fig.add_hrect(y0=30, y1=70, fillcolor="rgba(54,197,240,0.06)", line_width=0, row=2, col=1)
        grid = "rgba(95,135,150,0.15)"
        fig.update_layout(height=430, margin=dict(l=0, r=0, t=24, b=0), xaxis_rangeslider_visible=False,
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", hovermode="x unified",
                          font=dict(family="Share Tech Mono, monospace", color=ui.INK, size=11),
                          legend=dict(orientation="h", y=1.06, x=0, bgcolor="rgba(0,0,0,0)"))
        fig.update_xaxes(gridcolor=grid, zeroline=False)
        fig.update_yaxes(gridcolor=grid, zeroline=False)
        fig.update_yaxes(title_text="RSI", range=[0, 100], row=2, col=1)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    except Exception as e:
        st.warning(f"Chart offline: {e}")

    st.markdown('<div class="mc-section">Signals</div>', unsafe_allow_html=True)
    st.markdown("".join(f'<div class="mc-log">{ui.signal_glyph(s["kind"])}{"!" * s["severity"]} {escape(s["message"])} '
                        f'<small>· {s["source"]}</small></div>' for s in p["signals"])
                or '<div class="mc-d">no signals</div>', unsafe_allow_html=True)

    st.markdown('<div class="mc-section">Readouts</div>', unsafe_allow_html=True)
    kv = [
        ("Trend", (t.get("trend") or "—").upper()), ("RSI", ui.num(t.get("rsi"), ".0f")),
        ("vs SPY 1M", ui.pct(t.get("rs_spy_1m"))), ("vs SPY 3M", ui.pct(t.get("rs_spy_3m"))),
        (f"vs {t.get('sector_etf') or 'sector'} 3M", ui.pct(t.get("rs_sector_3m"))),
        ("From 52w high", ui.pct(t.get("drawdown_52w"))), ("50-day", ui.num(t.get("sma50"))),
        ("200-day", ui.num(t.get("sma200"))), ("Fwd P/E", ui.num(f.get("pe"), ".1f")), ("PEG", ui.num(f.get("peg"))),
        ("Rev growth", ui.pct(f.get("revenue_growth"))), ("Op margin", ui.pct(f.get("operating_margin"), signed=False)),
        ("Debt/Equity", ui.num(f.get("debt_to_equity"), ".1f")), ("Analyst upside", ui.pct(f.get("analyst_upside"))),
        ("Valuation", ui.num(f.get("pillar_valuation"), ".0f")), ("Growth", ui.num(f.get("pillar_growth"), ".0f")),
        ("Quality", ui.num(f.get("pillar_quality"), ".0f")), ("Balance", ui.num(f.get("pillar_balance"), ".0f")),
        ("Earnings", f"{ev['earnings_date']} (T-{ev['days_to_earnings']}d)" if ev.get("earnings_date") else "—"),
    ]
    st.markdown('<div class="mc-kv">' + "".join(f"<div><span>{escape(k)}</span>{escape(v)}</div>" for k, v in kv)
                + "</div>", unsafe_allow_html=True)

    if ev.get("rating_changes"):
        st.markdown('<div class="mc-section">Analyst moves</div>', unsafe_allow_html=True)
        st.markdown("".join(
            f'<div class="mc-log"><small>{escape(str(r["date"]))}</small> {escape(str(r.get("firm") or "?"))} · '
            f'{escape(str(r.get("action") or "").upper())} {escape(str(r.get("from_grade") or ""))} → '
            f'{escape(str(r.get("to_grade") or ""))}</div>' for r in ev["rating_changes"]), unsafe_allow_html=True)

    if ev.get("news"):
        st.markdown('<div class="mc-section">Incoming transmissions</div>', unsafe_allow_html=True)
        st.markdown("".join(
            f'<div class="mc-log mc-news"><small>{escape(n["published"][5:16].replace("T", " "))} · '
            f'{escape(n.get("publisher") or "")}</small><br>'
            + (f'<a href="{escape(n["url"])}" target="_blank">{escape(n["title"])}</a>' if n.get("url") else escape(n["title"]))
            + "</div>" for n in ev["news"]), unsafe_allow_html=True)

# ---------------------------------------------------------------- alert log
with log:
    alerts = [a for a in store.recent_alerts(150) if a["ticker"] in tickers]
    if not alerts:
        st.markdown('<div class="mc-d">no transmissions yet</div>', unsafe_allow_html=True)
    st.markdown("".join(
        f'<div class="mc-log"><small>{a["created_at"][5:16].replace("T", " ")}</small> '
        f'{ui.signal_glyph(a["kind"])}<b>{escape(a["ticker"])}</b> @ {a["price"]:.2f} — {escape(a["message"])}</div>'
        for a in alerts), unsafe_allow_html=True)

# ---------------------------------------------------------------- fleet management
with fleet:
    st.markdown('<div class="mc-section">Add targets</div>', unsafe_allow_html=True)
    with st.form("add", clear_on_submit=True, border=False):
        raw = st.text_input("Tickers", placeholder="e.g. PLTR, AMZN, TSM")
        a, b = st.columns(2)
        tier = a.radio("Tier", [1, 2], horizontal=True, format_func=lambda x: f"T{x} {'core' if x == 1 else 'tactical'}")
        shares = b.number_input("Shares (0 = watchlist)", min_value=0.0, value=0.0, step=1.0)
        submitted = st.form_submit_button("⊕ Add to fleet", use_container_width=True)
    if submitted and raw.strip():
        for sym in [x.strip().upper() for x in raw.replace(" ", ",").split(",") if x.strip()]:
            try:
                data.history(sym)  # confirms the symbol exists before saving it
            except Exception:
                st.error(f"{sym}: no market data found - check the symbol")
                continue
            store.upsert_ticker(sym, tier, shares)
            h = next(h for h in store.apply_overrides(base).holdings if h.ticker == sym)
            store.save_snapshot(evaluate(h, portfolio, data))
            st.success(f"{sym} locked on radar")
        st.rerun()

    st.markdown('<div class="mc-section">Remove targets</div>', unsafe_allow_html=True)
    drop = st.multiselect("Remove", sorted(tickers), label_visibility="collapsed", placeholder="Pick tickers to remove")
    if st.button("✕ Remove selected", disabled=not drop):
        for sym in drop:
            store.remove_ticker(sym)
        st.rerun()

    st.markdown('<div class="mc-section">Make it permanent</div>', unsafe_allow_html=True)
    st.caption("Changes here are saved in the app's database, which Streamlit Cloud wipes on a reboot or redeploy. "
               "To keep them, paste this into the app's STOCKWATCH_PORTFOLIO secret (between the triple quotes).")
    st.code(to_yaml(portfolio), language="yaml")
