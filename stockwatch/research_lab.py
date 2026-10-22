"""Research Lab for the dashboard: read-only views of the valuation and chart-pattern research.

The only bridge between the page and the research engines. Nothing here feeds scoring, plans,
alerts, orders or the portfolio. Pinned examples load from committed files; live checks run only
when asked, one at a time, on a background thread, and are kept for a few hours.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import chart_patterns as cp, sec_quality as sq, valuation_scenarios as vs

NY = ZoneInfo("America/New_York")
CHART_EXAMPLE = Path(__file__).resolve().parents[1] / "docs" / "examples" / "chart-pattern-amzn.json"
JOB_TTL = 12 * 3600          # a live check is kept this long before it can run again for the same ticker
TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
RESEARCH_ONLY = ("Research only: not a buy or sell signal, a price target or a probability. "
                 "Nothing here changes scores, plans or alerts.")


def clean_ticker(text: str | None) -> str | None:
    t = (text or "").strip().upper()
    return t if TICKER.match(t) else None


def pct(v, signed=True) -> str:
    return "—" if v is None else f"{v:{'+' if signed else ''}.1%}"


# ------------------------------------------------------------ valuation: evidence packets

# What a complete Phase 2A-2 packet needs, grouped the way the owner would fill it in.
EVIDENCE_GROUPS = [
    ("Price and shares", "observations", ("price", "shares")),
    ("Balance sheet", "observations", ("cash", "investments", "debt", "debt_noncurrent", "debt_current",
                                       "finance_lease_liabilities", "preferred", "noncontrolling")),
    ("Revenue and working capital", "observations", ("revenue", "operating_working_capital")),
    ("Cost of capital", "observations", ("treasury_10y", "beta", "borrowing_cost")),
    ("Reconciliations", "contracts", ("business_scope", "share_basis", "corporate_actions", "lease_scope",
                                      "capital_tax")),
    ("Bear / base / bull drivers", "scenarios", ("bear", "base", "bull")),
]
BANK_GROUP = ("Bank inputs", "observations", ("tangible_common_equity", "common_equity", "goodwill",
                                              "other_intangibles", "cet1_ratio", "credit_loss_ratio",
                                              "funding_cost", "historical_rotce"))


def load_scenario_config() -> dict:
    return yaml.safe_load(vs.CONFIG_PATH.read_text())


def completeness(cfg: dict) -> list[dict]:
    """Which evidence each configured company has. Presence only: values are checked on a live run."""
    out = []
    for ticker, packet in (cfg.get("companies") or {}).items():
        packet = packet or {}
        groups = []
        for name, section, keys in EVIDENCE_GROUPS + [BANK_GROUP]:
            have = sum(1 for k in keys if (packet.get(section) or {}).get(k))
            groups.append({"group": name, "have": have, "need": len(keys),
                           "state": "provided" if have == len(keys) else "partial" if have else "missing"})
        done = {g["group"] for g in groups if g["state"] == "provided"}
        industrial = {name for name, _, _ in EVIDENCE_GROUPS}
        bank = {BANK_GROUP[0], "Cost of capital", "Bear / base / bull drivers"}
        if not any(g["have"] for g in groups):
            status = vs.REQUIRED
        elif industrial <= done or bank <= done:
            status = "READY TO CHECK"   # complete enough to run; the live check still validates every record
        else:
            status = "INCOMPLETE"
        out.append({"ticker": ticker, "status": status, "groups": groups,
                    "missing": [g["group"] for g in groups if g["state"] != "provided" and g["group"] in industrial]})
    return out


# ------------------------------------------------------------ valuation: SYNTHETIC worked example

def _record(value, unit="USD", kind="observation", end="2025-12-31", **extra):
    return {"value": value, "unit": unit, "kind": kind, "status": "usable",
            "source": "SYNTHETIC: hand-calculated teaching fixture, not real market/company evidence",
            "rationale": "Demonstrates arithmetic and evidence schema only",
            "available_on": "2026-02-15", "period_end": end, **extra}


def synthetic_valuation(dilution: float = 0.0) -> tuple[dict, dict]:
    """The hand-checkable SYNTHETIC example: fictitious numbers and citations that value no real company.

    `dilution` adds that much non-SBC share issuance a year in years 1-5, fading to zero by year 10.
    """
    cfg = load_scenario_config()
    obs = {k: _record(v) for k, v in {
        "price": 10., "shares": 10., "cash": 20., "investments": 5., "debt": 25., "debt_noncurrent": 20.,
        "debt_current": 5., "finance_lease_liabilities": 0., "preferred": 0., "noncontrolling": 0.,
        "revenue": 100., "operating_working_capital": 10., "independent_normalized_fcff": 20.}.items()}
    obs["shares"]["unit"] = "shares"
    for k in ("price", "shares"):
        obs[k].update(class_id="SYNTH-common", split_basis_date="2025-12-31")
    obs["revenue"]["period_start"] = "2025-01-01"
    obs["price"].update(period_end="2026-02-27", available_on="2026-02-27")
    obs["treasury_10y"] = _record(.04, "ratio", end="2026-02-27", available_on="2026-02-27")
    obs["beta"] = _record(1., "ratio", method="SYNTHETIC beta=1, no regression performed")
    obs["borrowing_cost"] = _record(.05, "ratio")
    obs["peer_ev_fcff"] = _record(10., "multiple")
    obs["independent_normalized_fcff"]["method"] = "Independent synthetic FCFF = EBIT20 + D&A2 − maintenance2 = 20"
    contracts = {k: _record(v, "contract", "analyst_assumption") for k, v in {
        "business_scope": "operating_business_consolidated_drivers_reconciled",
        "share_basis": "fully_diluted_common_same_class", "corporate_actions": "verified_price_share_basis",
        "lease_scope": "finance_leases_in_debt_and_investment_operating_leases_in_costs",
        "cross_check_basis": "ev_fcff_after_sbc_same_lease_scope"}.items()}
    contracts["capital_tax"] = _record(0., "ratio", "analyst_assumption")
    scenarios = {}
    for name, margin in [("bear", .15), ("base", .20), ("bull", .25)]:
        drivers = {"growth": 0., "margin_pre_sbc": margin, "tax": 0., "dna_pct": .02, "maintenance_pct": .02,
                   "growth_capex_pct": 0., "wc_pct": .1, "sbc_pct": 0., "non_sbc_dilution": dilution}
        case = {k: _record([v] * 5, "ratio", "analyst_assumption") for k, v in drivers.items()}
        case["terminal"] = {k: _record(0. if k == "non_sbc_dilution" else v, "ratio", "analyst_assumption")
                            for k, v in drivers.items()}
        case["terminal"]["roic"] = _record(.2, "ratio", "analyst_assumption")
        scenarios[name] = case
    packet = {"observations": obs, "contracts": contracts, "scenarios": scenarios}
    facts = {}
    for tag, value in [("Revenues", 100.), ("OperatingIncomeLoss", 20.),
                       ("NetCashProvidedByUsedInOperatingActivities", 30.),
                       ("PaymentsToAcquirePropertyPlantAndEquipment", 2.), ("ShareBasedCompensation", 0.),
                       ("DepreciationDepletionAndAmortization", 2.)]:
        facts[tag] = {"units": {"USD": [{"val": value, "start": f"{y}-01-01", "end": f"{y}-12-31", "form": "10-K",
                                         "filed": f"{y + 1}-02-15", "accn": f"SYNTHETIC-{y}"} for y in range(2020, 2026)]}}
    facts["CashAndCashEquivalentsAtCarryingValue"] = {"units": {"USD": [{
        "val": 20., "end": "2025-12-31", "form": "10-K", "filed": "2026-02-15", "accn": "SYNTHETIC-2025"}]}}
    company = {"entityName": "SYNTHETIC teaching example", "facts": {"us-gaap": facts}}
    day = date(2026, 3, 1)
    q = sq.quality_company("SYNTHETIC", company, {"sic": "7372"}, day)
    report = vs.evaluate(q, company, packet, day, cfg)
    return cfg | {"companies": {"SYNTHETIC": packet}}, report


def scenario_rows(report: dict) -> list[list]:
    return [[name.title(), f"{s['equity_per_share']:.2f}", pct(s.get("rate"), False),
             pct(s.get("terminal_share"), False), f"{s.get('dilution_claim_weight', 1):.3f}"]
            for name, s in report.get("scenarios", {}).items()]


def driver_rows(scenario: dict) -> list[list]:
    return [[y["year"], f"{y['revenue']:.1f}", pct(y["drivers"]["margin_pre_sbc"], False),
             f"{y['fcff']:.2f}", pct(y["drivers"]["non_sbc_dilution"], False), f"{y['dilution_factor']:.4f}"]
            for y in scenario.get("years", [])]


def sensitivity_grid(report: dict) -> tuple[list[str], list[list]]:
    """Discount rate down, terminal growth across: equity per share, or why a cell is unavailable."""
    cells = report.get("sensitivity_only", [])
    growths = sorted({c["growth"] for c in cells})
    rows = []
    for r in sorted({c["rate"] for c in cells}):
        row = [pct(r, False)]
        for g in growths:
            c = next(c for c in cells if c["rate"] == r and c["growth"] == g)
            row.append(f"{c['equity_per_share']:.2f}" if "equity_per_share" in c else "n/a")
        rows.append(row)
    return ["Rate \\ terminal g"] + [pct(g, False) for g in growths], rows


# ------------------------------------------------------------ valuation: live SEC check

def valuation_check(ticker: str, as_of: date | None = None) -> dict:
    """Phase 2A-1 family and data quality plus the 2A-2 evidence gate, from SEC (and Yahoo for context)."""
    as_of = as_of or datetime.now(NY).date()
    report = vs.research_ticker(ticker, as_of, load_scenario_config())
    if "family" not in report:   # SEC wasn't reached: an outage to retry, not a finding to keep
        raise RuntimeError("; ".join(report.get("gaps") or ["SEC data not retrieved"]))
    return report


def sec_rows(report: dict) -> list[list]:
    rows = []
    for field, x in (report.get("sec_inputs") or {}).items():
        src = x.get("source") or {}
        rows.append([field.replace("_", " "), x["status"], src.get("end") or "—",
                     "; ".join(x.get("issues") or [])[:140] or "—"])
    return rows


def risk_rows(report: dict) -> list[list]:
    ctx = report.get("phase2a1_risk_context")
    if isinstance(ctx, list):
        return [[r["lens"], r["text"]] for r in ctx]
    return [["Risk context", (ctx or {}).get("reason", "not available")]]


# ------------------------------------------------------------ chart patterns

def chart_example(path: Path = CHART_EXAMPLE) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        return {"error": f"pinned example unreadable: {e}"}


def chart_run(provider, ticker: str, source: str, today: date | None = None) -> dict:
    """The chart lab on the app's adjusted daily history, with SPY as the market regime."""
    today = today or datetime.now(NY).date()
    frame = provider.history(ticker, period="max")
    bench = provider.history("SPY", period="max")
    # today's daily bar may still be forming: use completed sessions only
    frame, bench = frame.loc[frame.index.date < today], bench.loc[bench.index.date < today]
    report = cp.research(frame, adjusted=True, ticker=ticker, benchmark=bench)
    report["source"] = source
    return report


