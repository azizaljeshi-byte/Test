"""Old-vs-CIS shadow comparison on the frozen 23 October 2026 reference data.

    python -m stockwatch.cis.shadow            # prints the comparison as Markdown

For each reference stock, as a held core (Tier 1) position, a held Tier 2 position and a watchlist name:
- LEGACY: the existing engine (`engine.evaluate` -> verdict -> `tradeplan.build/refine/reconcile`) run on the
  same frozen completed bars. The frozen inputs have no fundamentals, events or research, so this is the
  engine's own "fundamentals unavailable, price action only" path, exactly as production runs when Yahoo
  blocks fundamentals. For ISRG the round also captured the live app's call (verdict BUY SETUP with the
  website's fundamental score of 77) in ISRG-scanner-audit.json, shown as its own row.
- CIS: `decision.decide` on the packet's own snapshot.
Nothing is sent, saved or activated.
"""
from __future__ import annotations

import json
import logging

from .. import config, engine
from . import decision, explain, features, level_packet, presentation

AUDIT = level_packet.FIXTURES / "ISRG-scanner-audit.json"
SECTOR_OF = {"FICO": "XLK", "CRDO": "XLK", "PODD": "XLV"}


class FrozenProvider:
    """Serves only the frozen completed bars. Fundamentals, quotes, events and research are unavailable."""

    def __init__(self, symbol: str):
        ref = explain.REFERENCE[symbol]
        fx = level_packet.FIXTURES
        bars = {symbol: ref["bars"], "SPY": ref["spy"]}
        if ref["sector"]:
            bars[ref["sector"][0]] = ref["sector"][1]
        self.bars = {k: features.completed(features.read_csv(fx / f), explain.BOUNDARY) for k, f in bars.items()}

    def history(self, ticker: str, period: str = "5y"):
        if ticker not in self.bars:
            raise KeyError(f"{ticker} is not in the frozen inputs")
        return self.bars[ticker]

    def fundamentals(self, ticker: str) -> dict:
        return {}

    def quote(self, ticker: str) -> dict:
        return {}

    def events(self, ticker: str) -> dict:
        return {}


def legacy(symbol: str, held: bool, tier: int) -> dict:
    """The existing engine's call on the frozen bars (fundamentals unavailable)."""
    pf = config.Portfolio(holdings=[], tiers={t: config.TierRules(**d) for t, d in config.DEFAULT_TIERS.items()},
                          settings=config.Settings(), source="frozen")
    h = config.Holding(symbol, tier, shares=10 if held else 0, cost_basis=None)
    level = logging.getLogger("stockwatch").level
    logging.getLogger("stockwatch").setLevel(logging.ERROR)       # the frozen provider has no research feeds
    try:
        ev = engine.evaluate(h, pf, FrozenProvider(symbol), light=True)
    finally:
        logging.getLogger("stockwatch").setLevel(level)
    row = _plan_row(ev.verdict, ev.plan or {}, "engine on frozen bars, fundamentals unavailable")
    # non-technical risk controls that would still take precedence over a CIS call at activation
    row["risk_controls"] = sorted({s.code for s in ev.signals if s.kind == "risk" and s.source != "technical"})
    return row


def isrg_observed() -> dict:
    """The live app's ISRG call captured in the reference round (watchlist, verdict BUY SETUP)."""
    snap = json.loads(AUDIT.read_text())["snapshots"]["completed"]
    return {**_plan_row("BUY SETUP (observed in the app, fundamentals 77)", snap["plan"], "captured live app, 22 Oct close"),
            "risk_controls": []}


def _plan_row(verdict: str, plan: dict, source: str) -> dict:
    t = next(iter(plan.get("targets") or []), None)
    return {"verdict": verdict, "stance": plan.get("stance") or "no plan", "entry": (plan.get("entry_low"), plan.get("entry_high")),
            "stop": plan.get("stop"), "target": None if t is None else (t["price"], t["label"]), "source": source}


def cis(symbol: str, held: bool, tier: int) -> dict:
    p = decision.reviewed_packets()[symbol]
    recent = presentation.recent(explain.report(symbol), decision.DEFENSE_LOOKBACK)
    return decision.decide(p, decision.inputs_from_packet(p, recent), held, tier)


CASES = (("held, Tier 1 (core)", True, 1), ("held, Tier 2", True, 2), ("watchlist", False, 2))


def compare() -> list[dict]:
    rows = []
    for symbol in explain.REFERENCE:
        for label, held, tier in CASES:
            old, new = legacy(symbol, held, tier), cis(symbol, held, tier)
            rows.append({"symbol": symbol, "case": label, "legacy": old, "cis": new,
                         "changed": decision.ACTIONS[new["action"]][1] != old["stance"]})
        if symbol == "ISRG":
            rows.append({"symbol": symbol, "case": "watchlist (live app capture)", "legacy": isrg_observed(),
                         "cis": cis(symbol, False, 2), "changed": True})
    return rows


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, tuple):
        return "–".join(_fmt(x) for x in v) if all(isinstance(x, (int, float)) for x in v if x is not None) else f"{_fmt(v[0])} ({v[1]})"
    return f"{v:,.2f}" if isinstance(v, (int, float)) else str(v)


def markdown(rows: list[dict]) -> str:
    out = ["| Stock | Case | Legacy verdict → plan | Legacy entry / stop / target | CIS action | CIS levels | Changed | "
           "Non-technical risk signals |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        o, n = r["legacy"], r["cis"]
        lv = n.get("levels") or {}
        out.append(f"| {r['symbol']} | {r['case']} | {o['verdict']} → {o['stance']} | {_fmt(o['entry'])} / {_fmt(o['stop'])} / "
                   f"{_fmt(o['target'])} | {n['action']} ({n['downside']['confirmed']}) | floor {_fmt(lv.get('floor'))}, "
                   f"failure < {_fmt(lv.get('failure'))} | {'yes' if r['changed'] else 'no'} | "
                   f"{', '.join(o['risk_controls']) or 'none'} |")
    return "\n".join(out)


if __name__ == "__main__":
    print(markdown(compare()))
