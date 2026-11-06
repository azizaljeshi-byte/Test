"""The Portfolio tab: a fake account that mirrors the owner's holdings and manages them. Display only: it reads `portfolio.status`.
Nothing here trades or changes a card, score, call or alert. Plain English, phone width, tappable ticker links."""
from __future__ import annotations

from html import escape

from . import portfolio, paper_layout as pl
from .paper_view import CSS as PAPER_CSS

CSS = PAPER_CSS + """
.pf-a{text-decoration:none;color:inherit;border-bottom:1px dotted var(--dz-muted,#8b95a7)}
.pf-prop{border:1px solid var(--dz-act,#ff7a7a);border-radius:12px;padding:10px 12px;margin:8px 0}
.pf-act{padding:8px 0;border-top:1px solid var(--dz-line,#243041);font-size:.9rem}.pf-act:first-of-type{border-top:0}
.pf-act small{color:var(--dz-muted,#8b95a7);display:block}
"""

ACTION_WORDS = {"TRIM": ("TRIMMED", "o"), "SIZE DOWN": ("SIZED DOWN", "o"), "ADD": ("ADDED", "p"), "NEW NAME": ("NEW NAME", "p"),
                "PROPOSE EXIT": ("PROPOSAL", "l"), "SELL ALL": ("SOLD", "l"), "KEPT": ("KEPT", "n"), "SEED": ("STARTED", "n"),
                "PROPOSAL WITHDRAWN": ("WITHDRAWN", "n"),
                "PROPOSE TRIM": ("PROPOSAL", "l"), "PROPOSE STARTER": ("PROPOSAL", "l"), "STARTER": ("STARTER", "p"), "REBUY": ("BOUGHT BACK", "p"),
                "REMINDER": ("STILL FALLING", "o"), "SKIPPED": ("SKIPPED", "n"), "REBUY DROPPED": ("DROPPED", "n")}


def link(ticker: str) -> str:
    t = escape(ticker)
    return f'<a class="pf-a" href="?view=target&t={t}" target="_self">{t}</a>'


def card(ticker: str, pos: dict, px, tags: list, proposal: dict | None, share: float | None) -> str:
    """One holding: shares, average cost, price now, amount, profit or loss, its share of the account and what the account has done to it."""
    shares, entry = pos["shares"], pos["entry"]
    pnl = (px - entry) * shares if px else None
    move = (px / entry - 1) * 100 if px else None
    word, k = pl.badge(pnl)
    chips = "".join(f'<span class="pl-tag {c}">{escape(x)}</span>' for x, c in tags)
    verb = "Profit" if (pnl or 0) > 0 else "Loss" if (pnl or 0) < 0 else "Result"
    fig = "—" if pnl is None else f"{pl.signed(pnl)} · {pl.pct(move)}"
    sub = [f'<span>{"Worth now " + pl.usd(shares * px) if px else "No price now"}</span>']
    if share is not None:
        sub.append(f'<span>{share:.1f}% of the account</span>')
    if pos.get("core"):
        sub.append(f'<span>core {pos["core"]:g} (never sold by it) · trading {max(0.0, shares - pos["core"]):g}</span>')
    if pos.get("trims"):
        sub.append(f'<span>trimmed {pos["trims"]}×</span>')
    why = f'<div class="pl-why">Proposed: sell the rest. {escape(proposal["why"])}</div>' if proposal else ""
    return (f'<div class="pl-t"><div class="pl-th"><b>{link(ticker)}</b><span class="pl-tag {k}">{word}</span></div>'
            f'<div class="pl-tags">{chips}</div>'
            f'<div class="pl-g"><div><small>Shares</small><b>{shares:g}</b></div><div><small>Average cost</small><b>{pl.usd(entry)}</b></div>'
            f'<div><small>Price now</small><b>{pl.usd(px)}</b></div><div><small>Amount</small><b>{pl.usd(shares * entry, 0)}</b></div></div>'
            f'<div class="pl-res"><span>{verb}</span><b class="{pl._cls(pnl)}">{fig}</b></div>'
            f'<div class="pl-sub">{"".join(sub)}</div>{why}</div>')


def _actions(book: dict, n: int = 25) -> str:
    rows = []
    for a in reversed(book["actions"][-n:]):
        word, c = ACTION_WORDS.get(a["action"], (a["action"], "n"))
        what = "" if a["action"] in ("SEED", "KEPT", "PROPOSAL WITHDRAWN", "REMINDER", "REBUY DROPPED") else f' {a["shares"]:g} at {pl.usd(a["price"])}' if a.get("price") else ""
        res = "" if a.get("result") is None or a["action"] in ("ADD", "NEW NAME") else f' · {pl.signed(a["result"])}'
        who = "" if a["ticker"] == "—" else f'<b>{link(a["ticker"])}</b> '
        rows.append(f'<div class="pf-act"><span class="pl-tag {c}">{word}</span> {who}{escape(what)}{escape(res)}'
                    f'<small>{pl.riyadh(a["time"])} Riyadh time · {escape(a["why"])}</small></div>')
    return "".join(rows) or '<div class="pp-m">Nothing yet.</div>'


