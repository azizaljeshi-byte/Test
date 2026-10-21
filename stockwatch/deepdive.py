"""Deeper research: earnings track record, smart money, valuation in context, price levels.

Each analyzer takes already-fetched data and returns (metrics, signals); missing
inputs just produce fewer metrics.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .signals import OPPORTUNITY, RISK, Signal


def _median(values):
    values = [v for v in values if v is not None and not np.isnan(v)]
    return statistics.median(values) if values else None


# --------------------------------------------------------------------- earnings

def _reaction(hist: pd.DataFrame, quarter_end) -> tuple[str | None, float | None]:
    """Earnings day isn't in the free data, so use the heaviest-volume day 10-80 days
    after the quarter closed - the report day almost always is."""
    start = pd.Timestamp(quarter_end) + pd.Timedelta(days=10)
    window = hist.loc[start:start + pd.Timedelta(days=70)]
    if len(window) < 5:
        return None, None
    day = window["Volume"].idxmax()
    i = hist.index.get_loc(day)
    if i == 0:
        return None, None
    return day.date().isoformat(), float(hist["Close"].iloc[i] / hist["Close"].iloc[i - 1] - 1)


def earnings_track(research: dict, hist: pd.DataFrame) -> tuple[dict, list[Signal]]:
    out: list[Signal] = []
    rows = []
    for e in research.get("earnings") or []:
        day, move = _reaction(hist, e["quarter"])
        rows.append({**e, "quarter": str(e["quarter"]), "report_day": day, "reaction": move})

    beats = [r["eps_actual"] > r["eps_estimate"] for r in rows
             if r.get("eps_actual") is not None and r.get("eps_estimate") is not None]
    streak = 0
    for b in beats:  # newest first
        if not b:
            break
        streak += 1
    moves = [abs(r["reaction"]) for r in rows if r["reaction"] is not None]
    m = {"quarters": rows, "beat_streak": streak, "beats": sum(beats), "reported": len(beats),
         "avg_move": float(np.mean(moves)) if moves else None}

    if streak >= 4:
        out.append(Signal(OPPORTUNITY, "earnings", "beat_streak", f"Beat EPS estimates {streak} quarters in a row", 1))
    if len(beats) >= 2 and not beats[0] and not beats[1]:
        out.append(Signal(RISK, "earnings", "missed_twice", "Missed EPS estimates the last 2 quarters", 2))

    q = [r for r in research.get("quarterly") or [] if r.get("revenue")]
    m["revenue_q"] = [{"period": str(r["period"]), "revenue": r["revenue"],
                       "op_margin": r["operating_income"] / r["revenue"] if r.get("operating_income") is not None else None,
                       "gross_margin": r["gross_profit"] / r["revenue"] if r.get("gross_profit") is not None else None}
                      for r in q]
    if len(q) >= 5:
        m["revenue_yoy_latest"] = q[0]["revenue"] / q[4]["revenue"] - 1
    if len(q) >= 4:
        seq = [q[i]["revenue"] / q[i + 1]["revenue"] - 1 for i in range(len(q) - 1)]
        m["revenue_qoq"] = seq
        if all(x < 0 for x in seq[:3]):
            out.append(Signal(RISK, "earnings", "revenue_falling", "Revenue fell 3 quarters in a row", 2))
        elif len(seq) >= 4 and all(x > 0 for x in seq[:4]):
            out.append(Signal(OPPORTUNITY, "earnings", "revenue_rising", "Revenue grew 4 quarters in a row", 1))
        margins = [x["op_margin"] for x in m["revenue_q"]]
        if margins[0] is not None and margins[min(4, len(margins) - 1)] is not None and len(margins) >= 4:
            delta = margins[0] - margins[min(4, len(margins) - 1)]
            m["margin_change"] = delta
            if delta >= 0.05:
                out.append(Signal(OPPORTUNITY, "earnings", "margin_expanding",
                                  f"Operating margin up {delta * 100:.0f} pts over the year", 1))
            elif delta <= -0.05:
                out.append(Signal(RISK, "earnings", "margin_shrinking",
                                  f"Operating margin down {-delta * 100:.0f} pts over the year", 1))
    return m, out


# --------------------------------------------------------------------- smart money

def _insider_kind(text: str) -> str | None:
    t = text.lower()
    if t.startswith("purchase") or " purchase " in t:
        return "buy"
    if t.startswith("sale") or " sale " in t:
        return "sell"
    return None  # awards, gifts, option exercises aren't conviction signals


def smart_money(f: dict, research: dict) -> tuple[dict, list[Signal]]:
    out: list[Signal] = []
    cutoff = datetime.now() - timedelta(days=90)
    buys, sells, buyers, sellers, recent = 0.0, 0.0, set(), set(), []
    txs = sorted(research.get("insiders") or [], key=lambda tx: tx.get("date") or datetime.min, reverse=True)
    for tx in txs:
        when = tx["date"].replace(tzinfo=None) if tx.get("date") else None
        kind = _insider_kind(tx.get("text") or "")
        recent.append({**tx, "date": when.date().isoformat() if when else None, "kind": kind})
        if not when or when < cutoff or not kind:
            continue
        if kind == "buy":
            buys += tx.get("value") or 0
            buyers.add(tx.get("insider"))
        else:
            sells += tx.get("value") or 0
            sellers.add(tx.get("insider"))

    sp, prior, now_short = f.get("short_pct_float"), f.get("shares_short_prior"), f.get("shares_short")
    m = {"insider_buy_90d": buys, "insider_sell_90d": sells, "buyers_90d": len(buyers),
         "sellers_90d": len(sellers), "insider_tx": recent[:10], "short_pct_float": sp,
         "days_to_cover": f.get("short_ratio"), "insider_pct": f.get("insider_pct"),
         "institution_pct": f.get("institution_pct"),
         "short_change": now_short / prior - 1 if now_short and prior else None}

    if len(buyers) >= 2 or buys >= 250_000:
        out.append(Signal(OPPORTUNITY, "smart money", "insider_buying",
                          f"Insiders bought ${buys:,.0f} in 90 days ({len(buyers)} buyer{'s' if len(buyers) != 1 else ''})", 2))
    elif buyers:
        out.append(Signal(OPPORTUNITY, "smart money", "insider_buying",
                          f"Insider purchase: ${buys:,.0f} in the last 90 days", 1))
    mcap = f.get("market_cap")
    if (len(sellers) >= 3 and not buyers) or (mcap and sells >= 0.01 * mcap):
        out.append(Signal(RISK, "smart money", "insider_selling",
                          f"{len(sellers)} insiders sold ${sells:,.0f} in 90 days with no buying", 1))

    if sp is not None:
        dtc = f"{f['short_ratio']:.1f} days to cover" if f.get("short_ratio") else "days to cover n/a"
        if sp >= 0.20:
            out.append(Signal(RISK, "smart money", "heavily_shorted",
                              f"Heavily shorted: {sp:.0%} of float ({dtc}) - violent moves both ways", 2))
        elif sp >= 0.10:
            out.append(Signal(RISK, "smart money", "shorted", f"Elevated short interest: {sp:.0%} of float ({dtc})", 1))
        ch = m["short_change"]
        if ch is not None and sp >= 0.05:
            if ch >= 0.30:
                out.append(Signal(RISK, "smart money", "shorts_adding", f"Short interest up {ch:.0%} vs last month", 1))
            elif ch <= -0.30:
                out.append(Signal(OPPORTUNITY, "smart money", "shorts_covering", f"Short interest down {-ch:.0%} vs last month", 1))
    return m, out


# --------------------------------------------------------------------- valuation

def _pe_history(research: dict, hist: pd.DataFrame) -> list[dict]:
    rows = []
    for a in research.get("annual") or []:
        eps = a.get("eps")
        if not eps or eps <= 0:
            continue
        upto = hist.loc[:pd.Timestamp(a["period"])]
        if upto.empty:
            continue
        price = float(upto["Close"].iloc[-1])
        rows.append({"year": pd.Timestamp(a["period"]).year, "pe": price / eps, "eps": eps})
    return rows


def levels(hist: pd.DataFrame, price: float) -> dict:
    """Nearest support/resistance from swing highs and lows over the last year."""
    h = hist.iloc[-260:]
    k = 5
    highs = h["High"][(h["High"] == h["High"].rolling(2 * k + 1, center=True).max())].tolist()
    lows = h["Low"][(h["Low"] == h["Low"].rolling(2 * k + 1, center=True).min())].tolist()
    pivots = sorted(highs + lows)
    zones: list[list[float]] = []
    for p in pivots:  # cluster pivots within 2% of each other into zones
        if zones and p <= zones[-1][0] * 1.02:
            zones[-1].append(p)
        else:
            zones.append([p])
    zone_levels = [(float(np.mean(z)), len(z)) for z in zones]
    below = [z for z in zone_levels if z[0] < price * 0.995]
    above = [z for z in zone_levels if z[0] > price * 1.005]
    support = max(below, key=lambda z: z[0]) if below else None
    resistance = min(above, key=lambda z: z[0]) if above else None
    return {"support": support[0] if support else None, "support_touches": support[1] if support else 0,
            "resistance": resistance[0] if resistance else None,
            "resistance_touches": resistance[1] if resistance else 0}


def valuation_context(f: dict, research: dict, hist: pd.DataFrame, peers: dict[str, dict],
                      price: float) -> tuple[dict, list[Signal]]:
    out: list[Signal] = []
    pe_now = f.get("pe_trailing")
    history = _pe_history(research, hist)
    pe_med = _median([r["pe"] for r in history])
    # A 5x gap from today's P/E almost always means a split the EPS history doesn't reflect.
    if pe_med and pe_now and pe_now > 0 and not (0.2 <= pe_med / pe_now <= 5):
        history, pe_med = [], None
    m: dict = {"pe_history": history, "pe_hist_median": pe_med, "pe_now": pe_now,
               "pe_vs_history": pe_now / pe_med - 1 if pe_now and pe_med and pe_now > 0 else None}

    peer_rows = [{"ticker": t, "pe": p.get("pe_forward"), "ps": p.get("price_to_sales"),
                  "growth": p.get("revenue_growth"), "margin": p.get("operating_margin"),
                  "market_cap": p.get("market_cap")} for t, p in peers.items() if p]
    m["peers"] = peer_rows
    m["self"] = {"pe": f.get("pe_forward"), "ps": f.get("price_to_sales"), "growth": f.get("revenue_growth"),
                 "margin": f.get("operating_margin"), "market_cap": f.get("market_cap")}
    m["peer_median_pe"] = peer_pe = _median([r["pe"] for r in peer_rows if r["pe"] and r["pe"] > 0])
    m["peer_median_ps"] = _median([r["ps"] for r in peer_rows if r["ps"]])
    m["peer_median_growth"] = peer_growth = _median([r["growth"] for r in peer_rows if r["growth"] is not None])
    fwd = f.get("pe_forward")
    m["pe_vs_peers"] = fwd / peer_pe - 1 if fwd and fwd > 0 and peer_pe else None

    if m["pe_vs_history"] is not None and len(history) >= 2:
        if m["pe_vs_history"] <= -0.25:
            out.append(Signal(OPPORTUNITY, "valuation", "cheap_vs_history",
                              f"P/E {pe_now:.0f} vs its {len(history)}-yr median {pe_med:.0f}: cheaper than its own history", 1))
        elif m["pe_vs_history"] >= 0.40:
            out.append(Signal(RISK, "valuation", "rich_vs_history",
                              f"P/E {pe_now:.0f} vs its {len(history)}-yr median {pe_med:.0f}: pricier than its own history", 1))
    if m["pe_vs_peers"] is not None:
        growth = f.get("revenue_growth")
        if m["pe_vs_peers"] <= -0.30 and (peer_growth is None or (growth or 0) >= peer_growth):
            out.append(Signal(OPPORTUNITY, "valuation", "cheap_vs_peers",
                              f"Forward P/E {fwd:.0f} vs peer median {peer_pe:.0f} with growth at least as good", 1))
        elif m["pe_vs_peers"] >= 0.50:
            out.append(Signal(RISK, "valuation", "rich_vs_peers",
                              f"Forward P/E {fwd:.0f} vs peer median {peer_pe:.0f} - priced for more than peers", 1))

    # fair value: each method gives (low, mid, high); the range spans them
    methods = {}
    if f.get("target_mean_price"):
        methods["analysts"] = (f.get("target_low_price") or f["target_mean_price"], f["target_mean_price"],
                               f.get("target_high_price") or f["target_mean_price"])
    eps_f = f.get("eps_forward")
    if eps_f and eps_f > 0 and pe_med:
        mid = eps_f * pe_med
        methods["own history"] = (mid * 0.85, mid, mid * 1.15)
    if eps_f and eps_f > 0 and peer_pe:
        mid = eps_f * peer_pe
        methods["peer multiple"] = (mid * 0.85, mid, mid * 1.15)
    # drop methods that land absurdly far from the price (bad inputs, not insight)
    methods = {k: v for k, v in methods.items() if 1 / 3 <= v[1] / price <= 3}
    if methods:
        mids = [v[1] for v in methods.values()]
        # with several methods, the spread between their central estimates is the range;
        # the extremes (e.g. the single most bullish analyst) would make it meaninglessly wide
        low, high = (min(mids), max(mids)) if len(mids) >= 2 else (next(iter(methods.values()))[0],
                                                                    next(iter(methods.values()))[2])
        fv = {"low": low, "mid": float(np.median(mids)), "high": high,
              "methods": {k: {"low": v[0], "mid": v[1], "high": v[2]} for k, v in methods.items()}}
        fv["upside"] = fv["mid"] / price - 1
        m["fair_value"] = fv
        if len(methods) >= 2 and price < fv["mid"] * 0.8:
            out.append(Signal(OPPORTUNITY, "valuation", "below_fair_value",
                              f"{-(price / fv['mid'] - 1):.0%} below estimated fair value ({fv['mid']:.2f})", 1))
        elif len(methods) >= 2 and price > fv["high"]:
            out.append(Signal(RISK, "valuation", "above_fair_value",
                              f"Above the top of the fair-value range ({fv['high']:.2f})", 1))

    m["levels"] = levels(hist, price)
    return m, out
