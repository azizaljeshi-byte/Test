"""One layout for the New call and Quick test accounts (owner, 5 Nov): the money summary, and one card per position with shares, entry
price, price now, the amount, a profit/loss badge with the figure and the percent, when it was bought, what kind of setup it is and what
it is doing now. Display only: it reads the books and prices, trades nothing and changes no rule, call or score."""
from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

NY, RIYADH = ZoneInfo("America/New_York"), ZoneInfo("Asia/Riyadh")
SLOW_MIN = 5                      # in profit and no new high for this long: the move is slowing (display only)


def usd(v, d: int = 2) -> str:
    return "—" if v is None else f'{"-" if v < 0 else ""}${abs(v):,.{d}f}'


def signed(v) -> str:
    return "—" if v is None else f'{"+" if v >= 0 else "−"}${abs(v):,.2f}'


def pct(v) -> str:
    return "—" if v is None else f'{"+" if v >= 0 else "−"}{abs(v):.1f}%'


def _cls(v) -> str:
    return "" if v is None else "up" if v >= 0 else "dn"


def riyadh(s) -> str:
    """'2026-11-04 12:02' (the New York clock the books use) as 'Nov 4 · 19:02', the owner's clock."""
    try:
        d = datetime.strptime(str(s)[:16], "%Y-%m-%d %H:%M").replace(tzinfo=NY).astimezone(RIYADH)
    except (ValueError, TypeError):
        return "—"
    return f"{d:%b} {d.day} · {d:%H:%M}"


def _aware(s) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=NY)


def money(cash: float, start: float, positions: dict, prices: dict) -> dict:
    """The account in dollars. Cash used is what the open positions cost, so cash + cash used = start + realized profit, whatever was sold
    in part or added to. A position with no price now is left out of the unrealized figure (unknown, never 0) and counted in `unpriced`."""
    used = sum(p["shares"] * p["entry"] for p in positions.values())
    priced = {t: p for t, p in positions.items() if prices.get(t)}
    unreal = sum((prices[t] - p["entry"]) * p["shares"] for t, p in priced.items())
    worth = cash + sum(p["shares"] * (prices.get(t) or p["entry"]) for t, p in positions.items())
    realized = cash + used - start
    return {"total": worth, "cash": cash, "used": used, "realized": realized, "unreal": unreal if positions else 0.0, "unpriced": len(positions) - len(priced),
            "profit": worth - start, "start": start, "n": len(positions), "cost_priced": sum(p["shares"] * p["entry"] for p in priced.values())}


def summary_html(m: dict, closed: int, tests: int = 0, test_sum: float = 0.0) -> str:
    pct = lambda a, b: "" if not b else f'{"+" if a >= 0 else "−"}{abs(a / b * 100):.2f}%'      # noqa: E731
    note = f'<small>includes {signed(test_sum)} from {tests} button test{"s" if tests != 1 else ""}</small>' if tests else ""
    miss = f'<small>{m["unpriced"]} open without a price now, left out</small>' if m["unpriced"] else "<small>open positions, right now</small>"
    return (f'<div class="pl-big"><div><small>Total amount</small><b>{usd(m["total"])}</b></div>'
            f'<div><small>Total profit</small><b class="{_cls(m["profit"])}">{signed(m["profit"])}</b><small>{pct(m["profit"], m["start"])} since {usd(m["start"], 0)}</small></div></div>'
            f'<div class="pl-k"><div><small>Cash at hand</small><b>{usd(m["cash"])}</b><small>{m["cash"] / m["total"] * 100:.0f}% of the account</small></div>'
            f'<div><small>Cash used</small><b>{usd(m["used"])}</b><small>{m["n"]} open position{"s" if m["n"] != 1 else ""}, at cost</small></div>'
            f'<div><small>Realized profit</small><b class="{_cls(m["realized"])}">{signed(m["realized"])}</b><small>{closed} closed trades{"<br>" if note else ""}</small>{note}</div>'
            f'<div><small>Unrealized profit</small><b class="{_cls(m["unreal"])}">{signed(m["unreal"])}</b>{miss}</div></div>')


def badge(pnl) -> tuple[str, str]:
    if pnl is None:
        return "NO PRICE", "n"
    return ("IN PROFIT", "p") if pnl > 0 else ("IN LOSS", "l") if pnl < 0 else ("BREAK-EVEN", "n")


