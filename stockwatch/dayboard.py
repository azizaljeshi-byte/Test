"""The Radar page as a list of tinted cards (red act, green buy, amber watch, blue calm) and a dot map: one word and
colour per stock, a good/bad gauge, and how many independent checks agree with the call. Display only: it reads the call, status, momentum and second opinions already on each snapshot and
changes none of them.

Words (from `ui.ring` and the plan's call, never a new rule):
  ACT      the plan says sell or sell some (unless it is waiting for the close, which is WATCH)
  BUY      buy or buy more, and the price is in the entry zone now
  WATCH    something is close: near an entry or a stop, earnings soon, a sell waiting for the close, or a buy held back
  CALM     nothing to do
  UNCLEAR  no usable signal for this stock

Six checks, each bullish, neutral, bearish or unknown (unknown is never counted as a no):
  price structure, momentum, second opinion (TradingView, else Finnhub), price data (Stooq), against the market, signals.
The gauge is their average on a five-step scale. If it points the other way from the call, the gauge says "unclear"
instead of showing two answers.
"""
from __future__ import annotations

from html import escape

from . import design, ui
from .ui import nan

WORDS = {"ACT": ("ACT", "#ff7a7a", "risk"), "BUY": ("BUY", "#7be3a8", "buy"), "WATCH": ("WATCH", "#ffc267", "warn"),
         "CALM": ("CALM", "#8ab4ff", "calm"), "UNCLEAR": ("UNCLEAR", "#8d8a84", "mute")}
STEPS = ("BAD", "WEAK", "NEUTRAL", "GOOD", "STRONG")
NEEDLE = (10, 30, 50, 70, 90)
BULL, NEUTRAL, BEAR = 1, 0, -1
MIN_KNOWN = 3


def word(snap: dict) -> str:
    p = snap["payload"]
    if p.get("error") or snap["verdict"] == "ERROR":
        return "UNCLEAR"
    r, _ = ui.ring(snap)
    if ui.reassess(snap):
        return "WATCH"
    side = ui.sector(snap["verdict"])
    call = ui.action(snap)[0]
    if call in ("SELL", "SELL SOME"):
        return "ACT"
    if r == 1:
        if side == "risk":
            return "ACT"
        if side == "opp" and call in ("BUY NOW", "BUY ON DIP", "BUY ON BREAKOUT", "BUY MORE"):
            return "BUY"
        return "WATCH"
    return "WATCH" if r == 2 else "CALM"


def held_sell(snap: dict) -> float | None | bool:
    """A sell that is waiting for the close (`ui.reassess`): the trailing stop to watch, None when there is no level,
    or False when no sell is being held."""
    if not ui.reassess(snap):
        return False
    p = snap["payload"]
    trail = (p.get("technical") or {}).get("trailing_stop")
    tripped = not nan(trail) and any(x.get("code") == "atr_trailing_stop" for x in p.get("signals") or [])
    return float(trail) if tripped else None


def _structure(snap):
    ps = ui.price_status(snap)
    if not ps or ps["code"] == "unknown":
        return None, "no price status"
    code = ps["code"]
    state = BULL if code in ("record_high", "strong_uptrend") else NEUTRAL if code == "pullback" else BEAR
    return state, f'Price structure: {(ps.get("label") or code).lower()}'


def _momentum(snap):
    mo = ui.momentum_of(snap)
    if not mo:
        return None, "momentum not read"
    state = BULL if mo["momentum"] in ("strong", "building") else NEUTRAL if mo["momentum"] == "stabilising" else BEAR
    return state, f'Momentum: {mo["momentum_label"].lower()}, {mo["cause_label"]}'


def _second(snap):
    sec = (ui.price_status(snap) or {}).get("second")
    if not sec:
        return None, "second opinion not asked (the stock is healthy)"
    if sec.get("unavailable") or not sec.get("signal"):
        why = sec.get("unavailable")
        return None, f'{sec.get("source", "Second opinion")}: no read' + (f" ({why})" if why else "")
    state = {"buy": BULL, "sell": BEAR}.get(sec["signal"], NEUTRAL)
    return state, f'{sec.get("source", "Second opinion")}: {sec["signal"].upper()}'


def _data(snap):
    ps = ui.price_status(snap) or {}
    pc = ps.get("pricecheck")
    if not pc:
        return None, "price data not re-checked here (only asked for stocks that are falling)"
    if pc.get("unavailable"):
        return None, f'price data skipped: {pc["unavailable"]}'
    return ("ok" if pc.get("agrees") else "bad"), f'Price data: {pc["verdict"]} with {pc["source"]}'


def _market(snap):
    rs = (snap["payload"].get("technical") or {}).get("rs_spy_3m")
    if nan(rs):
        return None, "against the market not read"
    state = BULL if rs > 0.02 else BEAR if rs < -0.02 else NEUTRAL
    return state, f'Against the market: {rs:+.0%} over 3 months'


