"""Holdings rotation (shadow mode: it only suggests, it never trades and changes no call).

For every stock you own it reads the New call. When a holding's call is EXIT, it suggests trimming part of it and names the
strongest stocks to move that money into. A stock qualifies only if its own New call is ADD or BUY, its risk is not High or
Extreme, its fundamentals and technicals are strong, and both beat the holding's. Otherwise the answer is "keep the cash".
"""
from __future__ import annotations

TRIM = {"EXIT": 0.5, "AVOID": 0.5}            # how much of a weak holding to trim
STRONG_FUND, STRONG_TECH = 60, 60
MAX_PICKS = 3


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def _oc(snap: dict) -> dict:
    oc = ((snap.get("payload") or {}).get("technical") or {}).get("one_call")
    return oc if isinstance(oc, dict) else {}


def _price(snap: dict):
    from . import ui
    px = ui._now(snap)[0]
    return float(px) if _num(px) is not None else None


def candidates(snaps: list[dict], weak: dict, exclude: set) -> list[dict]:
    """Stocks that could take the money, best first. `weak` is the holding's snapshot, to beat it on both scores."""
    out = []
    wf, wt = _num(weak.get("fundamental_score")), _num(weak.get("technical_score")) or 0
    for s in snaps:
        t = s["ticker"]
        oc = _oc(s)
        if t in exclude or not oc.get("known") or oc.get("call") not in ("ADD", "BUY"):
            continue
        if ((oc.get("risk") or {}).get("grade") or "") in ("High", "Extreme"):
            continue
        f, tc = _num(s.get("fundamental_score")), _num(s.get("technical_score"))
        if f is None or tc is None or f < STRONG_FUND or tc < STRONG_TECH:
            continue
        if tc <= wt or (wf is not None and f <= wf):
            continue                                          # must be clearly better, not just different
        out.append({"ticker": t, "call": oc["call"], "price": _price(s), "exit_line": oc.get("exit_line"), "fund": round(f), "tech": round(tc),
                    "risk": (oc.get("risk") or {}).get("grade"), "why": oc.get("why") or "",
                    "score": _num(s.get("composite")) or 0})
    out.sort(key=lambda c: -c["score"])
    return out[:MAX_PICKS]


def build(snaps: list[dict], holdings) -> list[dict]:
    """One row per owned stock (shares > 0), weakest first."""
    by = {s["ticker"]: s for s in snaps}
    owned = {h.ticker for h in holdings if h.shares and h.shares > 0}
    rows = []
    for h in holdings:
        if not h.shares or h.shares <= 0:
            continue
        s = by.get(h.ticker)
        if not s:
            rows.append({"ticker": h.ticker, "shares": h.shares, "action": "NO DATA", "note": "no reading for this stock yet", "picks": []})
            continue
        oc = _oc(s)
        px = _price(s)
        call = oc.get("call") if oc.get("known") else None
        pl = (px / h.cost_basis - 1) * 100 if px and h.cost_basis else None
        loss = (h.cost_basis - px) * h.shares if px and h.cost_basis and px < h.cost_basis else 0.0
        row = {"ticker": h.ticker, "shares": h.shares, "cost": h.cost_basis, "price": px, "pl_pct": pl, "loss": round(loss, 2), "call": call or "UNKNOWN",
               "exit_line": oc.get("exit_line"), "band_line": oc.get("band_line"), "why": oc.get("why") or "", "picks": [], "trim_shares": 0.0, "trim_value": 0.0}
        if call in TRIM:
            frac = TRIM[call]
            row["trim_shares"] = round(h.shares * frac, 4)
            row["trim_value"] = round(row["trim_shares"] * px, 2) if px else 0.0
            row["picks"] = candidates(list(by.values()), s, owned)
            row["action"] = "ROTATE" if row["picks"] else "TRIM · KEEP CASH"
            row["note"] = (f"trim {frac:.0%}, move to the best candidate" if row["picks"]
                           else f"trim {frac:.0%}; nothing clearly stronger right now, so keep the cash")
        elif call == "ON THE LINE":
            row["action"], row["note"] = "WATCH", "sitting on its exit line: a close below the band would turn this into a rotation"
        elif call is None:
            row["action"], row["note"] = "NO CALL", "no clear reading yet; nothing is suggested"
        else:
            row["action"], row["note"] = "HOLD", "no reason to rotate"
        rows.append(row)
    order = {"ROTATE": 0, "TRIM · KEEP CASH": 1, "WATCH": 2, "HOLD": 3, "NO CALL": 4, "NO DATA": 5}
    rows.sort(key=lambda r: (order.get(r["action"], 9), -(r.get("loss") or 0)))
    return rows


