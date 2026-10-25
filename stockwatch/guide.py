"""The trade guide on Details: a Buy tab and a Sell tab that walk through the steps. Display only: it reads the call,
the entry gates (`status.entry_blockers`), the plan (entry zone, stop, targets) and `tradeplan.size`, and changes none.

Buy: 1 check (a tick or cross per gate and one verdict: BUY, WAIT or DON'T BUY), 2 entry (zone against the live price),
3 size (account, risk per trade, shares, capped by the tier limit), 4 stop (stop, chart exit, Target 1, reward against risk).
Sell: why, how much, when, where. A missing read is "not read", never a pass or a fail.
"""
from __future__ import annotations

from html import escape

from . import status, tradeplan, ui
from .ui import nan

BUY_CALLS = ("BUY NOW", "BUY ON DIP", "BUY ON BREAKOUT", "BUY MORE")
HARD_BLOCK_DAYS = 2


def _usd(v) -> str:
    return "n/a" if v is None or nan(v) else f"${v:,.2f}"


def _ok(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def gates(snap: dict) -> list[dict]:
    """[{state: ok|bad|none, title, note}] one per check a buyer wants: zone, chart, momentum, second opinion, earnings."""
    p = snap["payload"]
    plan = p.get("plan") or {}
    price, _ = ui._price(snap)
    ps = ui.price_status(snap) or {}
    out = []
    lo, hi = plan.get("entry_low"), plan.get("entry_high")
    if _ok(price) and _ok(lo) and _ok(hi) and lo > 0:
        if lo <= price <= hi:
            out.append({"state": "ok", "title": "In the entry zone", "note": f"{lo:.2f} to {hi:.2f} · now {price:.2f}"})
        elif price > hi:
            out.append({"state": "bad", "title": "Above the entry zone", "note": f"zone {lo:.2f} to {hi:.2f} · now {price:.2f}: wait for a pullback"})
        else:
            out.append({"state": "bad", "title": "Below the entry zone", "note": f"zone {lo:.2f} to {hi:.2f} · now {price:.2f}: it is falling through"})
    else:
        out.append({"state": "none", "title": "Entry zone", "note": "no zone for this stock"})
    code = ps.get("code")
    if not code or code == "unknown":
        out.append({"state": "none", "title": "Chart", "note": "not read"})
    elif code in status.GATE_BAD_CHART + status.EXIT_CODES:
        out.append({"state": "bad", "title": "Chart", "note": (ps.get("label") or code).lower()})
    else:
        out.append({"state": "ok", "title": "Chart", "note": (ps.get("label") or code).lower()})
    mo = ui.momentum_of(snap)
    if not mo:
        out.append({"state": "none", "title": "Momentum", "note": "not read"})
    else:
        bad = mo["momentum"] in status.GATE_BAD_MOMENTUM
        out.append({"state": "bad" if bad else "ok", "title": "Momentum", "note": f'{mo["momentum_label"].lower()}, {mo["cause_label"]}'})
    sec = ps.get("second")
    if not sec or sec.get("unavailable") or not sec.get("signal"):
        out.append({"state": "none", "title": "Second opinion", "note": "not asked or not available"})
    else:
        out.append({"state": "bad" if sec["signal"] == "sell" else "ok", "title": sec.get("source", "Second opinion"),
                    "note": sec["signal"].upper()})
    days = (p.get("events") or {}).get("days_to_earnings")
    if days is None:
        out.append({"state": "none", "title": "Earnings", "note": "date not known"})
    elif days <= HARD_BLOCK_DAYS:
        out.append({"state": "bad", "title": "Earnings", "note": f"in {days} day{'s' if days != 1 else ''}: wait for the report"})
    else:
        out.append({"state": "ok", "title": "Earnings", "note": f"in {days} days"})
    return out


def verdict(snap: dict, gs: list[dict]) -> tuple[str, str, str]:
    """(word, class, one line). BUY only when the plan's call is a buy and no gate failed; DON'T BUY on a broken
    chart, earnings within two days or a sell plan; otherwise WAIT with the first thing missing."""
    call = ui.action(snap)[0]
    bad = [g for g in gs if g["state"] == "bad"]
    ps = ui.price_status(snap) or {}
    hard = ps.get("code") in status.EXIT_CODES or any(g["title"] == "Earnings" and g["state"] == "bad" for g in gs)
    if call in ("SELL", "SELL SOME", "REASSESS", "NO SIGNAL") or (hard and bad):
        return "DON'T BUY", "bad", f"The call is {call.lower()}." if call != "REASSESS" else "A sell is waiting for the close."
    if bad:
        first = bad[0]
        return "WAIT", "watch", f'{first["title"]}: {first["note"]}.'
    if call not in BUY_CALLS:
        return "WAIT", "watch", f"The plan says {call.lower()}, not buy."
    return "BUY", "good", "Every check agrees. Place a limit order, then the stop."


def _gate_row(g: dict) -> str:
    sym = {"ok": "✓", "bad": "✕", "none": "?"}[g["state"]]
    return f'<div class="tg-g {g["state"]}"><span>{sym}</span><div>{escape(g["title"])}<small>{escape(g["note"])}</small></div></div>'


def _step(n: int, title: str, body: str) -> str:
    return f'<div class="tg-s"><i>{n}</i><div><b>{escape(title)}</b>{body}</div></div>'


def _cell(label: str, value: str, extra: str = "", cls: str = "") -> str:
    return f'<div class="{cls}"><small>{escape(label)}</small><b>{value}</b>{f"<em>{extra}</em>" if extra else ""}</div>'


def buy_tab(snap: dict, account: float, risk_pct: float, max_pct: float) -> str:
    p = snap["payload"]
    plan = p.get("plan") or {}
    price, _ = ui._price(snap)
    gs = gates(snap)
    word, cls, line = verdict(snap, gs)
    steps = [_step(1, "Check: is it still a buy?", "".join(_gate_row(g) for g in gs)
                   + f'<div class="tg-v {cls}"><b>{escape(word)}</b> {escape(line)}</div>')]
    lo, hi, entry = plan.get("entry_low"), plan.get("entry_high"), plan.get("entry")
    if _ok(lo) and _ok(hi) and _ok(price):
        if word != "BUY":
            order = ("No entry now." if word == "DON'T BUY" else f"Not yet: set an alert at <b>{hi:.2f}</b> and look again when the checks agree.")
            order += " The numbers below are for planning only."
        elif lo <= price <= hi:
            order = f"Use a <b>limit order at {price:.2f}</b>, not a market order. Do not pay above {hi:.2f}."
        elif price > hi:
            order = f"Above the zone: set an alert at <b>{hi:.2f}</b> and wait for a pullback. Do not chase."
        else:
            order = "Below the zone: it is falling through. Wait until it closes back inside."
        steps.append(_step(2, "Entry: where to buy", f'<p>Zone <b>{lo:.2f} to {hi:.2f}</b>. {order}</p>'))
    else:
        steps.append(_step(2, "Entry: where to buy", "<p>No entry zone for this stock yet.</p>"))
    sizing = tradeplan.size(plan, account, risk_pct, max_pct) if plan and account else None
    if sizing:
        rps, ent = plan["risk_per_share"], plan["entry"]
        n = int(sizing["shares"])                                  # whole shares only: a fraction cannot be bought
        if n >= 1:
            cap = (f" That is over the {max_pct:.0f}% limit for this tier, so it is capped at <b>{n} shares</b>.") if sizing["capped"] else ""
            note = (f"<p>If the stop is hit you lose about <b>{_usd(n * rps)}</b> ({n * rps / account * 100:.1f}% of the account). "
                    f"The position costs about <b>{_usd(n * ent)}</b>.{cap}</p>")
        else:
            note = (f"<p>Your account is too small to size this within your limit. One share costs about <b>{_usd(ent)}</b> and "
                    f"risks <b>{_usd(rps)}</b> at the stop ({rps / account * 100:.1f}% of the account), more than your "
                    f"{risk_pct:g}% limit of {_usd(sizing['budget'])}. Skip it, or accept a bigger loss on purpose.</p>")
        body = ('<div class="tg-r">' + _cell("Account", _usd(account)) + _cell(f"Risk ({risk_pct:g}%)", _usd(sizing["budget"]))
                + _cell("Per share", _usd(rps)) + _cell("Shares", f"{n}") + "</div>" + note)
    else:
        body = "<p>Type your account size under the guide to see the number of shares.</p>"
    steps.append(_step(3, "Capital: how much to put in", body))
    stop = plan.get("stop")
    lv = (ui.price_status(snap) or {}).get("levels") or {}
    t1 = (plan.get("targets") or [None])[0]
    if _ok(stop) and _ok(entry):
        cells = _cell("Entry", f"{(price if _ok(price) and _ok(lo) and _ok(hi) and lo <= price <= hi else entry):.2f}")
        cells += _cell("Stop", f"{stop:.2f}", f"{(stop / entry - 1) * 100:+.1f}%", "r")
        if t1:
            cells += _cell("Target 1", f'{t1["price"]:.2f}', f'{(t1["price"] / entry - 1) * 100:+.1f}%', "g")
        rr = plan.get("rr")
        floor = lv.get("support_low")
        if not floor:
            exit_txt = ""
        elif _ok(price) and price < floor:
            exit_txt = f" The price is already below the chart floor (<b>{floor:.2f}</b>), so that exit has been hit."
        else:
            exit_txt = f" A daily close below <b>{floor:.2f}</b> is the chart exit."
        weak = " That is below 2 to 1: consider a smaller size." if _ok(rr) and rr < 2 else ""
        steps.append(_step(4, "Stop: where you are wrong", f'<div class="tg-r">{cells}</div>'
                           f'<p>Place the stop order right after the buy.{exit_txt}'
                           f'{f" Reward against risk: <b>{rr:.1f} to 1</b>." if _ok(rr) else ""}{weak}</p>'))
    else:
        steps.append(_step(4, "Stop: where you are wrong", "<p>No stop level for this stock yet.</p>"))
    return "".join(steps)


def sell_tab(snap: dict) -> str:
    p = snap["payload"]
    if p.get("watchlist"):
        return '<div class="tg-v watch"><b>Not held.</b> This stock is on your watchlist, so there is nothing to sell.</div>'
    plan = p.get("plan") or {}
    pos = p.get("position") or {}
    price, _ = ui._price(snap)
    call = ui.action(snap)[0]
    wait = ui.reassess(snap)
    ps = ui.price_status(snap) or {}
    lv = ps.get("levels") or {}
    r, why = ui.ring(snap)
    selling = call in ("SELL", "SELL SOME", "REASSESS")
    t1 = (plan.get("targets") or [None])[0]
    if selling:
        step1 = f'<div class="tg-v bad"><b>{escape(call)}</b> {escape(why if r < 3 else "the plan says reduce")}</div>'
        how = ("Sell <b>all</b> of it." if call == "SELL" else "Sell <b>about a third</b> and keep the rest under the stop."
               if call == "SELL SOME" else "Decide at the close: sell all if it closes weak.")
    else:
        step1 = '<div class="tg-v good"><b>NO SELL</b> Nothing in the plan says sell today.</div>'
        how = (f"None now. Plan: sell a third at <b>Target 1 {t1['price']:.2f}</b>, then trail the rest." if t1
               else "None now.")
    steps = [_step(1, "Why sell?", step1), _step(2, "How much", f"<p>{how}</p>")]
    if wait:
        when = f"<p>{escape(wait)}</p>"
    elif lv.get("support_low"):
        when = (f"<p>The chart exit uses the <b>daily close</b>. A close below <b>{lv['support_low']:.2f}</b> means sell. "
                f"During the day a dip below it is a warning: decide near the close (3:45 pm New York time).</p>")
    else:
        when = "<p>Decide on the daily close, not on an intraday dip.</p>"
    steps.append(_step(3, "When", when))
    cells = ""
    if _ok(price):
        cells += _cell("Now", f"{price:.2f}")
    stop = plan.get("stop")
    if _ok(stop):
        cells += _cell("Hard stop", f"{stop:.2f}", "protects against a gap", "r")
    back = lv.get("support_high") or (plan.get("entry_high") if _ok(plan.get("entry_high")) else None)
    if back:
        cells += _cell("Buy back only above", f"{back:.2f}", "", "g")
    result = ""
    shares, cost = pos.get("shares"), pos.get("cost_basis")
    if _ok(price) and _ok(shares) and _ok(cost) and shares:
        gain = (price - cost) * shares
        result = f'<p>Sold at {price:.2f}: <b>{"+" if gain >= 0 else "−"}{_usd(abs(gain))}</b> against your cost.</p>'
    steps.append(_step(4, "Where", f'<div class="tg-r">{cells}</div>{result}' if cells else "<p>No levels yet.</p>"))
    return "".join(steps)


def _slug(t: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in t)


def card(snap: dict, account: float, risk_pct: float, max_pct: float) -> str:
    sid = _slug(snap["ticker"])
    return (f'<style>{CSS}</style><div class="tg" id="tg-{sid}"><div class="tg-h">Trade guide</div>'
            f'<input type="radio" name="tgs-{sid}" id="tgb-{sid}" checked><input type="radio" name="tgs-{sid}" id="tgs-{sid}">'
            f'<div class="tg-sw"><label for="tgb-{sid}" class="b">Buy</label><label for="tgs-{sid}" class="s">Sell</label></div>'
            f'<div class="tg-buy">{buy_tab(snap, account, risk_pct, max_pct)}</div>'
            f'<div class="tg-sell">{sell_tab(snap)}</div>'
            f'<div class="tg-n">Automatic levels from daily bars. A guide, not advice: check the chart first.</div></div>')


CSS = """
.tg{background:var(--dz-surface,#121a25);border:1px solid var(--dz-line,#243041);border-radius:16px;padding:14px;margin:12px 0;color:var(--dz-ink,#e9eef5)}
.tg-h{font-size:1.1rem;font-weight:800}.tg input{display:none}
.tg-sw{display:flex;gap:6px;margin:10px 0}.tg-sw label{flex:1;text-align:center;padding:8px;border-radius:99px;border:1px solid var(--dz-line,#243041);font-weight:800;font-size:.8rem;cursor:pointer}
.tg-sell{display:none}.tg input:nth-of-type(2):checked~.tg-sell{display:block}.tg input:nth-of-type(2):checked~.tg-buy{display:none}
.tg input:nth-of-type(1):checked~.tg-sw .b{background:color-mix(in srgb,var(--dz-buy,#7be3a8) 25%,transparent);border-color:var(--dz-buy,#7be3a8)}
.tg input:nth-of-type(2):checked~.tg-sw .s{background:color-mix(in srgb,var(--dz-act,#ff7a7a) 25%,transparent);border-color:var(--dz-act,#ff7a7a)}
.tg-s{display:flex;gap:10px;padding:12px 0;border-top:1px solid var(--dz-line,#243041)}
.tg-s>i{font-style:normal;flex:none;width:24px;height:24px;border-radius:50%;background:var(--dz-ink,#e9eef5);color:var(--dz-bg,#0b1018);display:grid;place-items:center;font-weight:800;font-size:.8rem}
.tg-s>div{flex:1;min-width:0}.tg-s p{margin:6px 0 0;font-size:.84rem;line-height:1.45}
.tg-g{display:flex;gap:8px;margin-top:7px;font-size:.84rem}.tg-g span{flex:none;width:20px;height:20px;border-radius:6px;display:grid;place-items:center;font-weight:800;font-size:.75rem;color:#111}
.tg-g.ok span{background:var(--dz-buy,#7be3a8)}.tg-g.bad span{background:var(--dz-act,#ff7a7a)}.tg-g.none span{background:var(--dz-muted,#8b95a7)}
.tg-g small{display:block;color:var(--dz-muted,#8b95a7);font-size:.72rem}
.tg-v{padding:8px 10px;border-radius:10px;margin-top:10px;font-size:.84rem;border:1px solid var(--dz-line,#243041)}
.tg-v.good{border-color:var(--dz-buy,#7be3a8);background:color-mix(in srgb,var(--dz-buy,#7be3a8) 14%,transparent)}
.tg-v.bad{border-color:var(--dz-act,#ff7a7a);background:color-mix(in srgb,var(--dz-act,#ff7a7a) 14%,transparent)}
.tg-v.watch{border-color:var(--dz-watch,#ffc267);background:color-mix(in srgb,var(--dz-watch,#ffc267) 14%,transparent)}
.tg-r{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 0}.tg-r>div{flex:1 1 70px;background:color-mix(in srgb,var(--dz-ink,#e9eef5) 6%,transparent);border-radius:10px;padding:7px 8px}
.tg-r small{display:block;font-size:.64rem;color:var(--dz-muted,#8b95a7)}.tg-r b{font-size:1rem}.tg-r em{font-style:normal;font-size:.72rem;display:block;font-weight:700}
.tg-r .r{border:1px solid var(--dz-act,#ff7a7a)}.tg-r .g{border:1px solid var(--dz-buy,#7be3a8)}
.tg-n{font-size:.68rem;color:var(--dz-muted,#8b95a7);margin-top:8px}
"""
