"""The Portfolio tab: a fake account that mirrors the owner's holdings and manages them. Display only: it reads `portfolio.status`.
Nothing here trades or changes a card, score, call or alert. Plain English, phone width, tappable ticker links."""
from __future__ import annotations

from html import escape

from . import portfolio, paper_layout as pl, tape_screens as tape
from .paper_view import CSS as PAPER_CSS

CSS = PAPER_CSS + tape.CSS + """
.pf-tape{color:var(--dz-ink)}.pf-inline{font-size:12px;color:var(--dz-soft)}.pf-tape-head{display:flex;justify-content:space-between;align-items:start;gap:12px}
.pf-tape-head>b{font-size:16px}.pf-tape-result{text-align:right;font-weight:600;font-size:15px}.pf-tape-result.up{color:var(--dz-gain)}.pf-tape-result.dn{color:var(--dz-loss)}.pf-tape-result small{display:block;font-weight:400;font-size:12px;color:var(--dz-soft)}
.pf-tape details{margin-top:8px}.pf-tape summary{font-size:12px;color:var(--dz-soft);min-height:32px;cursor:pointer}
.pp-c:has(>.pf-tape){background:transparent;border:0;border-top:1px solid var(--dz-line);border-radius:0;padding:12px 0}

.pp .pf-a{text-decoration:none;color:var(--dz-ink);border-bottom:1px dotted var(--dz-muted,#8b95a7)}
.pf-prop{border:1px solid var(--dz-act,#ff7a7a);border-radius:12px;padding:10px 12px;margin:8px 0}
.pf-act{padding:8px 0;border-top:1px solid var(--dz-line,#243041);font-size:.9rem}.pf-act:first-of-type{border-top:0}
.pf-act small{color:var(--dz-muted,#8b95a7);display:block}
"""