def window(report: dict, size: int) -> dict | None:
    return next((w for w in report.get("windows", []) if w["window"] == size), None)


def summary_rows(w: dict) -> list[list]:
    """Matches and the two baselines side by side for each horizon."""
    groups = [("Matches", w.get("summary", {}))] + [
        ({"regime": "Same regime", "dip": "Any dip"}[k], v) for k, v in (w.get("baselines") or {}).items()]
    rows = []
    for h in sorted({h for _, g in groups for h in g}, key=int):
        for name, g in groups:
            s = g.get(h)
            if not s:
                continue
            lo_hi = s.get("wilson_95")
            rows.append([f"{h}d", name, s["n"], pct(s["median_return"]), pct(s["target_first_rate"], False),
                         pct(s["stop_first_rate"], False), pct(s["no_hit_rate"], False),
                         f"{max(lo_hi[0], 0):.0%}–{lo_hi[1]:.0%}" if lo_hi else "—"])
    return rows


def outcome_rows(match: dict) -> list[list]:
    return [[f"{h}d", pct(o["return"]), o["result"] + (" (same bar)" if o.get("same_bar_ambiguous") else ""),
             o["days"] or "—", pct(o["mfe"]), pct(o["mae"])] for h, o in match.get("outcomes", {}).items()]