def _signals(snap):
    sigs = snap["payload"].get("signals") or []
    if not sigs:
        return NEUTRAL, "Signals: nothing flagged"
    risk = max((s["severity"] for s in sigs if s["kind"] == "risk"), default=0)
    opp = max((s["severity"] for s in sigs if s["kind"] != "risk"), default=0)
    if risk >= 2 and risk >= opp:
        return BEAR, "Signals: a risk is flagged"
    if opp >= 2 and risk < 2:
        return BULL, "Signals: an opportunity is flagged"
    return NEUTRAL, "Signals: nothing strong"


def checks(snap: dict) -> list[dict]:
    out = []
    for fn in (_structure, _momentum, _second, _data, _market, _signals):
        state, text = fn(snap)
        out.append({"state": state, "text": text[:1].upper() + text[1:]})
    return out


def assess(snap: dict) -> dict:
    """{word, gauge: 0-4 or None, gauge_label, sure: (agree, known) or None, grade, checks, change}."""
    w = word(snap)
    cs = checks(snap)
    directional = [c["state"] for c in cs if c["state"] in (BULL, NEUTRAL, BEAR)]
    sell_side = w == "ACT" or (w == "WATCH" and held_sell(snap) is not False)
    out = {"word": w, "sell_side": sell_side, "checks": cs, "score": None, "gauge": None, "gauge_label": None, "sure": None, "grade": None, "why": None, "held_buy": False,
           "change": _change(snap, w)}
    if w == "UNCLEAR":
        out["why"] = snap["payload"].get("error") or "no usable signal"
        return out
    if len(directional) < MIN_KNOWN:
        out["why"] = f"only {len(directional)} of 6 checks could be read"
        return out
    s = sum(directional) / len(directional)
    step = 0 if s <= -0.6 else 1 if s <= -0.2 else 2 if s < 0.2 else 3 if s < 0.6 else 4
    if w == "BUY" and step <= 1:
        # A buy the checks argue against: show one answer, not two. The plan's call is untouched; the card says WATCH.
        w = out["word"] = "WATCH"
        out["held_buy"] = True
        out["why"] = "most checks lean negative, so the buy is held back"
        out["change"] = None
    elif sell_side and step >= 3:
        out["why"] = "the checks point the other way from the call"
        return out
    out["gauge"], out["gauge_label"], out["score"] = step, STEPS[step], round(s, 3)
    want = BEAR if sell_side else BULL if w == "BUY" else None
    if want is not None:
        known = [c for c in cs if c["state"] is not None]
        agree = sum(1 for c in known if c["state"] == want or c["state"] == "ok")
        out["sure"] = (agree, len(known))
        ratio = agree / len(known)
        out["grade"] = "HIGH" if ratio >= 0.8 else "MEDIUM" if ratio >= 0.55 else "LOW"
    return out


def _change(snap: dict, w: str) -> str | None:
    lv = (ui.price_status(snap) or {}).get("levels") or {}
    if w == "ACT" and lv.get("support_high"):
        return f'it closes back above {lv["support_high"]:.2f}: then hold and wait.'
    if w == "BUY" and lv.get("support_low"):
        return f'it closes below {lv["support_low"]:.2f}: then don\'t add.'
    return None


# ---------------------------------------------------------------- rendering

def _why(snap: dict, a: dict | None = None) -> str:
    if a and a.get("held_buy"):
        return "in the entry zone, but most checks lean negative: wait before adding"
    p = snap["payload"]
    if p.get("error"):
        return f'signal lost: {p["error"][:90]}'
    wait = ui.reassess(snap)
    if wait:
        return wait
    r, why = ui.ring(snap)
    if r < 3:
        return why
    top = (p.get("signals") or [None])[0]
    return top["message"] if top else "nothing to do"


SPOT = {"ACT": "act", "BUY": "buy", "WATCH": "watch", "CALM": "calm", "UNCLEAR": "calm"}
EDGE_WORDS = {"ACT": "Act", "BUY": "Buy", "WATCH": "Watch", "CALM": "Calm", "UNCLEAR": "No read"}
BEAT_BAND = 0.02          # draft: within 2% of the estimate is "in line" (docs/TIGHTENING.md section 10)


