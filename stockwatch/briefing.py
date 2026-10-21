"""Plain-English briefings built from scan snapshots: why the verdict, what changed, what to watch."""
from __future__ import annotations

import math

VERDICT_PHRASE = {
    "OPPORTUNITY - ADD": "is in a buy zone - a setup to add to the position",
    "STRONG HOLD": "is in good shape on both fundamentals and price action",
    "HOLD": "has nothing urgent - hold and keep monitoring",
    "TRIM / REVIEW": "is worth reviewing - consider trimming",
    "RISK - REVIEW": "needs attention now",
    "BUY SETUP": "is showing an entry setup",
    "WATCH": "is on watch - no entry signal yet",
    "AVOID": "is not attractive right now",
    "ERROR": "could not be scanned",
}


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def _band(score: float) -> str:
    return "strong" if score >= 70 else "solid" if score >= 55 else "mixed" if score >= 40 else "weak"


def _pct(v: float) -> str:
    return f"{v * 100:+.0f}%"


def stock(snap: dict, prev: dict | None = None) -> dict:
    p = snap["payload"]
    t, f, ev = p.get("technical") or {}, p.get("fundamental") or {}, p.get("events") or {}
    r = p.get("research") or {}
    earn, smart, val = r.get("earnings") or {}, r.get("smart_money") or {}, r.get("valuation") or {}
    price, tk = snap["price"], snap["ticker"]
    kind = "watchlist name" if p.get("watchlist") else f"Tier {snap['tier']} position"

    headline = f"{tk} ({kind}) {VERDICT_PHRASE.get(snap['verdict'], 'was scanned')}."
    if p.get("error"):
        return {"headline": headline, "why": [p["error"]], "changed": [], "watch": []}

    # ---- why
    why = []
    pillars = {k: f.get(f"pillar_{k}") for k in ("valuation", "growth", "quality", "balance")}
    pillars = {k: v for k, v in pillars.items() if _ok(v)}
    fs = snap["fundamental_score"]
    line = f"Fundamentals are {_band(fs)} ({fs:.0f}/100)"
    if len(pillars) >= 2:
        best, worst = max(pillars, key=pillars.get), min(pillars, key=pillars.get)
        line += f": best on {best} ({pillars[best]:.0f}), weakest on {worst} ({pillars[worst]:.0f})"
    why.append(line + ".")

    trend = t.get("trend")
    tline = {"up": "Price trend is up - above its 200-day average with the 50-day leading",
             "down": "Price trend is down - below its 200-day average with the 50-day lagging"}.get(
        trend, "Price trend is mixed - the averages disagree")
    if _ok(t.get("rsi")):
        rsi = t["rsi"]
        tline += f"; RSI {rsi:.0f}" + (" (oversold)" if rsi < 30 else " (overbought)" if rsi > 70 else "")
    why.append(tline + ".")
    if _ok(t.get("rs_spy_3m")):
        rs = t["rs_spy_3m"]
        why.append(f"Over 3 months it has {'outperformed' if rs >= 0 else 'underperformed'} the market by {abs(rs) * 100:.0f}%"
                   + (f" and its sector ({t['sector_etf']}) by {abs(t['rs_sector_3m']) * 100:.0f}%"
                      if _ok(t.get("rs_sector_3m")) and t.get("sector_etf") and (t["rs_sector_3m"] >= 0) == (rs >= 0) else "")
                   + ".")
    for s in [s for s in p["signals"] if s["severity"] >= 2][:3]:
        why.append(("Opportunity: " if s["kind"] == "opportunity" else "Risk: ") + s["message"] + ".")

    # ---- what changed
    changed = []
    if prev is None:
        changed.append("First scan on record - nothing to compare yet.")
    else:
        if prev["verdict"] != snap["verdict"]:
            changed.append(f"Verdict moved from {prev['verdict']} to {snap['verdict']}.")
        d = snap["composite"] - prev["composite"]
        if abs(d) >= 5:
            changed.append(f"Overall score {'rose' if d > 0 else 'fell'} {abs(d):.0f} points "
                           f"({prev['composite']:.0f} -> {snap['composite']:.0f}).")
        if _ok(prev.get("price")) and prev["price"]:
            move = price / prev["price"] - 1
            if abs(move) >= 0.03:
                changed.append(f"Price {'up' if move > 0 else 'down'} {abs(move) * 100:.1f}% since the last scan.")
        before = {s["code"] for s in prev["payload"].get("signals", [])}
        now = {s["code"] for s in p["signals"]}
        new = [s for s in p["signals"] if s["code"] not in before]
        gone = [s for s in prev["payload"].get("signals", []) if s["code"] not in now and s["severity"] >= 2]
        changed += [f"New: {s['message']}." for s in new[:3]]
        changed += [f"Cleared: {s['message']}." for s in gone[:2]]
        if not changed:
            changed.append("No meaningful change since the last scan.")

    # ---- what to watch
    watch = []
    if ev.get("earnings_date"):
        line = f"Earnings on {ev['earnings_date']} ({ev['days_to_earnings']} days)"
        if _ok(earn.get("avg_move")):
            line += f"; it has moved about {earn['avg_move'] * 100:.0f}% on recent report days"
        if earn.get("reported"):
            line += f", beating EPS estimates {earn['beats']} of the last {earn['reported']} times"
        watch.append(line + ".")
    lv = val.get("levels") or {}
    parts = []
    if _ok(lv.get("support")):
        parts.append(f"support near {lv['support']:.2f} ({_pct(lv['support'] / price - 1)})")
    if _ok(lv.get("resistance")):
        parts.append(f"resistance near {lv['resistance']:.2f} ({_pct(lv['resistance'] / price - 1)})")
    if parts:
        watch.append("Key levels: " + ", ".join(parts) + ".")
    sma200 = t.get("sma200")
    if _ok(sma200):
        if trend == "down" or price < sma200:
            watch.append(f"A close back above the 200-day ({sma200:.2f}, {_pct(sma200 / price - 1)}) would turn the trend up.")
        else:
            watch.append(f"Losing the 200-day ({sma200:.2f}, {_pct(sma200 / price - 1)}) would break the uptrend.")
    fv = val.get("fair_value")
    if fv:
        watch.append(f"Fair-value estimate {fv['low']:.2f}-{fv['high']:.2f}, midpoint {fv['mid']:.2f} "
                     f"({_pct(fv['upside'])}) from {len(fv['methods'])} method{'s' if len(fv['methods']) != 1 else ''}.")
    if not p.get("watchlist") and _ok(t.get("trailing_stop")):
        ts = t["trailing_stop"]
        watch.append(f"Price is below its trailing stop ({ts:.2f}) - the stop has been hit." if price < ts
                     else f"Trailing stop sits at {ts:.2f} ({_pct(ts / price - 1)}).")
    if _ok(smart.get("short_pct_float")) and smart["short_pct_float"] >= 0.15:
        watch.append(f"{smart['short_pct_float'] * 100:.0f}% of the float is sold short - expect sharp squeezes and drops.")
    return {"headline": headline, "why": why, "changed": changed, "watch": watch}


