"""Pure HTML for the Ask-the-AI screen. No AI calls, storage, trading or Streamlit."""
from __future__ import annotations

from datetime import datetime
from html import escape
import math
from urllib.parse import quote
from zoneinfo import ZoneInfo

COLORS = {"BUY": "#3dffa8", "HOLD": "#ffb020", "SELL": "#ff697b", "AVOID": "#ff697b"}
MEANINGS = {"BUY": "A possible entry. Check the conditions below.", "HOLD": "Wait. Not a buy yet.",
            "SELL": "If owned, review the exit below.", "AVOID": "Do not buy under these conditions."}
LEVELS = {"exit_line": "exit", "price": "price", "resistance": "resistance", "support": "support"}
CSS = """
.aiv{color:var(--dz-ink,#e9eef5);font:15px/1.5 system-ui;max-width:800px;margin:0 auto;overflow-wrap:anywhere}
.aiv *{box-sizing:border-box}.aiv-card{background:var(--dz-surface,#131b2e);border:1px solid var(--dz-line,#283348);border-radius:16px;padding:20px;margin:14px 0}
.aiv small,.aiv-muted{color:var(--dz-soft,#aab3c3)}.aiv-head{display:flex;justify-content:space-between;gap:12px;align-items:start}.aiv-head>div{min-width:0}
.aiv-ticker{font-size:26px;font-weight:800;letter-spacing:.02em}.aiv-price{text-align:right;white-space:nowrap}.aiv-price b{display:block;font-size:22px}
.aiv-call{border-left:4px solid var(--call);padding:12px 15px;margin:20px 0 12px;background:var(--dz-raised,#171f2c);border-radius:10px}.aiv-word{font-size:29px;font-weight:850;color:var(--call)}
.aiv-conf{display:flex;align-items:center;gap:6px;font-size:13px;margin:12px 0}.aiv-dot{width:9px;height:9px;border-radius:50%;background:var(--dz-line,#374050);display:inline-block}.aiv-dot.on{background:var(--call)}
.aiv-title{font-size:16px;font-weight:700;margin:20px 0 12px}.aiv-change{display:grid;grid-template-columns:50px minmax(0,1fr);gap:12px;border-top:1px solid var(--dz-line,#283348);padding:12px 0}.aiv-change b{color:var(--tone)}
.aiv-ladder{position:relative;margin:8px 0;padding-left:16px}.aiv-ladder:before{content:'';position:absolute;left:4px;top:20px;bottom:20px;border-left:1px solid var(--dz-line,#374050)}
.aiv-level{position:relative;display:grid;grid-template-columns:78px minmax(0,1fr);gap:12px;padding:13px 0;border-bottom:1px dotted #738092;color:#aab3c3}.aiv-level:before{content:'';position:absolute;left:-15px;top:23px;width:7px;height:7px;border-radius:50%;background:currentColor}
.aiv-level.exit{color:#3dffa8;border-bottom:1px dashed #3dffa8}.aiv-level.price{color:#70b8ff;border-bottom:1px solid #70b8ff}.aiv-level.support{color:#ff697b;border-bottom:1px dashed #ff697b}.aiv-level b{font-variant-numeric:tabular-nums}
.aiv-fact,.aiv-result{display:flex;justify-content:space-between;gap:16px;border-top:1px solid var(--dz-line,#283348);padding:10px 0}.aiv-fact>span{min-width:0}.aiv-fact>span:last-child{text-align:right}.aiv-plan>span:first-child{flex:1}.aiv-plan>span:last-child{flex:0 0 auto;white-space:nowrap}
.aiv-good{color:#3dffa8}.aiv-bad{color:#ff697b}.aiv-neutral{color:var(--dz-ink,#e9eef5)}.aiv-foot{font-size:12px;border-top:1px solid var(--dz-line,#283348);margin-top:18px;padding-top:12px;color:var(--dz-soft,#aab3c3)}
.aiv-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.aiv-tiles>div{background:var(--dz-raised,#171f2c);border-radius:10px;padding:12px}.aiv-tiles b{display:block;font-size:23px}.aiv-tiles small{display:block;font-size:12px}
.aiv-table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:13px}.aiv-table th,.aiv-table td{text-align:left;padding:10px 3px;vertical-align:top;border-bottom:1px solid var(--dz-line,#283348);overflow-wrap:anywhere}.aiv-table th:first-child{width:26%}.aiv-table th:nth-child(2){width:20%}.aiv-table th:nth-child(3){width:19%}
.aiv-demo{font-size:13px;color:#70b8ff;margin-bottom:12px}.aiv-headline{margin:12px 0}.aiv-status{padding:8px 0}
@media(max-width:450px){.aiv-card{padding:15px}.aiv-price b{font-size:19px}.aiv-tiles{gap:6px}.aiv-tiles>div{padding:9px}.aiv-conf{flex-wrap:wrap}}
"""


