"""The Quick tab: a fake $50,000 account that reads the day's chart and trades quickly. Display only: it reads `quick.status`.
Nothing here trades or changes a card, score, call or alert."""
from __future__ import annotations

from html import escape

from . import quick
from .paper_view import CSS, _signed, _usd, wl


def _pct(v) -> str:
    return "—" if v is None else f"{v:+.1f}%"


def html(st: dict, prices: dict | None = None) -> str:
    book, state = st["book"], st.get("state") or {}
    prices = prices or {}
    rep = quick.report(book, prices)
    eq = rep["equity"]
    msg = f'<div class="pp-note">{escape(state["note"])}</div>' if state.get("note") else ""
    msg += "".join(f'<div class="pp-sk"><b>{escape(t)}</b> {escape(w)}</div>' for t, w in (state.get("skipped") or {}).items())
    if st.get("sheet_error"):
        msg += f'<div class="pp-note bad">Not saved to Drive: {escape(st["sheet_error"])}</div>'
    opens = []
    for t in book["trades"]:
        if t["status"] != "OPEN":
            continue
        pos = book["positions"].get(t["ticker"], {})
        px = prices.get(t["ticker"])
        move = (px / t["entry"] - 1) * 100 if px else None
        pnl = (px - t["entry"]) * pos.get("shares", t["shares"]) if px else None
        riding = pos.get("stop", t["stop0"]) > t["entry"]
        opens.append(
            f'<div class="pp-t"><div class="pp-th"><b>{escape(t["ticker"])}</b><span>'
            f'{'<span class="pp-tag w">RIDING</span> ' if riding else ""}<span class="pp-tag o">{escape(t["kind"].upper())}</span></span></div>'
            f'<div class="pp-m">Bought {escape(t["opened"])} · {pos.get("shares", t["shares"])} sh @ {_usd(t["entry"])}</div>'
            f'<div class="pp-lb"><span>Stop {_usd(pos.get("stop", t["stop0"]))}</span>'
            f'<span class="{"up" if (pnl or 0) >= 0 else "dn"}"><b>{_signed(pnl)}{"" if move is None else f" · {move:+.1f}%"}</b></span>'
            f'<span>Peak {_usd(pos.get("peak", t["entry"]))}</span></div><div class="pp-why">{escape(t["reason"])}</div></div>')
    closed = [t for t in reversed(book["trades"]) if t["status"] == "CLOSED"][:15]
    rows = "".join(
        f'<div class="pp-row"><span><b>{escape(t["ticker"])}</b> <span class="pp-tag {"w" if t["result"] > 0 else "l"}">{"WIN" if t["result"] > 0 else "LOSS"}</span> '
        f'<small>{escape(t["kind"])}</small><br><small>{escape(t["exit_reason"] or "")} · {escape(t["closed"] or "")} · held {t["minutes"]} min · peak {_pct(t["best"])}</small></span>'
        f'<span class="{"up" if t["result"] > 0 else "dn"}"><b>{_signed(t["result"])} · {_pct(t["pct"])}</b></span></div>' for t in closed)
    skipped = "".join(f'<div class="pp-row"><span><b>{escape(s["ticker"])}</b> <small>{escape(s["day"])} {escape(s["time"])} · {escape(s["kind"])}</small><br>'
                      f'<small>{escape(s["reason"])}</small></span><span>{_usd(s["price"])}</span></div>' for s in reversed(book["skipped"][-8:]))
    vf = "" if rep["vs_fixed"] is None or not rep["rode"] else \
        f'<div class="pp-m">{rep["rode"]} trades ran past +{quick.FIXED_PCT:g}%. Riding them versus selling at +{quick.FIXED_PCT:g}%: {_signed(rep["vs_fixed"])}</div>'
    hold = "—" if rep["avg_minutes"] is None else f'{rep["avg_minutes"]:.0f} min'
    return (f'<style>{CSS}</style><div class="pp"><div class="pp-c"><div class="pp-h">Quick trading</div>'
            f'<div class="pp-m">A separate fake $50,000. It reads the day\'s chart, enters on its own and rides winners. Nothing here is real money.</div>{msg}'
            f'<div class="pp-k pp-k4"><div><small>Account</small><b>{_usd(eq)}</b></div><div><small>Since start</small>'
            f'<b class="{"up" if eq >= book["start"] else "dn"}">{_signed(eq - book["start"])}</b></div><div><small>Open</small><b>{rep["open"]} trades</b></div>'
            f'<div><small>Winning · losing</small><b>{wl(rep)[0]} · {wl(rep)[1]}</b><small>{rep["wins"]} won · {rep["closed"] - rep["wins"]} lost</small></div></div>'
            f'<div class="pp-m" style="margin-top:8px">Watching {state.get("watching", 0)} stocks you track.</div></div>'
            f'<div class="pp-c"><div class="pp-h">Open now</div>{"".join(opens) or "<div class=pp-m>No open trades.</div>"}</div>'
            f'<div class="pp-c"><div class="pp-h">Closed</div>{rows or "<div class=pp-m>No closed trades yet.</div>"}</div>'
            f'<div class="pp-c"><div class="pp-h">Scoreboard</div><div class="pp-k2"><div><small>Closed</small><b>{rep["closed"]}</b></div>'
            f'<div><small>Winning</small><b>{wl(rep)[0]}</b><small>{rep["wins"]} trades</small></div><div><small>Losing</small><b>{wl(rep)[1]}</b><small>{rep["closed"] - rep["wins"]} trades</small></div><div><small>Average win</small><b>{_pct(rep["avg_win"])}</b></div>'
            f'<div><small>Average loss</small><b>{_pct(rep["avg_loss"])}</b></div><div><small>Average hold</small><b>{hold}</b></div>'
            f'<div><small>Setups skipped</small><b>{rep["skipped"]}</b></div></div>{vf}'
            f'<div class="pp-v">Just watching for now. A few days of trades will show how it behaves; rules come after.</div>'
            f'<div class="pp-hd">Setups it saw but did not take</div>{skipped or "<div class=pp-m>None yet.</div>"}</div></div>')