def _sure_html(a: dict) -> str:
    """How sure: one dot per check that could be read; filled when it agrees with the call."""
    known = [c for c in a["checks"] if c["state"] is not None]
    if not known:
        return ""
    want = BEAR if a.get("sell_side") else BULL
    head = ""
    if a["sure"]:
        n, k = a["sure"]
        dots = "".join(f'<i class="{"y" if i < n else "n"}"></i>' for i in range(k))
        head = (f'<div class="rd-h"><span>How sure are we this is the right move</span><b>{n} of {k} agree</b></div>'
                f'<div class="rd-dots">{dots}</div>')
    rows = "".join(
        f'<li class="{"y" if (c["state"] == want or c["state"] == "ok") and a["sure"] else "n"}">{escape(c["text"])}</li>'
        for c in a["checks"])
    chg = f'<p class="rd-chg">Would change if {escape(a["change"])}</p>' if a["change"] else ""
    return f'<div class="rd-box">{head}<ul class="rd-chk">{rows}</ul>{chg}</div>'


def zones_html(snap: dict, price) -> str:
    z = (snap["payload"].get("technical") or {}).get("zones")
    if not isinstance(z, dict):
        return ""
    if not z.get("known"):
        return f'<div class="rd-h"><span>Where it may stop or turn</span></div><div class="rd-note">No read. {escape(z.get("why") or "")}</div>'
    if not (z["support"] or z["resistance"]):
        return ""
    now = (f'<div class="rd-now"><span>Price now {ui.num(price)}</span></div>' if not nan(price) else "")
    rows = "".join(design.zone_row("resistance", x["low"], x["high"], x["grade"], x["reasons"]) for x in reversed(z["resistance"]))
    rows += now + "".join(design.zone_row("support", x["low"], x["high"], x["grade"], x["reasons"]) for x in z["support"])
    return f'<div class="rd-h"><span>Where it may stop or turn</span></div>{rows}'


def day_move(snap: dict):
    """Today's move as a fraction (live during regular hours), or None when unknown."""
    p = snap["payload"]
    q = p.get("quote") or {}
    day = (p.get("technical") or {}).get("day_change")
    if q.get("market_state") == "REGULAR" and not nan(q.get("live_change")):
        day = q["live_change"]
    return None if nan(day) else float(day)


def last_quarter(snap: dict) -> str:
    """BEAT, MISS or IN LINE for the last reported quarter, from the EPS actual and estimate already on the snapshot."""
    rows = ((snap["payload"].get("research") or {}).get("earnings") or {}).get("quarters") or []
    for r in rows[:1]:
        act, est = r.get("eps_actual"), r.get("eps_estimate")
        if act is None or est is None or est == 0:
            return ""
        sur = (act - est) / abs(est)
        res = "BEAT" if sur > BEAT_BAND else "MISS" if sur < -BEAT_BAND else "IN LINE"
        return design.result_line(res, f"EPS {act:.2f} vs {est:.2f} expected ({sur:+.0%})", str(r.get("quarter") or "")[:10])
    return ""


def next_report(snap: dict) -> str:
    ev = (snap["payload"].get("events") or {})
    d = ev.get("days_to_earnings")
    if d is None:
        return ""
    when = f"in {d} day{'s' if d != 1 else ''}"
    return design.next_line("Next report" + (" (estimated date)" if ev.get("earnings_estimated") else ""), when)


def top_story(snap: dict) -> str:
    w = ui.wire_of(snap)
    stories = [x for x in (w or {}).get("stories") or [] if x.get("tier", 1) >= 2]
    if not stories:
        return ""
    x = max(stories, key=lambda t: t.get("rank", 0))
    tier = {3: "HOT", 2: "IMPORTANT"}.get(x["tier"], "ROUTINE")
    return design.news_line(tier, x["title"], ui._age(x["published"]), " · ".join(x.get("sources") or []))


def extra_price(snap: dict) -> str:
    """The quieter line under the price: LIVE time, and the pre-market or after-hours trade (or that there were none yet)."""
    pp = ui.price_parts(snap)
    bits = []
    if pp["live"]:
        bits.append(f'<span class="rd-live">● LIVE {pp["live"]}</span>')
    if pp["ext"]:
        label, price, change = pp["ext"]
        bits.append(f'<span>{escape(label)} <b>{price:.2f}</b> {design.change_pill(change)}</span>')
    if pp["note"]:
        bits.append(f'<span>{escape(pp["note"])}</span>')
    return f'<div class="rd-ext">{"".join(bits)}</div>' if bits else ""


def earnings_soon(snap: dict, days: int = 7) -> bool:
    d = (snap["payload"].get("events") or {}).get("days_to_earnings")
    return d is not None and 0 <= d <= days


def _words(snap: dict, a: dict) -> str:
    """The text on the call tag: the call, or the held-sell wording for a watch that is waiting for the close."""
    label = WORDS[a["word"]][0]
    if a.get("held_buy"):
        return "WATCH · BUY HELD BACK"
    held = held_sell(snap) if a["word"] == "WATCH" else False
    if held is not False:
        return f"WATCH · SELL BELOW {held:.2f}" if held else "WATCH · SELL IF IT CLOSES WEAK"
    call = ui.action(snap)[0] if a["word"] in ("ACT", "BUY") else ""
    return label + (f" · {call}" if call and call != label else "")


