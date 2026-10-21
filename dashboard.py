"""StockWatch dashboard: streamlit run dashboard.py"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from stockwatch import technical
from stockwatch.config import load_portfolio
from stockwatch.data import get_provider
from stockwatch.scanner import run_once
from stockwatch.store import Store

st.set_page_config(page_title="StockWatch", page_icon="📈", layout="wide")

VERDICT_COLORS = {
    "OPPORTUNITY - ADD": "#1a7f37", "BUY SETUP": "#1a7f37", "STRONG HOLD": "#2da44e",
    "HOLD": "#6e7781", "WATCH": "#6e7781", "TRIM / REVIEW": "#bf8700",
    "RISK - REVIEW": "#cf222e", "AVOID": "#cf222e", "ERROR": "#8250df",
}


@st.cache_resource
def get_store() -> Store:
    return Store()


def provider_name(portfolio) -> str:
    return "demo" if os.getenv("STOCKWATCH_DEMO") else portfolio.settings.data_provider


portfolio = load_portfolio()
store = get_store()

with st.sidebar:
    st.title("📈 StockWatch")
    st.caption(f"Portfolio: `{portfolio.source.name}` · data: `{provider_name(portfolio)}`")
    auto = st.toggle("Auto-scan while open", value=False,
                     help="Re-runs the scan on an interval. For 24/7 monitoring run the scanner process instead.")
    interval = st.number_input("Interval (minutes)", 1, 240, portfolio.settings.scan_interval_minutes)
    if st.button("🔄 Scan now", use_container_width=True, type="primary"):
        with st.spinner("Scanning..."):
            run_once(portfolio, get_provider(provider_name(portfolio)), store)
    tier_filter = st.multiselect("Tiers", [1, 2], default=[1, 2])
    show_watch = st.checkbox("Include watchlist", value=True)

if auto:
    @st.fragment(run_every=f"{int(interval)}m")
    def _auto_scan():
        run_once(portfolio, get_provider(provider_name(portfolio)), store)
    _auto_scan()

snaps = store.latest_snapshots()
if not snaps:
    st.info("No scans yet. Click **Scan now** in the sidebar, or run `python -m stockwatch.scanner`.")
    st.stop()

snaps = [s for s in snaps if s["tier"] in tier_filter and (show_watch or not s["payload"]["watchlist"])]
last_scan = max(s["scanned_at"] for s in snaps) if snaps else "-"

# ---------------------------------------------------------------- summary
held = [s for s in snaps if not s["payload"]["watchlist"] and not s["payload"]["error"]]
total_value = sum(s["payload"]["position"].get("value", 0) for s in held)
cost = sum((s["payload"]["position"].get("cost_basis") or 0) * s["payload"]["position"]["shares"] for s in held)
n_risk = sum(any(x["kind"] == "risk" and x["severity"] >= 3 for x in s["payload"]["signals"]) for s in snaps)
n_opp = sum(s["verdict"] in ("OPPORTUNITY - ADD", "BUY SETUP") for s in snaps)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Portfolio value", f"${total_value:,.0f}",
          f"{total_value / cost - 1:+.1%} vs cost" if cost else None)
c2.metric("Positions / watchlist", f"{len(held)} / {sum(s['payload']['watchlist'] for s in snaps)}")
c3.metric("🟢 Opportunities", n_opp)
c4.metric("🔴 Urgent risks", n_risk)
c5.metric("Last scan (UTC)", last_scan[11:16] if len(last_scan) > 11 else last_scan, last_scan[:10], delta_color="off")

# ---------------------------------------------------------------- table
def fmt_pct(v):
    return None if v is None or pd.isna(v) else v * 100

rows = []
for s in snaps:
    p = s["payload"]
    t, f, pos = p["technical"], p["fundamental"], p["position"]
    top = next(iter(p["signals"]), None)
    rows.append({
        "Ticker": s["ticker"], "Tier": s["tier"], "Type": "Watch" if p["watchlist"] else "Held",
        "Verdict": s["verdict"], "Price": s["price"],
        "Composite": s["composite"], "Fundamental": s["fundamental_score"], "Technical": s["technical_score"],
        "Trend": t.get("trend"), "RSI": t.get("rsi"),
        "P/L %": fmt_pct(pos.get("pnl_pct")), "Weight %": pos.get("weight_pct"),
        "1M %": fmt_pct(t.get("ret_1m")), "Fwd P/E": f.get("pe"),
        "Rev growth %": fmt_pct(f.get("revenue_growth")), "Top signal": top["message"] if top else "",
    })
df = pd.DataFrame(rows)

def color_verdict(v):
    return f"background-color: {VERDICT_COLORS.get(v, '#6e7781')}; color: white; font-weight: 600"

st.subheader("Holdings & watchlist")
score_cfg = dict(min_value=0, max_value=100, format="%.0f")
st.dataframe(
    df.style.map(color_verdict, subset=["Verdict"]),
    hide_index=True, use_container_width=True,
    column_config={
        "Price": st.column_config.NumberColumn(format="%.2f"),
        "Composite": st.column_config.ProgressColumn(**score_cfg),
        "Fundamental": st.column_config.ProgressColumn(**score_cfg),
        "Technical": st.column_config.ProgressColumn(**score_cfg),
        "RSI": st.column_config.NumberColumn(format="%.0f"),
        "P/L %": st.column_config.NumberColumn(format="%+.1f"),
        "Weight %": st.column_config.NumberColumn(format="%.1f"),
        "1M %": st.column_config.NumberColumn(format="%+.1f"),
        "Fwd P/E": st.column_config.NumberColumn(format="%.1f"),
        "Rev growth %": st.column_config.NumberColumn(format="%+.1f"),
    },
)

# ---------------------------------------------------------------- detail + alerts
left, right = st.columns([3, 2])

with left:
    st.subheader("Stock detail")
    ticker = st.selectbox("Ticker", [s["ticker"] for s in snaps])
    snap = next(s for s in snaps if s["ticker"] == ticker)
    p = snap["payload"]
    st.markdown(f"**{p.get('name') or ticker}** · Tier {snap['tier']} · "
                f"<span style='color:{VERDICT_COLORS.get(snap['verdict'])};font-weight:700'>{snap['verdict']}</span>",
                unsafe_allow_html=True)

    try:
        hist = get_provider(provider_name(portfolio)).history(ticker).iloc[-260:]
        ind = technical.indicators(hist)
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03)
        fig.add_trace(go.Candlestick(x=ind.index, open=ind.Open, high=ind.High, low=ind.Low, close=ind.Close,
                                     name="Price", showlegend=False), 1, 1)
        for col, color in (("SMA50", "#0969da"), ("SMA200", "#bf8700")):
            fig.add_trace(go.Scatter(x=ind.index, y=ind[col], name=col, line=dict(width=1.4, color=color)), 1, 1)
        fig.add_trace(go.Scatter(x=ind.index, y=ind.BB_upper, line=dict(width=0.6, color="#8c959f"),
                                 name="Bollinger", showlegend=False), 1, 1)
        fig.add_trace(go.Scatter(x=ind.index, y=ind.BB_lower, line=dict(width=0.6, color="#8c959f"),
                                 fill="tonexty", fillcolor="rgba(140,149,159,0.08)", showlegend=False), 1, 1)
        pos = p["position"]
        if pos.get("cost_basis"):
            fig.add_hline(y=pos["cost_basis"], line_dash="dot", line_color="#6e7781",
                          annotation_text="cost", row=1, col=1)
        if pos.get("stop_price"):
            fig.add_hline(y=pos["stop_price"], line_dash="dash", line_color="#cf222e",
                          annotation_text="stop", row=1, col=1)
        fig.add_trace(go.Scatter(x=ind.index, y=ind.RSI, name="RSI", line=dict(color="#8250df")), 2, 1)
        fig.add_hrect(y0=30, y1=70, fillcolor="rgba(130,80,223,0.06)", line_width=0, row=2, col=1)
        fig.add_trace(go.Bar(x=ind.index, y=ind.MACD - ind.MACD_signal, name="MACD hist",
                             marker_color=["#2da44e" if v >= 0 else "#cf222e" for v in ind.MACD - ind.MACD_signal]),
                      3, 1)
        fig.update_layout(height=560, margin=dict(l=0, r=0, t=10, b=0), xaxis_rangeslider_visible=False,
                          legend=dict(orientation="h", y=1.02))
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.warning(f"Could not load chart: {e}")

    f, t = p["fundamental"], p["technical"]
    a, b = st.columns(2)
    with a:
        st.markdown("**Fundamental pillars**")
        for k in ("valuation", "growth", "quality", "balance"):
            v = f.get(f"pillar_{k}")
            st.progress(int(v) if v is not None else 0, text=f"{k.title()}: {'n/a' if v is None else f'{v:.0f}'}")
    with b:
        st.markdown("**Technical snapshot**")
        st.write(f"Trend **{t.get('trend')}** · RSI **{t.get('rsi', 0):.0f}**")
        st.write(f"50d {t.get('sma50', 0):.2f} · 200d {t.get('sma200', 0):.2f}")
        st.write(f"52w range {t.get('low_52w', 0):.2f} – {t.get('high_52w', 0):.2f} "
                 f"({t.get('drawdown_52w', 0):+.0%} from high)")

    st.markdown("**Active signals**")
    if not p["signals"]:
        st.caption("Nothing notable.")
    for sig in p["signals"]:
        icon = "🟢" if sig["kind"] == "opportunity" else "🔴"
        st.markdown(f"{icon} {'❗' * sig['severity']} *{sig['source']}* — {sig['message']}")

    hist_scores = pd.DataFrame(store.history(ticker))
    if len(hist_scores) > 1:
        st.markdown("**Score history**")
        st.line_chart(hist_scores.set_index("scanned_at")[["composite", "fundamental_score", "technical_score"]])

with right:
    st.subheader("Alert feed")
    alerts = pd.DataFrame(store.recent_alerts())
    if alerts.empty:
        st.caption("No alerts yet.")
    else:
        kind = st.radio("Show", ["All", "Opportunities", "Risks"], horizontal=True)
        if kind != "All":
            alerts = alerts[alerts.kind == ("opportunity" if kind == "Opportunities" else "risk")]
        for _, a_ in alerts.head(60).iterrows():
            icon = "🟢" if a_.kind == "opportunity" else "🔴"
            st.markdown(f"{icon} **{a_.ticker}** @ {a_.price:.2f} — {a_.message}  \n"
                        f"<small style='color:#6e7781'>{a_.created_at.replace('T', ' ')} · {a_.source}</small>",
                        unsafe_allow_html=True)
