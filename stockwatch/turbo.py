"""Turbo: a fast buy / wait / pass decision on a ticker you just spotted, with today's momentum.

It reuses the full engine (watchlist mode), then looks at how the stock is trading today so a
stock that's already run hard gets "wait for a pullback" instead of a chase.
"""
from __future__ import annotations

import math
from datetime import datetime

import pandas as pd

from .data import NY, us_session

CHASE_DAY_MOVE = 0.05      # up this much today ...
CHASE_EXTENSION_ATR = 2.0  # ... and this many ATRs above the 20-day average: don't chase


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def momentum(intraday: pd.DataFrame | None, hist: pd.DataFrame, atr: float, prev_close: float | None) -> dict:
    """Today's move, VWAP, relative volume and how stretched the price is."""
    out: dict = {}
    close = hist["Close"]
    sma20 = float(close.rolling(20).mean().iloc[-1])
    avg_vol = float(hist["Volume"].iloc[-21:-1].mean()) if len(hist) > 21 else None
    if intraday is not None and not intraday.empty:
        bars = intraday.dropna(subset=["Close"])
        idx = bars.index if bars.index.tz is not None else bars.index.tz_localize("UTC")
        ny = idx.tz_convert(NY)
        today = ny[-1].date()
        today_bars = bars[[d == today for d in ny.date]]
        sessions = [us_session(ts.to_pydatetime()) for ts in idx[[d == today for d in ny.date]]]
        regular = today_bars[[s == "REGULAR" for s in sessions]]
        price = float(bars["Close"].iloc[-1])
        out.update(price=price, session=us_session(), as_of=idx[-1].to_pydatetime())
        if not regular.empty and regular["Volume"].sum() > 0:
            vwap = float((regular["Close"] * regular["Volume"]).sum() / regular["Volume"].sum())
            out.update(vwap=vwap, vs_vwap=price / vwap - 1, day_high=float(regular["High"].max()),
                       day_low=float(regular["Low"].min()), volume=float(regular["Volume"].sum()))
            if avg_vol:
                start = ny[-1].replace(hour=9, minute=30, second=0, microsecond=0)
                elapsed = min(max((ny[-1] - start).total_seconds() / (390 * 60), 0.05), 1.0)
                out["rel_volume"] = out["volume"] / (avg_vol * elapsed)
    else:
        price = float(close.iloc[-1])
        out["price"] = price
    if prev_close:
        out["day_change"] = out["price"] / prev_close - 1
    if atr:
        out["extension_atr"] = (out["price"] - sma20) / atr
    out["sma20"] = sma20
    return out