def _text(value) -> str:
    return escape(str(value)) if value is not None else "unknown"


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _price(value) -> str:
    value = _num(value)
    return "unknown" if value is None else f"{value:,.2f}"


def _time(value) -> str:
    if not value:
        return "unknown time"
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if at.tzinfo is None:
            return f"{at:%d %b %H:%M} (time zone unknown)"
        return f"{at.astimezone(ZoneInfo('America/New_York')):%d %b %H:%M} NY"
    except ValueError:
        return str(value)


def _ticker(value, tracked: set[str] | None) -> str:
    text = _text(value)
    if not value or (tracked is not None and value not in tracked):
        return text
    href = "?view=target&t=" + quote(str(value), safe="")
    return f'<a href="{escape(href, quote=True)}" target="_self">{text}</a>'


def _wrap(body):
    return f'<style>{CSS}</style><div class="aiv">{body}</div>'


def plan_html(plan) -> str:
    """The trade plan box: entry, stop, targets, reward vs risk. Advice only; nothing here is placed."""
    if not isinstance(plan, dict):
        return '<div class="aiv-title">Plan</div><div class="aiv-muted">No plan for this answer.</div>'
    rows = [("Entry", plan.get("entry"), ""), ("Stop loss", plan.get("stop"), plan.get("stop_why")),
            ("Take profit 1", plan.get("target1"), plan.get("target_why")), ("Take profit 2", plan.get("target2"), "")]
    body = ''.join(f'<div class="aiv-fact aiv-plan"><span>{label}{"<br><small>" + _text(why) + "</small>" if why else ""}</span>'
                   f'<span>{_price(val)}</span></div>' for label, val, why in rows if val is not None)
    rr = _num(plan.get("reward_risk"))
    rr_text = f'<div class="aiv-fact"><span>Gain for each $1 risked</span><span>${rr:.1f}</span></div>' if rr is not None else ""
    return f'<div class="aiv-title">Plan (advice only)</div>{body}{rr_text}'