LOG_KEY = "rotation_log"


def log(store, rows: list[dict], day: str) -> bool:
    """Shadow record: one line per stock, day and suggestion, so the suggestions can be judged against what happened later."""
    import json
    raw = store.get_setting(LOG_KEY)
    entries = json.loads(raw) if raw else []
    seen = {(e["day"], e["ticker"], e["action"]) for e in entries[-400:]}
    new = [{"day": day, "ticker": r["ticker"], "action": r["action"], "price": r.get("price"), "picks": [p["ticker"] for p in r["picks"]],
            "pick_prices": {p["ticker"]: p["price"] for p in r["picks"]}}
           for r in rows if r["action"] in ("ROTATE", "TRIM · KEEP CASH") and (day, r["ticker"], r["action"]) not in seen]
    if not new:
        return False
    store.set_setting(LOG_KEY, json.dumps((entries + new)[-400:]))
    return True


def html(rows: list[dict]) -> str:
    from html import escape
    from . import ui
    colors = {"ROTATE": ui.RISK, "TRIM · KEEP CASH": ui.WARN, "WATCH": ui.WARN, "HOLD": ui.OPP, "NO CALL": ui.MUTED, "NO DATA": ui.MUTED}
    f = lambda v, d=2: "n/a" if v is None else f"{v:,.{d}f}"                    # noqa: E731
    cards = []
    for r in rows:
        c = colors.get(r["action"], ui.MUTED)
        pl = "" if r.get("pl_pct") is None else f' · {r["pl_pct"]:+.1f}% vs cost'
        line = f'Exit line {f(r.get("exit_line"))}' if r.get("exit_line") else ""
        row_css = "margin:.35rem 0;font-size:.88rem;line-height:1.45;font-family:inherit;white-space:normal"
        picks = "".join(
            f'<div style="{row_css}"><b style="font-size:1rem">→ {escape(p["ticker"])}</b> '
            f'<span style="opacity:.85">{escape(p["call"])} at {f(p["price"])} · exit line {f(p["exit_line"])}</span><br>'
            f'<span style="opacity:.7">Fundamentals {p["fund"]} · Technicals {p["tech"]} · Risk {escape(str(p["risk"]))}</span></div>'
            for p in r.get("picks", []))
        trim = (f'<div style="{row_css}"><b>Trim</b> {r["trim_shares"]:g} of {r["shares"]:g} shares (about &#36;{r["trim_value"]:,.0f})'
                + (f'<br><span style="opacity:.7">Loss so far on the whole position: &#36;{r["loss"]:,.0f}</span>' if r.get("loss") else "") + '</div>') if r.get("trim_shares") else ""
        box = (f'<div style="margin-top:.5rem;padding-top:.4rem;border-top:1px solid rgba(128,128,128,.3)">{trim}{picks}</div>'
               if trim or picks else "")
        cards.append(
            f'<a class="mc-a" href="?view=target&t={escape(r["ticker"])}" target="_self"><div class="mc-li" style="--c:{c};--a:{c}">'
            f'<div class="call"><span class="mc-chip" style="--c:{c}"><b>{escape(r["action"])}</b></span>'
            f'<span class="mc-chip" style="--c:{ui.WARN if r.get("call") in ("ADD", "BUY") else ui.NEWCALL_COLOR.get(r.get("call"), ui.MUTED)}"><b>New call</b> {escape(str(r.get("call", "")))}</span></div>'
            f'<div class="hd"><div class="id"><span class="mc-tk">{escape(r["ticker"])}</span><span class="nm">{r["shares"]:g} shares'
            f'{" · cost " + f(r.get("cost")) if r.get("cost") else ""}</span></div><div class="mc-px">{f(r.get("price"))}</div></div>'
            f'<div class="why">{escape(r.get("note", ""))}{escape(pl)}{" · " + escape(line) if line else ""}'
            + ('<br><span style="opacity:.7">Near its exit line: not a reason to add by itself.</span>' if r.get("call") in ("ADD", "BUY") else "") + '</div>'
            + box + '</div></a>')
    return "".join(cards) or '<div class="mc-d">No holdings with shares in the sheet.</div>'
