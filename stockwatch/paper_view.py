"""The Paper tab: the fake account, the test list, open and closed trades, the buys the gates held back, and the report.
Display only: it reads `paper_live.status`. Nothing here trades or changes a card, score, call or alert."""
from __future__ import annotations

from datetime import datetime
from html import escape

from . import paper


def _usd(v) -> str:
    return "—" if v is None else f'{"-" if v < 0 else ""}${abs(v):,.2f}'


def _signed(v) -> str:
    return "—" if v is None else f'{"+" if v >= 0 else "−"}${abs(v):,.2f}'


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


def html(st: dict, prices: dict | None = None, now: datetime | None = None) -> str:
    book: paper.Book = st["book"]
    state = st.get("state") or {}
    rep = paper.report(book, prices or {})
    day_start = book.start
    eq = rep["equity"]
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
    opens = []
    for t in book.trades:
        if t["status"] != "OPEN":
            continue
        px = (prices or {}).get(t["ticker"])
        pos = book.positions.get(t["ticker"], {})
        move = (px / t["entry"] - 1) * 100 if px else None
        pnl = (px - t["entry"]) * pos.get("shares", t["shares"]) if px else None
        span = (t["target1"] or t["entry"]) - t["stop"]
        spot = max(0, min(100, ((px or t["entry"]) - t["stop"]) / span * 100)) if span else 50
        opens.append(
            f'<div class="pp-t"><div class="pp-th"><b>{escape(t["ticker"])}</b><span class="pp-tag o">OPEN</span></div>'
            f'<div class="pp-m">Bought {escape(t["opened"])} · {pos.get("shares", t["shares"])} sh @ {_usd(t["entry"])}</div>'
            f'<div class="pp-bar"><i style="left:{spot:.0f}%"></i></div>'
            f'<div class="pp-lb"><span>Stop {_usd(pos.get("stop", t["stop"]))}</span>'
            f'<span class="{"up" if (pnl or 0) >= 0 else "dn"}"><b>{_signed(pnl)}{"" if move is None else f" · {move:+.1f}%"}</b></span>'
            f'<span>Target {_usd(t["target1"])}</span></div><div class="pp-why">{escape(t["reason"])}</div></div>')
    closed = [t for t in reversed(book.trades) if t["status"] == "CLOSED"][:12]
    rows = "".join(
        f'<div class="pp-row"><span><b>{escape(t["ticker"])}</b> <span class="pp-tag {"w" if t["result"] > 0 else "l"}">{"WIN" if t["result"] > 0 else "LOSS"}</span><br>'
        f'<small>{escape(t["exit_reason"] or "")} · {escape(t["closed"] or "")}</small></span>'
        f'<span class="{"up" if t["result"] > 0 else "dn"}"><b>{_signed(t["result"])} · {_r(t["r"])}</b></span></div>' for t in closed)
    blocked = "".join(f'<div class="pp-row"><span><b>{escape(b["ticker"])}</b> <small>{escape(b["time"])}</small><br><small>{escape(b["reason"])}</small></span>'
                      f'<span>{_usd(b["price"])}</span></div>' for b in reversed(book.blocked[-8:]))
    wr = "—" if rep["win_rate"] is None else f'{rep["win_rate"] * 100:.0f}%'
    return (f'<style>{CSS}</style><div class="pp"><div class="pp-c"><div class="pp-h">Paper trading</div>'
            f'<div class="pp-m">A fake account follows the rules. Nothing here is real money.</div>{msg}'
            f'<div class="pp-k"><div><small>Account</small><b>{_usd(eq)}</b></div><div><small>Since start</small>'
            f'<b class="{"up" if eq >= day_start else "dn"}">{_signed(eq - day_start)}</b></div><div><small>Open</small><b>{rep["open"]} trades</b></div></div>'
            f'<div class="pp-hd">Test list · {len(state.get("tickers", []))} stocks</div><div class="pp-chs">{chips or "<small>none yet</small>"}</div>{skipped}</div>'
            f'<div class="pp-c"><div class="pp-h">Open now</div>{"".join(opens) or "<div class=pp-m>No open trades.</div>"}</div>'
            f'<div class="pp-c"><div class="pp-h">Closed</div>{rows or "<div class=pp-m>No closed trades yet.</div>"}</div>'
            f'<div class="pp-c"><div class="pp-h">Report</div><div class="pp-k2"><div><small>Closed</small><b>{rep["closed"]}</b></div>'
            f'<div><small>Win rate</small><b>{wr}</b></div><div><small>Average R</small><b>{_r(rep["avg_r"])}</b></div>'
            f'<div><small>Buys held back</small><b>{rep["blocked"]}</b></div></div>'
            f'<div class="pp-v">{escape(rep["verdict"])}</div>'
            f'<div class="pp-hd">Buys the entry gates held back</div>{blocked or "<div class=pp-m>None yet.</div>"}</div></div>')


CSS = """
.pp-c{background:var(--dz-surface,#121a25);border:1px solid var(--dz-line,#243041);border-radius:16px;padding:14px;margin-bottom:12px;color:var(--dz-ink,#e9eef5)}
.pp-h{font-size:1.1rem;font-weight:800}.pp-m,.pp-c small{color:var(--dz-muted,#8b95a7);font-size:.74rem}
.pp-note{margin:8px 0;padding:8px 10px;border-radius:10px;font-size:.78rem;border:1px solid var(--dz-watch,#ffc267);background:color-mix(in srgb,var(--dz-watch,#ffc267) 12%,transparent)}
.pp-note.bad{border-color:var(--dz-act,#ff7a7a);background:color-mix(in srgb,var(--dz-act,#ff7a7a) 12%,transparent)}
.pp-k,.pp-k2{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px}.pp-k2{grid-template-columns:repeat(2,1fr)}
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