def _ratings(snap: dict, a: dict) -> str:
    fund = design.fundamentals_rating(snap.get("fundamental_score"))
    tech = design.technical_rating(a["gauge"])
    return design.rating("Fundamentals", fund) + design.rating("Technical", tech)


def _open(snap: dict, a: dict) -> str:
    price, _ = ui._price(snap)
    p = snap["payload"]
    from .tradeplan import summary
    try:
        plan = summary(p.get("plan"))
    except (KeyError, TypeError, ValueError):       # a plan from an older snapshot: leave the line off, never break the page
        plan = ""
    flow = ui.flow_line(snap)
    parts = [f'<div class="rd-rates">{_ratings(snap, a)}</div>',
             design.gauge_line(a["gauge"], a["gauge_label"] if a["gauge"] is not None else (a["why"] or "No read")),
             _sure_html(a), zones_html(snap, price)]
    if plan:
        parts.append(f'<div class="rd-h"><span>Plan</span></div><div class="rd-note">{escape(plan)}</div>')
    if flow:
        parts.append(f'<div class="rd-h"><span>Flow</span></div><div class="rd-note">{escape(flow)}</div>')
    parts.append(f'<a class="rd-go" href="?view=target&t={escape(snap["ticker"])}" target="_self">Details →</a>')
    return f'<div class="rd-open">{"".join(parts)}</div>'


def card(snap: dict, was: str | None = None) -> str:
    """One tinted row. Tap to open it; the Details button goes to the full page."""
    a = assess(snap)
    cls = SPOT[a["word"]]
    price, _ = ui._price(snap)
    p = snap["payload"]
    name = (p.get("profile") or {}).get("name") or p.get("name") or ""
    name = "" if name.upper() == snap["ticker"] else name
    own = "owned" if not p["watchlist"] else "watching"
    sure = f'<span class="rd-sure">{a["sure"][0]}/{a["sure"][1]} sure</span>' if a["sure"] else ""
    new = f'<span class="rd-sure">● new · was {escape(was.lower())}</span>' if was else ""
    tag = f'<span class="dz-call dz-{cls}">{escape(_words(snap, a))}</span>'
    bell = f'<span class="rd-bell">{design.bell(True, "Earnings this week")}</span>' if earnings_soon(snap) else ""
    lines = last_quarter(snap) + next_report(snap) + top_story(snap)
    sid = _slug(snap["ticker"])
    return (f'<details class="rd-row dz-{cls}" id="c-{sid}"><summary>'
            f'<div class="rd-top"><div><b class="rd-tk">{escape(snap["ticker"])}</b><small>{escape(name)} · {own}</small></div>'
            f'<div class="rd-px"><b>{ui.num(price)}</b>{design.change_pill(day_move(snap))}{extra_price(snap)}</div></div>'
            f'<div class="rd-mid">{tag}{sure}{new}{bell}</div>'
            f'<p class="rd-why">{escape(_why(snap, a))}</p></summary>'
            f'{_open(snap, a)}<div class="rd-lines">{lines}</div></details>')


def _slug(t: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in t)


def movers(snaps: list[dict], n: int = 4) -> str:
    """The biggest moves today, up or down, as tappable chips."""
    rows = [(abs(m), m, s) for s in snaps if (m := day_move(s)) is not None]
    rows.sort(key=lambda t: -t[0])
    if not rows:
        return ""
    chips = "".join(f'<a class="rd-mv" href="?view=target&t={escape(s["ticker"])}" target="_self"><b>{escape(s["ticker"])}</b>'
                    f'{design.change_pill(m)}</a>' for _, m, s in rows[:n])
    return f'<div class="rd-h"><span>Top movers today</span></div><div class="rd-movers">{chips}</div>'


def events_calendar(snaps: list[dict]) -> str:
    """Upcoming earnings on your list, soonest first (only dates already on the snapshots)."""
    rows = sorted((((s["payload"].get("events") or {}).get("days_to_earnings"), s) for s in snaps
                   if (s["payload"].get("events") or {}).get("days_to_earnings") is not None), key=lambda t: t[0])
    rows = [(d, s) for d, s in rows if d >= 0][:5]
    if not rows:
        return ""
    body = "".join(
        f'<a class="rd-ev" href="?view=target&t={escape(s["ticker"])}" target="_self"><b>{escape(s["ticker"])}</b>'
        f'<span>Reports earnings{" (estimated)" if s["payload"]["events"].get("earnings_estimated") else ""}</span>'
        f'<small>{"today" if d == 0 else f"in {d} d"}</small></a>' for d, s in rows)
    return f'<div class="rd-h"><span>Coming up</span></div><div class="rd-evs">{body}</div>'