def portfolio(snaps: list[dict], prevs: dict[str, dict | None], regime: dict | None) -> list[str]:
    lines = []
    if regime:
        mood = {"RISK-ON": "supportive (SPY in an uptrend)", "RISK-OFF": "hostile (SPY below its 200-day)",
                "CAUTION": "mixed (SPY trend unclear)"}[regime["state"]]
        lines.append(f"Market backdrop is {mood}; SPY {_pct(regime['day_change'])} today.")
    urgent = [s["ticker"] for s in snaps if any(x["kind"] == "risk" and x["severity"] >= 3 for x in s["payload"]["signals"])]
    if urgent:
        lines.append(f"Needs attention now: {', '.join(urgent)}.")
    opps = [s["ticker"] for s in snaps if s["verdict"] in ("OPPORTUNITY - ADD", "BUY SETUP")]
    if opps:
        lines.append(f"In a buy zone: {', '.join(opps)}.")
    soon = sorted((s["payload"]["events"]["days_to_earnings"], s["ticker"]) for s in snaps
                  if (s["payload"].get("events") or {}).get("days_to_earnings") is not None
                  and s["payload"]["events"]["days_to_earnings"] <= 7)
    if soon:
        lines.append("Reporting this week: " + ", ".join(f"{t} ({d}d)" for d, t in soon) + ".")
    flips = [f"{s['ticker']} {prevs[s['ticker']]['verdict']} -> {s['verdict']}" for s in snaps
             if prevs.get(s["ticker"]) and prevs[s["ticker"]]["verdict"] != s["verdict"]]
    if flips:
        lines.append("Changed since last sweep: " + "; ".join(flips[:5]) + ".")
    ranked = sorted((s for s in snaps if not s["payload"].get("error")), key=lambda s: s["composite"], reverse=True)
    if len(ranked) >= 6:
        lines.append("Strongest: " + ", ".join(s["ticker"] for s in ranked[:3])
                     + ". Weakest: " + ", ".join(s["ticker"] for s in ranked[-3:]) + ".")
    if not urgent and not opps:
        lines.append("No urgent risks or buy setups right now.")
    return lines
