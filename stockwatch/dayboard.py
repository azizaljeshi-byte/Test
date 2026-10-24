"""The Radar page as a day board: one word and colour per stock, a good/bad gauge, and how many independent checks
agree with the call. Display only: it reads the call, status, momentum and second opinions already on each snapshot and
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

from . import ui
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
        return None, f'{sec.get("source", "Second opinion")}: no read'
    state = {"buy": BULL, "sell": BEAR}.get(sec["signal"], NEUTRAL)
    return state, f'{sec.get("source", "Second opinion")}: {sec["signal"].upper()}'


def _data(snap):
    pc = (ui.price_status(snap) or {}).get("pricecheck")
    if not pc or pc.get("unavailable"):
        return None, "price data not re-checked"
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
    out = {"word": w, "checks": cs, "score": None, "gauge": None, "gauge_label": None, "sure": None, "grade": None, "why": None,
           "change": _change(snap, w)}
    if w == "UNCLEAR":
        out["why"] = snap["payload"].get("error") or "no usable signal"
        return out
    if len(directional) < MIN_KNOWN:
        out["why"] = f"only {len(directional)} of 6 checks could be read"
        return out
    s = sum(directional) / len(directional)
    step = 0 if s <= -0.6 else 1 if s <= -0.2 else 2 if s < 0.2 else 3 if s < 0.6 else 4
    if (w == "ACT" and step >= 3) or (w == "BUY" and step <= 1):
        out["why"] = "the checks point the other way from the call"
        return out
    out["gauge"], out["gauge_label"], out["score"] = step, STEPS[step], round(s, 3)
    want = BEAR if w == "ACT" else BULL if w == "BUY" else None
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

def _why(snap: dict) -> str:
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


def gauge_html(a: dict, mini: bool = False) -> str:
    if a["gauge"] is None:
        bars = "".join('<i style="background:#555;opacity:.5"></i>' for _ in range(5))
        note = "" if mini else f'<div class="lab"><b>UNCLEAR</b><span>{escape(a["why"] or "")}</span></div>'
        return f'<div class="gauge{" mini" if mini else ""}"><div class="bar">{bars}</div>{note}</div>'
    lab = "" if mini else f'<div class="lab"><span>Bad</span><b>{a["gauge_label"]}</b><span>Strong</span></div>'
    return (f'<div class="gauge{" mini" if mini else ""}"><div class="bar"><i></i><i></i><i></i><i></i><i></i>'
            f'<span class="needle" style="left:{NEEDLE[a["gauge"]]}%"></span></div>{lab}</div>')


def _checks_html(a: dict) -> str:
    known = [c for c in a["checks"] if c["state"] is not None]
    head = ""
    if a["sure"]:
        n, k = a["sure"]
        dots = "".join(f'<i class="{"y" if i < n else "n"}"></i>' for i in range(k))
        head = (f'<div class="cf-h"><span>HOW SURE ARE WE THIS IS THE RIGHT MOVE</span><b>{a["grade"]} · {n} of {k} agree</b></div>'
                f'<div class="dots">{dots}</div>')
    want = BEAR if a["word"] == "ACT" else BULL
    rows = "".join(
        f'<li class="{"y" if (c["state"] == want or c["state"] == "ok") and a["sure"] else "n"}">{escape(c["text"])}</li>'
        for c in a["checks"])
    chg = f'<p class="chg">Would change if {escape(a["change"])}</p>' if a["change"] else ""
    return f'<div class="conf">{head}<ul class="chk">{rows}</ul>{chg}</div>' if known else ""


def _zone(z: dict, kind: str) -> str:
    return (f'<div class="z {kind}"><span class="nm2">{"Support" if kind == "sup" else "Resistance"}</span>'
            f'<b>${z["low"]:.2f}' + (f' – {z["high"]:.2f}' if z["high"] != z["low"] else "") + '</b>'
            f'<em class="g {z["grade"][0].lower()}">{z["grade"]}</em><small>{escape(" · ".join(z["reasons"]))}</small></div>')


def zones_html(snap: dict, price) -> str:
    z = (snap["payload"].get("technical") or {}).get("zones")
    if not isinstance(z, dict):
        return ""
    if not z.get("known"):
        return f'<div class="h5">SUPPORT &amp; RESISTANCE ZONES</div><div class="zn">No read. {escape(z.get("why") or "")}</div>'
    if not (z["support"] or z["resistance"]):
        return ""
    now = f'<div class="now"><span>Price now {ui.num(price)}</span></div>' if not nan(price) else ""
    body = ("".join(_zone(x, "res") for x in reversed(z["resistance"])) + now + "".join(_zone(x, "sup") for x in z["support"]))
    return f'<div class="h5">SUPPORT &amp; RESISTANCE ZONES</div><div class="ladder">{body}</div>'


def _head(snap: dict, a: dict, was: str | None, big: bool) -> str:
    label, color, cls = WORDS[a["word"]]
    price, day_html = ui._price(snap)
    p = snap["payload"]
    name = (p.get("profile") or {}).get("name") or p.get("name") or ""
    name = "" if name.upper() == snap["ticker"] else name
    own = "owned" if not p["watchlist"] else "watching"
    call = ui.action(snap)[0] if a["word"] in ("ACT", "BUY") else ""
    badge = ""
    if a["sure"]:
        badge = f'<span class="badge">{a["sure"][0]}/{a["sure"][1]} sure</span>'
    new = f'<span class="badge">● NEW · was {escape(was.lower())}</span>' if was else ""
    word_txt = label + (f" · {call}" if call and call != label else "")
    return (f'<div class="top"><div><div class="tk">{escape(snap["ticker"])}</div><div class="nm">{escape(name)} · {own}</div></div>'
            f'<div class="px"><b>{ui.num(price)}</b>{day_html}</div></div>'
            f'<span class="act">{escape(word_txt)}</span>{badge}{new}<p class="why">{escape(_why(snap))}</p>')


def _open(snap: dict, a: dict) -> str:
    price, _ = ui._price(snap)
    p = snap["payload"]
    from .tradeplan import summary
    try:
        plan = summary(p.get("plan"))
    except (KeyError, TypeError, ValueError):       # a plan from an older snapshot: leave the line off, never break the page
        plan = ""
    flow = ui.flow_line(snap)
    parts = [_checks_html(a), zones_html(snap, price)]
    if plan:
        parts.append(f'<div class="h5">PLAN</div><div class="zn">{escape(plan)}</div>')
    if flow:
        parts.append(f'<div class="h5">FLOW</div><div class="zn">{escape(flow)}</div>')
    return (f'<div class="open">{"".join(parts)}<div class="foot"><span class="close">▲ Close</span>'
            f'<a class="go" href="?view=target&t={escape(snap["ticker"])}" target="_self">Open full details →</a></div></div>')


def card(snap: dict, was: str | None = None, kind: str = "big") -> str:
    a = assess(snap)
    _, _, cls = WORDS[a["word"]]
    if kind == "tile":
        price, day_html = ui._price(snap)
        label = WORDS[a["word"]][0]
        head = (f'<span class="w">{label}</span><div class="tk">{escape(snap["ticker"])}</div>'
                f'<div class="p">{ui.num(price)}{day_html}</div><div class="t">{escape(_why(snap))}</div>{gauge_html(a, True)}')
        return f'<details class="mid {cls}"><summary>{head}</summary>{_open(snap, a)}</details>'
    return (f'<details class="big {cls}"><summary>{_head(snap, a, was, True)}{gauge_html(a)}'
            f'<div class="more"><span>Tap for the full picture</span><span>▾</span></div></summary>{_open(snap, a)}</details>')


def chip(snap: dict) -> str:
    price, _ = ui._price(snap)
    day = (snap["payload"].get("technical") or {}).get("day_change")
    mv = "" if nan(day) else f'<span>{day:+.1%}</span>'.replace("-", "−")
    own = "" if snap["payload"]["watchlist"] else '<i class="own"></i>'
    return (f'<a class="chip" href="?view=target&t={escape(snap["ticker"])}" target="_self">{own}'
            f'<b>{escape(snap["ticker"])}</b>{mv}</a>')


def render(snaps: list[dict], changed: dict[str, str] | None = None, brief: str = "") -> str:
    changed = changed or {}
    need, close, calm = [], [], []
    for s in sorted(snaps, key=ui._ring_sort):
        w = word(s)
        (need if w in ("ACT", "BUY") else calm if w == "CALM" else close).append(s)
    parts = [f'<style>{CSS}</style><div class="db">', headline(len(need), len(close), len(calm)), board(sorted(snaps, key=ui._ring_sort))]
    if brief:
        parts.append(f'<details class="brief"><summary>Today\'s brief</summary>{brief}</details>')
    if need:
        parts.append(f'<div class="sec"><span class="dot" style="background:#ff7a7a"></span>Needs you today <small>{len(need)}</small></div>')
        parts += [card(s, changed.get(s["ticker"])) for s in need]
    if close:
        parts.append(f'<div class="sec"><span class="dot" style="background:#ffc267"></span>Getting close <small>{len(close)}</small></div>')
        parts.append('<div class="grid">' + "".join(card(s, changed.get(s["ticker"]), "tile") for s in close) + '</div>')
    if calm:
        parts.append(f'<div class="sec"><span class="dot" style="background:#8ab4ff"></span>All calm <small>{len(calm)} · nothing to do</small></div>')
        parts.append('<div class="chips">' + "".join(chip(s) for s in calm) + '</div>')
    if not (need or close or calm):
        parts.append('<div class="zn">No stocks with this status right now.</div>')
    parts.append(KEY + "</div>")
    return "".join(parts)


def _slug(t: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in t)


def _summary_panel(s: dict, a: dict, sid: str) -> tuple[str, str]:
    """(css rule, html) for the quick-look panel under a map; shown when its radio is checked."""
    label, color, _ = WORDS[a["word"]]
    price, day_html = ui._price(s)
    sure_txt = f' · {a["sure"][0]}/{a["sure"][1]} sure' if a["sure"] else ""
    html = (f'<div class="pvc" id="dbc-{sid}" style="--c:{color}"><div class="top"><div><div class="tk">{escape(s["ticker"])}</div>'
            f'<span class="act">{label}</span><span class="nm">{escape(a["gauge_label"] or "unclear")}{sure_txt}</span></div>'
            f'<div class="px"><b>{ui.num(price)}</b>{day_html}</div></div><p class="why">{escape(_why(s))}</p>'
            f'{gauge_html(a, True)}<div class="foot"><label for="dbp-none">✕ Close</label>'
            f'<a class="go" href="?view=target&t={escape(s["ticker"])}" target="_self">Open full details →</a></div></div>')
    rule = (f'#dbp-{sid}:checked~.pvs #dbc-{sid}{{display:block}}'
            f'#dbp-{sid}:checked~.gboard [for=dbp-{sid}]{{z-index:5;filter:brightness(1.25);outline:2px solid #fff;outline-offset:2px}}')
    return rule, html


def _wrap(inner: str, rules: list[str], radios: list[str], panels: list[str]) -> str:
    return (f'<div class="pulsewrap"><style>{"".join(rules)}</style>'
            '<input type="radio" name="db-pv" id="dbp-none" class="pvr" aria-label="Close summary">' + "".join(radios) + inner +
            f'<div class="pvs"><div class="hint">Tap one for a quick look.</div>{"".join(panels)}</div></div>')


def portfolio_read(items: list[tuple[dict, dict]]) -> tuple[float | None, str]:
    """Where the holdings stand: the average gauge score of the stocks you own (all stocks when none are owned)."""
    own = [a["score"] for s, a in items if a["score"] is not None and not s["payload"]["watchlist"]]
    sc = own or [a["score"] for s, a in items if a["score"] is not None]
    if len(sc) < MIN_KNOWN:
        return None, "UNCLEAR"
    m = sum(sc) / len(sc)
    step = 0 if m <= -0.6 else 1 if m <= -0.2 else 2 if m < 0.2 else 3 if m < 0.6 else 4
    return m, STEPS[step]


def board(snaps: list[dict]) -> str:
    """The gauge board: the same needle gauge as each card, for the whole portfolio, with every stock sitting under the step
    it reached. Big dial = your holdings overall; five columns = Bad, Weak, Neutral, Good, Strong; a chip's colour is its call
    (red act, green buy, amber watch, blue calm), a pulsing edge means act or buy, a filled chip is owned. Tap a chip for
    its summary under the board (hidden radios and CSS, no script)."""
    items = [(s, assess(s)) for s in snaps]
    mean, read = portfolio_read(items)
    cols = {i: [] for i in range(5)}
    unclear = []
    for s, a in sorted(items, key=lambda i: (ui._ring_sort(i[0]))):
        (cols[a["gauge"]] if a["gauge"] is not None else unclear).append((s, a))
    chips_for = lambda group: "".join(_chip_bead(s, a) for s, a in group)
    radios, rules, panels = [], [], []
    for s, a in items:
        sid = _slug(s["ticker"])
        radios.append(f'<input type="radio" name="db-pv" id="dbp-{sid}" class="pvr" aria-label="Show {escape(s["ticker"])}">')
        rule, html = _summary_panel(s, a, sid)
        rules.append(rule)
        panels.append(html)
    color = {"BAD": "#ff7a7a", "WEAK": "#ffa566", "NEUTRAL": "#d6d2c4", "GOOD": "#a6e08a", "STRONG": "#4fd88f", "UNCLEAR": "#8d8a84"}[read]
    ang = -90 + 90 * (1 + mean) if mean is not None else None
    needle = f'<span class="gneedle" style="--to:{ang:.0f}deg"></span><span class="ghub"></span>' if ang is not None else ""
    heads = "".join(f'<div class="gcol"><div class="gh">{STEPS[i].title()}<small>{len(cols[i])}</small></div>{chips_for(cols[i])}</div>' for i in range(5))
    unk = (f'<div class="gunk"><span>UNCLEAR · {len(unclear)}</span>{chips_for(unclear)}</div>' if unclear else "")
    inner = (f'<div class="gboard"><div class="gdial"><div class="garc"></div>{needle}'
             f'<div class="gread" style="--c:{color}"><small>YOUR HOLDINGS</small><b>{read}</b></div></div>'
             f'<div class="gcols">{heads}</div>{unk}</div>'
             '<div class="pkey"><span>Needle: your holdings overall</span><span>Each chip sits under how its stock looks now</span>'
             '<span><b class="k hot"></b>Pulsing: act or buy</span><span><b class="k own"></b>Filled: owned</span></div>')
    return _wrap(inner, rules, radios, panels)


def _chip_bead(s: dict, a: dict) -> str:
    sid = _slug(s["ticker"])
    label, color, cls = WORDS[a["word"]]
    own = not s["payload"]["watchlist"]
    return (f'<label class="gchip {cls}{" own" if own else ""}{" hot" if a["word"] in ("ACT", "BUY") else ""}" for="dbp-{sid}" '
            f'style="--c:{color}" title="{escape(s["ticker"])}: {label.lower()}">{escape(s["ticker"])}</label>')


def headline(n_need: int, n_close: int, n_calm: int) -> str:
    return (f'<h1><em class="e1">{n_need} need{"s" if n_need == 1 else ""} you</em>, <em class="e2">{n_close} {"is" if n_close == 1 else "are"} close</em> '
            f'and <em class="e3">{n_calm} {"is" if n_calm == 1 else "are"} calm</em>.</h1>')


KEY = ('<div class="key"><b>Quick key</b>'
       '<div><span class="w2" style="background:#ff7a7a">ACT</span>Do something now (sell or sell some)</div>'
       '<div><span class="w2" style="background:#7be3a8">BUY</span>Buy or buy more, price in the entry zone</div>'
       '<div><span class="w2" style="background:#ffc267">WATCH</span>Something is close. Not yet.</div>'
       '<div><span class="w2" style="background:#8ab4ff">CALM</span>Nothing to do</div>'
       '<div><span class="w2" style="background:#8d8a84">UNCLEAR</span>Not enough data, or the checks disagree</div>'
       '<div class="soft">Needle: how good or bad it looks now. "5/6 sure": how many checks agree with the call. '
       'Zone grades: HIGH = many reasons agree, MEDIUM = two, LOW = weak. Display only; it changes no call or alert.</div></div>')

CSS = """
.db .gboard{background:#12151d;border:1px solid var(--line);border-radius:22px;padding:14px 8px 10px}
.db .gdial{position:relative;width:86%;margin:0 auto 3.3rem;aspect-ratio:2/1.08}
.db .garc{position:absolute;left:0;right:0;top:0;bottom:8%;border-radius:999px 999px 0 0;overflow:hidden;
  background:conic-gradient(from -90deg at 50% 100%,#ff6b6b 0 36deg,#ffa566 36deg 72deg,#d6d2c4 72deg 108deg,#a6e08a 108deg 144deg,#4fd88f 144deg 180deg,transparent 180deg);
  -webkit-mask:radial-gradient(circle at 50% 100%,transparent 58%,#000 59%);mask:radial-gradient(circle at 50% 100%,transparent 58%,#000 59%);opacity:.85}
.db .gneedle{position:absolute;left:50%;bottom:8%;width:4px;height:48%;border-radius:4px;background:#fff;transform-origin:50% 100%;transform:translateX(-50%) rotate(var(--to));animation:gsweep 1.5s cubic-bezier(.3,1.35,.5,1) both;box-shadow:0 0 8px rgba(255,255,255,.5)}
.db .ghub{position:absolute;left:50%;bottom:8%;width:16px;height:16px;margin:0 0 -8px -8px;border-radius:50%;background:#fff}
@keyframes gsweep{from{transform:translateX(-50%) rotate(-90deg)}}
.db .gread{position:absolute;left:0;right:0;top:100%;margin-top:.25rem;text-align:center}.db .gread small{display:block;font-size:.55rem;letter-spacing:.12em;color:var(--mut)}.db .gread b{font:700 1.15rem/1.1 Georgia,serif;color:var(--c);letter-spacing:.05em}
.db .gcols{display:grid;grid-template-columns:repeat(5,1fr);gap:4px;margin-top:.9rem;align-items:start}
.db .gcol{display:flex;flex-direction:column;gap:4px;min-width:0;border-top:3px solid var(--line);padding-top:4px}
.db .gcol:nth-child(1){border-color:#ff6b6b}.db .gcol:nth-child(2){border-color:#ffa566}.db .gcol:nth-child(3){border-color:#d6d2c4}.db .gcol:nth-child(4){border-color:#a6e08a}.db .gcol:nth-child(5){border-color:#4fd88f}
.db .gh{font-size:.56rem;letter-spacing:.06em;text-transform:uppercase;color:var(--soft);text-align:center;margin-bottom:2px}.db .gh small{display:block;font-size:.7rem;color:var(--ink);letter-spacing:0}
.db .gchip{display:block;text-align:center;font-size:.6rem;font-weight:800;letter-spacing:.01em;padding:.28rem 0;border-radius:9px;color:var(--ink);cursor:pointer;
  border:1.5px solid color-mix(in srgb,var(--c) 70%,transparent);background:#171b25;position:relative;animation:pop .45s cubic-bezier(.2,1.3,.4,1) both}
.db .gchip.own{background:color-mix(in srgb,var(--c) 30%,#12151d)}
.db .gchip.hot{border-color:var(--c);box-shadow:0 0 0 0 var(--c);animation:pop .45s cubic-bezier(.2,1.3,.4,1) both,glow 1.8s ease-out infinite}
@keyframes glow{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--c) 70%,transparent)}100%{box-shadow:0 0 0 7px transparent}}
.db .gunk{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:.7rem;font-size:.56rem;color:var(--mut);letter-spacing:.08em}.db .gunk .gchip{padding:.28rem .6rem}
@media (prefers-reduced-motion:reduce){.db .gneedle,.db .gchip,.db .gchip.hot{animation:none}}
.db .pulsewrap{position:relative;margin-bottom:.4rem}.db .pvr{position:absolute;opacity:0;pointer-events:none}
.db .pkey{display:flex;gap:.2rem .9rem;flex-wrap:wrap;font-size:.64rem;color:var(--mut);margin:.5rem .2rem}.db .pkey .k{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:.3rem;border:2px solid var(--soft);vertical-align:-1px}
.db .pkey .k.own{background:var(--soft)}.db .pkey .k.hot{border-color:var(--risk);box-shadow:0 0 0 3px rgba(255,122,122,.25)}.db .pkey .k.ring{border-color:var(--buy);border-right-color:rgba(255,255,255,.2)}
.db .pvs .hint{font-size:.74rem;color:var(--mut);text-align:center;padding:.3rem}.db .pvc{display:none;background:var(--card);border:1px solid var(--line);border-left:5px solid var(--c);border-radius:16px;padding:.8rem;animation:rise .25s ease-out}
.db .pvc~.hint{display:none}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.db .pvc .act{margin-top:.5rem;background:var(--c)}.db .pvc .nm{margin-left:.5rem}.db .pvc .px small{color:var(--c)}.db .pvc .foot label{cursor:pointer}
@keyframes pop{from{opacity:0;transform:scale(.7)}to{opacity:1;transform:none}}
.db{--ink:#f4f1ea;--soft:#b6b2a8;--mut:#7d7a72;--card:#181b25;--line:#272b38;--buy:#7be3a8;--risk:#ff7a7a;--warn:#ffc267;--calm:#8ab4ff;color:var(--ink)}
.db h1{font:700 1.6rem/1.2 Georgia,"Iowan Old Style",serif !important;margin:.2rem 0 .8rem !important;letter-spacing:-.01em;color:var(--ink)}
.db h1 em{font-style:normal;padding:0 .25em;border-radius:6px}.db .e1{background:#41201f;color:var(--risk)}.db .e2{background:#3b2d14;color:var(--warn)}.db .e3{background:#1b2540;color:var(--calm)}
.db .ribbon{display:flex;gap:3px;height:12px;border-radius:99px;overflow:hidden;margin-bottom:.35rem}.db .ribbon i{display:block}
.db .rl{display:flex;gap:3px;font-size:.7rem;color:var(--mut);margin-bottom:1.1rem}.db .rl span:last-child{text-align:right}
.db .brief{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:.6rem .8rem;margin-bottom:.4rem}.db .brief summary{font-size:.82rem;color:var(--soft)}
.db .sec{display:flex;align-items:center;gap:.5rem;font-weight:700;font-size:.95rem;margin:1.2rem 0 .6rem}.db .sec small{font-weight:400;color:var(--mut)}.db .dot{width:10px;height:10px;border-radius:50%}
.db details>summary{list-style:none;cursor:pointer}.db details>summary::-webkit-details-marker{display:none}
.db .big{border-radius:22px;padding:15px;margin-bottom:10px;background:var(--bg2);border:1px solid var(--bd)}
.db .big.risk{--bg2:#41201f;--bd:#6b2f2d;--c:var(--risk)}.db .big.buy{--bg2:#17382b;--bd:#2b6a50;--c:var(--buy)}.db .big.warn{--bg2:#3b2d14;--bd:#6b5322;--c:var(--warn)}.db .big.calm{--bg2:#1b2540;--bd:#2c3a66;--c:var(--calm)}.db .big.mute{--bg2:#23252d;--bd:#3a3d48;--c:#8d8a84}
.db .top{display:flex;justify-content:space-between;align-items:flex-start}.db .tk{font:700 1.3rem/1 Georgia,serif;color:var(--ink)}.db .nm{font-size:.74rem;color:var(--soft);margin-top:.2rem}
.db .px{text-align:right}.db .px b{display:block;font:700 1.55rem/1 ui-monospace,Menlo,monospace;color:var(--ink)}.db .px small{font-size:.82rem;color:var(--c);font-weight:600}
.db .act{display:inline-block;margin-top:.8rem;background:var(--c);color:#111;font-weight:800;font-size:.78rem;letter-spacing:.05em;padding:.3rem .7rem;border-radius:99px}
.db .badge{display:inline-block;margin-left:.5rem;font-size:.7rem;color:var(--ink);border:1px solid rgba(255,255,255,.3);border-radius:99px;padding:.18rem .55rem;vertical-align:middle}
.db .why{margin:.6rem 0 0;color:var(--ink);font-size:.88rem}
.db .gauge{margin-top:.8rem}.db .gauge .bar{position:relative;display:flex;gap:3px;height:9px}.db .gauge .bar i{flex:1;border-radius:9px;opacity:.4}
.db .gauge .bar i:nth-child(1){background:#ff6b6b}.db .gauge .bar i:nth-child(2){background:#ffa566}.db .gauge .bar i:nth-child(3){background:#d6d2c4}.db .gauge .bar i:nth-child(4){background:#a6e08a}.db .gauge .bar i:nth-child(5){background:#4fd88f}
.db .needle{position:absolute;top:-5px;width:4px;height:19px;border-radius:3px;background:#fff;box-shadow:0 0 0 2px rgba(0,0,0,.45);transform:translateX(-50%)}
.db .gauge .lab{display:flex;justify-content:space-between;font-size:.66rem;color:var(--soft);margin-top:.35rem;gap:.5rem}.db .gauge .lab b{color:var(--ink)}
.db .mini{margin-top:.5rem}.db .mini .bar{height:6px}.db .mini .needle{height:14px;top:-4px;width:3px}
.db .more{display:flex;justify-content:space-between;margin-top:.8rem;font-size:.78rem;color:var(--soft)}
.db .grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.db .grid details[open]{grid-column:1/-1}
.db .mid{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:12px;border-top:4px solid var(--c)}
.db .mid.warn{--c:var(--warn)}.db .mid.mute{--c:#8d8a84}.db .mid.calm{--c:var(--calm)}.db .mid.risk{--c:var(--risk)}.db .mid.buy{--c:var(--buy)}
.db .mid .tk{font-size:1.1rem}.db .mid .p{font:600 1.05rem ui-monospace,monospace;margin-top:.4rem;color:var(--ink)}.db .mid .p small{font-size:.76rem;color:var(--c);margin-left:.3rem}
.db .mid .t{font-size:.72rem;color:var(--soft);margin-top:.4rem}
.db .mid .w{display:inline-block;background:var(--c);color:#111;font-weight:800;font-size:.66rem;letter-spacing:.05em;padding:.15rem .5rem;border-radius:99px;margin-bottom:.4rem}
.db .chips{display:flex;flex-wrap:wrap;gap:7px}.db .chip{background:var(--card);border:1px solid var(--line);border-radius:99px;padding:.35rem .7rem;font-size:.82rem;display:flex;gap:.4rem;align-items:center;text-decoration:none;color:var(--ink)}
.db .chip span{font-size:.74rem;color:var(--mut)}.db .chip .own{width:7px;height:7px;border-radius:50%;background:var(--buy)}
.db .open{margin-top:.9rem;border-top:1px dashed rgba(255,255,255,.2);padding-top:.8rem;color:var(--ink)}
.db .conf{background:rgba(0,0,0,.28);border-radius:16px;padding:.7rem .8rem;margin-bottom:.9rem}
.db .cf-h{display:flex;justify-content:space-between;gap:.5rem;font-size:.62rem;letter-spacing:.07em;color:var(--soft)}.db .cf-h b{color:var(--ink);font-size:.78rem;white-space:nowrap;letter-spacing:0}
.db .dots{display:flex;gap:4px;margin:.5rem 0}.db .dots i{flex:1;height:7px;border-radius:9px}.db .dots .y{background:var(--buy)}.db .dots .n{background:rgba(255,255,255,.18)}
.db .chk{list-style:none;margin:0;padding:0;font-size:.8rem}.db .chk li{padding:.18rem 0 .18rem 1.3rem;position:relative}.db .chk li:before{position:absolute;left:0;font-weight:800}
.db .chk .y:before{content:"✓";color:var(--buy)}.db .chk .n:before{content:"–";color:var(--mut)}.db .chk .n{color:var(--soft)}
.db .chg{margin:.5rem 0 0;font-size:.76rem;color:var(--warn)}
.db .h5{font-size:.64rem;letter-spacing:.08em;color:var(--soft);margin:.6rem 0 .5rem}.db .zn{font-size:.82rem;color:var(--ink)}
.db .ladder{display:flex;flex-direction:column;gap:6px}
.db .z{display:grid;grid-template-columns:1fr auto;background:rgba(0,0,0,.25);border-radius:12px;padding:.5rem .7rem;border-left:4px solid}.db .z.res{border-color:var(--risk)}.db .z.sup{border-color:var(--buy)}
.db .z .nm2{font-size:.68rem;color:var(--soft)}.db .z b{font:700 .95rem ui-monospace,monospace}.db .z em{grid-column:2;grid-row:1/3;align-self:center;font-style:normal;font-size:.64rem;font-weight:800;padding:.2rem .5rem;border-radius:99px;color:#111}
.db .z small{grid-column:1/3;font-size:.7rem;color:var(--soft);margin-top:.15rem}.db .g.h{background:var(--buy)}.db .g.m{background:var(--warn)}.db .g.l{background:#8d8a84}
.db .now{text-align:center;font-size:.72rem;position:relative}.db .now:before{content:"";position:absolute;left:0;right:0;top:50%;border-top:1px dashed rgba(255,255,255,.35)}.db .now span{position:relative;background:var(--bg2,#181b25);padding:0 .6rem}
.db .foot{display:flex;justify-content:space-between;margin-top:.9rem;font-size:.8rem;color:var(--soft)}.db .go{color:var(--ink);font-weight:700;text-decoration:none}
.db .key{margin-top:1.4rem;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:.8rem 1rem;font-size:.8rem;display:grid;gap:.35rem}.db .key div{display:flex;gap:.6rem;align-items:center}
.db .key .w2{min-width:4rem;text-align:center;font-weight:800;font-size:.68rem;padding:.15rem .4rem;border-radius:99px;color:#111}.db .key .soft{color:var(--soft);display:block}
"""
