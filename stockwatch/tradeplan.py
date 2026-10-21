"""Rule-based trade plan: entry zone, stop, targets, outlook and exit rules.

Levels come from chart structure (support/resistance, moving averages, 52-week high)
and volatility (ATR); targets also consider fair value and analyst targets. Every
number is derived mechanically, so the plan is consistent and explainable, not a
prediction.
"""
from __future__ import annotations

import math

import pandas as pd

from . import deepdive

NEW_ENTRY = {"BUY NOW", "BUY ON PULLBACK", "BUY THE BREAKOUT", "WAIT FOR CONFIRMATION", "ADD"}
MIN_RR = 1.5          # reward-to-risk below this isn't worth a new entry


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def build(hist: pd.DataFrame, tech: dict, fund: dict, fs: float, verdict: str, tier: int, watchlist: bool,
          levels: dict | None = None, fair_value: dict | None = None, events: dict | None = None,
          quote: dict | None = None) -> dict:
    price, atr = tech["price"], tech["atr"]
    if not (_ok(price) and _ok(atr) and atr > 0):
        return {}
    close = hist["Close"]
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50, sma200, trend = tech.get("sma50"), tech.get("sma200"), tech.get("trend")
    hi52 = tech.get("high_52w")
    lv = levels or deepdive.levels(hist, price)
    sup, res = lv.get("support"), lv.get("resistance")
    mult = 3.0 if tier == 1 else 2.0
    held = not watchlist
    notes: list[str] = []

    # ---- stance and entry zone. New entries need the engine's BUY SETUP verdict; otherwise the plan
    # waits for a trigger, so the plan never says "buy" while the verdict says "watch".
    trigger = None
    setup_ok = verdict == "BUY SETUP"
    weak = verdict in ("RISK - REVIEW", "AVOID") or (trend == "down" and fs < 50)

    def pullback_zone():
        anchors = [a for a in (sup, sma20, sma50) if _ok(a) and price - 3 * atr <= a <= price]
        anchor = max(anchors) if anchors else price - atr
        return anchor, anchor + 0.5 * atr

    if held:
        stance = {"OPPORTUNITY - ADD": "ADD", "TRIM / REVIEW": "TRIM", "RISK - REVIEW": "REDUCE / EXIT"}.get(verdict, "HOLD")
        low, high = pullback_zone()
    elif weak:
        stance = "NO TRADE"
        low, high = pullback_zone()
    elif trend == "up" and _ok(hi52) and price >= hi52 * 0.97:
        pivot = res if _ok(res) and res <= price * 1.05 else hi52
        low, high = max(pivot, price - 0.5 * atr), max(pivot, price) + 0.25 * atr
        stance = "BUY THE BREAKOUT" if setup_ok else "WAIT FOR CONFIRMATION"
        trigger = f"a close above {pivot:.2f} on above-average volume, or the first pullback that holds it"
    elif trend == "up":
        low, high = pullback_zone()
        if price > high + 0.25 * atr:
            stance = "BUY ON PULLBACK"
            trigger = f"limit order in the zone, {(high / price - 1) * 100:+.1f}% below the current price"
        elif setup_ok:
            stance = "BUY NOW"
            low, high = max(low, price - 0.5 * atr), price
        else:
            stance = "WAIT FOR CONFIRMATION"
            trigger = f"a bounce from the zone: a close above {high + 0.5 * atr:.2f}"
    elif setup_ok:
        stance = "BUY NOW"
        low, high = price - 0.5 * atr, price
    else:
        stance = "WAIT FOR CONFIRMATION"
        level = sma200 if _ok(sma200) and price < sma200 else (sma50 if _ok(sma50) else price + atr)
        low, high = level, level + 0.5 * atr
        trigger = f"a daily close back above {level:.2f} ({(level / price - 1) * 100:+.1f}%)"
    entry = (low + high) / 2 if not held else price

    # ---- stop: structural if it's sensible, otherwise volatility-based
    vol_stop = entry - mult * atr
    struct = sup - 0.5 * atr if _ok(sup) and sup < low else None
    if struct is not None and 0.75 * atr <= entry - struct <= 1.5 * mult * atr:
        stop, stop_basis = struct, f"below support at {sup:.2f}"
    else:
        stop, stop_basis = vol_stop, f"{mult:.0f}x ATR below {'the current price' if held else 'entry'}"
    risk = entry - stop

    # ---- targets: chart levels, fair value and analyst view above the entry
    candidates = []
    if _ok(res) and res > entry:
        candidates.append((res, "resistance"))
    if _ok(hi52) and hi52 > entry * 1.01:
        candidates.append((hi52, "52-week high"))
    if fair_value and fair_value.get("mid", 0) > entry:
        candidates.append((fair_value["mid"], "fair value"))
    if _ok(fund.get("analyst_upside")) and price * (1 + fund["analyst_upside"]) > entry:
        candidates.append((price * (1 + fund["analyst_upside"]), "analyst target"))
    candidates.sort()
    # first target: the nearest level that pays at least 1.5x the risk, but no further than 5x
    t1 = next(((p, l) for p, l in candidates if entry + 1.5 * risk <= p <= entry + 5 * risk),
              (entry + 2 * risk, "2R measured move"))
    t2 = next(((p, l) for p, l in candidates if t1[0] * 1.03 <= p <= entry + 8 * risk),
              (max(entry + 3.5 * risk, t1[0] + 1.5 * risk), "measured move"))
    rr = (t1[0] - entry) / risk if risk > 0 else 0.0
    if stance in ("BUY NOW", "BUY THE BREAKOUT", "ADD") and rr < MIN_RR:
        notes.append(f"Reward-to-risk is only {rr:.1f}:1 here; a lower entry would improve it.")

    # ---- outlook
    rs = tech.get("rs_spy_3m")
    if trend == "up" and fs >= 55:
        bias = "bullish"
        outlook = (f"Trend and fundamentals agree. Base case: higher, toward {t1[0]:.2f} and then {t2[0]:.2f}. "
                   f"The view is wrong if it closes below {stop:.2f}.")
    elif trend == "down" and (fs < 50 or (_ok(rs) and rs < -0.10)):
        bias = "bearish"
        floor = f"next support near {sup:.2f} ({(sup / price - 1) * 100:+.0f}%)" if _ok(sup) else "no clear support nearby"
        outlook = f"Sellers are in control: {floor}. It needs a close above {sma200:.2f} (200-day) to change that." \
            if _ok(sma200) else f"Sellers are in control: {floor}."
    else:
        bias = "neutral"
        rng = (f"between {sup:.2f} and {res:.2f}" if _ok(sup) and _ok(res) else "around current levels")
        outlook = f"Mixed signals. Likely range-bound {rng} until one side breaks."
    horizon = "Position trade: 3-12 months" if tier == 1 else "Swing trade: 2-8 weeks"

    # ---- exit rules
    trail = (f"the 50-day average (now {sma50:.2f})" if tier == 1 and _ok(sma50)
             else f"the 20-day average (now {sma20:.2f})")
    exits = [f"Stop: sell if it closes below {stop:.2f} ({stop_basis}).",
             f"Take a third at {t1[0]:.2f} ({t1[1]}) and move the stop to break-even.",
             f"Trail the rest under {trail}; sell the remainder near {t2[0]:.2f} ({t2[1]}).",
             "Sell early if a thesis-break alert fires (weak fundamentals with a technical breakdown) or on a death cross.",
             "Time stop: if the first target isn't reached within " + ("6 months" if tier == 1 else "6 weeks")
             + ", reassess instead of waiting."]
    if held and stance == "TRIM":
        exits.insert(0, "Trim now: take some profit and keep the rest under the trailing stop.")
    if stance == "REDUCE / EXIT":
        exits = ["Reduce or exit now: the risk signals outweigh the reasons to hold.",
                 f"If you keep part of it, sell the rest on a close below {stop:.2f}.",
                 (f"Rebuild only after a close back above {sma200:.2f} (200-day) with the risk alerts cleared."
                  if _ok(sma200) and price < sma200 else "Rebuild only once the risk alerts clear.")]

    ev = events or {}
    if ev.get("days_to_earnings") is not None and 0 <= ev["days_to_earnings"] <= 7:
        notes.append(f"Earnings in {ev['days_to_earnings']} days: either wait for the report or open half a position.")
    q = quote or {}
    if _ok(q.get("ext_change")) and abs(q["ext_change"]) >= 0.03:
        notes.append(f"{'Pre-market' if q.get('ext_session') == 'pre' else 'After hours'} it's {q['ext_change'] * 100:+.1f}%: "
                     "let the open settle before acting on these levels.")
    if stance == "NO TRADE":
        trigger = (f"revisit after a close above {sma200:.2f} (200-day)" if _ok(sma200) and price < sma200
                   else "revisit when the risk signals clear")
        exits = ["No position to manage. Don't buy while the risk signals stand.", f"Then: {trigger}."]

    return {"stance": stance, "bias": bias, "entry_low": low, "entry_high": high, "entry": entry,
            "trigger": trigger, "stop": stop, "stop_basis": stop_basis, "risk_per_share": risk,
            "targets": [{"price": t1[0], "label": t1[1], "r": (t1[0] - entry) / risk if risk > 0 else None},
                        {"price": t2[0], "label": t2[1], "r": (t2[0] - entry) / risk if risk > 0 else None}],
            "rr": rr, "outlook": outlook, "horizon": horizon, "exits": exits, "notes": notes, "price": price}


