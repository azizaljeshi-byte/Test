"""Rule-based trade plan: entry zone, stop, targets, outlook and exit rules.

Levels come from chart structure (support/resistance, moving averages, 52-week high)
and volatility (ATR); targets also consider fair value and analyst targets. Every
number is derived mechanically, so the plan is consistent and explainable, not a
prediction.
"""
from __future__ import annotations

import math

import pandas as pd

from . import deepdive, status

NEW_ENTRY = {"BUY NOW", "BUY ON PULLBACK", "BUY THE BREAKOUT", "WAIT FOR CONFIRMATION", "ADD"}
MIN_RR = 1.5          # reward-to-risk below this isn't worth a new entry


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


FAR_ABOVE = 0.15        # a trigger more than 15% above the price is shown as steps, not one distant number


def recovery_steps(price: float, sma20, sma50, sma200) -> str | None:
    """'recovery steps: 20-day 352.10 (+6.4%), 50-day 410.00 (+23.9%), 200-day 518.65 (+56.7%)': each moving average
    still above the price, nearest first. None when none of them is above it."""
    steps = sorted((v, name) for name, v in (("20-day", sma20), ("50-day", sma50), ("200-day", sma200))
                   if _ok(v) and v > price)
    if not steps:
        return None
    return "recovery steps: " + ", ".join(f"{name} {v:.2f} ({(v / price - 1) * 100:+.1f}%)" for v, name in steps)


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
        if level / price - 1 > FAR_ABOVE:       # too far to act on as one number: show the steps up to it
            trigger = recovery_steps(price, sma20, sma50, sma200) or trigger
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

    return {"stance": stance, "bias": bias, "sma20": sma20, "entry_low": low, "entry_high": high, "entry": entry,
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


def exit_on_breakdown(plan: dict | None, price_status: dict | None, watchlist: bool) -> dict | None:
    """The plan follows the call: when a confirmed breakdown makes a held stock a SELL (`status.forces_exit`, off
    unless EXIT_ON_BREAKDOWN is set), the plan becomes the exit plan, so the list, the card, Details and Telegram
    never show a sell call over a hold or trim plan. A plan that already says reduce / exit is left alone."""
    if not plan or plan.get("stance") == "REDUCE / EXIT" or not status.forces_exit(price_status, watchlist):
        return plan
    lv, code = price_status["levels"], price_status["code"]
    if code == "breakdown":
        first = f"Exit the trade: closed below support ({lv['support_low']:.2f})."
        second = f"If you keep part of it, sell the rest on a close below the deeper level, {lv['deep_below']:.2f}."
        short = f"exit · closed below support {lv['support_low']:.2f}"
    else:
        first = f"Exit now: closed below the deeper level ({lv['deep_below']:.2f})."
        second = f"The deeper level ({lv['deep_below']:.2f}) is already broken, so there is no lower line to wait for."
        short = f"exit now · below the deeper level {lv['deep_below']:.2f}"
    return {**plan, "stance": "REDUCE / EXIT", "bias": "bearish", "status_exit": short,
            "exits": [first, second, f"Rebuild only after a close back above the support zone ({lv['support_high']:.2f}) "
                                     "with the risk signals clear."],
            "notes": list(plan.get("notes", [])) + ["Automatic support levels, not reviewed: check the chart."],
            "outlook": f"Support broke: {price_status['why']} That is a risk-control exit whatever the longer-term "
                       f"picture says. Rebuild only once price recovers above {lv['support_high']:.2f}."}


def hold_off_buying(plan: dict | None, price_status: dict | None, watchlist: bool, technical: dict | None = None) -> dict | None:
    """The plan follows the call: a confirmed breakdown, or a failed entry gate (`status.entry_blockers`), under a buy or add
    plan turns it into hold (wait, on a watchlist name), so no screen shows 'buy more' next to bad evidence. Entry, stop
    and targets stay for reference."""
    if not plan or plan.get("stance") not in status.BUY_STANCES or not status.blocks_buy(price_status, technical):
        return plan
    lv = price_status.get("levels") or {}
    stance = "WAIT FOR CONFIRMATION" if watchlist else "HOLD"
    if price_status.get("code") not in status.EXIT_CODES:
        why = "; ".join(status.entry_blockers(price_status, technical))
        return {**plan, "stance": stance, "status_exit": f"don't buy yet · {why}",
                "trigger": "every entry check agrees: the chart holds, momentum is not falling and no other source says sell",
                "notes": list(plan.get("notes", [])) + [f"Buy held back: {why}."]}
    low = lv.get("support_low")
    short = f"don't add yet · closed below support {low:.2f}" if low else "don't add yet · support broke"
    trigger = f"a close back above the support zone ({lv['support_high']:.2f}) with the risk signals clear" \
        if lv.get("support_high") else "price recovers above support"
    return {**plan, "stance": stance, "status_exit": short, "trigger": trigger,
            "notes": list(plan.get("notes", [])) + [
                "Support broke on a completed close, so adding is on hold. Automatic levels, not reviewed: check the chart."]}


def summary(plan: dict) -> str:
    """One-line plan for cards and notifications."""
    if not plan:
        return ""
    if plan.get("status_exit"):
        return plan["status_exit"]
    t1 = plan["targets"][0]["price"]
    if plan["stance"] in ("BUY NOW", "BUY ON PULLBACK", "BUY THE BREAKOUT", "ADD"):
        return (f"{plan['stance'].lower()} {plan['entry_low']:.2f}-{plan['entry_high']:.2f} · stop {plan['stop']:.2f} · "
                f"target {t1:.2f} ({plan['rr']:.1f}R)")
    if plan["stance"] == "WAIT FOR CONFIRMATION":
        return f"wait: {plan['trigger']}"
    if plan["stance"] == "NO TRADE":
        return f"no trade: {plan['trigger']}"
    if plan["stance"] == "REDUCE / EXIT":
        return f"reduce / exit · if keeping some, sell below {plan['stop']:.2f}"
    if plan["stance"] == "TRIM / PROTECT":
        return f"trim / protect · keep the rest above {plan['stop']:.2f} · target {t1:.2f}"
    return f"{plan['stance'].lower()} · stop {plan['stop']:.2f} · target {t1:.2f}"


ENTRY_STANCES = {"BUY NOW", "BUY THE BREAKOUT", "BUY ON PULLBACK"}


def refine(plan: dict, history: dict | None, street: dict | None, events: dict | None, tier: int, held: bool,
           tech: dict, fs: float) -> dict:
    """Tighten the plan with what happened in similar past setups, the earnings setup and the
    forward view, so it weighs where the company is heading and not only today's chart."""
    plan = {**plan, "notes": list(plan.get("notes", [])), "exits": list(plan["exits"]), "history": history}
    st = street or {}
    t1 = plan["targets"][0]["price"]

    # ---- older scenarios: hit rate and a realistic timeframe
    default_days = 126 if tier == 1 else 30
    days = None
    if history and history["n"] >= 6 and history.get("median_days_to_target"):
        days = history["median_days_to_target"]
        weeks = max(round(days / 5), 1)
        plan["timeframe"] = (f"Target 1 was reached in a median of {days:.0f} trading days (about {weeks} "
                             f"week{'s' if weeks != 1 else ''}) in {history['n']} similar past setups")
    else:
        plan["timeframe"] = f"No reliable history; plan on up to {default_days} trading days"
    deadline = int(min(max(round((days or default_days) * 1.5), 10), default_days * 2))
    plan["time_stop_days"] = deadline
    plan["exits"] = [e for e in plan["exits"] if not e.startswith("Time stop")]
    if plan["stance"] not in ("REDUCE / EXIT", "NO TRADE"):
        plan["exits"].append(f"Time stop: if {t1:.2f} isn't reached within about {deadline} trading days "
                             f"(~{deadline / 5:.0f} weeks), reassess rather than wait.")
    if history and history["n"] >= 10:
        win = history["win_rate"]
        if plan["stance"] in ENTRY_STANCES and win < 0.40:
            plan["notes"].append(f"History is against this entry: only {win:.0%} of {history['n']} similar setups "
                                 f"reached the target before the stop. Waiting for confirmation instead.")
            plan["stance"] = "WAIT FOR CONFIRMATION"
            plan["trigger"] = plan.get("trigger") or f"a close above {plan['entry_high'] + 0.5 * tech['atr']:.2f}"
        elif plan["stance"] in ENTRY_STANCES and win >= 0.60:
            plan["notes"].append(f"History supports it: {win:.0%} of {history['n']} similar setups reached the target first.")
        elif held and history["loss_rate"] >= 0.55:
            plan["notes"].append(f"In {history['n']} similar past setups the stop was hit first {history['loss_rate']:.0%} "
                                 f"of the time; keep the stop tight.")

    # ---- earnings: will the report likely work for or against us?
    setup = st.get("earnings_setup")
    if setup and setup["days"] <= 7:
        if setup["verdict"] == "unfavourable":
            if plan["stance"] in ENTRY_STANCES or plan["stance"] == "ADD":
                plan["stance"] = "WAIT FOR CONFIRMATION"
                plan["trigger"] = f"the earnings report in {setup['days']} days; reassess the day after"
                plan["notes"].append("Earnings setup is unfavourable, so no new buying before the report.")
            elif held:
                plan["notes"].append("Earnings setup is unfavourable: " + ("consider trimming before the report."
                                     if tier == 2 else "hold the core position but don't add before the report."))
        elif setup["verdict"] == "favourable" and (plan["stance"] in ENTRY_STANCES or held):
            plan["notes"].append("Earnings setup is favourable; a half position before the report is reasonable, "
                                 "the rest after it confirms.")

    # ---- forward view: street consensus, estimate direction and the 3-12 month ranges
    forward, score = [], 0.0
    score += {"up": 1, "down": -1}.get(tech.get("trend"), 0)
    score += 1 if fs >= 60 else -1 if fs < 45 else 0
    c = st.get("consensus")
    if c:
        med = (st.get("targets") or {}).get("median")
        forward.append(f"The street rates it {c['label']} ({c['buy']} buy, {c['hold']} hold, {c['sell']} sell)"
                       + (f" with a median target of {med:.2f} ({st['upside_median'] * 100:+.0f}%)."
                          if _ok(med) and _ok(st.get("upside_median")) else "."))
        score += 0.5 if c["score"] <= 2.4 else -1 if c["score"] > 3.0 else 0
    g = (st.get("growth") or {})
    g0, g1 = (g.get("0y") or {}).get("eps"), (g.get("+1y") or {}).get("eps")
    if _ok(g0) or _ok(g1):
        forward.append("Expected EPS growth: " + ", ".join(x for x in (
            f"this year {g0 * 100:+.0f}%" if _ok(g0) else None, f"next year {g1 * 100:+.0f}%" if _ok(g1) else None) if x) + ".")
        score += 0.5 if _ok(g1) and g1 > 0.10 else -0.5 if _ok(g1) and g1 < 0 else 0
    r30 = (st.get("revisions") or {}).get("eps_30d")
    if _ok(r30) and abs(r30) >= 0.01:
        forward.append(f"Estimates moved {r30 * 100:+.1f}% in the last 30 days.")
        score += 1 if r30 >= 0.03 else -1 if r30 <= -0.03 else 0
    year = next((x for x in st.get("scenarios") or [] if x["months"] == 12), None)
    if year:
        forward.append(f"12-month range: bear {year['bear']:.2f}, base {year['base']:.2f}, bull {year['bull']:.2f}; "
                       f"about {year['p_up']:.0%} chance of being higher.")
        score += 0.5 if year["p_up"] >= 0.6 else -0.5 if year["p_up"] < 0.45 else 0
    plan["forward"] = forward
    plan["forward_score"] = score
    plan["bias"] = "bullish" if score >= 1.5 else "bearish" if score <= -1.5 else "neutral"
    if plan["stance"] in ENTRY_STANCES and c and c["score"] > 3.0 and _ok(r30) and r30 < 0:
        plan["notes"].append("The street is negative and cutting estimates; the chart setup alone isn't enough.")
        plan["stance"] = "WAIT FOR CONFIRMATION"
        plan["trigger"] = plan.get("trigger") or "estimate revisions turning up"
    return plan


SHORT_TERM_RISKS = {"atr_trailing_stop"}   # momentum breaks, as opposed to thesis or cost-basis problems


def reconcile(plan: dict, signals: list) -> dict:
    """One answer when the short-term risk rules and the bigger picture disagree.

    A trailing-stop hit on a stock whose trend and fundamentals are still positive means trim
    and protect, not exit; a serious problem (thesis breakdown, cost-basis stop) stays an exit
    but the plan says plainly that risk control is overriding a positive longer-term view."""
    if not plan or plan.get("stance") != "REDUCE / EXIT" or plan.get("bias") != "bullish":
        return plan
    urgent = [s for s in signals if s.kind == "risk" and s.severity >= 3]
    reasons = "; ".join(s.message for s in urgent[:2]) or "the risk signals"
    t1, t2 = (t["price"] for t in plan["targets"])
    plan = {**plan, "bias": "mixed", "exits": list(plan["exits"]), "notes": list(plan.get("notes", []))}
    if urgent and all(s.code in SHORT_TERM_RISKS for s in urgent):
        plan["stance"] = "TRIM / PROTECT"
        plan["outlook"] = (f"Short term and long term disagree. Short-term momentum broke ({reasons}), but the bigger "
                           f"picture is still positive: trend and fundamentals agree, with a base case back toward "
                           f"{t1:.2f} and then {t2:.2f}. So protect, don't abandon: take some off and keep the rest "
                           f"under a firm stop at {plan['stop']:.2f}.")
        plan["exits"] = [
            "Trim a third to a half now: short-term momentum has broken.",
            f"Keep the rest with a stop at {plan['stop']:.2f} (on a daily close).",
            f"Add back on a close above the 20-day average ({plan['sma20']:.2f}), which shows the pullback is over.",
            f"Take more off near {t1:.2f}, and the rest near {t2:.2f}.",
        ] + [e for e in plan["exits"] if e.startswith("Time stop")]
    else:
        plan["outlook"] = (f"The longer-term picture looks positive, but {reasons}. That's a risk-control exit: "
                           f"protecting capital comes before the upside case. Rebuild only once these clear.")
    return plan
