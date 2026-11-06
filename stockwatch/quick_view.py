"""The Quick tab: a fake $50,000 account that reads the day's chart and trades quickly. Display only: it reads `quick.status`.
Nothing here trades or changes a card, score, call or alert."""
from __future__ import annotations

from html import escape

from . import quick, paper_layout as pl
from .paper_view import CSS, _signed, _usd, wl


def _pct(v) -> str:
    return "—" if v is None else f"{v:+.1f}%"


def parts(st: dict, prices: dict | None = None, now=None) -> tuple[str, list, str]:
    """(top, [(ticker, card)], rest): the page in pieces, so the dashboard can put a sell button under each open card."""
    book, state = st["book"], st.get("state") or {}
    prices = prices or {}
    rep = quick.report(book, prices)
    msg = f'<div class="pp-note">{escape(state["note"])}</div>' if state.get("note") else ""
    msg += "".join(f'<div class="pp-sk"><b>{escape(t)}</b> {escape(w)}</div>' for t, w in (state.get("skipped") or {}).items())
    if st.get("sheet_error"):
        msg += f'<div class="pp-note bad">Not saved to Drive: {escape(st["sheet_error"])}</div>'
    m = pl.money(book["cash"], book["start"], book["positions"], prices)
    opens = []
    for t in book["trades"]:
        pos = book["positions"].get(t["ticker"])
        if t["status"] != "OPEN" or not pos:
            continue
        tags = [(t["kind"].upper(), "o")] + ([(f'LEVEL {t["levels"]}', "o")] if int(t.get("levels") or 1) > 1 else [])
        opens.append((t["ticker"], pl.open_card(t, pos, prices.get(t["ticker"]), tags, now, why=t["reason"])))
    closed = [t for t in reversed(book["trades"]) if t["status"] == "CLOSED"][:15]
    rows = "".join(pl.closed_row(t, [(t["kind"].upper(), "o")] + pl.sold_tags(t), t.get("pct"),
                                 f'{t["exit_reason"] or ""} · held {t["minutes"]} min · peak {_pct(t["best"])}') for t in closed)
    skipped = "".join(f'<div class="pp-row"><span><b>{escape(s["ticker"])}</b> <small>{escape(s["day"])} {escape(s["time"])} · {escape(s["kind"])}</small><br>'
                      f'<small>{escape(s["reason"])}</small></span><span>{_usd(s["price"])}</span></div>' for s in reversed(book["skipped"][-8:]))
    vf = "" if rep["vs_fixed"] is None or not rep["rode"] else \
        f'<div class="pp-m">{rep["rode"]} trades ran past +{quick.FIXED_PCT:g}%. Riding them versus selling at +{quick.FIXED_PCT:g}%: {_signed(rep["vs_fixed"])}</div>'
    hold = "—" if rep["avg_minutes"] is None else f'{rep["avg_minutes"]:.0f} min'
    top = (f'<div class="pp-c"><div class="pp-h">Quick trading</div>'
            f'<div class="pp-m">A separate fake $50,000. It reads the day\'s chart, enters on its own and rides winners. Nothing here is real money.</div>{msg}'
            f'{pl.summary_html(m, rep["closed"])}'
            f'<div class="pp-k pp-k2"><div><small>Open</small><b>{rep["open"]} trades</b></div>'
            f'<div><small>Winning · losing</small><b>{wl(rep)[0]} · {wl(rep)[1]}</b><small>{rep["wins"]} won · {rep["closed"] - rep["wins"]} lost</small></div></div>'
            f'<div class="pp-m" style="margin-top:8px">Watching {state.get("watching", 0)} stocks you track.</div></div>')
    rest = (f'<div class="pp-c"><div class="pp-h">Closed</div>{rows or "<div class=pp-m>No closed trades yet.</div>"}</div>'
            f'<div class="pp-c"><div class="pp-h">Scoreboard</div><div class="pp-k2"><div><small>Closed</small><b>{rep["closed"]}</b></div>'
            f'<div><small>Winning</small><b>{wl(rep)[0]}</b><small>{rep["wins"]} trades</small></div><div><small>Losing</small><b>{wl(rep)[1]}</b><small>{rep["closed"] - rep["wins"]} trades</small></div><div><small>Average win</small><b>{_pct(rep["avg_win"])}</b></div>'
            f'<div><small>Average loss</small><b>{_pct(rep["avg_loss"])}</b></div><div><small>Average hold</small><b>{hold}</b></div>'
            f'<div><small>Setups skipped</small><b>{rep["skipped"]}</b></div></div>{vf}'
            f'<div class="pp-v">Just watching for now. A few days of trades will show how it behaves; rules come after.</div>'
            f'<div class="pp-hd">Setups it saw but did not take</div>{skipped or "<div class=pp-m>None yet.</div>"}</div>')
    return top, opens, rest


def open_html(opens: list) -> str:
    return '<div class="pp-c"><div class="pp-h">Open now</div>' + ("".join(c for _t, c in opens) or "<div class=pp-m>No open trades.</div>") + '</div>'


def html(st: dict, prices: dict | None = None, now=None) -> str:
    top, opens, rest = parts(st, prices, now)
    return f'<style>{CSS}</style><div class="pp">{top}{open_html(opens)}{rest}</div>'
