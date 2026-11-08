"""HTML for the Momentum tab: one table per run, five narrow columns so it fits a phone. Display only."""
from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

ARROW = {1: ('<span style="color:var(--opp)">▲</span>'), -1: ('<span style="color:var(--risk)">▼</span>'), 0: '<span style="color:var(--muted)">●</span>'}


def _arrow(r: dict, key: str) -> str:
    d = r.get("dir")
    return "" if not d else " " + ARROW[d[key]]


def _sub(text: str) -> str:
    return f'<br><small style="color:var(--muted)">{escape(text)}</small>'


def table(rows: list[dict]) -> str:
    """The rows of one run. Brackets are the change since yesterday's close; arrows are the change since the previous run."""
    body = []
    for r in rows:
        tag = ""
        if r.get("tag") == "NEW":
            tag = ' <span class="mc-tag" style="color:var(--info)">NEW</span>'
        elif r.get("tag") == "FADING":
            tag = ' <span class="mc-tag" style="color:var(--warn)">FADING</span>'
        mine = ' <span class="mc-tag">yours</span>' if r.get("tracked") else ""
        sym = escape(r["t"])
        chg, hist_d = f"{r['chg']:+.1f}%", f"{r['hist_d']:+.2f}"
        rsi_d = f"{r['rsi_d']:+.1f}"
        day = "day none" if r.get("rsi_day") is None else f"day {r['rsi_day']:.0f}"
        miss = _sub("missing: " + r["miss"]) if r.get("miss") else ""
        vol = "unknown" if r.get("vol_x") is None else f"{r['vol_x']:.1f}×"
        body.append(
            "<tr>"
            f'<td><a class="mc-a" href="?view=target&t={sym}" target="_self"><b>{sym}</b></a>{mine}{tag}{miss}</td>'
            f'<td>{r["price"]:,.2f}{_arrow(r, "price")}{_sub(chg)}</td>'
            f'<td>{r["rsi"]:.1f}{_arrow(r, "rsi")}{_sub(rsi_d)}{_sub(day)}</td>'
            f'<td>{r["hist"]:+.2f}{_arrow(r, "hist")}{_sub(hist_d)}</td>'
            f'<td>{vol}{_arrow(r, "vol")}</td>'
            "</tr>")
    head = "".join(f"<th>{h}</th>" for h in ("Stock", "Price", "RSI", "MACD", "Volume"))
    return (f'<style>.rs-tbl td,.rs-tbl th{{padding:.3rem .26rem !important}}.rs-tbl td:first-child,.rs-tbl th:first-child{{padding-left:.1rem !important}}</style>'
            f'<div class="mc-tbl rs-tbl"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def stamp(state: dict) -> str:
    at = datetime.fromisoformat(state["at"])
    return f'{at:%H:%M} New York, {at.astimezone(ZoneInfo("Asia/Riyadh")):%H:%M} Riyadh'


def left_line(state: dict) -> str:
    out = state.get("left") or []
    return "" if not out else "Left the list: " + "; ".join(f'{x["t"]} ({x["why"]})' for x in out)
