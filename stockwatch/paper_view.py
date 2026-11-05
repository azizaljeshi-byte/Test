"""The Paper tab: the fake account, the test list, open and closed trades, the buys the gates held back, and the report.
Display only: it reads `paper_live.status`. Nothing here trades or changes a card, score, call or alert."""
from __future__ import annotations

from datetime import datetime
from html import escape

from . import paper, paper_layout as pl


def _usd(v) -> str:
    return "—" if v is None else f'{"-" if v < 0 else ""}${abs(v):,.2f}'


def _signed(v) -> str:
    return "—" if v is None else f'{"+" if v >= 0 else "−"}${abs(v):,.2f}'


def wl(rep: dict) -> tuple[str, str]:
    """Winning and losing percentages (a flat trade counts as a loss), for the tiles."""
    if not rep["closed"]:
        return "—", "—"
    w = rep["wins"] / rep["closed"] * 100
    return f"{w:.0f}%", f"{100 - w:.0f}%"


def _r(v) -> str:
    return "—" if v is None else f"{v:+.1f}R"


def setup_note(cfg: dict) -> str:
    if not cfg["list"]:
        return ("Not set up yet. Add the test list link as <b>STOCKWATCH_PAPER_LIST_URL</b> in the app's secrets "
                "(the Test list tab of your paper-trading Sheet, shared as Anyone with the link, Viewer), then reboot.")
    if not (cfg["webhook"] and cfg["token"]):
        return ("The test list is connected, but the journal is only kept in the app, which a reboot wipes. "
                "Add <b>STOCKWATCH_PAPER_WEBHOOK</b> and <b>STOCKWATCH_PAPER_TOKEN</b> to keep it in your Sheet (see docs/PAPER_TRADING.md).")
    return ""


def empty_reason(st: dict) -> str:
    """Why the test list is empty, in plain words."""
    state = st.get("state")
    if not st["cfg"]["list"]:
        return "No test list link is set yet."
    if state is not None and state.get("note") and not state.get("tickers"):
        return state["note"]
    if state is None:
        return "The tracker has not run its first paper cycle since the app started. Wait a minute and reload."
    return "The list was read but has no rows with Paper = yes (check the Ticker and Paper headers in the Test list tab)."


def html(st: dict, prices: dict | None = None, now: datetime | None = None) -> str:
    book: paper.Book = st["book"]
    state = st.get("state") or {}
    rep = paper.report(book, prices or {})
    chips = "".join(
        f'<span class="pp-ch{" off" if t in (state.get("skipped") or {}) else ""}" title="{escape((state.get("skipped") or {}).get(t, ""))}">{escape(t)}</span>'
        for t in state.get("tickers", []))
    skipped = "".join(f'<div class="pp-sk"><b>{escape(t)}</b> {escape(w)}</div>' for t, w in (state.get("skipped") or {}).items())
    note = setup_note(st["cfg"])
    msg = f'<div class="pp-note">{note}</div>' if note else ""
    if state.get("note") and not note:
        msg += f'<div class="pp-note">{escape(state["note"])}</div>'
    if st.get("push_error"):
        msg += f'<div class="pp-note bad">The Sheet did not accept the last save: {escape(st["push_error"])}</div>'
    m = pl.money(book.cash, book.start, book.positions, prices or {})
    tests = [t for t in book.trades if t["status"] == "CLOSED" and str(t.get("exit_reason") or "").startswith("forced sell")]
    opens = []
    for t in book.trades:
        pos = book.positions.get(t["ticker"])
        if t["status"] != "OPEN" or not pos:
            continue
        call = str(t["reason"]).split(":")[0].strip()
        tags = ([(f"{call} CALL", "o")] if call in ("BUY", "ADD") else []) + ([("STRETCHING", "o")] if pos.get("stretch") else [])
        opens.append(pl.open_card(t, pos, (prices or {}).get(t["ticker"]), tags, now, why=t["reason"]))
    closed = [t for t in reversed(book.trades) if t["status"] == "CLOSED"][:12]
    rows = "".join(pl.closed_row(t, [("TEST SELL", "n")] if str(t.get("exit_reason") or "").startswith("forced sell") else [],
                                 t["result"] / (t["entry"] * t["shares"]) * 100 if t.get("entry") and t.get("shares") else None,
                                 f'{t["exit_reason"] or ""} · {_r(t.get("r"))}') for t in closed)
    blocked = "".join(f'<div class="pp-row"><span><b>{escape(b["ticker"])}</b> <small>{escape(b["time"])}</small><br><small>{escape(b["reason"])}</small></span>'
                      f'<span>{_usd(b["price"])}</span></div>' for b in reversed(book.blocked[-8:]))
    sg = rep["stretch_gain"]
    stretch_line = "" if sg is None else f" · versus selling all at the first target: {_signed(sg)}"
    return (f'<style>{CSS}</style><div class="pp"><div class="pp-c"><div class="pp-h">Paper trading</div>'
            f'<div class="pp-m">A fake account follows the rules. Nothing here is real money.</div>{msg}'
            f'{pl.summary_html(m, rep["closed"] - len(tests), len(tests), sum(t["result"] for t in tests))}'
            f'<div class="pp-k pp-k2"><div><small>Open</small><b>{rep["open"]} trades</b></div>'
            f'<div><small>Winning · losing</small><b>{wl(rep)[0]} · {wl(rep)[1]}</b><small>{rep["wins"]} won · {rep["closed"] - rep["wins"]} lost</small></div></div>'
            f'<div class="pp-hd">Test list · {len(state.get("tickers", []))} stocks</div><div class="pp-chs">{chips or "<small>" + empty_reason(st) + "</small>"}</div>{skipped}</div>'
            f'<div class="pp-c"><div class="pp-h">Open now</div>{"".join(opens) or "<div class=pp-m>No open trades.</div>"}</div>'
            f'<div class="pp-c"><div class="pp-h">Closed</div>{rows or "<div class=pp-m>No closed trades yet.</div>"}</div>'
            f'<div class="pp-c"><div class="pp-h">Report</div><div class="pp-k2"><div><small>Closed</small><b>{rep["closed"]}</b></div>'
            f'<div><small>Winning</small><b>{wl(rep)[0]}</b><small>{rep["wins"]} trades</small></div><div><small>Losing</small><b>{wl(rep)[1]}</b><small>{rep["closed"] - rep["wins"]} trades</small></div><div><small>Average R</small><b>{_r(rep["avg_r"])}</b></div>'
            f'<div><small>Buys held back</small><b>{rep["blocked"]}</b></div></div>'
            f'<div class="pp-m">Stretched trades: {rep["stretched"]}{stretch_line}</div>'
            f'<div class="pp-v">{escape(rep["verdict"])}</div>'
            f'<div class="pp-hd">Buys the entry gates held back</div>{blocked or "<div class=pp-m>None yet.</div>"}</div></div>')