MAP_CAP = 6.0              # a move beyond +/-6% sits at the edge of the map


def dot_map(snaps: list[dict]) -> str:
    """Every stock as a dot. Left to right: how good it looks (Bad to Strong). Up and down: today's move. Bigger dot = needs
    more attention, colour = the call. Names stay off until a filter (Act, Watch, Buy, Calm) is picked. Zoom with + and -
    (hidden radios and CSS, no script). Stocks with no gauge reading are counted, not placed."""
    placed, nogauge = [], 0
    for s in snaps:
        a = assess(s)
        if a["score"] is None:
            nogauge += 1
            continue
        mv = day_move(s)
        placed.append((s, a, 0.0 if mv is None else mv * 100))
    dots = []
    for s, a, mv in placed:
        cls = SPOT[a["word"]]
        x = 4 + (a["score"] + 1) / 2 * 92
        y = 50 - max(-MAP_CAP, min(MAP_CAP, mv)) / MAP_CAP * 44
        size = {"act": 26, "buy": 26, "watch": 19, "calm": 13}[cls]
        pulse = " dz-pulse rd-pulse" if cls in ("act", "buy") else ""
        dots.append(f'<a class="rd-dot dz-{cls}{pulse}" href="#c-{_slug(s["ticker"])}" target="_self" '
                    f'style="left:{x:.1f}%;top:{y:.1f}%;--sz:{size}px" title="{escape(s["ticker"])}: {EDGE_WORDS[a["word"]].lower()}">'
                    f'<span>{escape(s["ticker"])}</span></a>')
    filt = [("all", "All"), ("act", "Act"), ("watch", "Watch"), ("buy", "Buy"), ("calm", "Calm")]
    radios = "".join(f'<input type="radio" name="rd-f" id="rdf-{k}" class="rd-r"{" checked" if k == "all" else ""}>' for k, _ in filt)
    labels = "".join(f'<label for="rdf-{k}">{t}</label>' for k, t in filt)
    zoom_r = "".join(f'<input type="radio" name="rd-z" id="rdz-{i}" class="rd-r"{" checked" if i == 1 else ""}>' for i in (1, 2, 3))
    zoom_l = '<label for="rdz-3" class="rd-zin" title="Zoom in">+</label><label for="rdz-1" class="rd-zout" title="Zoom out">−</label>'
    note = f'<div class="rd-note">{nogauge} not placed: not enough checks could be read.</div>' if nogauge else ""
    return (f'<div class="rd-mapwrap">{radios}{zoom_r}<div class="rd-h"><span>Map of your list</span></div>'
            f'<div class="rd-filters">{labels}<span class="rd-zoom">{zoom_l}</span></div>'
            f'<div class="rd-scroll"><div class="rd-map"><i class="rd-axis"></i><b class="rd-l1">Bad</b><b class="rd-l2">Strong</b>'
            f'<b class="rd-l3">Up today</b><b class="rd-l4">Down today</b>{"".join(dots)}</div></div>'
            f'<div class="rd-note">Further right = looks better. Higher = up more today. Bigger dot = needs more attention. '
            f'Tap a dot to jump to its card.</div>{note}</div>')


def headline(n_need: int, n_close: int, n_calm: int) -> str:
    return (f'<h1 class="rd-h1"><em class="dz-act">{n_need} need{"s" if n_need == 1 else ""} you</em>, '
            f'<em class="dz-watch">{n_close} {"is" if n_close == 1 else "are"} close</em> '
            f'and <em class="dz-calm">{n_calm} {"is" if n_calm == 1 else "are"} calm</em>.</h1>')


TODAY_ICON = {"good": "▲", "bad": "▼", "careful": "!", "info": "i"}


def _chip(t: str, cls: str, extra: str = "") -> str:
    return (f'<a class="rd-bc {cls}" href="?view=target&t={escape(t)}" target="_self">{escape(t)}'
            f'{f"<small>{escape(extra)}</small>" if extra else ""}</a>')


def _row(kind: str, title: str, text: str = "", chips: str = "") -> str:
    return (f'<div class="rd-br"><i class="dz-ic dz-k-{kind}">{TODAY_ICON[kind]}</i><div><b>{escape(title)}</b>'
            f'{f"<p>{text}</p>" if text else ""}{f"<div class=rd-cs>{chips}</div>" if chips else ""}</div></div>')


