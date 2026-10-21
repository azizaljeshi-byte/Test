"""Combines technical + fundamental analysis into one verdict per holding."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import fundamental, technical
from .config import Holding, Portfolio
from .data import DataProvider
from .signals import OPPORTUNITY, RISK, Signal

log = logging.getLogger(__name__)


@dataclass
class Evaluation:
    ticker: str
    tier: int
    watchlist: bool
    price: float
    technical_score: float
    fundamental_score: float
    composite: float
    verdict: str
    signals: list[Signal]
    technical: dict
    fundamental: dict
    position: dict = field(default_factory=dict)
    name: str | None = None
    error: str | None = None
    scanned_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    @property
    def opportunities(self) -> list[Signal]:
        return [s for s in self.signals if s.kind == OPPORTUNITY]

    @property
    def risks(self) -> list[Signal]:
        return [s for s in self.signals if s.kind == RISK]


def _confluence(fs: float, tech: dict, tech_signals: list[Signal], tier: int) -> list[Signal]:
    """The 'both at once' rules: a signal only one side sees is weaker than one both agree on."""
    out = []
    trend = tech["trend"]

    # A trailing-stop hit on a high-quality name still above its 200-day is a pullback,
    # not a thesis break: keep the warning but don't treat it as urgent.
    if fs >= 65 and trend == "up":
        for s in tech_signals:
            if s.code == "atr_trailing_stop":
                s.severity = 2
                s.message += " - fundamentals intact, likely a pullback"
    entry_trigger = any(s.kind == OPPORTUNITY and s.severity >= 2 for s in tech_signals) or (
        trend == "up" and tech["rsi"] < 40)
    breakdown = trend == "down" or any(s.kind == RISK and s.severity >= 2 for s in tech_signals)

    if fs >= 65 and entry_trigger:
        out.append(Signal(OPPORTUNITY, "combined", "quality_entry",
                          f"Strong fundamentals ({fs:.0f}) + technical entry trigger: add / buy zone", 3))
    elif fs >= 65 and trend == "down":
        out.append(Signal(RISK, "combined", "value_trap_watch",
                          "Fundamentals look good but price is in a downtrend - wait for the trend to turn", 1))
    if fs < 40 and breakdown:
        out.append(Signal(RISK, "combined", "thesis_breakdown",
                          f"Weak fundamentals ({fs:.0f}) confirmed by technical breakdown: re-check the thesis", 3))
    elif fs < 45 and tier == 1:
        out.append(Signal(RISK, "combined", "core_fundamentals_weak",
                          f"Fundamental score {fs:.0f} is low for a Tier 1 core holding", 2))
    if fs < 40 and trend == "up" and tech["rsi"] > 70:
        out.append(Signal(RISK, "combined", "momentum_without_support",
                          "Price momentum is running ahead of weak fundamentals", 1))
    return out


def _position(h: Holding, price: float, tech: dict, rules) -> tuple[dict, list[Signal]]:
    if h.is_watchlist:
        return {}, []
    out: list[Signal] = []
    value = h.shares * price
    pos = {"shares": h.shares, "value": value, "cost_basis": h.cost_basis}
    if h.cost_basis:
        pnl = price / h.cost_basis - 1
        pos["pnl_pct"] = pnl
        pos["stop_price"] = h.cost_basis * (1 - rules.stop_loss_pct / 100)
        if price <= pos["stop_price"]:
            out.append(Signal(RISK, "position", "stop_loss",
                              f"Down {-pnl:.0%} from cost - hit the Tier {h.tier} stop of -{rules.stop_loss_pct:.0f}%", 3))
        elif pnl <= -rules.stop_loss_pct / 200:
            out.append(Signal(RISK, "position", "stop_loss_near",
                              f"Down {-pnl:.0%} from cost - halfway to the -{rules.stop_loss_pct:.0f}% stop", 2))
    if h.target_price and price >= h.target_price:
        out.append(Signal(RISK, "position", "target_reached",
                          f"Reached target price {h.target_price:.2f} - consider taking profit", 2))
    return pos, out


def _verdict(ev: Evaluation) -> str:
    codes = {s.code for s in ev.signals}
    urgent_risk = any(s.kind == RISK and s.severity >= 3 for s in ev.signals)
    if ev.watchlist:
        if "quality_entry" in codes:
            return "BUY SETUP"
        if urgent_risk or ev.composite < 40:
            return "AVOID"
        return "WATCH"
    if urgent_risk:
        return "RISK - REVIEW"
    if "quality_entry" in codes:
        return "OPPORTUNITY - ADD"
    if "target_reached" in codes or ev.composite < 40:
        return "TRIM / REVIEW"
    if ev.composite >= 65:
        return "STRONG HOLD"
    return "HOLD"


def evaluate(h: Holding, portfolio: Portfolio, provider: DataProvider) -> Evaluation:
    rules = portfolio.rules(h.tier)
    try:
        hist = provider.history(h.ticker)
        ts, tech, tech_sig = technical.analyze(hist, rules.trailing_atr_mult, owned=not h.is_watchlist)
        price = tech["price"]
        try:
            f = provider.fundamentals(h.ticker)
        except Exception as e:  # fundamentals are often flaky; degrade gracefully
            log.warning("fundamentals failed for %s: %s", h.ticker, e)
            f = {}
        fs, fund, fund_sig = fundamental.analyze(f, price)
    except Exception as e:
        log.exception("evaluation failed for %s", h.ticker)
        return Evaluation(h.ticker, h.tier, h.is_watchlist, float("nan"), 0, 0, 0, "ERROR", [], {}, {}, error=str(e))

    composite = rules.fundamental_weight * fs + rules.technical_weight * ts
    pos, pos_sig = _position(h, price, tech, rules)
    signals = tech_sig + fund_sig + _confluence(fs, tech, tech_sig, h.tier) + pos_sig
    signals.sort(key=lambda s: (-s.severity, s.kind))
    ev = Evaluation(h.ticker, h.tier, h.is_watchlist, price, round(ts, 1), round(fs, 1),
                    round(composite, 1), "", signals, tech, fund, pos, name=f.get("name"))
    ev.verdict = _verdict(ev)
    return ev


def scan(portfolio: Portfolio, provider: DataProvider, workers: int = 6) -> list[Evaluation]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        evals = list(pool.map(lambda h: evaluate(h, portfolio, provider), portfolio.holdings))

    # portfolio-level checks need every position's value
    total = sum(e.position.get("value", 0) for e in evals if not e.error)
    for e in evals:
        if e.error or e.watchlist or not total:
            continue
        weight = e.position["value"] / total * 100
        e.position["weight_pct"] = weight
        limit = portfolio.rules(e.tier).max_position_pct
        if weight > limit:
            e.signals.append(Signal(RISK, "position", "concentration",
                                    f"Position is {weight:.1f}% of the portfolio (Tier {e.tier} limit {limit:.0f}%)", 2))
    return evals