CSS = pl.CSS + """
.pp-c{background:var(--dz-surface,#121a25);border:1px solid var(--dz-line,#243041);border-radius:16px;padding:14px;margin-bottom:12px;color:var(--dz-ink,#e9eef5)}
.pp-h{font-size:1.1rem;font-weight:800}.pp-m,.pp-c small{color:var(--dz-muted,#8b95a7);font-size:.74rem}
.pp-note{margin:8px 0;padding:8px 10px;border-radius:10px;font-size:.78rem;border:1px solid var(--dz-watch,#ffc267);background:color-mix(in srgb,var(--dz-watch,#ffc267) 12%,transparent)}
.pp-note.bad{border-color:var(--dz-act,#ff7a7a);background:color-mix(in srgb,var(--dz-act,#ff7a7a) 12%,transparent)}
.pp-k,.pp-k2{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px}.pp-k2{grid-template-columns:repeat(2,1fr)}.pp-k4{grid-template-columns:repeat(4,1fr)}@media(max-width:560px){.pp-k4{grid-template-columns:repeat(2,1fr)}}
.pp-k>div,.pp-k2>div{background:color-mix(in srgb,var(--dz-ink,#e9eef5) 6%,transparent);border-radius:10px;padding:8px}.pp-k b,.pp-k2 b{display:block;font-size:1.05rem}
.up{color:var(--dz-buy,#7be3a8)}.dn{color:var(--dz-act,#ff7a7a)}
.pp-hd{font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;color:var(--dz-soft,#9aa4b2);font-weight:800;margin:14px 0 6px}
.pp-chs{display:flex;flex-wrap:wrap;gap:6px}.pp-ch{border:1px solid var(--dz-line,#243041);border-radius:99px;padding:4px 10px;font-weight:800;font-size:.78rem}.pp-ch.off{opacity:.45;border-style:dashed}
.pp-sk{font-size:.72rem;color:var(--dz-muted,#8b95a7);margin-top:4px}.pp-sk b{color:var(--dz-ink,#e9eef5)}
.pp-t{padding:10px 0;border-top:1px solid var(--dz-line,#243041)}.pp-t:first-of-type{border-top:0}.pp-th{display:flex;justify-content:space-between;align-items:baseline}
.pp-tag{font-size:.66rem;font-weight:800;padding:2px 7px;border-radius:99px;border:1px solid}.pp-tag.o{color:var(--dz-watch,#ffc267)}.pp-tag.w{color:var(--dz-buy,#7be3a8)}.pp-tag.l{color:var(--dz-act,#ff7a7a)}
.pp-bar{position:relative;height:8px;border-radius:5px;background:linear-gradient(90deg,var(--dz-act,#ff7a7a),var(--dz-line,#243041) 45%,var(--dz-buy,#7be3a8));margin:12px 0 4px}
.pp-bar i{position:absolute;top:-4px;width:4px;height:16px;border-radius:2px;background:var(--dz-ink,#e9eef5)}
.pp-lb{display:flex;justify-content:space-between;font-size:.66rem;color:var(--dz-muted,#8b95a7)}.pp-why{font-size:.76rem;margin-top:4px}
.pp-row{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-top:1px solid var(--dz-line,#243041);font-size:.82rem}.pp-row:first-of-type{border-top:0}
.pp-v{padding:9px 10px;border-radius:10px;margin-top:10px;font-size:.84rem;font-weight:700;background:color-mix(in srgb,var(--dz-watch,#ffc267) 16%,transparent);border:1px solid var(--dz-watch,#ffc267)}
"""