def today_card(lines: list[str], tickers=(), when: str = "") -> str:
    """The mission brief as an always-open card: one row per kind of line, an icon on each, tickers as tappable chips.
    It reads the lines `briefing.portfolio` already writes (nothing new is computed) and falls back to a plain row for any
    line it does not know."""
    import re
    rows = []
    for line in lines:
        m = re.match(r"(Market backdrop is) (.*)", line)
        if m:
            kind = "good" if "supportive" in line else "bad" if "hostile" in line else "careful"
            rows.append(_row(kind, "Market", escape("The backdrop is " + m.group(2))))
            continue
        m = re.match(r"Needs attention now: (.*)\.$", line)
        if m:
            ts = [x.strip() for x in m.group(1).split(",")]
            rows.append(_row("bad", "Needs you today", f"{len(ts)} stock{'s' if len(ts) != 1 else ''}", "".join(_chip(t, "act") for t in ts)))
            continue
        m = re.match(r"In a buy zone: (.*)\.$", line)
        if m:
            ts = [x.strip() for x in m.group(1).split(",")]
            rows.append(_row("good", "In a buy zone", f"{len(ts)} stock{'s' if len(ts) != 1 else ''}", "".join(_chip(t, "buy") for t in ts)))
            continue
        m = re.match(r"Reporting this week: (.*)\.$", line)
        if m:
            chips = "".join(_chip(a, "cal", b) for a, b in re.findall(r"([A-Z][A-Z0-9.\-]*) \((\d+d)\)", m.group(1)))
            rows.append(_row("careful", "Reporting this week", "", chips))
            continue
        m = re.match(r"Big out-of-hours moves: (.*)\.$", line)
        if m:
            found = re.findall(r"([A-Z][A-Z0-9.\-]*) ([+-][\d.]+)% (pre|AH)", m.group(1))
            chips = "".join(_chip(t, "dn" if float(c) < 0 else "up", f"{float(c):+.1f}% {w}") for t, c, w in found)
            rows.append(_row("info", "Out of hours", "Big moves", chips))
            continue
        m = re.match(r"Strongest: (.*?)\. Weakest: (.*)\.$", line)
        if m:
            def group(label, txt, cls):
                return f'<span class="rd-lb">{label}</span>' + "".join(_chip(x.strip(), cls) for x in txt.split(","))
            rows.append(_row("info", "Strongest and weakest", "", group("Strongest", m.group(1), "buy") + group("Weakest", m.group(2), "dn")))
            continue
        m = re.match(r"Changed since last sweep: (.*)\.$", line)
        if m:
            rows.append(_row("careful", "Changed since the last sweep", ui.link_tickers(m.group(1), tickers)))
            continue
        rows.append(_row("info", "Note", ui.link_tickers(line, tickers)))
    if not rows:
        return ""
    sub = f"<small>{escape(when)}</small>" if when else ""
    return f'<div class="rd-today"><div class="rd-th"><span>Today</span>{sub}</div>{"".join(rows)}</div>'


def render(snaps: list[dict], changed: dict[str, str] | None = None, brief: str = "") -> str:
    changed = changed or {}
    need, close, calm = [], [], []
    for s in sorted(snaps, key=ui._ring_sort):
        w = word(s)
        (need if w in ("ACT", "BUY") else calm if w == "CALM" else close).append(s)
    parts = [f'<style>{CSS}</style><div class="rd">', headline(len(need), len(close), len(calm)), movers(snaps)]
    parts.append(dot_map(snaps))
    if brief:
        parts.append(brief)
    for title, group, cls in (("Needs you today", need, "act"), ("Getting close", close, "watch"), ("All calm", calm, "calm")):
        if group:
            parts.append(f'<div class="rd-sec"><i class="dz-{cls}"></i>{title} <small>{len(group)}</small></div>')
            parts += [card(s, changed.get(s["ticker"])) for s in group]
    if not (need or close or calm):
        parts.append('<div class="rd-note">No stocks with this status right now.</div>')
    parts.append(events_calendar(snaps))
    parts.append(KEY + "</div>")
    return "".join(parts)


KEY = ('<div class="rd-key"><b>Quick key</b>'
       '<div><span class="dz-call dz-act">ACT</span>Do something now (sell or sell some)</div>'
       '<div><span class="dz-call dz-buy">BUY</span>Buy or buy more, price in the entry zone</div>'
       '<div><span class="dz-call dz-watch">WATCH</span>Something is close. Not yet.</div>'
       '<div><span class="dz-call dz-calm">CALM</span>Nothing to do</div>'
       '<div class="rd-note">"5/6 sure": how many checks agree with the call. The bell: earnings are due within a week. The line with the bolt: how good or bad the stock '
       'looks now. Display only; it changes no call or alert.</div></div>')