def html(verdict: dict | None, tracked: set[str] | None = None) -> str:
    """An escaped verdict card, including unasked/pending/failed states and unknown facts."""
    if not verdict:
        return _wrap('<div class="aiv-card aiv-status">Not asked yet. Choose a stock and tap Ask.</div>')
    v = verdict
    status = v.get("status")
    ticker = _ticker(v.get("ticker"), tracked)
    if status == "asking":
        return _wrap(f'<div class="aiv-card" role="status"><div class="aiv-ticker">{ticker}</div><p>Asking…</p>'
                     '<small>The answer will appear here. You can leave this tab.</small></div>')
    if status == "failed":
        return _wrap(f'<div class="aiv-card" role="status"><div class="aiv-ticker">{ticker}</div><p>Could not answer</p>'
                     f'<span class="aiv-muted">{_text(v.get("error") or "The AI could not answer. Try again later.")}</span></div>')
    if status != "ready" or v.get("verdict") not in COLORS:
        return _wrap('<div class="aiv-card">Answer unavailable. No valid verdict was saved.</div>')
    call = v["verdict"]
    confidence = v.get("confidence")
    confidence = confidence if isinstance(confidence, int) and not isinstance(confidence, bool) and 1 <= confidence <= 5 else None
    dots = ''.join(f'<i class="aiv-dot{" on" if confidence and i < confidence else ""}" aria-hidden="true"></i>' for i in range(5))
    confidence_text = f"{confidence} of 5" if confidence else "unknown"
    changes = ''.join(f'<div class="aiv-change" style="--tone:{COLORS[c]}"><b>{c}</b><span>{_text(v.get(k))}</span></div>'
                      for c,k in (("BUY","change_buy"),("HOLD","change_hold"),("SELL","change_sell")))
    levels = sorted(v.get("levels") or [], key=lambda x: ( _num(x.get("price")) is None, -(_num(x.get("price")) or 0)))
    def level_label(level):
        if level.get("kind") == "price":
            return "Price · " + str(v.get("price_label") or "time unknown")
        return level.get("label")
    ladder = ''.join(f'<div class="aiv-level {LEVELS.get(lv.get("kind"), "resistance")}"><b>{_price(lv.get("price"))}</b>'
                     f'<span>{_text(level_label(lv))}</span></div>' for lv in levels)
    facts = ''.join(f'<div class="aiv-fact"><span>{_text(f.get("label"))}</span>'
                    f'<span class="aiv-{f.get("tone") if f.get("tone") in ("good","bad","neutral") and f.get("value") is not None else "muted"}">'
                    f'{_text(f.get("value"))}</span></div>' for f in v.get("facts") or [])
    demo = '<div class="aiv-demo">Synthetic demo · no AI call</div>' if v.get("demo") else ""
    return _wrap(f'<section class="aiv-card" style="--call:{COLORS[call]}">{demo}<div class="aiv-head">'
                 f'<div><div class="aiv-ticker">{ticker}</div><small>{_text(v.get("name") or "")} · {_text(v.get("sector") or "unknown sector")}</small></div>'
                 f'<div class="aiv-price"><b>{_price(v.get("price"))}</b><small>{_text(v.get("price_label"))}</small></div></div>'
                 f'<div class="aiv-call"><div class="aiv-word">{call}</div><div>{MEANINGS[call]}</div>'
                 f'<div class="aiv-conf" aria-label="Confidence: {confidence_text}">{dots}<span>Confidence: {confidence_text}</span></div></div>'
                 f'<p class="aiv-headline">{_text(v.get("headline"))}</p><div class="aiv-title">What would change it</div>{changes}'
                 f'{plan_html(v.get("plan"))}<div class="aiv-title">Price ladder</div><div class="aiv-ladder">{ladder or "Levels unknown"}</div>'
                 f'<div class="aiv-title">Facts</div>{facts or "Facts unknown"}'
                 f'<div class="aiv-foot">Saved {_text(_time(v.get("asked_at")))} · scored at +60 min and at the close · places no trade</div></section>')


def _return(value):
    value = _num(value)
    return "—" if value is None else f"{value:+.2f}%"


def history_html(rows: list[dict], tracked: set[str] | None = None) -> str:
    """Scored returns are percentage points, not fractions; only ready real verdicts enter statistics."""
    ready = [r for r in rows if r.get("status") == "ready" and not r.get("demo")]
    def success(call, up):
        scored = [_num((r.get("scored") or {}).get("plus60")) for r in ready if r.get("verdict") == call]
        scored = [v for v in scored if v is not None]
        return f"{sum(v > 0 if up else v < 0 for v in scored) / len(scored):.0%}" if scored else "—"
    tiles = ''.join(f'<div><b>{value}</b><small>{label}</small></div>' for label,value in (
        ("AI verdicts",str(len(ready))), ("BUY rose · +60 min",success("BUY",True)), ("AVOID fell · +60 min",success("AVOID",False))))
    body = []
    for r in rows:
        status = r.get("status")
        if status == "asking":
            continue  # pending placeholders belong on the card, not in the outcome history
        call = r.get("verdict") if status == "ready" else "Asking…" if status == "asking" else "Failed"
        sc = (r.get("scored") or {}) if status == "ready" else {}
        body.append(f'<tr><td>{_text(_time(r.get("asked_at")))}</td><td>{_ticker(r.get("ticker"), tracked)}'
                    f'{"<small> · demo</small>" if r.get("demo") else ""}</td><td>{_text(call)}</td>'
                    f'<td>{_return(sc.get("plus60"))}</td><td>{_return(sc.get("close"))}</td></tr>')
    demo = '<p class="aiv-muted">Synthetic demo rows are excluded from statistics.</p>' if any(r.get("demo") for r in rows) else ""
    table = ('<table class="aiv-table"><thead><tr><th scope="col">Saved</th><th scope="col">Stock</th><th scope="col">Verdict</th>'
             '<th scope="col">+60 min</th><th scope="col">Close</th></tr></thead><tbody>'+''.join(body)+'</tbody></table>') if body else '<p class="aiv-muted">No verdicts saved yet.</p>'
    return _wrap(f'<section class="aiv-card"><div class="aiv-title" style="margin-top:0">How the AI did</div>'
                 f'<div class="aiv-tiles">{tiles}</div>{demo}{table}</section>')