ACTION_WORDS = {"TRIM": ("TRIMMED", "o"), "SIZE DOWN": ("SIZED DOWN", "o"), "ADD": ("ADDED", "p"), "NEW NAME": ("NEW NAME", "p"),
                "PROPOSE EXIT": ("PROPOSAL", "l"), "SELL ALL": ("SOLD", "l"), "KEPT": ("KEPT", "n"), "SEED": ("STARTED", "n"), "CASH": ("CASH SET", "n"), "HARD STOP": ("STOP HIT", "l"), "PROFIT EXIT": ("PROFIT EXIT", "p"),
                "PROPOSAL WITHDRAWN": ("WITHDRAWN", "n"),
                "PROPOSE TRIM": ("PROPOSAL", "l"), "PROPOSE STARTER": ("PROPOSAL", "l"), "PROPOSE DIP": ("PROPOSAL", "l"), "DIP ADD": ("ADDED", "p"), "STARTER": ("STARTER", "p"), "REBUY": ("BOUGHT BACK", "p"),
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
    sub = [f'<span>{"Worth now " + pl.usd(shares * px) if px else "No price now"}</span>']
    if share is not None:
        sub.append(f'<span>{share:.1f}% of the account</span>')
    if pos.get("core"):
        sub.append(f'<span>core {pos["core"]:g} (never sold by it) · trading {max(0.0, shares - pos["core"]):g}</span>')
    if pos.get("trims"):
        sub.append(f'<span>trimmed {pos["trims"]}×</span>')
    lines = []
    if pos.get("stop"):
        gap = (px / pos["stop"] - 1) * 100 if px else None
        lock = " · break-even or better" if pos["stop"] >= pos["entry"] else ""
        lines.append(f'<span>Hard stop {pl.usd(pos["stop"])}{lock}' + (f' · {gap:.1f}% away' if gap is not None else "") + '</span>')
    if pos.get("target"):
        lines.append(f'<span>Profit exit {pl.usd(pos["target"])} (resistance)</span>')
    elif pos.get("stop") and px and px > pos["entry"]:
        lines.append('<span>No resistance read above: only the stop</span>')
    broker = ('<span class="pl-tag p">BROKER STOP SET</span>' if pos.get("broker_stop") else '<span class="pl-tag l">NO BROKER STOP</span>') if pos.get("stop") else ""
    sub += lines
    why = f'<div class="pl-why">Proposed: sell the rest. {escape(proposal["why"])}</div>' if proposal else ""
    result=pl.signed(pnl) if pnl is not None else 'unknown'
    move_text=pl.pct(move) if move is not None else 'unknown'
    return (f'<div class="pf-tape"><div class="pf-tape-head"><b>{link(ticker)}</b>'
            f'<div class="pf-tape-result {pl._cls(pnl)}">{result}<small>{move_text}</small></div></div>'
            f'<small class="pf-inline">{shares:g} shares · average {pl.usd(entry)}</small><div class="pl-tags">{chips}{broker}<span class="pl-tag {k}">{word}</span></div>{why}'
            f'<details><summary>Position details</summary><div class="pl-g"><div><small>Shares</small><b>{shares:g}</b></div>'
            f'<div><small>Average cost</small><b>{pl.usd(entry)}</b></div><div><small>Price now</small><b>{tape.money(px)}</b></div>'
            f'<div><small>Amount</small><b>{pl.usd(shares*entry,0)}</b></div></div><div class="pl-sub">{"".join(sub)}</div></details></div>')



def _actions(book: dict, n: int = 25) -> str:
    rows = []
    for a in reversed(book["actions"][-n:]):
        word, c = ACTION_WORDS.get(a["action"], (a["action"], "n"))
        what = "" if a["action"] in ("SEED", "KEPT", "PROPOSAL WITHDRAWN", "REMINDER", "REBUY DROPPED", "CASH") else f' {a["shares"]:g} at {pl.usd(a["price"])}' if a.get("price") else ""
        res = "" if a.get("result") is None or a["action"] in ("ADD", "NEW NAME") else f' · {pl.signed(a["result"])}'
        who = "" if a["ticker"] == "—" else f'<b>{link(a["ticker"])}</b> '
        rows.append(f'<div class="pf-act"><span class="pl-tag {c}">{word}</span> {who}{escape(what)}{escape(res)}'
                    f'<small>{pl.riyadh(a["time"])} Riyadh time · {escape(a["why"])}</small></div>')
    return "".join(rows) or '<div class="pp-m">Nothing yet.</div>'


def parts(st: dict, prices: dict | None = None, now=None) -> tuple[str, list, str]:
    """(top, [(ticker, card)], rest): the page in pieces, so the dashboard can put a sell button under each open card."""
    book, state = st["book"], st.get("state") or {}
    prices = {t:px for t,px in (prices or {}).items() if tape.number(px) is not None and px>0}
    if not book["positions"] and not book.get("seeded"):
        return ('<div class="pp-c"><div class="pp-h">Portfolio</div><div class="pp-m">Not started yet. It starts by itself at the next market session, '
                'from the holdings in your Sheet.</div></div>', [], "")
    m = pl.money(book["cash"], book["start"], book["positions"], prices)
    gate = state.get("gate") or ""
    msg = (f'<div class="pp-note">{escape(state["note"])}</div>' if state.get("note") else "")
    msg += "".join(f'<div class="pp-sk"><b>{escape(t)}</b> {escape(w)}</div>' for t, w in (state.get("skipped") or {}).items())
    adds = book.get("adds_day") or {}
    today = f'{adds.get("n", 0)} add{"s" if adds.get("n", 0) != 1 else ""} today' if adds.get("day") == (now.date().isoformat() if now else adds.get("day")) else "no adds today"
    complete=not m['unpriced']
    total_value=m['total'] if complete else None
    profit=pl.signed(m['profit']) if complete else 'unknown'
    top=(f'<div class="ts"><small>Portfolio · total value · fake money</small><div class="ts-price">{tape.money(total_value)}</div>'
         f'<small>Result {profit} · Cash {tape.money(m["cash"])} · {len(book["positions"])} holdings</small>'
         +(f'<div class="ts-warning">{m["unpriced"]} holdings have no current price; total value and result are unknown.</div>' if not complete else '')+
         f'{msg}<div class="ts-foot">Started {pl.riyadh(book["seeded"])} Riyadh · {today} · '
         f'{"adds paused: " + escape(gate) if gate else "adds allowed"}</div></div>')
    account_rows=[('Start',book.get('start')),('Cash used',m['used']),('Realized',m['realized']),('Unrealized',m['unreal'] if complete else None)]
    top+='<div class="ts"><details><summary>Account numbers</summary><div class="ts-table"><table>'+''.join(
        f'<tr><td>{label}</td><td>{tape.money(value)}</td></tr>' for label,value in account_rows)+'</table></div></details></div>'
    ss = portfolio.stop_summary(book)
    if ss["total"]:
        top += (f'<div class="pp-c"><div class="pp-h">Hard stops</div><div class="pp-m"><b>Broker stops set: {ss["set"]} of {ss["total"]}.</b>'
                + (f' Not set: {", ".join(link(t) for t in ss["none"][:14])}{"…" if len(ss["none"])>14 else ""}.' if ss['none'] else '')
                + (' Move up: '+', '.join(f'{link(t)} to {pl.usd(a)} (was {pl.usd(b)})' for t,a,b in ss['move'])+'.' if ss['move'] else '')+
                '<details><summary>Stop behavior</summary>Every position has a hard stop and sells all when the price touches it. '
                'In profit the stop sits at your cost or higher, so a winner cannot turn into a loss, and the stock sells at its resistance.</details></div></div>')
    total = m["total"] or 1.0
    opens = []
    for ticker, pos in sorted(book["positions"].items(), key=lambda kv: -(kv[1]["shares"] * (prices.get(kv[0]) or kv[1]["entry"]))):
        px = prices.get(ticker)
        tags = [("HOLDING" if pos.get("source") == "holding" else "ADDED BY IT", "o")]
        if ticker in book.get("picks", {}):
            tags.insert(0, ("YOUR PICK", "p"))
        if ticker in book.get("dips", {}):
            tags.insert(0, ("ADDS ON DIPS", "p"))
        if ticker in book.get("rebuys", {}):
            tags.append(("BUY-BACK WAITING", "o"))
        if ticker in book["proposals"]:
            tags.append(("EXIT PROPOSED", "l"))
        elif pos.get("trims"):
            tags.append(("TRIMMED", "o"))
        opens.append((ticker, card(ticker, pos, px, tags, book["proposals"].get(ticker), (pos["shares"] * px) / total * 100 if complete and px else None)))
    held = "".join(f'<div class="pp-row"><span><b>{link(b["ticker"])}</b> <small>{pl.riyadh(b["time"])} Riyadh time</small><br>'
                   f'<small>{escape(b["reason"])}</small></span><span>{pl.usd(b["price"])}</span></div>' for b in reversed(book["blocked"][-8:]))
    rules = (f'<div class="pp-m">Trim: the call is EXIT or AVOID and the chart is weak, checked at 15:45 New York, 25% then 25% again, never below half of the most '
             f'it held. Add: fundamentals {portfolio.FUND_ADD:.0f}+, fair value {portfolio.FAIR_UP * 100:.0f}% above the price and the analyst '
             f'target {portfolio.ANALYST_UP * 100:.0f}% above, the call BUY or ADD, risk not High, no earnings in {portfolio.EARN_DAYS} days, turning up with normal volume, '
             f'the market gate open. About {portfolio.RISK_PCT:g}% at risk per add, at most {portfolio.MAX_ADDS_DAY} adds a day. Your picks (KEEP or PICK in the Notes): half is core, never trimmed by it (only the hard stop or you sell it); trims are proposed to you, the buy-back after an approved trim is automatic. First version: it will be adjusted as it runs.</div>')
    sug = ""
    for r in state.get("suggested") or []:
        z = f'buy {r["zone"][0]:.2f} to {r["zone"][1]:.2f}' if r.get("zone") else "no entry zone"
        extra = (f' · stop {r["stop"]:.2f}' if r.get("stop") else "") + (f' · first target {r["target"]:.2f}' if r.get("target") else "")
        sug += (f'<div class="pp-row"><span><b>{link(r["ticker"])}</b> <small>{pl.usd(r["price"])} · fundamentals {r["fund"]:.0f}</small><br>'
                f'<small>{escape(r["note"])} ({z}{extra})</small></span></div>')
    sug = (f'<div class="pp-c"><div class="pp-h">Suggested adds</div><div class="pp-m">Saved suggestions. Tap a stock for its details.</div>{sug or "<div class=pp-m>None right now.</div>"}</div>')
    rest = (f'{sug}<div class="pp-c"><div class="pp-h">What it did</div>{_actions(book)}</div>'
            f'<div class="pp-c"><div class="pp-h">Adds it held back</div>{held or "<div class=pp-m>None yet.</div>"}</div>'
            f'<div class="pp-c"><div class="pp-h">Rules</div>{rules}</div>')
    return top, opens, rest


def html(st: dict, prices: dict | None = None, now=None) -> str:
    top, opens, rest = parts(st, prices, now)
    cards = '<div class="pp-c"><div class="pp-h">Holdings</div>' + ("".join(c for _t, c in opens) or "<div class=pp-m>None open.</div>") + "</div>"
    return f'<style>{CSS}</style><div class="pp">{top}{cards}{rest}</div>'
