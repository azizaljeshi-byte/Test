"""StockWatch Mission Control: streamlit run dashboard.py"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from stockwatch import briefing, finnhub, live, technical, tradeplan, turbo, ui
from stockwatch.config import Holding, load_portfolio, sheet_edit_url, to_yaml
from stockwatch.data import NY, get_provider, us_session
from stockwatch.engine import evaluate
from stockwatch.relative import market_regime
from stockwatch.store import Store

st.set_page_config(page_title="StockWatch · Mission Control", page_icon="🛸", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)


# Streamlit keeps cached objects across code updates; keying them on the code itself makes a
# deploy rebuild them instead of serving an instance of the previous version's classes.
CODE_VERSION = hashlib.sha1(b"".join(
    f.read_bytes() for f in sorted(Path(__file__).parent.joinpath("stockwatch").glob("*.py")))).hexdigest()[:8]


@st.cache_resource
def get_store(code_version: str) -> Store:
    return Store()


@st.cache_resource
def provider(name: str, code_version: str):
    return get_provider(name)


@st.cache_data(ttl=60, show_spinner=False)
def cached_portfolio(code_version: str):
    return load_portfolio()


base = cached_portfolio(CODE_VERSION)
store = get_store(CODE_VERSION)
data = provider("demo" if os.getenv("STOCKWATCH_DEMO") else base.settings.data_provider, CODE_VERSION)
# with a Google Sheet, the sheet is the only list; dashboard additions are for setups without one
portfolio = base if base.sheet_url else store.apply_overrides(base)
tickers = {h.ticker for h in portfolio.holdings}

# tickers that appeared in the sheet since this browser session last looked get an overview
known = st.session_state.setdefault("known_tickers", set(tickers))
if base.sheet_url and tickers - known:
    st.session_state.just_added = sorted(tickers - known)
st.session_state.known_tickers = known | tickers


@st.cache_resource
def tracker(name: str, code_version: str) -> live.Tracker:
    """One background tracker per app process; it sweeps and refreshes prices while the market trades."""
    return live.Tracker(provider(name, code_version))


tracking = tracker("demo" if os.getenv("STOCKWATCH_DEMO") else base.settings.data_provider, CODE_VERSION)


def scan_now():
    live.sweep(data, store)


snaps = [s for s in store.latest_snapshots() if s["ticker"] in tickers]
last_scan = max((s["scanned_at"] for s in snaps), default=None)
session = ui.SESSION_LABEL[us_session()]
quote_times = [(x["payload"].get("quote") or {}).get("fetched_at") for x in snaps]
quote_times = [q for q in quote_times if q]
price_label = (f" · prices {max(quote_times)[11:16]} UTC" if quote_times and us_session() != "CLOSED" else "")
st.markdown(ui.header(f"{session}{price_label} · {len(tickers)} targets · last sweep "
                      f"{last_scan[5:16].replace('T', ' ') + ' UTC' if last_scan else 'never'}"),
            unsafe_allow_html=True)

try:
    local_now = datetime.now(ZoneInfo(st.context.timezone or "UTC"))
except Exception:
    local_now = datetime.now(NY)
greeting = ("Good morning" if 5 <= local_now.hour < 12 else "Good afternoon" if local_now.hour < 18
            else "Good evening") + "."

# ---------------------------------------------------------------- controls
if base.sheet_error:
    st.warning(f"Couldn't read the Google Sheet, showing the backup list instead. {base.sheet_error}")

def controls():
    c1, c2 = st.columns([1, 1.6])
    if c1.button("⟳ Sweep now", use_container_width=True):
        with st.spinner("Sweeping targets..."):
            scan_now()
        st.rerun()
    status = tracking.status()
    if not status["alive"]:
        c2.caption("⚠ Live tracking stopped. Reboot the app to restart it.")
    elif status["session"] == "CLOSED":
        c2.caption("Market closed. Live tracking resumes at 4:00am New York time.")
    else:
        nxt = status["next_sweep_in"]
        def every(sec):
            return f"{sec // 60} min" if sec % 60 == 0 else f"{sec}s"
        c2.caption(f"🟢 Live: full analysis every {every(live.SWEEP_SECONDS)}, prices every "
                   f"{every(live.QUOTE_SECONDS)}" + (f" · next analysis in {nxt}s" if nxt else " · analysing now"))


@st.fragment(run_every="30s")
def _watch_for_updates():
    """Reload the page when the tracker lands new results, and pop up the important new alerts."""
    mark = store.watermark()
    seen = st.session_state.get("watermark")
    if seen is None:
        st.session_state.watermark = mark
        return
    if mark != seen:
        fresh = [a for a in store.alerts_after(seen[1])
                 if (a["ticker"] in tickers or a["source"] == "S&P scan") and a["severity"] >= 2]
        for a in fresh[:5]:
            st.toast(f"{'🟢' if a['kind'] == 'opportunity' else '🔴'} {a['ticker']}: {a['message']}")
        if len(fresh) > 5:
            st.toast(f"+{len(fresh) - 5} more new alerts in the Log")
        st.session_state.watermark = mark
        st.rerun()


_watch_for_updates()


if not snaps:
    controls()
    st.info("No telemetry yet. Hit **⟳ Sweep now** to run the first scan.")
    st.stop()

# ---------------------------------------------------------------- status tiles
reg = None
try:
    reg = market_regime(data.history(portfolio.settings.benchmark))
    reg_color = {"RISK-ON": ui.OPP, "RISK-OFF": ui.RISK}.get(reg["state"], ui.WARN)
    market_tile = ("Market", reg["state"], f"{session} · SPY {ui.pct(reg['day_change'], digits=1)} · "
                   f"{ui.pct(reg['vs_200d'])} vs 200d", reg_color)
except Exception:
    market_tile = ("Market", "NO SIGNAL", "benchmark unavailable", ui.MUTED)

urgent = [s for s in snaps if any(x["kind"] == "risk" and x["severity"] >= 3 for x in s["payload"]["signals"])]
opps = [s for s in snaps if s["verdict"] in ("OPPORTUNITY - ADD", "BUY SETUP")]
soon = [s for s in snaps if (s["payload"].get("events") or {}).get("days_to_earnings") is not None
        and s["payload"]["events"]["days_to_earnings"] <= 7]
held = [s for s in snaps if not s["payload"]["watchlist"]]
def _names(group):
    return ui.link_tickers(" ".join(s["ticker"] for s in group[:5]), tickers)


parts = []
if urgent:
    parts.append(f"<b>{len(urgent)} need{'s' if len(urgent) == 1 else ''} your attention</b>")
if opps:
    parts.append(f"<b>{len(opps)} {'is' if len(opps) == 1 else 'are'} in a buy zone</b>")
if soon:
    parts.append(f"{len(soon)} report{'s' if len(soon) == 1 else ''} earnings this week")
summary = ("Across your " + f"{len(held)} positions and {len(snaps) - len(held)} watchlist names: "
           + (", ".join(parts) if parts else "nothing urgent right now") + ".")
if reg:
    summary += f" The market backdrop reads <b>{reg['state'].lower()}</b>."
st.markdown(ui.hero(greeting, summary), unsafe_allow_html=True)

st.markdown(ui.tiles([
    (market_tile[0] + " mood", market_tile[1], escape(market_tile[2]), market_tile[3]),
    ("Needs attention", str(len(urgent)), _names(urgent) or "all clear", ui.RISK if urgent else ui.MUTED),
    ("Buy zone", str(len(opps)), _names(opps) or "nothing in range", ui.OPP if opps else ui.MUTED),
    ("Earnings this week", str(len(soon)), _names(soon) or "quiet week", ui.WARN if soon else ui.MUTED),
]), unsafe_allow_html=True)

controls()


# ---------------------------------------------------------------- navigation (driven by the URL so links can jump)
VIEWS = {"radar": "◉ Radar", "turbo": "⚡ Turbo", "target": "◎ Details", "market": "✦ S&P 500", "log": "≡ Log",
         "fleet": "+ Fleet"}
current = st.query_params.get("view", "radar")
current = current if current in VIEWS else "radar"
picked = st.segmented_control("View", list(VIEWS), format_func=VIEWS.get, default=current,
                              label_visibility="collapsed")
view = picked or current
if view != current:
    st.query_params["view"] = view

# ---------------------------------------------------------------- radar
prevs = {s["ticker"]: store.previous_snapshot(s["ticker"]) for s in snaps}

def verdict_changes(snaps: list[dict]) -> dict[str, str]:
    """Stocks whose verdict changed in the last 30 minutes -> the verdict they had before."""
    cutoff = time.time() - 30 * 60
    out = {}
    for x in snaps:
        prev = prevs.get(x["ticker"])
        if prev and prev["verdict"] != x["verdict"] and datetime.fromisoformat(x["scanned_at"]).timestamp() >= cutoff:
            out[x["ticker"]] = prev["verdict"]
    return out


@st.fragment
def radar_list(snaps: list[dict]):
    """Filter + cards. A fragment, so tapping a filter redraws only this part of the page."""
    # filters follow the verdict shown on each card, so every card in a filter shows that status
    groups = {
        "Risk": lambda x: x["verdict"] in ("RISK - REVIEW", "TRIM / REVIEW", "AVOID"),
        "Opportunity": lambda x: x["verdict"] in ("OPPORTUNITY - ADD", "BUY SETUP"),
        "Hold": lambda x: x["verdict"] in ("HOLD", "STRONG HOLD", "WATCH"),
        "Held": lambda x: not x["payload"]["watchlist"],
        "Watch": lambda x: x["payload"]["watchlist"],
    }
    icons = {"Risk": "▼ ", "Opportunity": "▲ ", "Hold": "● "}
    labels = {"All": f"All ({len(snaps)})"} | {
        g: f"{icons.get(g, '')}{g} ({sum(1 for x in snaps if fn(x))})" for g, fn in groups.items()}
    choice = st.pills("Filter", list(labels), format_func=labels.get, default="All", key="radar_filter",
                      label_visibility="collapsed")
    shown = sorted(snaps, key=ui.urgency)
    if choice in groups:
        shown = [x for x in shown if groups[choice](x)]
    st.markdown(ui.cards(shown, changed=verdict_changes(snaps)) if shown else '<div class="mc-d">No stocks with this status right now.</div>',
                unsafe_allow_html=True)


if view == "radar":
    st.markdown(ui.mission_brief(briefing.portfolio(snaps, prevs, reg), tickers), unsafe_allow_html=True)
    radar_list(snaps)

# ---------------------------------------------------------------- target detail
if view == "target":
    order = [s["ticker"] for s in sorted(snaps, key=ui.urgency)]
    wanted = (st.query_params.get("t") or "").upper()
    extra = store.snapshot(wanted) if wanted and wanted not in order else None
    if extra:
        order = [wanted] + order
    pick = st.selectbox("Stock", order, index=order.index(wanted) if wanted in order else 0)
    if pick != wanted:
        st.query_params["t"] = pick
    ticker = pick
    snap = extra if extra and ticker == wanted else next(s for s in snaps if s["ticker"] == ticker)
    if ticker not in tickers:
        st.caption("Not in your list. " + ("Add a row to your Google Sheet to track it." if base.sheet_url
                                           else "Add it on the Fleet tab to track it."))
    p = snap["payload"]
    t, f, ev = p["technical"], p["fundamental"], p.get("events") or {}
    st.markdown(ui.cards([snap]), unsafe_allow_html=True)
    industry = (p.get("profile") or {}).get("industry")
    if industry:
        st.caption(industry)
    note = next((h.notes for h in portfolio.holdings if h.ticker == ticker and h.notes), None)
    if note:
        st.markdown(f'<div class="mc-log"><small>YOUR NOTE</small><br>{escape(note)}</div>', unsafe_allow_html=True)
    st.markdown(ui.brief(briefing.stock(snap, prevs.get(ticker))), unsafe_allow_html=True)
    research = p.get("research") or {}
    today_news = [n for n in ev.get("news") or []
                  if (datetime.now(NY) - datetime.fromisoformat(n["published"])).total_seconds() <= 36 * 3600]
    st.markdown('<div class="mc-section">Today\'s news</div>', unsafe_allow_html=True)
    st.markdown(ui.news_list(today_news) if today_news else
                '<div class="mc-d">No headlines in the last day. Older news is further down.</div>', unsafe_allow_html=True)

    plan = p.get("plan") or {}
    if plan:
        portfolio_value = sum(x["payload"]["position"].get("value", 0) for x in snaps if not x["payload"]["watchlist"])
        risk_pct = st.session_state.get("risk_pct", portfolio.settings.risk_per_trade_pct)
        sizing = tradeplan.size(plan, portfolio_value, risk_pct, portfolio.rules(snap["tier"]).max_position_pct)
        st.markdown(ui.trade_plan(plan, sizing, risk_pct, portfolio_value), unsafe_allow_html=True)
        st.select_slider("Risk per trade (% of portfolio lost if the stop is hit)", [0.25, 0.5, 1.0, 1.5, 2.0],
                         value=risk_pct, key="risk_pct")

    street_m = research.get("street") or {}
    if street_m:
        st.markdown('<div class="mc-section">Outlook · 3 to 12 months</div>', unsafe_allow_html=True)
        if not street_m.get("consensus"):
            st.caption("Analyst ratings and targets are missing. " + "Yahoo blocks this data for apps on Streamlit Cloud. " + ("Finnhub didn't have it either." if finnhub.enabled() else "Add a free FINNHUB_API_KEY secret (finnhub.io) to fill it."))
        st.markdown(ui.outlook(street_m, snap["price"]), unsafe_allow_html=True)
    elif ticker not in tickers:
        if st.button("Run the full analysis (street view, outlook, SEC)"):
            with st.spinner(f"Analysing {ticker}..."):
                store.save_snapshot(evaluate(Holding(ticker, 2, 0), portfolio, data))
            st.rerun()

    with st.expander("Company overview & report card", expanded=False):
        st.markdown(ui.overview_card(briefing.overview(snap), ticker), unsafe_allow_html=True)
    lv = (research.get("valuation") or {}).get("levels") or {}

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
        if plan:
            fig.add_hrect(y0=plan["entry_low"], y1=plan["entry_high"], fillcolor="rgba(61,255,168,0.12)", line_width=0,
                          row=1, col=1)
            fig.add_hline(y=plan["stop"], line_dash="dash", line_width=1, line_color=ui.RISK, row=1, col=1,
                          annotation_text=f"stop {plan['stop']:.2f}", annotation_font_color=ui.RISK,
                          annotation_position="bottom left")
        for level, label in ((lv.get("support"), "support"), (lv.get("resistance"), "resistance")):
            if level:
                fig.add_hline(y=level, line_dash="dot", line_width=1, line_color=ui.MUTED, row=1, col=1,
                              annotation_text=f"{label} {level:.2f}", annotation_font_color=ui.MUTED,
                              annotation_position="top left")
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

    earn = research.get("earnings") or {}
    with st.expander("Earnings track record", expanded=False):
        if earn.get("reported"):
            st.markdown(f"Beat EPS estimates **{earn['beats']} of {earn['reported']}** recent quarters"
                        + (f" · streak **{earn['beat_streak']}**" if earn.get("beat_streak") else "")
                        + (f" · avg report-day move **±{earn['avg_move'] * 100:.1f}%**" if earn.get("avg_move") else ""))
            st.markdown(ui.table(["Quarter", "Est EPS", "Actual", "Surprise", "Report-day move"], [
                [q["quarter"], ui.num(q.get("eps_estimate")), ui.num(q.get("eps_actual")),
                 ui.pct(q.get("surprise_pct"), digits=1), ui.pct(q.get("reaction"), digits=1)]
                for q in earn["quarters"]]), unsafe_allow_html=True)
            st.caption("Report day is estimated as the heaviest-volume session after each quarter closed.")
        if earn.get("revenue_q"):
            qoq = earn.get("revenue_qoq") or []
            st.markdown(ui.table(["Quarter", "Revenue", "QoQ", "Gross margin", "Op margin"], [
                [r["period"], ui.money(r["revenue"]), ui.pct(qoq[i], digits=1) if i < len(qoq) else "—",
                 ui.pct(r.get("gross_margin"), signed=False), ui.pct(r.get("op_margin"), signed=False)]
                for i, r in enumerate(earn["revenue_q"])]), unsafe_allow_html=True)
            if earn.get("revenue_yoy_latest") is not None:
                st.caption(f"Latest quarter revenue vs a year ago: {ui.pct(earn['revenue_yoy_latest'], digits=1)}")
        if not earn.get("reported") and not earn.get("revenue_q"):
            st.caption("No earnings history available for this symbol.")

    sm = research.get("smart_money") or {}
    with st.expander("Smart money & short interest", expanded=False):
        if sm and not any(sm.get(k) is not None for k in ("short_pct_float", "insider_pct", "institution_pct")) \
                and not sm.get("insider_tx"):
            st.caption("Short interest, ownership and insider trades are missing. " + "Yahoo blocks this data for apps on Streamlit Cloud. " + ("Finnhub didn't have it either." if finnhub.enabled() else "Add a free FINNHUB_API_KEY secret (finnhub.io) to fill it.")
                       + " Short interest and institutional ownership need a paid plan on most providers.")
        elif sm:
            st.markdown('<div class="mc-kv">' + "".join(f"<div><span>{k}</span>{escape(v)}</div>" for k, v in [
                ("Short % float", ui.pct(sm.get("short_pct_float"), signed=False)),
                ("Days to cover", ui.num(sm.get("days_to_cover"), ".1f")),
                ("Short Δ vs last month", ui.pct(sm.get("short_change"))),
                ("Insiders own", ui.pct(sm.get("insider_pct"), signed=False)),
                ("Institutions own", ui.pct(sm.get("institution_pct"), signed=False)),
                ("Insider buys 90d", f"{ui.money(sm.get('insider_buy_90d'))} ({sm.get('buyers_90d', 0)})"),
                ("Insider sells 90d", f"{ui.money(sm.get('insider_sell_90d'))} ({sm.get('sellers_90d', 0)})"),
            ]) + "</div>", unsafe_allow_html=True)
            if sm.get("insider_tx"):
                st.markdown(ui.table(["Date", "Insider", "Role", "Type", "Value"], [
                    [tx.get("date") or "—", (tx.get("insider") or "—")[:22], (tx.get("position") or "—")[:18],
                     {"buy": "BUY", "sell": "SELL"}.get(tx.get("kind"), "other"), ui.money(tx.get("value"))]
                    for tx in sm["insider_tx"]]), unsafe_allow_html=True)
                st.caption("Only open-market purchases and sales count as signals; awards and option exercises don't. "
                           "Many sales are pre-planned (10b5-1).")
        else:
            st.caption("No ownership data available.")

    va = research.get("valuation") or {}
    with st.expander("Valuation in context", expanded=False):
        fv = va.get("fair_value")
        if fv:
            st.markdown(ui.fair_value_bar(fv, snap["price"]), unsafe_allow_html=True)
            st.markdown(ui.table(["Method", "Low", "Mid", "High"], [
                [k, ui.num(v["low"]), ui.num(v["mid"]), ui.num(v["high"])] for k, v in fv["methods"].items()]),
                unsafe_allow_html=True)
        st.markdown(f"P/E now **{ui.num(va.get('pe_now'), '.1f')}** · own history median "
                    f"**{ui.num(va.get('pe_hist_median'), '.1f')}** · peer median forward "
                    f"**{ui.num(va.get('peer_median_pe'), '.1f')}**")
        if va.get("pe_history"):
            st.markdown(ui.table(["Year", "EPS", "P/E at year end"], [
                [r["year"], ui.num(r["eps"]), ui.num(r["pe"], ".1f")] for r in va["pe_history"]]), unsafe_allow_html=True)
        if va.get("peers"):
            rows = [[r["ticker"], ui.num(r["pe"], ".1f"), ui.num(r["ps"], ".1f"), ui.pct(r["growth"]),
                     ui.pct(r["margin"], signed=False), ui.money(r["market_cap"])]
                    for r in [{"ticker": ticker, **(va.get("self") or {})}] + va["peers"]]
            st.markdown(ui.table(["Peer", "Fwd P/E", "P/S", "Rev growth", "Op margin", "Mkt cap"], rows, highlight=0),
                        unsafe_allow_html=True)
            st.caption("Peers are the largest companies in the same industry, so small caps are compared with giants.")
        if not fv and not va.get("peers"):
            st.caption("Not enough data for a valuation comparison.")

    sec_m = research.get("sec") or {}
    with st.expander("SEC filings", expanded=False):
        if sec_m.get("filings"):
            st.markdown("".join(
                f'<div class="mc-log"><small>{escape(f["date"])}</small><br>'
                f'<a href="{escape(f["url"])}" target="_blank" style="color:var(--info)">{escape(f["label"])}</a></div>'
                for f in sec_m["filings"]), unsafe_allow_html=True)
            facts = []
            if sec_m.get("shares_change_1y") is not None:
                facts.append(f"Share count {ui.pct(sec_m['shares_change_1y'], digits=1)} over the last year")
            if sec_m.get("form4_90d"):
                facts.append(f"{sec_m['form4_90d']} insider (Form 4) filings in 90 days")
            if facts:
                st.caption(" · ".join(facts))
        else:
            st.caption("No SEC data. Foreign companies and funds may file differently, or SEC was unreachable.")

    parts = t.get("score_parts") or []
    if parts:
        with st.expander(f"Why the technical score is {snap['technical_score']:.0f}", expanded=False):
            ordered = sorted(parts, key=lambda x: x[1])
            st.markdown(ui.table(["Factor", "Points"], [[name, f"{pts:+.1f}"] for name, pts in ordered]
                                 + [["Net (50 is neutral)", f"{sum(pt for _, pt in parts):+.1f}"]], wrap=True),
                        unsafe_allow_html=True)
            st.caption("Each factor adds or subtracts points from a neutral 50. The total goes through a smooth "
                       "curve, so a stock where every factor is negative lands near 5-15 instead of a flat 0, "
                       "and weak stocks can still be told apart.")

    with st.expander("All readouts", expanded=False):
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
        with st.expander("Analyst moves", expanded=False):
            st.markdown("".join(
                f'<div class="mc-log"><small>{escape(str(r["date"]))}</small> {escape(str(r.get("firm") or "?"))} · '
                f'{escape(str(r.get("action") or "").upper())} {escape(str(r.get("from_grade") or ""))} → '
                f'{escape(str(r.get("to_grade") or ""))}</div>' for r in ev["rating_changes"]), unsafe_allow_html=True)

    if ev.get("news"):
        with st.expander("All recent news", expanded=False):
            st.markdown(ui.news_list(ev["news"], limit=20), unsafe_allow_html=True)

# ---------------------------------------------------------------- S&P 500 scan
if view == "market":
    st.markdown('<div class="mc-section">S&P 500 opportunity scan</div>', unsafe_allow_html=True)
    st.markdown("Screens all S&P 500 stocks for technical entry setups, then runs the full fundamental and "
                "technical evaluation on the strongest 25. Stocks already in your list are skipped.")
    mstat = tracking.status()
    if mstat["market_running"] or live.MARKET_LOCK.locked():
        st.caption("✦ Scanning the S&P 500 now; results appear here automatically when it finishes.")
    elif mstat["session"] == "CLOSED":
        st.caption("Auto-scan runs every 30 minutes while the market trades (4:00am-8:00pm New York).")
    elif mstat["next_market_in"] is not None:
        st.caption(f"🟢 Auto-scan every {live.MARKET_SECONDS // 60} min · next in "
                   f"{max(1, mstat['next_market_in'] // 60)} min")
    if mstat.get("market_error"):
        st.caption(f"⚠ Last automatic scan failed: {mstat['market_error'][:120]}")
    # the scan runs on the tracker's thread, so page refreshes can't interrupt it halfway
    st.button("✦ Scan the S&P 500 now", use_container_width=True,
              disabled=mstat["market_running"] or live.MARKET_LOCK.locked(),
              on_click=lambda: tracking.maybe_market_scan(store, force=True))
    ms = store.latest_market_scan()
    if not ms:
        st.caption("No scan yet. It takes a minute or two on live data.")
    else:
        when = ms["scanned_at"][5:16].replace("T", " ")
        st.caption(f"Last scan {when} UTC · {ms['priced']} of {ms['universe']} stocks priced · "
                   f"{ms['setups']} setups · {len(ms['results'])} evaluated in depth. Tap a stock for details.")
        before = store.latest_market_scan(offset=1) or {}
        was = {r["ticker"] for r in before.get("results", []) if r["verdict"] == "BUY SETUP"}
        new_setups = {r["ticker"] for r in ms["results"] if r["verdict"] == "BUY SETUP" and r["ticker"] not in was}
        pick = st.pills("Show", ["Buy setups", "All finalists"], default="Buy setups", label_visibility="collapsed")
        rows = [r for r in ms["results"] if pick == "All finalists" or r["verdict"] == "BUY SETUP"]
        rows.sort(key=lambda r: r["ticker"] not in new_setups)   # new setups first
        st.markdown(f'<div class="mc-cards">{"".join(ui.market_card(r, r["ticker"] in new_setups) for r in rows)}</div>'
                    if rows else '<div class="mc-d">No buy setups in the last scan. Try "All finalists".</div>',
                    unsafe_allow_html=True)

# ---------------------------------------------------------------- turbo: quick decision on any ticker
if view == "turbo":
    st.markdown('<div class="mc-section">Turbo · quick decision</div>', unsafe_allow_html=True)
    st.caption("Spotted a mover? Get a buy / wait / pass call in seconds without adding it to your list.")
    def _turbo_submit():
        # runs before the rerun, so a background refresh can't swallow the request
        sym = (st.session_state.get("turbo_input") or "").strip().upper()
        if sym:
            st.session_state.turbo_ticker = sym
            st.session_state.turbo_result = {"ticker": sym, "quick": None, "deep": None, "ev": None, "error": None}

    with st.form("turbo", clear_on_submit=False, border=False):
        c1, c2 = st.columns([2, 1])
        c1.text_input("Ticker", placeholder="e.g. PLTR", key="turbo_input", label_visibility="collapsed")
        c2.form_submit_button("⚡ Decide", use_container_width=True, on_click=_turbo_submit)
    res = st.session_state.get("turbo_result")
    if res:
        sym, slot = res["ticker"], st.empty()
        # each stage is computed once and kept, so the page's periodic reloads only redraw it
        try:
            if res["quick"] is None and res["deep"] is None and not res["error"]:
                with st.spinner(f"Quick read on {sym}..."):
                    res["ev"], res["quick"] = turbo.run(sym, portfolio, data, deep=False)
            if res["deep"] is None and not res["error"]:
                slot.markdown(ui.turbo_card(res["quick"], deep=False), unsafe_allow_html=True)
                with st.spinner("Adding analysts, SEC filings and the earnings setup..."):
                    res["ev"], res["deep"] = turbo.run(sym, portfolio, data, deep=True)
                store.save_snapshot(res["ev"])   # so the full details page opens for it
                recent = [t for t in st.session_state.get("turbo_recent", []) if t != sym]
                st.session_state.turbo_recent = [sym] + recent[:7]
        except Exception as e:
            res["error"] = f"{sym}: couldn't get a decision ({e}). Check the symbol."
        if res["error"]:
            slot.error(res["error"])
        else:
            slot.markdown(ui.turbo_card(res["deep"], deep=True), unsafe_allow_html=True)
            if res["ev"].plan:
                st.markdown(ui.trade_plan(res["ev"].plan, None, 0, 0), unsafe_allow_html=True)
            st.markdown(f'<a class="mc-a" href="?view=target&t={escape(sym)}" target="_self">'
                        f'<div class="mc-plan" style="text-align:center"><b>OPEN</b>full details for {escape(sym)} →'
                        f'</div></a>', unsafe_allow_html=True)
            if sym not in tickers:
                st.caption("Not in your list. " + ("Add a row to your Google Sheet to track it." if base.sheet_url
                                                   else "Use the Fleet tab to track it."))
    if st.session_state.get("turbo_recent"):
        st.caption("Recent: " + " · ".join(st.session_state.turbo_recent))

# ---------------------------------------------------------------- alert log
if view == "log":
    alerts = [a for a in store.recent_alerts(150) if a["ticker"] in tickers or a["source"] == "S&P scan"]
    if not alerts:
        st.markdown('<div class="mc-d">no transmissions yet</div>', unsafe_allow_html=True)
    st.markdown("".join(
        f'<div class="mc-log"><small>{a["created_at"][5:16].replace("T", " ")}</small> '
        f'{ui.signal_glyph(a["kind"])}<b>{escape(a["ticker"])}</b> @ {a["price"]:.2f} — {escape(a["message"])}</div>'
        for a in alerts), unsafe_allow_html=True)

    with st.expander("System diagnostics", expanded=False):
        now_ny = datetime.now(NY)
        st.markdown('<div class="mc-kv">' + "".join(f"<div><span>{k}</span>{escape(str(v))}</div>" for k, v in [
            ("Code version", CODE_VERSION), ("New York time", now_ny.strftime("%a %H:%M")),
            ("Session (clock)", us_session()), ("Data source", type(getattr(data, "inner", data)).__name__),
            ("Ticker list", "Google Sheet" if base.sheet_url else "secret / YAML + app edits"),
            ("Finnhub fallback", "on" if finnhub.enabled() else "off (no FINNHUB_API_KEY)"),
            ("Tickers", len(tickers)),
        ]) + "</div>", unsafe_allow_html=True)
        st.caption("Extended-hours prices come from minute bars, which keep working when Yahoo rate-limits the app. "
                   "'Blocked' fundamentals mean Yahoo refused the request; they're retried on the next sweep.")
        st.markdown(ui.table(["Ticker", "Session", "Ext price", "Type", "Source", "Fundamentals", "Fetched (UTC)", "Problem"], [
            [x["ticker"], q.get("market_state") or "—", ui.num(q.get("ext_price")),
             (q.get("ext_session") or "—") + (" (last night)" if q.get("ext_stale") else ""), q.get("source") or "—",
             "ok" if (x["payload"].get("fundamental") or {}).get("available", True) else "blocked",
             (q.get("fetched_at") or "—")[11:19], (q.get("error") or "")[:60]]
            for x in snaps for q in [x["payload"].get("quote") or {}]]), unsafe_allow_html=True)
        st.text_input("Ticker to test", value=next(iter(sorted(tickers)), "AAPL"), key="probe")
        # results are kept in session state: the page's automatic refreshes would otherwise wipe a
        # button's output a few seconds after the tap
        def _test_finnhub():
            sym = (st.session_state.get("probe") or "AAPL").strip().upper()
            if not finnhub.enabled():
                st.session_state.diag = ("error", "No FINNHUB_API_KEY found. Add it in Settings → Secrets, then reboot.")
                return
            try:
                recs = finnhub._get("/stock/recommendation", symbol=sym)
                metric = (finnhub._get("/stock/metric", symbol=sym, metric="all") or {}).get("metric") or {}
                st.session_state.diag = ("success", f"Finnhub works: {len(recs)} months of analyst ratings and "
                                                    f"{len(metric)} key ratios for {sym}.")
            except Exception as e:
                msg = str(e)
                hint = ("the key is wrong or not activated" if "401" in msg else
                        "this data needs a paid plan" if "403" in msg else
                        "too many requests; wait a minute" if "429" in msg else "check the key and try again")
                st.session_state.diag = ("error", f"Finnhub request failed: {msg[:120]} ({hint}).")

        def _raw_quote():
            sym = (st.session_state.get("probe") or "AAPL").strip().upper()
            inner = getattr(data, "inner", data)
            try:
                raw = inner.raw_quote(sym) if hasattr(inner, "raw_quote") else inner.quote(sym)
                st.session_state.diag = ("code", json.dumps({"raw": raw, "parsed": inner.quote(sym)}, indent=1, default=str))
            except Exception as e:
                st.session_state.diag = ("error", f"Quote failed: {e}")

        b1, b2 = st.columns(2)
        b1.button("Test Finnhub key", on_click=_test_finnhub, use_container_width=True)
        b2.button("Fetch raw quote", on_click=_raw_quote, use_container_width=True)
        kind, msg = st.session_state.get("diag", (None, None))
        if kind == "success":
            st.success(msg)
        elif kind == "error":
            st.error(msg)
        elif kind == "code":
            st.code(msg, language="json")

# ---------------------------------------------------------------- fleet management


def overview_for(h: Holding, acquired: bool) -> None:
    """Show a ticker's overview, scanning it first if it hasn't been scanned yet."""
    snap = next((x for x in store.latest_snapshots() if x["ticker"] == h.ticker), None)
    if snap is None:
        with st.spinner(f"Acquiring {h.ticker}..."):
            store.save_snapshot(evaluate(h, portfolio, data))
        snap = next((x for x in store.latest_snapshots() if x["ticker"] == h.ticker), None)
    if snap:
        st.markdown(ui.overview_card(briefing.overview(snap), h.ticker, acquired=acquired), unsafe_allow_html=True)


if view == "fleet":
    just_added = [t for t in st.session_state.get("just_added", []) if t in tickers]
    for sym in st.session_state.get("add_failed", []):
        st.error(f"{sym}: no market data found - check the symbol")

    if base.sheet_url:
        st.markdown('<div class="mc-section">Ticker list</div>', unsafe_allow_html=True)
        st.markdown(f"Your tickers come from your **[Google Sheet ↗]({sheet_edit_url(base.sheet_url)})**. "
                    "Add or delete rows there; the app picks up changes within a minute, "
                    "and new tickers get an overview here.")
        if st.button("⟳ Reload sheet now"):
            cached_portfolio.clear()
            st.rerun()
    else:
        st.markdown('<div class="mc-section">Add targets</div>', unsafe_allow_html=True)
        with st.form("add", clear_on_submit=True, border=False):
            raw = st.text_input("Tickers", placeholder="e.g. PLTR, AMZN, TSM")
            a, b = st.columns(2)
            tier = a.radio("Tier", [1, 2], horizontal=True, format_func=lambda x: f"T{x} {'core' if x == 1 else 'tactical'}")
            shares = b.number_input("Shares (0 = watchlist)", min_value=0.0, value=0.0, step=1.0)
            submitted = st.form_submit_button("⊕ Add to fleet", use_container_width=True)
        if submitted and raw.strip():
            added, failed = [], []
            with st.spinner("Acquiring target..."):
                for sym in dict.fromkeys(x.strip().upper() for x in raw.replace(" ", ",").split(",") if x.strip()):
                    try:
                        data.history(sym)  # confirms the symbol exists before saving it
                    except Exception:
                        failed.append(sym)
                        continue
                    store.upsert_ticker(sym, tier, shares)
                    h = next(h for h in store.apply_overrides(base).holdings if h.ticker == sym)
                    store.save_snapshot(evaluate(h, portfolio, data))
                    added.append(sym)
            st.session_state.just_added, st.session_state.add_failed = added, failed
            st.rerun()

    for sym in just_added:
        overview_for(next(h for h in portfolio.holdings if h.ticker == sym), acquired=True)
    if just_added and st.button("Dismiss overview", key="dismiss"):
        st.session_state.just_added, st.session_state.add_failed = [], []
        st.rerun()

    st.markdown('<div class="mc-section">Quick look</div>', unsafe_allow_html=True)
    look = st.text_input("Look up any ticker without tracking it", placeholder="e.g. AMZN",
                         key="quick_look").strip().upper()
    if look:
        try:
            data.history(look)
            overview_for(Holding(look, 2, 0), acquired=False)
            if look not in tickers:
                st.caption("Not tracked. " + ("Add a row to the sheet to track it." if base.sheet_url
                                              else "Use Add targets above to track it."))
        except Exception:
            st.error(f"{look}: no market data found - check the symbol")

    if not base.sheet_url:
        st.markdown('<div class="mc-section">Remove targets</div>', unsafe_allow_html=True)
        drop = st.multiselect("Remove", sorted(tickers), label_visibility="collapsed", placeholder="Pick tickers to remove")
        if st.button("✕ Remove selected", disabled=not drop):
            for sym in drop:
                store.remove_ticker(sym)
            st.rerun()

        st.markdown('<div class="mc-section">Make it permanent</div>', unsafe_allow_html=True)
        st.caption("Changes here are saved in the app's database, which Streamlit Cloud wipes on a reboot or redeploy. "
                   "To keep them, paste this into the app's STOCKWATCH_PORTFOLIO secret (between the triple quotes), "
                   "or connect a Google Sheet with STOCKWATCH_SHEET_URL.")
        st.code(to_yaml(portfolio), language="yaml")
