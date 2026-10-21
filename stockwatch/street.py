"""The street view and the stock's possible paths.

- consensus, price targets, forward estimates and how they're being revised
- options-implied moves (next month, and across the next earnings report)
- 3/6/12-month bear/base/bull ranges with the probability of being higher
- an earnings setup verdict: is the next report likely to work for us or against us?
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .signals import OPPORTUNITY, RISK, Signal

MARKET_RETURN = 0.07   # long-run yearly market return, blended into the base case because targets run optimistic


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def consensus(recs: list[dict]) -> dict | None:
    """Mean rating on a 1 (strong buy) to 5 (strong sell) scale, now and three months ago."""
    def score(r):
        n = sum(r.get(k, 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell"))
        if not n:
            return None, 0
        s = (r.get("strongBuy", 0) * 1 + r.get("buy", 0) * 2 + r.get("hold", 0) * 3 + r.get("sell", 0) * 4
             + r.get("strongSell", 0) * 5) / n
        return s, n
    if not recs:
        return None
    now, n = score(recs[0])
    if now is None:
        return None
    then, _ = score(recs[min(3, len(recs) - 1)])
    label = ("Strong Buy" if now <= 1.8 else "Buy" if now <= 2.4 else "Hold" if now <= 3.0
             else "Underperform" if now <= 3.5 else "Sell")
    r = recs[0]
    return {"score": now, "label": label, "analysts": n, "change_3m": now - then if then else None,
            "buy": r.get("strongBuy", 0) + r.get("buy", 0), "hold": r.get("hold", 0),
            "sell": r.get("sell", 0) + r.get("strongSell", 0)}


def scenarios(price: float, sigma: float, target: float | None) -> list[dict]:
    """Lognormal ranges (16th / 50th / 84th percentile) for 3, 6 and 12 months."""
    if not (_ok(price) and _ok(sigma) and sigma > 0):
        return []
    street = (target / price - 1) if _ok(target) and target > 0 else MARKET_RETURN
    yearly = 0.5 * max(min(street, 0.6), -0.5) + 0.5 * MARKET_RETURN
    out = []
    for months in (3, 6, 12):
        t = months / 12
        base = price * (1 + yearly) ** t
        spread = sigma * math.sqrt(t)
        out.append({"months": months, "bear": base * math.exp(-spread), "base": base, "bull": base * math.exp(spread),
                    "p_up": _phi(math.log(base / price) / spread)})
    return out


def historical_vol(hist: pd.DataFrame) -> float | None:
    r = np.log(hist["Close"]).diff().dropna().iloc[-252:]
    return float(r.std() * math.sqrt(252)) if len(r) > 60 else None


def earnings_setup(days: int | None, earn: dict, revisions: dict, hist: pd.DataFrame, market: pd.DataFrame | None,
                   implied: float | None, valuation: dict) -> dict | None:
    """Score the factors that tend to decide whether a report works for or against holders."""
    if days is None or days < 0:
        return None
    factors = []
    if earn.get("reported"):
        rate = earn["beats"] / earn["reported"]
        if rate >= 0.75:
            factors.append((1, f"beat estimates {earn['beats']} of the last {earn['reported']} times"))
        elif rate <= 0.5:
            factors.append((-1, f"missed or matched in {earn['reported'] - earn['beats']} of the last {earn['reported']}"))
    rev = revisions.get("eps_30d")
    if _ok(rev):
        if rev >= 0.02:
            factors.append((1, f"estimates rose {rev * 100:.0f}% over the past month"))
        elif rev <= -0.02:
            factors.append((-1, f"estimates fell {-rev * 100:.0f}% over the past month"))
    moves = [q["reaction"] for q in earn.get("quarters", []) if _ok(q.get("reaction"))]
    if moves:
        avg = float(np.mean(moves))
        if avg >= 0.02:
            factors.append((1, f"the stock rose on recent report days (average {avg * 100:+.1f}%)"))
        elif avg <= -0.02:
            factors.append((-1, f"the stock fell on recent report days (average {avg * 100:+.1f}%)"))
    if market is not None and len(hist) > 21:
        both = pd.concat([hist["Close"], market["Close"]], axis=1, join="inner").dropna()
        if len(both) > 21:
            run = (both.iloc[-1, 0] / both.iloc[-21, 0]) / (both.iloc[-1, 1] / both.iloc[-21, 1]) - 1
            if run >= 0.10:
                factors.append((-1, f"it ran up {run * 100:.0f}% vs the market this month, so expectations are high"))
            elif run <= -0.10:
                factors.append((1, f"it lagged the market by {-run * 100:.0f}% this month, so expectations are low"))
    pvp = valuation.get("pe_vs_peers")
    if _ok(pvp) and pvp >= 0.5:
        factors.append((-1, "it trades at a premium to peers, which leaves little room for disappointment"))
    score = sum(f[0] for f in factors)
    verdict = "favourable" if score >= 2 else "unfavourable" if score <= -2 else "mixed"
    hist_move = float(np.mean([abs(m) for m in moves])) if moves else None
    note = None
    if _ok(implied) and _ok(hist_move) and hist_move > 0 and implied > 1.5 * hist_move:
        note = (f"Options price a ±{implied * 100:.0f}% move, bigger than its usual ±{hist_move * 100:.0f}%: "
                "the market expects an unusually large reaction.")
    return {"days": days, "verdict": verdict, "score": score, "factors": [f[1] for f in factors],
            "for": [f[1] for f in factors if f[0] > 0], "against": [f[1] for f in factors if f[0] < 0],
            "implied_move": implied, "typical_move": hist_move, "note": note}


def analyze(raw: dict, price: float, hist: pd.DataFrame, market: pd.DataFrame | None, earn: dict,
            valuation: dict, days_to_earnings: int | None, owned: bool) -> tuple[dict, list[Signal]]:
    out: list[Signal] = []
    m: dict = {}

    c = consensus(raw.get("recs") or [])
    m["consensus"] = c
    if c and _ok(c.get("change_3m")):
        if c["change_3m"] <= -0.3:
            out.append(Signal(OPPORTUNITY, "street", "consensus_up",
                              f"Analysts turned more bullish over 3 months (now {c['label']}, {c['buy']} buy / "
                              f"{c['hold']} hold / {c['sell']} sell)", 1))
        elif c["change_3m"] >= 0.3:
            out.append(Signal(RISK, "street", "consensus_down",
                              f"Analysts turned more cautious over 3 months (now {c['label']})", 1))

    tg = raw.get("targets") or {}
    m["targets"] = {k: tg.get(k) for k in ("low", "mean", "median", "high")}
    if _ok(tg.get("median")) and price:
        m["upside_median"] = tg["median"] / price - 1
    if _ok(tg.get("low")) and price:
        m["downside_low"] = tg["low"] / price - 1

    eps, rev = raw.get("eps") or {}, raw.get("revenue") or {}
    m["growth"] = {p: {"eps": (eps.get(p) or {}).get("growth"), "revenue": (rev.get(p) or {}).get("growth"),
                       "eps_avg": (eps.get(p) or {}).get("avg"), "analysts": (eps.get(p) or {}).get("analysts")}
                   for p in ("0q", "+1q", "0y", "+1y") if eps.get(p) or rev.get(p)}
    g0, g1 = (eps.get("0y") or {}).get("growth"), (eps.get("+1y") or {}).get("growth")
    if _ok(g1) and _ok(g0):
        if g1 > g0 and g1 >= 0.15:
            out.append(Signal(OPPORTUNITY, "street", "growth_accelerating",
                              f"Earnings growth expected to accelerate next year ({g0 * 100:+.0f}% -> {g1 * 100:+.0f}%)", 1))
        elif g1 < 0:
            out.append(Signal(RISK, "street", "earnings_expected_down",
                              f"Analysts expect earnings to shrink next year ({g1 * 100:+.0f}%)", 1))

    # estimate revisions: the direction analysts are moving matters more than the level
    trend, revs = raw.get("eps_trend") or {}, raw.get("revisions") or {}
    period = "0y" if trend.get("0y") else next(iter(trend), None)
    revisions = {}
    if period:
        t = trend[period]
        for lag in ("30d", "90d"):
            if _ok(t.get("current")) and _ok(t.get(lag)) and t[lag]:
                revisions[f"eps_{lag}"] = t["current"] / t[lag] - 1
    r0 = revs.get("0y") or next(iter(revs.values()), {}) if revs else {}
    revisions["up30"], revisions["down30"] = (r0 or {}).get("up30"), (r0 or {}).get("down30")
    m["revisions"] = revisions
    r30, up, down = revisions.get("eps_30d"), revisions.get("up30") or 0, revisions.get("down30") or 0
    if (_ok(r30) and r30 >= 0.03) or (up >= 3 and up >= 2 * max(down, 1)):
        out.append(Signal(OPPORTUNITY, "street", "estimates_rising",
                          f"Analysts are raising estimates: {f'EPS estimate {r30 * 100:+.1f}% in 30 days, ' if _ok(r30) else ''}"
                          f"{up} up / {down} down", 2))
    elif (_ok(r30) and r30 <= -0.03) or (down >= 3 and down >= 2 * max(up, 1)):
        out.append(Signal(RISK, "street", "estimates_falling",
                          f"Analysts are cutting estimates: {f'EPS estimate {r30 * 100:+.1f}% in 30 days, ' if _ok(r30) else ''}"
                          f"{up} up / {down} down", 2))

    opts = {o["label"]: o for o in raw.get("options") or []}
    m["options"] = list(opts.values())
    month = opts.get("1 month")
    sigma = (month.get("call_iv") if month else None) or historical_vol(hist)
    m["sigma"], m["sigma_source"] = sigma, "options" if month and month.get("call_iv") else "price history"
    m["implied_move_1m"] = month.get("implied_move") if month else None
    m["scenarios"] = scenarios(price, sigma, tg.get("median") or tg.get("mean"))

    implied_e = (opts.get("earnings") or {}).get("implied_move")
    setup = earnings_setup(days_to_earnings, earn, revisions, hist, market, implied_e, valuation)
    m["earnings_setup"] = setup
    if setup and setup["days"] <= 14:
        if setup["verdict"] == "unfavourable":
            out.append(Signal(RISK, "earnings", "earnings_setup_bad",
                              f"Earnings in {setup['days']} days and the setup looks unfavourable: "
                              + "; ".join(setup["against"][:2]), 2 if owned else 1))
        elif setup["verdict"] == "favourable":
            out.append(Signal(OPPORTUNITY, "earnings", "earnings_setup_good",
                              f"Earnings in {setup['days']} days and the setup looks favourable: "
                              + "; ".join(setup["for"][:2]), 1))
    return m, out
