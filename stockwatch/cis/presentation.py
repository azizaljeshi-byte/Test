"""Plotly figures and table rows for the chart-judgment view. Real adjusted bars only; nothing synthetic."""
from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .. import ui
from . import explain

UP, DOWN, FLOOR, WARN, FAIL, DAMAGE, CEIL, INK, MUTED = (
    ui.OPP, ui.RISK, ui.OPP, ui.WARN, "#ff8c42", ui.RISK, ui.INFO, ui.INK, ui.MUTED)
GRID = "rgba(95,135,150,0.15)"


def _layout(fig, height):
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", hovermode="x unified", showlegend=False,
                      font=dict(family="Share Tech Mono, monospace", color=INK, size=11), dragmode=False)
    fig.update_xaxes(gridcolor=GRID, zeroline=False, rangeslider_visible=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def level_lines(packet) -> dict[str, list[tuple]]:
    """Every drawable level, grouped so the page can show or hide each group: (low, high, label, colour)."""
    dn = packet["downside"]
    return {
        "Floor": [(dn["zone"]["low"], dn["zone"]["high"], f"floor {dn['zone']['low']:g}–{dn['zone']['high']:g}", FLOOR)],
        "Failure & damage": [(dn["failure"], dn["failure"], f"failure <{dn['failure']:g}", FAIL),
                             (dn["major_damage"], dn["major_damage"], f"major damage <{dn['major_damage']:g}", DAMAGE)],
        "Ceilings": [(c["zone"]["low"], c["zone"]["high"], f"ceiling {c['zone']['low']:g}–{c['zone']['high']:g}", CEIL)
                     for c in packet.ceilings],
    }


def candles(r: dict, show: list[str], sessions: int = 130):
    """Adjusted daily candles with aligned volume, the chosen level groups, and the quote marked separately."""
    b = r["bars"].iloc[-sessions:]
    p = r["packet"]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.76, 0.24], vertical_spacing=0.02)
    fig.add_trace(go.Candlestick(x=b.index, open=b["Open"], high=b["High"], low=b["Low"], close=b["Close"],
                                 increasing_line_color=UP, decreasing_line_color=DOWN, name="daily"), 1, 1)
    f = r["bars"]["Close"]
    for n, colour in ((50, WARN), (200, MUTED)):
        fig.add_trace(go.Scatter(x=b.index, y=f.rolling(n).mean().iloc[-sessions:], name=f"SMA{n}",
                                 line=dict(color=colour, width=1)), 1, 1)
    colours = [UP if c >= o else DOWN for o, c in zip(b["Open"], b["Close"])]
    fig.add_trace(go.Bar(x=b.index, y=b["Volume"], marker_color=colours, name="volume"), 2, 1)
    lo_px, hi_px = b["Low"].min(), b["High"].max()
    gap = (hi_px - lo_px) * 0.05                   # labels closer than this would overlap on a phone
    placed = {"left": [], "right": []}
    for group in show:
        side = "right" if group == "Ceilings" else "left"
        for lo, hi, label, colour in level_lines(p).get(group, []):
            if hi < lo_px * 0.95 or lo > hi_px * 1.05:
                continue                                  # off this window's scale: listed in Key levels instead
            if hi > lo:
                fig.add_hrect(y0=lo, y1=hi, fillcolor=colour, opacity=0.15, line_width=0, row=1, col=1)
            fig.add_hline(y=lo, line_color=colour, line_width=1, line_dash="dot", row=1, col=1)
            if all(abs(lo - y) > gap for y in placed["left"] + placed["right"]):
                placed[side].append(lo)
                fig.add_annotation(x=0 if side == "left" else 1, xref="x domain", xanchor=side, y=lo, yanchor="bottom",
                                   text=label, showarrow=False, font=dict(size=10, color=colour), row=1, col=1)
    q = p["quote"]
    fig.add_trace(go.Scatter(x=[b.index[-1]], y=[q["price"]], mode="markers", name="quote (partial, not a close)",
                             marker=dict(symbol="diamond-open", size=11, color=INK)), 1, 1)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    fig = _layout(fig, 420)
    fig.update_yaxes(range=[lo_px * 0.95, hi_px * 1.05], row=1, col=1)     # the candles set the scale, not the averages
    return fig


def weekly(r: dict, weeks: int = 104):
    w = r["weekly"].iloc[-weeks:]
    fig = go.Figure(go.Candlestick(x=w.index, open=w["Open"], high=w["High"], low=w["Low"], close=w["Close"],
                                   increasing_line_color=UP, decreasing_line_color=DOWN, name="weekly"))
    for col, colour in (("ma10w", WARN), ("ma40w", MUTED)):
        fig.add_trace(go.Scatter(x=w.index, y=w[col], name=col.replace("ma", "SMA").replace("w", " wk"),
                                 line=dict(color=colour, width=1)))
    return _layout(fig, 260)