def decide(ev, mom: dict) -> dict:
    """One decision with a confidence, a plan line and the reasons on both sides."""
    plan = ev.plan or {}
    stance = plan.get("stance", "NO TRADE")
    day, ext = mom.get("day_change"), mom.get("extension_atr")
    chasing = _ok(day) and _ok(ext) and day >= CHASE_DAY_MOVE and ext >= CHASE_EXTENSION_ATR
    notes = []

    price, atr = mom.get("price"), (ev.technical or {}).get("atr") or 0
    # the plan's levels come from daily bars; a mover can already be far from them right now
    ran_past = _ok(price) and plan.get("entry_high") and price > plan["entry_high"] + 0.5 * atr
    broke_stop = _ok(price) and plan.get("stop") and price < plan["stop"]

    if stance in ("NO TRADE",) or ev.verdict in ("AVOID", "RISK - REVIEW") or broke_stop:
        decision = "PASS"
        line = (f"already below the stop level ({plan['stop']:.2f})" if broke_stop
                else plan.get("trigger") or "the risk signals outweigh the setup")
    elif stance in ("BUY NOW", "BUY THE BREAKOUT") and ran_past and not chasing:
        decision = "WAIT FOR PULLBACK"
        notes.append(f"At {price:.2f} it's already above the entry zone ({plan['entry_low']:.2f}-"
                     f"{plan['entry_high']:.2f}); buying here worsens the reward-to-risk.")
        line = f"buy zone {plan['entry_low']:.2f}-{plan['entry_high']:.2f} · stop {plan['stop']:.2f}"
    elif stance in ("BUY NOW", "BUY THE BREAKOUT") and not chasing:
        decision = "BUY"
        line = (f"entry {plan['entry_low']:.2f}-{plan['entry_high']:.2f} · stop {plan['stop']:.2f} · "
                f"target {plan['targets'][0]['price']:.2f} ({plan['rr']:.1f}R)")
    elif stance == "BUY ON PULLBACK" or chasing:
        decision = "WAIT FOR PULLBACK"
        zone = (plan.get("entry_low"), plan.get("entry_high"))
        if chasing:
            notes.append(f"It's up {day * 100:.1f}% today and {ext:.1f} ATRs above its 20-day average: "
                         "chasing here risks buying the top of the move.")
            zone = (mom["sma20"] + 0.5 * ev.technical["atr"], mom["sma20"] + 1.0 * ev.technical["atr"]) \
                if stance != "BUY ON PULLBACK" else zone
        if all(_ok(z) for z in zone):
            stop = plan.get("stop")
            if not _ok(stop) or stop > zone[0] - 0.5 * atr:   # the zone moved; the stop must sit below it
                stop = zone[0] - 2 * atr
            line = f"buy zone {zone[0]:.2f}-{zone[1]:.2f} · stop {stop:.2f}"
        else:
            line = "wait for a pullback toward the 20-day average"
    else:
        decision = "WAIT FOR TRIGGER"
        line = f"buy on {plan['trigger']}" if plan.get("trigger") else "wait for the setup to confirm"

    # confidence: agreement between the score, history and the earnings setup
    points = 0
    points += 1 if ev.composite >= 65 else -1 if ev.composite < 45 else 0
    hist = plan.get("history") or {}
    if hist.get("n", 0) >= 10:
        points += 1 if hist["win_rate"] >= 0.55 else -1 if hist["win_rate"] < 0.40 else 0
    setup = ((ev.research or {}).get("street") or {}).get("earnings_setup")
    if setup and setup["days"] <= 7:
        points -= 1
        notes.append(f"Earnings in {setup['days']} days ({setup['verdict']} setup): size down or wait for the report.")
    rvol = mom.get("rel_volume")
    if _ok(rvol) and rvol >= 1.5 and _ok(day):
        points += 1 if day > 0 and decision != "PASS" else 0
        notes.append(f"Volume is running {rvol:.1f}x normal for this time of day.")
    if _ok(mom.get("vs_vwap")):
        notes.append(f"{'Above' if mom['vs_vwap'] >= 0 else 'Below'} today's VWAP ({mom['vwap']:.2f}) by "
                     f"{abs(mom['vs_vwap']) * 100:.1f}%: {'buyers' if mom['vs_vwap'] >= 0 else 'sellers'} in control today.")
    confidence = "High" if points >= 2 else "Low" if points <= -1 else "Medium"
    if decision == "PASS":
        confidence = "High" if ev.composite < 40 else "Medium"

    pros = [s.message for s in ev.signals if s.kind == "opportunity"][:3]
    cons = [s.message for s in ev.signals if s.kind == "risk" and s.severity >= 2][:3]
    return {"ticker": ev.ticker, "name": ev.name, "decision": decision, "confidence": confidence, "line": line,
            "verdict": ev.verdict, "composite": ev.composite, "fundamental": ev.fundamental_score,
            "technical": ev.technical_score, "pros": pros, "cons": cons, "notes": notes, "momentum": mom,
            "chasing": chasing, "decided_at": datetime.now().astimezone().isoformat(timespec="seconds")}


def run(ticker: str, portfolio, provider, deep: bool):
    """Evaluate a ticker that isn't in the list. deep=False skips analysts/SEC/research for speed."""
    from .config import Holding
    from .data import _bar_summary
    from .engine import evaluate

    ev = evaluate(Holding(ticker.upper(), 2, 0), portfolio, provider, light=not deep)
    if ev.error:
        raise ValueError(ev.error)
    hist = provider.history(ev.ticker)
    try:
        intraday = provider.intraday(ev.ticker)
        summary = _bar_summary(intraday)
        live = us_session() == "REGULAR" and summary["last_session"] == "REGULAR"
        prev = summary["prev_regular"] if live else summary["last_regular"]
    except Exception:
        intraday, prev = None, None
    if not prev:   # pre-market: nothing has traded in today's regular session yet, so compare with the last close
        prev = float(hist["Close"].iloc[-1]) if us_session() == "PRE" else float(hist["Close"].iloc[-2])
    mom = momentum(intraday, hist, ev.technical.get("atr"), prev)
    return ev, decide(ev, mom)