CSS = """
.rd{color:var(--dz-ink)}
.rd-h1{font:700 1.45rem/1.25 system-ui,sans-serif !important;margin:.2rem 0 .8rem !important;color:var(--dz-ink)}
.rd-h1 em{white-space:nowrap;font-style:normal;padding:0 .3em;border-radius:7px;color:var(--dz-c);background:color-mix(in srgb,var(--dz-c) 16%,transparent)}
.rd-h{font-size:.68rem;letter-spacing:.07em;text-transform:uppercase;color:var(--dz-muted);margin:14px 2px 8px;display:flex;justify-content:space-between;gap:8px}
.rd-h b{color:var(--dz-ink);text-transform:none;letter-spacing:0;font-size:.78rem}
.rd-note{font-size:.78rem;color:var(--dz-muted);margin:6px 2px}
.rd-movers{display:flex;gap:8px;overflow-x:auto;padding-bottom:4px}
.rd-mv,.rd-ev{display:flex;align-items:center;gap:8px;text-decoration:none;color:var(--dz-ink);background:var(--dz-surface);border:1px solid var(--dz-line);border-radius:12px;padding:8px 11px}
.rd-mv{flex:none}.rd-evs{display:grid;gap:6px}.rd-ev span{flex:1;color:var(--dz-soft);font-size:.82rem}.rd-ev small{color:var(--dz-muted)}
.rd-sec{display:flex;align-items:center;gap:8px;font-weight:700;font-size:.95rem;margin:20px 2px 10px}
.rd-sec i{width:10px;height:10px;border-radius:50%;background:var(--dz-c)}.rd-sec small{font-weight:400;color:var(--dz-muted)}
.rd-row{margin-bottom:9px;border-radius:14px;border:1px solid color-mix(in srgb,var(--dz-c) 30%,var(--dz-line));border-left:5px solid var(--dz-c);
  background:color-mix(in srgb,var(--dz-c) 9%,var(--dz-surface));padding:12px 13px}
.rd-row:target{box-shadow:0 0 0 2px var(--dz-c)}
.rd-row>summary{list-style:none;cursor:pointer}.rd-row>summary::-webkit-details-marker{display:none}
.rd-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
.rd-tk{font-size:1.15rem;display:block}.rd-top small{display:block;color:var(--dz-muted);font-size:.74rem;margin-top:2px}
.rd-px{text-align:right}.rd-px b{display:block;font-size:1.15rem;font-variant-numeric:tabular-nums;margin-bottom:3px}
.rd-mid{display:flex;align-items:center;gap:8px;margin-top:9px;flex-wrap:wrap}
.rd-bell{margin-left:auto}.rd-ext{margin-top:5px;font-size:.72rem;color:var(--dz-muted);display:grid;gap:3px;justify-items:end}
.rd-ext span{display:flex;gap:5px;align-items:center;justify-content:flex-end;white-space:nowrap}.rd-ext b{color:var(--dz-ink);font-size:.8rem;margin:0}.rd-ext .dz-chg{font-size:.68rem}.rd-live{color:var(--dz-buy)}.rd-sure{font-size:.72rem;color:var(--dz-muted)}
.rd-why{margin:8px 0 0;font-size:.88rem;color:var(--dz-soft)}
.rd-open{margin-top:12px;border-top:1px solid var(--dz-line);padding-top:10px}
.rd-rates{margin-bottom:4px}
.rd-box{background:color-mix(in srgb,var(--dz-ink) 5%,transparent);border-radius:12px;padding:10px 12px;margin:10px 0}
.rd-dots{display:flex;gap:4px;margin:7px 0}.rd-dots i{flex:1;height:6px;border-radius:9px;background:var(--dz-line)}.rd-dots .y{background:var(--dz-buy)}
.rd-chk{list-style:none;margin:0;padding:0;font-size:.82rem}.rd-chk li{padding:3px 0 3px 20px;position:relative}
.rd-chk li:before{position:absolute;left:0;font-weight:800}.rd-chk .y:before{content:"✓";color:var(--dz-buy)}
.rd-chk .n:before{content:"–";color:var(--dz-muted)}.rd-chk .n{color:var(--dz-soft)}
.rd-chg{margin:7px 0 0;font-size:.78rem;color:var(--dz-watch)}
.rd-now{text-align:center;font-size:.74rem;color:var(--dz-muted);margin:2px 0 8px}
.rd-go{display:block;text-align:center;margin-top:12px;padding:10px;border-radius:11px;background:var(--dz-ink);color:var(--dz-bg);font-weight:700;text-decoration:none}
.rd-lines{margin-top:2px}
.rd-today{background:var(--dz-surface);border:1px solid var(--dz-line);border-radius:16px;padding:14px;border-top:3px solid var(--dz-ink);margin:14px 0}
.rd-th{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}.rd-th span{font-size:1.15rem;font-weight:800}
.rd-th small{color:var(--dz-muted);font-size:.72rem}
.rd-br{display:flex;gap:10px;padding:11px 0;border-top:1px solid var(--dz-line)}.rd-br:first-of-type{border-top:0}.rd-br>div{flex:1;min-width:0}
.rd-br b{font-size:.74rem;text-transform:uppercase;letter-spacing:.06em;color:var(--dz-soft)}
.rd-br p{margin:4px 0 0;font-size:.86rem;line-height:1.4;color:var(--dz-ink)}.rd-br p a{color:var(--dz-calm)}
.rd-cs{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px;align-items:center}
.rd-bc{display:inline-flex;gap:5px;align-items:center;font-size:.76rem;font-weight:800;padding:4px 9px;border-radius:99px;text-decoration:none;color:var(--dz-ink);
  border:1px solid color-mix(in srgb,var(--dz-c) 55%,transparent);background:color-mix(in srgb,var(--dz-c) 14%,transparent)}
.rd-bc small{font-weight:600;color:var(--dz-muted)}.rd-bc.act,.rd-bc.dn{--dz-c:var(--dz-act)}.rd-bc.buy,.rd-bc.up{--dz-c:var(--dz-buy)}.rd-bc.cal{--dz-c:var(--dz-watch)}
.rd-bc.dn small{color:var(--dz-act)}.rd-bc.up small{color:var(--dz-buy)}.rd-lb{font-size:.68rem;color:var(--dz-muted)}
.rd-key{margin-top:22px;background:var(--dz-surface);border:1px solid var(--dz-line);border-radius:14px;padding:12px 14px;font-size:.8rem;display:grid;gap:7px}
.rd-key div{display:flex;gap:10px;align-items:center}.rd-key .rd-note{display:block}
.rd-r{position:absolute;opacity:0;pointer-events:none}
.rd-filters{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.rd-filters label,.rd-zoom label{cursor:pointer;color:var(--dz-soft) !important;font-size:.78rem;font-weight:600;padding:5px 12px;border-radius:99px;background:var(--dz-surface);border:1px solid var(--dz-line);color:var(--dz-soft)}
.rd-zoom{display:flex;gap:6px;margin-left:auto}.rd-zoom label{width:30px;text-align:center;padding:5px 0}
#rdf-all:checked~.rd-filters [for=rdf-all],#rdf-act:checked~.rd-filters [for=rdf-act],#rdf-watch:checked~.rd-filters [for=rdf-watch],
#rdf-buy:checked~.rd-filters [for=rdf-buy],#rdf-calm:checked~.rd-filters [for=rdf-calm]{background:var(--dz-ink) !important;color:var(--dz-bg) !important;border-color:var(--dz-ink)}
.rd-scroll{overflow:auto;border-radius:14px;border:1px solid var(--dz-line);background:var(--dz-surface)}
.rd-map{position:relative;height:300px;min-width:100%;width:100%}
#rdz-2:checked~.rd-scroll .rd-map{width:170%;height:420px}#rdz-3:checked~.rd-scroll .rd-map{width:260%;height:560px}
.rd-axis{position:absolute;left:0;right:0;top:50%;border-top:1px dashed var(--dz-line)}
.rd-map>b{position:absolute;font-size:.64rem;font-weight:600;color:var(--dz-muted);letter-spacing:.04em}
.rd-l1{left:8px;bottom:6px}.rd-l2{right:8px;bottom:6px}.rd-l3{left:8px;top:6px}.rd-l4{left:8px;top:50%;margin-top:4px}
.rd-dot{position:absolute;width:var(--sz);height:var(--sz);margin:calc(var(--sz)/-2) 0 0 calc(var(--sz)/-2);border-radius:50%;
  background:var(--dz-c);border:2px solid var(--dz-surface);text-decoration:none;transition:opacity .2s}
.rd-dot span{display:none;position:absolute;left:50%;top:100%;transform:translateX(-50%);font-size:.62rem;font-weight:800;color:var(--dz-ink);white-space:nowrap}
.rd-pulse{animation:rdp 1.8s ease-out infinite}
@keyframes rdp{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--dz-c) 60%,transparent)}100%{box-shadow:0 0 0 10px transparent}}
#rdf-act:checked~.rd-scroll .rd-dot:not(.dz-act),#rdf-watch:checked~.rd-scroll .rd-dot:not(.dz-watch),
#rdf-buy:checked~.rd-scroll .rd-dot:not(.dz-buy),#rdf-calm:checked~.rd-scroll .rd-dot:not(.dz-calm){opacity:.12;pointer-events:none}
#rdf-act:checked~.rd-scroll .rd-dot.dz-act span,#rdf-watch:checked~.rd-scroll .rd-dot.dz-watch span,
#rdf-buy:checked~.rd-scroll .rd-dot.dz-buy span,#rdf-calm:checked~.rd-scroll .rd-dot.dz-calm span,#rdz-3:checked~.rd-scroll .rd-dot span{display:block}
@media (prefers-reduced-motion:reduce){.rd-pulse,.rd-dot{animation:none !important;transition:none}}
"""
