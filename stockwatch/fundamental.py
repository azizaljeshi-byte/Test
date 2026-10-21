"""Fundamental scoring and signals.

Each metric contributes points to one of four pillars (valuation, growth,
quality, balance sheet). Missing metrics are skipped rather than penalized, and
the score is normalized by the points that were actually available.
"""
from __future__ import annotations

from .signals import OPPORTUNITY, RISK, Signal


def _band(value, bands):
    """bands: list of (threshold, points) checked in order with value <= threshold."""
    for threshold, points in bands:
        if value <= threshold:
            return points
    return bands[-1][1]


def analyze(f: dict, price: float) -> tuple[float, dict, list[Signal]]:
    signals: list[Signal] = []
    got = 0.0
    possible = 0.0
    pillars: dict[str, list[float]] = {"valuation": [], "growth": [], "quality": [], "balance": []}

    def add(pillar: str, points: float, max_points: float = 10):
        nonlocal got, possible
        got += points
        possible += max_points
        pillars[pillar].append(points / max_points)

    g = f.get

    # --- valuation
    pe = g("pe_forward") or g("pe_trailing")
    if pe is not None:
        if pe <= 0:
            add("valuation", 2)
        else:
            add("valuation", _band(pe, [(12, 10), (18, 8), (25, 6), (35, 4), (50, 2), (float("inf"), 0)]))
            if pe > 60:
                signals.append(Signal(RISK, "fundamental", "valuation_stretched",
                                      f"Forward P/E {pe:.0f} - valuation leaves little room for error", 1))
    peg = g("peg")
    if peg is not None and peg > 0:
        add("valuation", _band(peg, [(1.0, 10), (1.5, 7), (2.0, 5), (3.0, 2), (float("inf"), 0)]))
        if peg < 1.0:
            signals.append(Signal(OPPORTUNITY, "fundamental", "peg_cheap",
                                  f"PEG {peg:.2f}: growth available at a reasonable price", 1))

    upside = None
    if g("target_mean_price") and price:
        upside = g("target_mean_price") / price - 1
        add("valuation", _band(upside, [(-0.10, 0), (0.0, 3), (0.10, 5), (0.20, 7), (float("inf"), 10)]))
        if upside >= 0.25:
            signals.append(Signal(OPPORTUNITY, "fundamental", "analyst_upside",
                                  f"Analyst mean target implies {upside:+.0%} upside", 1))
        elif upside <= -0.05:
            signals.append(Signal(RISK, "fundamental", "above_target",
                                  f"Trading {-upside:.0%} above the analyst mean target", 2))

    # --- growth
    rg = g("revenue_growth")
    if rg is not None:
        add("growth", _band(rg, [(-0.05, 0), (0.0, 2), (0.05, 4), (0.10, 6), (0.20, 8), (float("inf"), 10)]))
        if rg < 0:
            signals.append(Signal(RISK, "fundamental", "revenue_declining",
                                  f"Revenue shrinking {-rg:.0%} year over year", 2))
    eg = g("earnings_growth")
    if eg is not None:
        add("growth", _band(eg, [(-0.15, 0), (0.0, 3), (0.10, 6), (0.25, 8), (float("inf"), 10)]))
        if eg < -0.15:
            signals.append(Signal(RISK, "fundamental", "earnings_declining",
                                  f"Earnings down {-eg:.0%} year over year", 2))

    # --- quality
    om = g("operating_margin")
    if om is not None:
        add("quality", _band(om, [(0.0, 0), (0.08, 3), (0.15, 6), (0.25, 8), (float("inf"), 10)]))
        if om < 0:
            signals.append(Signal(RISK, "fundamental", "unprofitable", "Negative operating margin", 2))
    roe = g("roe")
    if roe is not None:
        add("quality", _band(roe, [(0.0, 0), (0.08, 3), (0.15, 6), (0.25, 8), (float("inf"), 10)]))
    fcf = g("free_cash_flow")
    if fcf is not None:
        add("quality", 10 if fcf > 0 else 0)
        if fcf < 0:
            signals.append(Signal(RISK, "fundamental", "negative_fcf", "Burning cash (negative free cash flow)", 2))

    # --- balance sheet
    de = g("debt_to_equity")
    if de is not None:
        add("balance", _band(de, [(0.3, 10), (0.8, 8), (1.5, 5), (2.5, 2), (float("inf"), 0)]))
        if de > 2.5:
            signals.append(Signal(RISK, "fundamental", "high_leverage", f"Debt/equity {de:.1f}x is high", 2))
    cr = g("current_ratio")
    if cr is not None:
        add("balance", _band(cr, [(0.8, 0), (1.0, 3), (1.5, 7), (float("inf"), 10)]))
        if cr < 1.0:
            signals.append(Signal(RISK, "fundamental", "liquidity", f"Current ratio {cr:.2f} below 1", 1))

    rec = g("recommendation_mean")
    if rec is not None:
        # analyst consensus counts half as much as the hard numbers
        add("valuation", _band(rec, [(1.8, 10), (2.3, 7), (2.8, 5), (3.3, 2), (float("inf"), 0)]) / 2, 5)

    score = 100 * got / possible if possible else 50.0
    metrics = {
        "pe": pe, "peg": peg, "analyst_upside": upside, "revenue_growth": rg, "earnings_growth": eg,
        "operating_margin": om, "roe": roe, "debt_to_equity": de, "current_ratio": cr, "free_cash_flow": fcf,
        "coverage": possible,
        **{f"pillar_{k}": round(100 * sum(v) / len(v), 1) if v else None for k, v in pillars.items()},
    }
    return score, metrics, signals
