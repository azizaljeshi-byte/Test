"""Combines technical + fundamental analysis into one verdict per holding."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import catalysts, deepdive, fundamental, relative, sec, technical
from .config import Holding, Portfolio
from .data import SECTOR_ETFS, DataProvider
from .signals import OPPORTUNITY, RISK, Signal

log = logging.getLogger(__name__)

PROFILE_KEYS = ("name", "sector", "industry", "summary", "website", "employees", "country", "market_cap")


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
    events: dict = field(default_factory=dict)
    research: dict = field(default_factory=dict)
    profile: dict = field(default_factory=dict)
    quote: dict = field(default_factory=dict)
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


SHIFT_BARS = 5        # compare with the picture one trading week ago
SHIFT_POINTS = 20     # technical-score change that counts as a regime shift


def _technical_shift(hist, ts: float, fs: float, atr_mult: float, owned: bool) -> list[Signal]:
    """Flag a big swing in the technical picture on its own: fundamentals move quarterly,
    price action daily, so a breakdown or turn shouldn't wait for both to agree."""
    if len(hist) < 260:
        return []
    before, _, _ = technical.analyze(hist.iloc[:-SHIFT_BARS], atr_mult, owned)
    delta = ts - before
    if abs(delta) < SHIFT_POINTS:
        return []
    fund = (f"fundamentals unchanged and still solid ({fs:.0f}) - more likely a price move than a thesis change"
            if fs >= 55 else f"with fundamentals already weak ({fs:.0f})")
    if delta < 0:
        return [Signal(RISK, "technical", "technical_breakdown",
                       f"Technical picture deteriorated over the past week ({before:.0f} -> {ts:.0f}), {fund}", 2)]
    return [Signal(OPPORTUNITY, "technical", "technical_turn",
                   f"Technical picture improved over the past week ({before:.0f} -> {ts:.0f}), {fund}", 2)]


def _extended_hours(q: dict, watchlist: bool) -> list[Signal]:
    """Pre-market / after-hours moves, often an earnings or news reaction the daily bars haven't seen yet."""
    ch = q.get("ext_change")
    if ch is None or abs(ch) < 0.03:
        return []
    label = "Pre-market" if q.get("ext_session") == "pre" else "After hours"
    kind = OPPORTUNITY if ch > 0 else RISK
    sev = 2 if abs(ch) >= 0.05 and not watchlist else 1
    return [Signal(kind, "extended hours", f"ext_{q.get('ext_session')}_{'up' if ch > 0 else 'down'}",
                   f"{label}: {ch:+.1%} at {q['ext_price']:.2f}", sev)]


def _optional(fn, *args):
    """Supporting data (benchmarks, news) is nice to have; never fail the evaluation over it."""
    try:
        return fn(*args)
    except Exception as e:
        log.info("%s%s unavailable: %s", getattr(fn, "__name__", fn), args, e)
        return None


def evaluate(h: Holding, portfolio: Portfolio, provider: DataProvider, light: bool = False,
             hist=None) -> Evaluation:
    """light=True skips deep research and SEC data (used when screening many tickers)."""
    rules = portfolio.rules(h.tier)
    try:
        hist = hist if hist is not None else provider.history(h.ticker)
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

    shift_sig = _technical_shift(hist, ts, fs, rules.trailing_atr_mult, not h.is_watchlist)

    # relative strength nudges the technical score; benchmarks are cached across tickers
    sector_etf = SECTOR_ETFS.get(f.get("sector") or "")
    rs_adj, rs, rs_sig = relative.analyze(
        hist, _optional(provider.history, portfolio.settings.benchmark),
        _optional(provider.history, sector_etf) if sector_etf else None, sector_etf, h.tier)
    ts = float(min(100, max(0, ts + rs_adj)))
    tech.update(rs)

    quote = _optional(provider.quote, h.ticker) or {}
    ext_sig = _extended_hours(quote, h.is_watchlist)

    raw_events = _optional(provider.events, h.ticker) or {}
    events, event_sig = catalysts.analyze(raw_events, owned=not h.is_watchlist, tier=h.tier)

    # deep research is informational: it adds signals but doesn't move the scores
    raw = {} if light else (_optional(provider.research, h.ticker) or {})
    peers = {p: _optional(provider.fundamentals, p) for p in raw.get("peers") or []}
    research, deep_sig = {}, []
    deep = () if light else (("earnings", lambda: deepdive.earnings_track(raw, hist)),
                             ("smart_money", lambda: deepdive.smart_money(f, raw)),
                             ("valuation", lambda: deepdive.valuation_context(f, raw, hist, peers, price)))
    for key, fn in deep:
        try:
            research[key], sig = fn()
            deep_sig += sig
        except Exception as e:
            log.warning("%s research failed for %s: %s", key, h.ticker, e)

    raw_sec = None if light else _optional(provider.filings, h.ticker)
    if raw_sec:
        try:
            research["sec"], sec_sig = sec.analyze(raw_sec, f.get("market_cap"))
            deep_sig += sec_sig
        except Exception as e:
            log.warning("SEC analysis failed for %s: %s", h.ticker, e)

    composite = rules.fundamental_weight * fs + rules.technical_weight * ts
    pos, pos_sig = _position(h, price, tech, rules)
    signals = (tech_sig + rs_sig + fund_sig + _confluence(fs, tech, tech_sig, h.tier)
               + shift_sig + event_sig + deep_sig + ext_sig + pos_sig)
    signals.sort(key=lambda s: (-s.severity, s.kind))
    ev = Evaluation(h.ticker, h.tier, h.is_watchlist, price, round(ts, 1), round(fs, 1),
                    round(composite, 1), "", signals, tech, fund, pos, events, research,
                    {k: f.get(k) for k in PROFILE_KEYS}, quote, name=f.get("name"))
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