def status(pos: dict, px, now: datetime | None = None) -> tuple[str, str]:
    """(tag, note) for what an open position is doing: RIDING (the stop is above the entry, so a profit is locked in), RISING, SLOWING (in
    profit, no new high for SLOW_MIN minutes), a dip read from the account's own rule, or BELOW ENTRY. Empty when there is no price."""
    if not px:
        return "", ""
    now = (now or datetime.now(NY)).astimezone(NY)
    entry = pos["entry"]
    stop = max(pos.get("trail") or 0.0, pos.get("stop") or 0.0)
    read = str(pos.get("read") or "")
    if px < entry:
        low = read.lower()
        if "stabilis" in low and "or stabilis" not in low:
            return "STABILISING", read
        if "falling" in low and "or stabilis" not in low:
            return "FALLING", read
        return ("DIP WATCH", read) if read else ("BELOW ENTRY", "")
    if stop > entry:
        return "RIDING", f"profit locked in above {usd(stop)}"
    at = _aware(pos.get("peak_at") or pos.get("best_at"))
    if at is not None and (now - at).total_seconds() / 60 >= SLOW_MIN:
        mins = int((now - at).total_seconds() // 60)
        return "SLOWING", "no new high for " + (f"{mins} min" if mins < 120 else f"{mins / 60:.0f} h")
    return "RISING", ""


def open_card(t: dict, pos: dict, px, tags: list[tuple[str, str]], now=None, extra: str = "", why: str = "") -> str:
    shares, entry = pos["shares"], pos["entry"]
    pnl = (px - entry) * shares if px else None
    move = (px / entry - 1) * 100 if px else None
    word, k = badge(pnl)
    st, note = status(pos, px, now)
    chips = "".join(f'<span class="pl-tag {c}">{escape(x)}</span>' for x, c in tags) + (f'<span class="pl-tag s">{escape(st)}</span>' if st else "")
    verb = "Profit" if (pnl or 0) > 0 else "Loss" if (pnl or 0) < 0 else "Result"
    fig = "—" if pnl is None else f"{signed(pnl)} · {pct(move)}"
    return (f'<div class="pl-t"><div class="pl-th"><b>{escape(t["ticker"])}</b><span class="pl-tag {k}">{word}</span></div>'
            f'<div class="pl-tags">{chips}</div><div class="pl-when">Bought {riyadh(t["opened"])} Riyadh time</div>'
            f'<div class="pl-g"><div><small>Shares</small><b>{shares:g}</b></div><div><small>Entry price</small><b>{usd(entry)}</b></div>'
            f'<div><small>Price now</small><b>{usd(px)}</b></div><div><small>Amount</small><b>{usd(shares * entry, 0)}</b></div></div>'
            f'<div class="pl-res"><span>{verb}</span><b class="{_cls(pnl)}">{fig}</b></div>'
            f'<div class="pl-sub"><span>{"Worth now " + usd(shares * px) if px else "No price now"}</span><span>Stop {usd(pos.get("trail") or pos.get("stop"))}</span>{extra}</div>'
            + (f'<div class="pl-why">{escape(note)}</div>' if note else "") + (f'<div class="pl-why">{escape(why)}</div>' if why else "") + '</div>')


def closed_row(t: dict, tags: list[tuple[str, str]], pct_, detail: str) -> str:
    shares, entry, out, res = t["shares"], t["entry"], t.get("exit"), t["result"]
    won = res > 0
    chips = f'<span class="pl-tag {"p" if won else "l"}">{"WIN" if won else "LOSS"}</span>' + "".join(f'<span class="pl-tag {c}">{escape(x)}</span>' for x, c in tags)
    p = "" if pct_ is None else f" · {pct(pct_)}"
    return (f'<div class="pl-t"><div class="pl-th"><b>{escape(t["ticker"])}</b><span class="pl-tags">{chips}</span></div>'
            f'<div class="pl-when">Bought {riyadh(t["opened"])} · sold {riyadh(t.get("closed"))} Riyadh time</div>'
            f'<div class="pl-g"><div><small>Shares</small><b>{shares:g}</b></div><div><small>Entry price</small><b>{usd(entry)}</b></div>'
            f'<div><small>Sold at</small><b>{usd(out)}</b></div><div><small>Amount</small><b>{usd(shares * entry, 0)}</b></div></div>'
            f'<div class="pl-res"><span>{"Profit" if won else "Loss"}</span><b class="{_cls(res)}">{signed(res)}{p}</b></div>'
            f'<div class="pl-why">{escape(detail)}</div></div>')


CSS = """
.pl-big{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px}.pl-big>div,.pl-k>div{background:color-mix(in srgb,var(--dz-ink,#e9eef5) 6%,transparent);border-radius:10px;padding:8px}
.pl-big b{display:block;font-size:1.3rem}.pl-k{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px}.pl-k b{display:block;font-size:1.02rem}
.pl-t{padding:12px 0;border-top:1px solid var(--dz-line,#243041)}.pl-t:first-of-type{border-top:0}
.pl-th{display:flex;justify-content:space-between;align-items:center;gap:8px}.pl-th>b{font-size:1.05rem}
.pl-tags{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}.pl-th .pl-tags{margin-top:0;justify-content:flex-end}
.pl-tag{font-size:.66rem;font-weight:800;padding:2px 8px;border-radius:99px;border:1px solid;white-space:nowrap}
.pl-tag.p{color:var(--dz-buy,#7be3a8)}.pl-tag.l{color:var(--dz-act,#ff7a7a)}.pl-tag.n{color:var(--dz-muted,#8b95a7)}.pl-tag.o{color:var(--dz-watch,#ffc267)}.pl-tag.s{color:var(--dz-ink,#e9eef5)}
.pl-when{font-size:.72rem;color:var(--dz-muted,#8b95a7);margin-top:6px}
.pl-g{display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin:8px 0 6px}.pl-g small{display:block}.pl-g b{font-size:.9rem}
.pl-res{display:flex;justify-content:space-between;align-items:center;background:color-mix(in srgb,var(--dz-ink,#e9eef5) 6%,transparent);border-radius:10px;padding:8px 10px}.pl-res b{font-size:1.05rem}
.pl-sub{font-size:.7rem;color:var(--dz-muted,#8b95a7);margin-top:6px;display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}.pl-why{font-size:.74rem;margin-top:4px}
"""