def analogue_path(r: dict, a: dict):
    """One past match's 20-session close path (signal close = 100), with its own ATR band."""
    n = len(a["path"])
    fig = go.Figure(go.Scatter(x=list(range(n)), y=a["path"], mode="lines+markers", name=a["date"],
                               line=dict(color=CEIL, width=2)))
    fig.add_hline(y=100, line_color=MUTED, line_dash="dot")
    if a.get("atr_pct"):
        band = a["atr_pct"] * 100
        fig.add_hrect(y0=100 - band, y1=100 + band, fillcolor=MUTED, opacity=0.12, line_width=0)
    fig.update_xaxes(title_text="sessions after the signal")
    fig.update_yaxes(title_text="close, signal = 100")
    return _layout(fig, 240)


def floor_rows(r: dict) -> list[list[str]]:
    p, ev = r["packet"], r["evaluation"]
    dn = p["downside"]
    hit = {b["threshold"]: b for b in ev["session_extreme_breaches"]}
    def intraday(name):
        b = hit.get(name)
        if not b or b["crossed_below"] is None:
            return "unknown"
        return ("crossed, quote back above" if b["quote_recovered_at_or_above"] else "crossed, quote below") \
            if b["crossed_below"] else "not crossed"
    return [["Floor", f"{dn['zone']['low']:g}–{dn['zone']['high']:g}", "hold above", "—"],
            ["Warning", f"< {dn['warning']:g}", "close below", intraday("warning")],
            ["Failure", f"< {dn['failure']:g}", "close below", intraday("failure")],
            ["Major damage", f"< {dn['major_damage']:g}", "close below", intraday("major_damage")]]


def ceiling_rows(r: dict) -> list[list[str]]:
    return [[f"{c['low']:g}–{c['high']:g}", explain.pct(c["distance_to_low"]), explain.CEILING_LABEL[c["confirmation"]],
             c["location"]] for c in r["ladder"]]


def number_rows(r: dict) -> list[list[str]]:
    m, money, pct = r["metrics"], explain.money, explain.pct
    rows = [["Completed close", f"{money(m['Close'])} ({m['session']})"],
            ["Daily change", pct(m["daily_change"])],
            ["Weekly change (last completed week)", pct(m["weekly_change"])],
            ["SMA20 / 50 / 200", f"{money(m['ma20'])} / {money(m['ma50'])} / {money(m['ma200'])}"],
            ["Distance to SMA50 / 200", f"{pct(m['dist50'])} / {pct(m['dist200'])}"],
            ["RSI14 (Wilder)", "unknown" if m["rsi"] is None else f"{m['rsi']:.1f}"],
            ["ATR14 (Wilder)", f"{money(m['atr'])} ({pct(m['atr_pct'], False)} of price)"],
            ["MACD / signal / histogram change",
             f"{m['macd']:.2f} / {m['signal']:.2f} / {m['histogram_change']:+.2f}"],
            ["Volume vs prior 20 sessions", f"{m['Volume']:,.0f} / {m['volavg20']:,.0f} = {m['rv']:.2f}×"],
            ["252-session closing high (close-only)", money(m["close_high_252"])],
            ["252-session intraday high / low", f"{money(m['intraday_high_252'])} / {money(m['intraday_low_252'])}"]]
    for name, vals in r["relative"].items():
        label = "SPY" if name == "SPY" else f"{name} (sector proxy)"
        rows.append([f"Return vs {label}, 21 / 63 sessions", f"{pct(vals[21])} / {pct(vals[63])}"])
    if not r["sector"]:
        rows.append(["Sector proxy", "unavailable (not captured in the frozen inputs)"])
    w = r["weekly"].iloc[-1]
    rows.append([f"Weekly close vs SMA10 / SMA40 wk (week ending {w.name.date()})",
                 f"{money(w['Close'])} vs {money(w['ma10w'])} / {money(w['ma40w'])}"])
    return rows


def _ret(v) -> str:
    return "not yet" if v is None else f"{v:+.1%}"


def history_rows(r: dict) -> list[list[str]]:
    """Signal date, rank distance and the close returns that followed (unobserved horizons say 'not yet')."""
    return [[a["date"], f"{a['distance']:.2f}", _ret(a["returns"]["5"]), _ret(a["returns"]["10"]), _ret(a["returns"]["20"])]
            for a in r["history"]["analogues"]]


def excursion_rows(r: dict) -> list[list[str]]:
    """The path inside each 20-session window: best high, worst low, and the endpoint category."""
    return [[a["date"], _ret(a["mfe"]), _ret(a["mae"]), a["category"] or "not yet"] for a in r["history"]["analogues"]]


def recent(r: dict, n: int = 10) -> list[dict]:
    """The last n completed sessions as plain bars (for the decision adapter's floor-defense check)."""
    return [{"session": str(i.date()), "high": float(x.High), "low": float(x.Low), "close": float(x.Close), "completed": True}
            for i, x in r["bars"].iloc[-n:].iterrows()]