def parts(st: dict, prices: dict | None = None, now=None) -> tuple[str, list, str]:
    """(top, [(ticker, card)], rest): the page in pieces, so the dashboard can put a sell button under each open card."""
    book, state = st["book"], st.get("state") or {}
    prices = prices or {}
    if not book["positions"] and not book.get("seeded"):
        return ('<div class="pp-c"><div class="pp-h">Portfolio</div><div class="pp-m">Not started yet. It starts by itself at the next market session, '
                'from the holdings in your Sheet.</div></div>', [], "")
    m = pl.money(book["cash"], book["start"], book["positions"], prices)
    sales = len([a for a in book["actions"] if a["action"] in ("TRIM", "SIZE DOWN", "SELL ALL")])
    gate = state.get("gate") or ""
    msg = (f'<div class="pp-note">{escape(state["note"])}</div>' if state.get("note") else "")
    msg += "".join(f'<div class="pp-sk"><b>{escape(t)}</b> {escape(w)}</div>' for t, w in (state.get("skipped") or {}).items())
    adds = book.get("adds_day") or {}
    today = f'{adds.get("n", 0)} add{"s" if adds.get("n", 0) != 1 else ""} today' if adds.get("day") == (now.date().isoformat() if now else adds.get("day")) else "no adds today"
    top = (f'<div class="pp-c"><div class="pp-h">Portfolio</div>'
           f'<div class="pp-m">A fake account that mirrors the stocks you hold, at your cost, and manages them carefully. It trims poor positions in steps, '
           f'sizes down big ones and adds only to undervalued stocks with very strong fundamentals. It never sells one to zero without your yes. '
           f'Stocks you flag KEEP or PICK in the Notes column are yours: half is a core it never sells, the other half is traded only when you tap Approve. '
           f'Nothing here is real money.</div>{msg}'
           f'{pl.summary_html(m, sales, closed_label="trim or sale" if sales == 1 else "trims and sales")}'
           f'<div class="pp-m" style="margin-top:8px">Started {pl.riyadh(book["seeded"])} Riyadh time · {today} · '
           f'{"adds paused: " + escape(gate) if gate else "adds allowed"} · watching {state.get("watching", 0)} stocks.</div></div>')
    total = m["total"] or 1.0
    opens = []
    for ticker, pos in sorted(book["positions"].items(), key=lambda kv: -(kv[1]["shares"] * (prices.get(kv[0]) or kv[1]["entry"]))):
        px = prices.get(ticker)
        tags = [("HOLDING" if pos.get("source") == "holding" else "ADDED BY IT", "o")]
        if ticker in book.get("picks", {}):
            tags.insert(0, ("YOUR PICK", "p"))
        if ticker in book.get("rebuys", {}):
            tags.append(("BUY-BACK WAITING", "o"))
        if ticker in book["proposals"]:
            tags.append(("EXIT PROPOSED", "l"))
        elif pos.get("trims"):
            tags.append(("TRIMMED", "o"))
        opens.append((ticker, card(ticker, pos, px, tags, book["proposals"].get(ticker), (pos["shares"] * (px or pos["entry"])) / total * 100)))
    held = "".join(f'<div class="pp-row"><span><b>{link(b["ticker"])}</b> <small>{pl.riyadh(b["time"])} Riyadh time</small><br>'
                   f'<small>{escape(b["reason"])}</small></span><span>{pl.usd(b["price"])}</span></div>' for b in reversed(book["blocked"][-8:]))
    rules = (f'<div class="pp-m">Trim: the call is EXIT or AVOID and the chart is weak, checked at 15:45 New York, 25% then 25% again, never below half of the most '
             f'it held. Add: fundamentals {portfolio.FUND_ADD:.0f}+, fair value {portfolio.FAIR_UP * 100:.0f}% above the price and the analyst '
             f'target {portfolio.ANALYST_UP * 100:.0f}% above, the call BUY or ADD, risk not High, no earnings in {portfolio.EARN_DAYS} days, turning up with normal volume, '
             f'the market gate open. About {portfolio.RISK_PCT:g}% at risk per add, at most {portfolio.MAX_ADDS_DAY} adds a day. Your picks (KEEP or PICK in the Notes): half is core and never sold by it; trims are proposed to you, the buy-back after an approved trim is automatic. First version: it will be adjusted as it runs.</div>')
    sug = ""
    for r in state.get("suggested") or []:
        z = f'buy {r["zone"][0]:.2f} to {r["zone"][1]:.2f}' if r.get("zone") else "no entry zone"
        extra = (f' · stop {r["stop"]:.2f}' if r.get("stop") else "") + (f' · first target {r["target"]:.2f}' if r.get("target") else "")
        sug += (f'<div class="pp-row"><span><b>{link(r["ticker"])}</b> <small>{pl.usd(r["price"])} · fundamentals {r["fund"]:.0f}</small><br>'
                f'<small>{escape(r["note"])} ({z}{extra})</small></span></div>')
    sug = (f'<div class="pp-c"><div class="pp-h">Suggested adds</div><div class="pp-m">Stocks you do not hold, with strong fundamentals and a price under fair value. '
           f'Tap one to open it. For a stock you want anyway, flag it PICK in your Sheet.</div>{sug or "<div class=pp-m>None right now.</div>"}</div>')
    rest = (f'{sug}<div class="pp-c"><div class="pp-h">What it did</div>{_actions(book)}</div>'
            f'<div class="pp-c"><div class="pp-h">Adds it held back</div>{held or "<div class=pp-m>None yet.</div>"}</div>'
            f'<div class="pp-c"><div class="pp-h">Rules</div>{rules}</div>')
    return top, opens, rest


def html(st: dict, prices: dict | None = None, now=None) -> str:
    top, opens, rest = parts(st, prices, now)
    cards = '<div class="pp-c"><div class="pp-h">Holdings</div>' + ("".join(c for _t, c in opens) or "<div class=pp-m>None open.</div>") + "</div>"
    return f'<style>{CSS}</style><div class="pp">{top}{cards}{rest}</div>'