def holdout_note(w: dict, settings: dict) -> str:
    wf = w.get("walk_forward") or {}
    return (f"Out-of-sample checks: {wf.get('n', 0)} (library frozen at {wf.get('train_end', '—')}; "
            f"each needs at least {settings.get('min_matches', '?')} matches for every method).")


# ------------------------------------------------------------ background jobs

class Jobs:
    """One research job at a time per app process; results are kept for `ttl` seconds.

    The page only reads `get`; a button's on_click calls `submit`, so reruns never start work.
    """

    def __init__(self, ttl: float = JOB_TTL, keep: int = 24):
        self.ttl, self.keep = ttl, keep
        self._lock = threading.Lock()
        self._jobs: dict[tuple[str, str], dict] = {}

    def get(self, kind: str, ticker: str) -> dict | None:
        with self._lock:
            job = self._jobs.get((kind, ticker))
            if job and job["state"] != "running" and time.time() - job["finished"] > self.ttl:
                del self._jobs[(kind, ticker)]
                return None
            return dict(job) if job else None

    def busy(self) -> tuple[str, str] | None:
        with self._lock:
            return next((k for k, j in self._jobs.items() if j["state"] == "running"), None)

    def submit(self, kind: str, ticker: str, fn) -> str:
        with self._lock:
            running = next((k for k, j in self._jobs.items() if j["state"] == "running"), None)
            if running:
                return f"Still working on {running[1]}. Try again when it finishes."
            job = self._jobs.get((kind, ticker))
            if job and job["state"] == "done" and time.time() - job["finished"] <= self.ttl:
                return f"{ticker} was checked at {job['when']} UTC; showing that result."
            self._jobs[(kind, ticker)] = {"state": "running", "started": time.time(), "finished": None,
                                          "when": None, "result": None, "error": None}
            for old in sorted((k for k, j in self._jobs.items() if j["state"] != "running"),
                              key=lambda k: self._jobs[k]["finished"])[:max(0, len(self._jobs) - self.keep)]:
                del self._jobs[old]

        def run():
            try:
                result, error = fn(), None
            except Exception as e:   # shown on the page; never retried automatically
                result, error = None, f"{type(e).__name__}: {e}"
            with self._lock:
                self._jobs[(kind, ticker)] = {"state": "error" if error else "done", "started": None,
                                              "finished": time.time(), "result": result, "error": error,
                                              "when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}
        threading.Thread(target=run, name=f"research-{kind}-{ticker}", daemon=True).start()
        return f"Checking {ticker}. This takes a minute or two; the result appears here."
