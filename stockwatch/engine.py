"""Combines technical + fundamental analysis into one verdict per holding."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import analogs, catalysts, debtcash, deepdive, fundamental, momentum, newsfeed, relative, sec, status, street, technical, tradeplan, transitions, zones
from .config import Holding, Portfolio
from . import data, finnhub
from .data import SECTOR_ETFS, DataProvider
from .signals import OPPORTUNITY, RISK, Signal

log = logging.getLogger(__name__)

MIN_FUND_COVERAGE = 30   # fundamental points available (3+ measures) before the score is trusted

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
    plan: dict = field(default_factory=dict)
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
    fund = ("fundamentals currently unavailable" if fs is None else
            f"fundamentals unchanged and still solid ({fs:.0f}) - more likely a price move than a thesis change"
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
        if f.get("source"):
            fund["source"] = f["source"]
        if (fund.get("coverage") or 0) < MIN_FUND_COVERAGE:
            # Yahoo refused or returned too little: compute fundamentals from the company's SEC filings
            facts = _optional(provider.sec_facts, h.ticker) if hasattr(provider, "sec_facts") else None
            if facts:
                f = {**sec.derive(facts, price), **{k: v for k, v in f.items() if v is not None}}
                fs, fund, fund_sig = fundamental.analyze(f, price)
                fund["source"] = "SEC filings"
    except Exception as e:
        log.exception("evaluation failed for %s", h.ticker)
        return Evaluation(h.ticker, h.tier, h.is_watchlist, float("nan"), 0, 0, 0, "ERROR", [], {}, {}, error=str(e))

    shift_sig = _technical_shift(hist, ts, fs if (fund.get("coverage") or 0) >= MIN_FUND_COVERAGE else None,
                                 rules.trailing_atr_mult, not h.is_watchlist)

    # relative strength nudges the technical score; benchmarks are cached across tickers
    sector_etf = SECTOR_ETFS.get(f.get("sector") or "")
    market_hist = _optional(provider.history, portfolio.settings.benchmark)
    sector_hist = _optional(provider.history, sector_etf) if sector_etf else None
    rs_adj, rs, rs_sig = relative.analyze(hist, market_hist, sector_hist, sector_etf, h.tier)
    if rs_adj:
        tech["score_parts"] = tech.get("score_parts", []) + [("Relative strength vs SPY (3 months)", round(rs_adj, 1))]
        tech["raw_points"] = tech.get("raw_points", 0) + rs_adj
        ts = technical.to_score(tech["raw_points"])
    tech.update(rs)

    quote = _optional(provider.quote, h.ticker) or {}
    ext_sig = _extended_hours(quote, h.is_watchlist)

    # one plain status from record high to deep breakdown; display and exit-call only, it never moves a score
    now = datetime.now(timezone.utc)
    live = transitions.current_quote(quote, now)
    tech["price_status"] = _optional(status.assess, hist, now, live[0] if live else None, not h.is_watchlist)
    # how the move is happening (momentum and whether it is an event, the market, selling pressure or drift); display only
    tech["momentum"] = _optional(momentum.assess, hist, market_hist, sector_hist, now)
    tech["zones"] = _optional(zones.assess, hist, now)       # graded support and resistance zones; display only
    ps = tech["price_status"]
    if not light and isinstance(ps, dict) and ps.get("code") in status.BEARISH:
        # a second source's technical read, only where it matters (a weak or broken stock), to keep the requests few
        ps["second"] = status.second_opinion(ps["code"], _optional(data.second_opinion, h.ticker),
                                             (ps.get("levels") or {}).get("close")) or status.second_unavailable(finnhub.enabled())
        # an independent price series re-checks that the closes behind this status are right (catches bad Yahoo data)
        ps["pricecheck"] = _optional(data.price_check, h.ticker, hist["Close"]) or {"source": "Stooq", "unavailable": "the check did not run"}

    raw_sec = None if light else _optional(provider.filings, h.ticker)
    raw_events = _optional(provider.events, h.ticker) or {}
    if not raw_events.get("earnings_date") and raw_sec:
        estimate = sec.estimate_next_earnings(raw_sec.get("filings") or [])
        if estimate:
            raw_events = {**raw_events, "earnings_date": estimate, "earnings_estimated": True}
    events, event_sig = catalysts.analyze(raw_events, owned=not h.is_watchlist, tier=h.tier)
    events["earnings_estimated"] = bool(raw_events.get("earnings_estimated"))
    # news from several sources, ranked (display and Telegram only: it never feeds `catalysts` or any score)
    events["wire"] = None if light else _optional(newsfeed.build, h.ticker, f.get("name"), raw_events.get("news"),
                                                  (raw_sec or {}).get("filings") if raw_sec else None, finnhub.enabled())

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

    raw_street = None if light else _optional(provider.street, h.ticker)
    if raw_street:
        try:
            research["street"], street_sig = street.analyze(
                raw_street, price, hist, market_hist, research.get("earnings") or {}, research.get("valuation") or {},
                events.get("days_to_earnings"), not h.is_watchlist)
            deep_sig += street_sig
        except Exception as e:
            log.warning("street analysis failed for %s: %s", h.ticker, e)

    if raw_sec:
        try:
            research["sec"], sec_sig = sec.analyze(raw_sec, f.get("market_cap"))
            deep_sig += sec_sig
        except Exception as e:
            log.warning("SEC analysis failed for %s: %s", h.ticker, e)

    try:         # debt and cash for the Details card (display only; the company-facts file is cached for a day)
        if not light:
            research["debt_cash"] = debtcash.build(f, _optional(provider.sec_facts, h.ticker)
                                                   if hasattr(provider, "sec_facts") else None)
    except Exception as e:
        log.info("debt and cash failed for %s: %s", h.ticker, e)

    # too few fundamental measures (usually a blocked Yahoo request) means "unknown", not "bad"
    fund["available"] = (fund.get("coverage") or 0) >= MIN_FUND_COVERAGE
    if fund["available"]:
        composite = rules.fundamental_weight * fs + rules.technical_weight * ts
        confluence = _confluence(fs, tech, tech_sig, h.tier)
    else:
        composite = ts
        confluence = [Signal(RISK, "fundamental", "fundamentals_unavailable",
                             "Fundamentals unavailable right now (neither Yahoo nor SEC filings returned enough); "
                             "this verdict is based on price action only", 1)]
    pos, pos_sig = _position(h, price, tech, rules)
    signals = (tech_sig + rs_sig + fund_sig + confluence
               + shift_sig + event_sig + deep_sig + ext_sig + pos_sig)
    signals.sort(key=lambda s: (-s.severity, s.kind))
    ev = Evaluation(h.ticker, h.tier, h.is_watchlist, price, round(ts, 1), round(fs, 1),
                    round(composite, 1), "", signals, tech, fund, pos, events, research,
                    {k: f.get(k) for k in PROFILE_KEYS}, quote, name=f.get("name"))
    ev.verdict = _verdict(ev)
    try:
        val = research.get("valuation") or {}
        plan_fs = fs if fund["available"] else 50.0   # unknown fundamentals count as neutral, not weak
        plan = tradeplan.build(hist, tech, fund, plan_fs, ev.verdict, h.tier, h.is_watchlist, val.get("levels"),
                               val.get("fair_value"), events, quote)
        if plan:
            entry = plan["entry"]
            history = analogs.replay(hist, (entry - plan["stop"]) / entry,
                                     (plan["targets"][0]["price"] - entry) / entry, h.tier)
            plan = tradeplan.refine(plan, history, research.get("street"), events, h.tier, not h.is_watchlist,
                                    tech, plan_fs)
            plan = tradeplan.reconcile(plan, signals)
            plan = tradeplan.exit_on_breakdown(plan, tech.get("price_status"), h.is_watchlist)
            plan = tradeplan.hold_off_buying(plan, tech.get("price_status"), h.is_watchlist, tech)
        ev.plan = plan
    except Exception as e:
        log.warning("trade plan failed for %s: %s", h.ticker, e)
    return ev


def scan(portfolio: Portfolio, provider: DataProvider, workers: int = 6, on_ready=None) -> list[Evaluation]:
    """Evaluate every holding. on_ready(evaluation) runs in the caller's thread as each one finishes,
    before the portfolio-level checks, so a slow sweep can show results as they come in."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(evaluate, h, portfolio, provider): i for i, h in enumerate(portfolio.holdings)}
        evals: list[Evaluation | None] = [None] * len(futures)
        for fut in as_completed(futures):
            evals[futures[fut]] = fut.result()
            if on_ready:
                on_ready(evals[futures[fut]])

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