def size(plan: dict, portfolio_value: float, risk_pct: float, max_position_pct: float) -> dict | None:
    """Shares so that hitting the stop loses risk_pct of the portfolio, capped by the tier's max weight."""
    if not plan or not portfolio_value or plan.get("risk_per_share", 0) <= 0:
        return None
    budget = portfolio_value * risk_pct / 100
    shares = budget / plan["risk_per_share"]
    cap = portfolio_value * max_position_pct / 100 / plan["entry"]
    capped = shares > cap
    shares = min(shares, cap)
    return {"shares": shares, "value": shares * plan["entry"], "risk": shares * plan["risk_per_share"],
            "budget": budget, "capped": capped}


def summary(plan: dict) -> str:
    """One-line plan for cards and notifications."""
    if not plan:
        return ""
    t1 = plan["targets"][0]["price"]
    if plan["stance"] in ("BUY NOW", "BUY ON PULLBACK", "BUY THE BREAKOUT", "ADD"):
        return (f"{plan['stance'].lower()} {plan['entry_low']:.2f}-{plan['entry_high']:.2f} · stop {plan['stop']:.2f} · "
                f"target {t1:.2f} ({plan['rr']:.1f}R)")
    if plan["stance"] == "WAIT FOR CONFIRMATION":
        return f"wait: {plan['trigger']}"
    if plan["stance"] == "NO TRADE":
        return f"no trade: {plan['trigger']}"
    return f"{plan['stance'].lower()} · stop {plan['stop']:.2f} · target {t1:.2f}"
