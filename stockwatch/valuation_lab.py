"""Read-only valuation research (Phase 2A-1 of the valuation work, Issue #8).

For each company it decides which kind of valuation fits how the business earns its cash, says why,
and runs only what the data supports in 2A-1:

- **cash compounder:** a reverse valuation, i.e. what growth the market price is implying, across a
  sensitivity grid of discount rates and terminal growth;
- **cash-burning company:** cash runway and share-count growth; no intrinsic value;
- **cyclical company or bank:** classified, with the evidence; their models come in 2A-2;
- **insurers, REITs, utilities, other financials:** not supported in 2A.

Every input comes from the Phase 1B data-quality layer (sec_quality) with its status and filing
source. A critical input that isn't usable makes the model unavailable, with the reason; nothing is
estimated or filled in. There is no fair value, BUY/SELL, score or probability here, and nothing in
the app imports this module. Assumptions are in valuation_assumptions.yaml.

    python -m stockwatch.valuation_lab MSFT AVGO MU JPM RIVN BRK-B --markdown v.md --json v.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

from . import sec
from . import sec_quality as sq
from .sec_audit import FIELDS, _days, _money, identification_line, summary

ASSUMPTIONS_FILE = Path(__file__).with_name("valuation_assumptions.yaml")

COMPOUNDER, CYCLICAL, CASH_BURN, BANK, UNSUPPORTED, INSUFFICIENT = (
    "cash compounder", "cyclical", "cash-burning", "bank", "not supported in 2A", "insufficient evidence")
COMPUTED, UNAVAILABLE, DEFERRED = "computed", "unavailable", "deferred to 2A-2"

NOT_APPLICABLE_MODELS = {
    COMPOUNDER: ["cash runway (the company funds itself)", "bank P/TBV and ROE (not a bank)",
                 "mid-cycle normalization (no cycle in the history window)"],
    CYCLICAL: ["reverse valuation on trailing cash flow (a cycle peak or trough would mislead)",
               "bank P/TBV and ROE (not a bank)"],
    CASH_BURN: ["DCF and reverse valuation (no positive cash flow to discount)", "P/E (losses)",
                "bank P/TBV and ROE (not a bank)"],
    BANK: ["DCF, free cash flow and EV multiples (deposits and loans are the business)", "cash runway"],
    UNSUPPORTED: ["all 2A models: this kind of company needs its own model, not built yet"],
    INSUFFICIENT: ["every model until the classification is clear"],
}
BANK_NEEDS = ["tangible common equity (equity minus goodwill and intangibles)", "return on tangible equity history",
              "CET1 capital ratio", "net charge-offs and provisions"]


def load_assumptions(path: Path | None = None) -> dict:
    with open(path or ASSUMPTIONS_FILE) as fh:
        return yaml.safe_load(fh)


# ------------------------------------------------------------------ inputs

def _input(label: str, value, status: str, source: str | None = None, notes: list[str] | None = None) -> dict:
    return {"label": label, "value": value, "status": status, "source": source, "notes": notes or []}


def _ttm_input(q: dict, key: str) -> dict:
    f = q["fields"][key]
    t = f.get("ttm") or {"status": sq.UNKNOWN, "value": None, "parts": [], "reason": "not a flow figure"}
    src = "; ".join(f"{name}: {p['concept']} {p['start']} to {p['end']}, {p['form']} {p['accn']} filed {p['filed']}"
                    for name, p in t.get("parts", []))
    status = t.get("data_status") if t["status"] == sq.NOT_APPLICABLE else t["status"]
    return _input(f"{f['label']} (TTM)", t.get("value"), status, src or None,
                  [t["reason"]] if t.get("reason") else [])


def _balance_input(q: dict, key: str) -> dict:
    bs = q["balance_sheet"]
    row = next((r for r in bs["rows"] if r["key"] == key), None)
    if not row:
        return _input(FIELDS[key][0], None, sq.UNKNOWN, None, [bs.get("reason") or "no balance-sheet date"])
    status = row.get("data_status", row["status"])
    src = f"{row['concept']} on {bs['date']}, filed {row.get('filed')}, {row.get('accn')}" if row.get("concept") else None
    return _input(f"{row['label']} on {bs['date']}", row["value"], status, src, row["notes"])


def _cover_input(q: dict) -> dict:
    row = next(r for r in q["shares"]["rows"] if r["key"] == "cover")
    status = row["status"]
    value = row["values"][0] if len(row["values"]) == 1 else None
    if len(row["values"]) > 1:
        status = sq.RECONCILE
    return _input("Shares outstanding (cover page)", value, status,
                  f"cover page dated {row['date']}" if row["date"] else None, row["notes"])


def _blockers(inputs: list[dict]) -> list[str]:
    """Why a model can't run: each critical input that isn't usable, with its status and reason."""
    out = []
    for i in inputs:
        if i["status"] != sq.USABLE or i["value"] is None:
            why = f"; {i['notes'][0]}" if i["notes"] else ""
            state = "missing" if i["status"] == sq.USABLE else i["status"]     # usable status but no number
            out.append(f"{i['label']} is {state}{why}")
    return out


# ---------------------------------------------------------------- price

def close_on(history, as_of: date) -> tuple[float | None, str | None]:
    """The last close on or before as_of (no look-ahead). history: a DataFrame with a date index and Close."""
    if history is None or len(history) == 0:
        return None, None
    rows = history[history.index.normalize() <= str(as_of)]
    if not len(rows):
        return None, None
    return float(rows["Close"].iloc[-1]), rows.index[-1].date().isoformat()


def fetch_price(ticker: str, as_of: date) -> dict:
    """Close on or before as_of from Yahoo (not dividend-adjusted). For a past as_of, Yahoo's closes are
    split-adjusted, so a split since then would make market cap wrong; the note says so."""
    from .data import _yahoo
    import yfinance

    @_yahoo
    def get():
        return yfinance.Ticker(ticker).history(start=str(as_of - timedelta(days=10)),
                                               end=str(as_of + timedelta(days=1)), auto_adjust=False)
    try:
        df = get()
        df.index = df.index.tz_localize(None)
    except Exception as e:
        return _input("Share price", None, sq.UNKNOWN, None, [f"price not retrieved: {type(e).__name__}: {e}"])
    price, day = close_on(df, as_of)
    if price is None:
        return _input("Share price", None, sq.UNKNOWN, None, [f"no close on or before {as_of}"])
    notes = [] if as_of >= date.today() - timedelta(days=5) else [
        "past as-of date: Yahoo closes are split-adjusted, so check no split happened since"]
    return _input("Share price", price, sq.USABLE, f"Yahoo Finance close on {day}", notes)


# --------------------------------------------------------- classification

def annual_history(company: dict, key: str, as_of: date) -> list[dict]:
    """Fiscal-year figures filed by as_of, newest first, each with its source and a quality status.

    The first concept in priority order that reports a year wins, at its latest filing. The same
    checks as sec_quality apply per year: two values in one filing make the year unknown (no
    number), a revision in a later filing or another tag disagreeing (outside a known scope pair)
    makes it needs reconciliation. Periods ending within 300 days of a newer one are dropped."""
    _label, _kind, unit, concepts = FIELDS[key]
    by_concept = sq._candidates(company, concepts, unit, as_of)[0]
    annual = {c: [f for f in fs if sq._is_annual(f)] for c, fs in by_concept.items()}
    rows: list[dict] = []
    for end in sorted({f["end"] for fs in annual.values() for f in fs}, reverse=True):
        concept = next(c for c in concepts if any(f["end"] == end for f in annual.get(c, [])))
        group = sorted((f for f in annual[concept] if f["end"] == end), key=lambda f: f.get("filed") or "")
        chosen, name = group[-1], concept.split(":")[-1]
        flags: list[tuple[str, str]] = []
        if len({f.get("start") for f in group}) > 1:
            flags.append((sq.RECONCILE, "two period starts for this fiscal year"))
        if (contested := sq._contest(annual[concept], chosen, unit)):
            flags.append(contested)
        for other in concepts:
            same = [f for f in annual.get(other, []) if other != concept and f["end"] == end
                    and f.get("start") == chosen.get("start")]
            if same:
                alt = max(same, key=lambda f: f.get("filed") or "")
                if sq._differs(alt["val"], chosen["val"]) and not sq._known_scope_pair(key, name, other):
                    flags.append((sq.RECONCILE, f"{other.split(':')[-1]} {_money(alt['val'])} disagrees with {name} "
                                                f"{_money(chosen['val'])}"))
        status = sq._status(flags)
        rows.append({"end": end, "start": chosen.get("start"), "concept": name,
                     "value": None if status == sq.UNKNOWN else chosen["val"], "status": status,
                     "issues": [t for _, t in flags], "accn": chosen.get("accn"), "form": chosen.get("form"),
                     "filed": chosen.get("filed")})
    kept: list[dict] = []
    for r in rows:
        if not kept or sq._gap(kept[-1]["end"], r["end"]) >= 300:
            kept.append(r)
    return kept


EVIDENCE_FIELDS = ("revenue", "operating_income", "operating_cash_flow", "capex")


FY_ALIGN_DAYS = 10    # fiscal-year ends this close are the same year (52/53-week calendars move by days)


def _evidence(company: dict, as_of: date, n: int, fy_end: str | None = None) -> list[dict]:
    """One row per fiscal year, newest first: each field's value, status and actual source period.

    Rows come from every field's fiscal-year ends and the company's latest fiscal year, so a year
    with revenue missing shows as unknown rather than dropping out. A field fills a row only if its
    period ends within FY_ALIGN_DAYS of that row, and each figure fills at most one row: a figure
    from a different fiscal calendar never stands in for two years."""
    hist = {k: annual_history(company, k, as_of) for k in EVIDENCE_FIELDS}
    ends: list[str] = []
    for end in sorted({h["end"] for hs in hist.values() for h in hs} | ({fy_end} if fy_end else set()), reverse=True):
        if not ends or sq._gap(ends[-1], end) > FY_ALIGN_DAYS:
            ends.append(end)
    used: dict[str, set[int]] = {k: set() for k in EVIDENCE_FIELDS}
    rows = []
    for end in ends[:n]:
        row = {"end": end, "status": {}, "issues": [], "sources": {}, "periods": []}
        for k in EVIDENCE_FIELDS:
            near = [(abs(sq._gap(h["end"], end)), i) for i, h in enumerate(hist[k])
                    if i not in used[k] and abs(sq._gap(h["end"], end)) <= FY_ALIGN_DAYS]
            h = hist[k][min(near)[1]] if near else None
            if h:
                used[k].add(min(near)[1])
                if f"{h['start']} to {h['end']}" not in row["periods"]:
                    row["periods"].append(f"{h['start']} to {h['end']}")
            row[k] = h["value"] if h else None
            row["status"][k] = h["status"] if h else sq.UNKNOWN
            if not h:
                row["issues"].append(f"{FIELDS[k][0]} not reported for this fiscal year")
            elif h["status"] != sq.USABLE:
                row["issues"].append(f"{FIELDS[k][0]} {h['status']}: {'; '.join(h['issues'])}")
            row["sources"][k] = (f"{h['concept']} {h['start']} to {h['end']}, {h['form']} {h['accn']} filed {h['filed']}"
                                 if h else None)
        ok = row["status"]["operating_cash_flow"] == row["status"]["capex"] == sq.USABLE
        row["ocf_minus_capex"] = row["operating_cash_flow"] - row["capex"] if ok else None
        rows.append(row)
    return rows


def classify(q: dict, company: dict, as_of: date, cfg: dict) -> dict:
    """Which kind of valuation fits, the rule that decided it, and the evidence. Deterministic.

    Only fiscal years whose figures pass the quality checks count. A cycle found in usable years
    is evidence; ruling a cycle out (to call a company a compounder) needs every year in the window
    usable and consecutive, otherwise the answer is insufficient evidence, naming the years."""
    c = cfg["classifier"]
    sect = q["sector"]
    sic = sect["sic"]
    out = {"family": None, "rule": None, "evidence": []}
    override = (cfg.get("overrides") or {}).get(q["ticker"])
    if override:
        out.update(family=override["family"], rule=f"override in the assumptions file: {override['reason']}")
    elif sect["kind"] == "bank":
        out.update(family=BANK, rule=f"SIC {sic} ({sect['description']}): a bank")
    elif sect["kind"] or (sic and (sic == 6798 or 4900 <= sic <= 4949)):
        out.update(family=UNSUPPORTED, rule=f"SIC {sic} ({sect['description']}): insurers, REITs, utilities and "
                                            "other financial companies need their own models")
    else:
        rows = _evidence(company, as_of, c["history_years"], q["reference"].get("fy_end"))
        out["evidence"] = rows
        ocf, capex = _ttm_input(q, "operating_cash_flow"), _ttm_input(q, "capex")
        blocked = _blockers([ocf, capex])
        usable = lambda r, k: r["status"][k] == sq.USABLE and r[k] is not None
        pairs = [(a, b) for a, b in zip(rows, rows[1:]) if sq._gap(a["end"], b["end"]) <= 400]
        drops = [f"FY ending {a['end']}: revenue {(a['revenue'] / b['revenue'] - 1):+.0%}" for a, b in pairs
                 if usable(a, "revenue") and usable(b, "revenue") and b["revenue"] > 0
                 and a["revenue"] / b["revenue"] - 1 <= -c["cyclical_revenue_drop"]]
        oi = [r["operating_income"] for r in rows if usable(r, "operating_income")]
        swing = any(v < 0 for v in oi) and any(v > 0 for v in oi)
        recent = rows[:c["compounder_years"]]
        gaps = [f"no fiscal year between {b['end']} and {a['end']}" for a, b in zip(rows, rows[1:])
                if sq._gap(a["end"], b["end"]) > 400]
        untrusted = [f"FY {r['end']}: " + "; ".join(r["issues"]) for r in rows
                     if not (usable(r, "revenue") and usable(r, "operating_income"))]
        untrusted += [f"FY {r['end']}: " + "; ".join(r["issues"]) for r in recent
                      if r["ocf_minus_capex"] is None and usable(r, "revenue") and usable(r, "operating_income")]
        if blocked:
            out.update(family=INSUFFICIENT, rule="trailing cash flow can't be read: " + "; ".join(blocked))
        elif ocf["value"] - capex["value"] < 0:
            out.update(family=CASH_BURN, rule=f"TTM operating cash flow minus capex is {_money(ocf['value'] - capex['value'])}")
        elif drops or swing:
            out.update(family=CYCLICAL, rule="; ".join(drops + ([f"an operating loss and an operating profit within "
                                                                 f"{len(rows)} fiscal years"] if swing else [])))
        elif len(rows) < c["min_history_years"]:
            out.update(family=INSUFFICIENT, rule=f"only {len(rows)} fiscal years of revenue: a cycle can't be ruled out")
        elif gaps or untrusted:
            out.update(family=INSUFFICIENT, rule="a cycle can't be ruled out from trusted figures: "
                                                 + "; ".join(gaps + untrusted))
        elif all(r["ocf_minus_capex"] > 0 for r in recent):
            out.update(family=COMPOUNDER, rule=f"OCF minus capex positive in each of the last {len(recent)} fiscal "
                                               f"years and no cycle in {len(rows)} usable years")
        else:
            out.update(family=INSUFFICIENT, rule="OCF minus capex not positive in each of the last "
                                                 f"{len(recent)} fiscal years, and no cycle found")
    out["not_applicable"] = NOT_APPLICABLE_MODELS[out["family"]]
    return out


# ------------------------------------------------------ reverse valuation

def present_value(fcf0: float, g: float, r: float, gt: float, years: int = 10, driver_years: int = 5) -> tuple[float, float]:
    """(value, terminal share): years 1..driver_years grow at g, then growth fades linearly to gt by the
    last year; a Gordon terminal value after the last year. Year-end discounting."""
    pv, f = 0.0, fcf0
    for t in range(1, years + 1):
        growth = g if t <= driver_years else g + (gt - g) * (t - driver_years) / (years - driver_years)
        f *= 1 + growth
        pv += f / (1 + r) ** t
    tv = f * (1 + gt) / (r - gt) / (1 + r) ** years
    return pv + tv, tv / (pv + tv)


def implied_growth(target: float, fcf0: float, r: float, gt: float, years: int = 10, driver_years: int = 5,
                   search: tuple[float, float] = (-0.5, 1.0)) -> dict:
    """The growth over years 1..driver_years at which present_value equals target (bisection)."""
    lo, hi = search
    if fcf0 <= 0 or target <= 0:
        return {"growth": None, "note": "needs positive cash flow and a positive market value"}
    if present_value(fcf0, lo, r, gt, years, driver_years)[0] > target:
        return {"growth": None, "note": f"below {lo:.0%} a year: the price implies shrinking cash flow"}
    if present_value(fcf0, hi, r, gt, years, driver_years)[0] < target:
        return {"growth": None, "note": f"above {hi:.0%} a year: more growth than this model can express"}
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if present_value(fcf0, mid, r, gt, years, driver_years)[0] < target else (lo, mid)
    g = (lo + hi) / 2
    return {"growth": g, "terminal_share": present_value(fcf0, g, r, gt, years, driver_years)[1], "note": None}


def _lease_funded(company: dict, ocf_ttm: dict, as_of: date) -> dict | None:
    """Assets obtained under new finance leases for the same fiscal year as the TTM, when the TTM is a
    single fiscal year: spending that isn't in capex."""
    concept = "RightOfUseAssetObtainedInExchangeForFinanceLeaseLiability"
    parts = ocf_ttm.get("parts") or []
    if len(parts) != 1:
        return None
    p = parts[0][1]
    facts = sq._candidates(company, [concept], "USD", as_of)[0].get(concept, [])
    same = [f for f in facts if f.get("start") == p["start"] and f["end"] == p["end"]]
    if not same:
        return None
    hit = max(same, key=lambda f: f.get("filed") or "")
    if sq._contest(same, hit, "USD"):
        return None
    return {"value": hit["val"], "source": f"{concept} {p['start']} to {p['end']}, {hit.get('form')} {hit.get('accn')}"}


def reverse_valuation(q: dict, company: dict, price: dict, as_of: date, cfg: dict) -> dict:
    """What annual growth the market price implies for owner free cash flow (OCF - capex - SBC), at
    each discount rate and terminal growth in the sensitivity grid. Not a fair value."""
    ocf, capex, sbc = (_ttm_input(q, k) for k in ("operating_cash_flow", "capex", "sbc"))
    shares = _cover_input(q)
    inputs = [price, shares, ocf, capex, sbc]
    out = {"model": "reverse valuation (owner free cash flow)", "inputs": inputs}
    blocked = _blockers(inputs)
    if blocked:
        return out | {"status": UNAVAILABLE, "reason": "; ".join(blocked)}
    p = cfg["projection"]
    mcap = price["value"] * shares["value"]
    bases = [("owner FCF: OCF - capex - SBC", ocf["value"] - capex["value"] - sbc["value"], None)]
    lease = _lease_funded(company, q["fields"]["operating_cash_flow"]["ttm"], as_of)
    if lease:
        bases.append(("owner FCF less assets obtained under new finance leases",
                      bases[0][1] - lease["value"], lease["source"]))
    grids = []
    for label, fcf0, source in bases:
        rows = []
        for r in cfg["discount"]["sensitivity_rates"]:
            for gt in p["terminal_sensitivity"]:
                if r - gt < cfg["discount"]["min_spread"]:
                    rows.append({"rate": r, "terminal": gt, "growth": None, "note": "rate too close to terminal growth"})
                    continue
                rows.append({"rate": r, "terminal": gt, **implied_growth(mcap, fcf0, r, gt, p["years"], p["driver_years"],
                                                                         tuple(p["growth_search"]))})
        grids.append({"basis": label, "fcf": fcf0, "source": source, "yield": fcf0 / mcap, "rows": rows})
    return out | {"status": COMPUTED, "market_cap": mcap, "grids": grids,
                  "notes": ["Sensitivity only: the discount rates are not a measured cost of capital (beta and cost of "
                            "debt aren't collected yet).",
                            "OCF is after interest, so this is an equity-level cash flow set against market cap.",
                            "Capex is gross: it includes growth capex, so owner FCF is conservative on that side.",
                            f"Years 1-{p['driver_years']} grow at the implied rate, years {p['driver_years'] + 1}-"
                            f"{p['years']} fade linearly to the terminal rate."]}


# -------------------------------------------------------------- runway

def _share_growth(company: dict, as_of: date, ref: dict) -> dict:
    """Growth in the diluted weighted-average share count (the EPS denominator) from the same quarter a
    year earlier. It isn't the number of shares issued. Both quarters must pass the quality checks
    (no contested or revised values) and the latest must be current; otherwise no percentage."""
    label = "Diluted weighted-average shares (EPS denominator), latest quarter vs a year earlier"
    _l, _k, unit, concepts = FIELDS["diluted_shares"]
    by_concept = sq._candidates(company, concepts, unit, as_of)[0]
    quarters = {c: [f for f in fs if f.get("start") and 70 <= _days(f) <= 110] for c, fs in by_concept.items()}
    end = max((f["end"] for fs in quarters.values() for f in fs), default=None)
    if not end:
        return _input(label, None, sq.UNKNOWN, None, ["no quarterly figure"])
    concept = next(c for c in concepts if any(f["end"] == end for f in quarters.get(c, [])))
    facts = quarters[concept]
    periods = lambda fs: sorted({(f["start"], f["end"]) for f in fs})
    now = periods(f for f in facts if f["end"] == end)
    if len(now) > 1:
        return _input(label, None, sq.RECONCILE, None, [
            f"{len(now)} different quarter periods end {end} ({', '.join(f'{a} to {b}' for a, b in now)}): ambiguous"])
    latest = max((f for f in facts if f["end"] == end), key=lambda f: f.get("filed") or "")
    target = date.fromisoformat(end) - timedelta(days=365)
    prior = [f for f in facts if abs((date.fromisoformat(f["end"]) - target).days) <= 10]
    if not prior:
        return _input(label, None, sq.UNKNOWN, None, [f"no {concept.split(':')[-1]} quarter ending about {target}"])
    then = periods(prior)
    if len(then) > 1:
        return _input(label, None, sq.RECONCILE, None, [
            f"{len(then)} different quarter periods a year earlier ({', '.join(f'{a} to {b}' for a, b in then)}): "
            "ambiguous"])
    before = max(prior, key=lambda f: f.get("filed") or "")
    if abs(_days(before) - _days(latest)) > 10:
        return _input(label, None, sq.RECONCILE, None, [
            f"the year-earlier quarter ({_days(before)} days) isn't comparable with the latest ({_days(latest)} days)"])
    cite = lambda f: f"{f['start']} to {f['end']}: {f['val']:,.0f}, {f.get('form')} {f.get('accn')} filed {f.get('filed')}"
    flags = [c for c in (sq._contest(facts, latest, "shares"), sq._contest(facts, before, "shares")) if c]
    # a quarterly figure is judged against the latest reported period, wherever it was filed (10-K or 10-Q)
    behind = sq._gap(ref["end"], end) if ref.get("end") else None
    if behind is None or behind > sq.INSTANT_STALE:
        flags.append((sq.STALE, f"latest quarter ends {end}, {behind} days before the company's latest report"
                      if behind is not None else "the company's latest reported period is unknown"))
    if not before["val"]:
        flags.append((sq.UNKNOWN, "the year-earlier count is zero"))
    status = sq._status(flags)
    value = latest["val"] / before["val"] - 1 if status == sq.USABLE else None
    return _input(label, value, status, f"{cite(latest)} vs {cite(before)}", [t for _, t in flags])


def runway(q: dict, company: dict, as_of: date) -> dict:
    """Months of cash at the trailing burn rate, and dilution so far. No intrinsic value."""
    cash, sti = _balance_input(q, "cash"), _balance_input(q, "short_term_investments")
    ocf, capex = _ttm_input(q, "operating_cash_flow"), _ttm_input(q, "capex")
    out = {"model": "cash runway and dilution", "inputs": [cash, sti, ocf, capex]}
    blocked = _blockers([cash, ocf, capex])
    if blocked:
        return out | {"status": UNAVAILABLE, "reason": "; ".join(blocked)}
    notes = ["Excludes undrawn credit lines, debt maturities and new financing (not collected).",
             "Intrinsic value: unavailable. A company burning cash has no positive cash flow to discount."]
    liquidity = cash["value"]
    if sti["status"] == sq.USABLE and sti["value"] is not None:
        liquidity += sti["value"]
    else:
        notes.insert(0, f"Short-term investments are {sti['status']}: left out, so runway may be understated.")
    burn = capex["value"] - ocf["value"]
    dilution = _share_growth(company, as_of, q["reference"])
    antidilutive = next((d for d in q["shares"]["dilution"] if d["key"] == "antidilutive"), None)
    return out | {"status": COMPUTED, "liquidity": liquidity, "burn": burn,
                  "months": liquidity / burn * 12 if burn > 0 else None,
                  "dilution": dilution, "antidilutive": antidilutive, "notes": notes}


# ----------------------------------------------------------- risk lenses

def total_debt(company: dict, as_of: date, day: str | None) -> dict:
    """Debt on the balance-sheet date, only where its parts reconcile; leases are listed separately.

    A total needs the long-term component confirmed (tagged, an explicit zero counts) and every
    tagged part consistent with the others. Otherwise there's no number: the status says why and the
    note gives any partial subtotal. A missing tag is never read as zero debt."""
    label = f"Total debt on {day}"
    if not day:
        return _input(label, None, sq.UNKNOWN, None, ["no balance-sheet date"])
    names = ("LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings",
             "CommercialPaper")
    facts = {}
    for c in names:
        cands = sq._candidates(company, [c], "USD", as_of)[0].get(c, [])
        f = sq._at(cands, day)
        if f and sq._contest(cands, f, "USD"):
            return _input(label, None, sq.UNKNOWN, None, [f"{c} has contested values on {day}"])
        facts[c] = f["val"] if f else None
    ltd, nc, cur, dc, stb, cp = (facts[c] for c in names)
    tagged = ", ".join(f"{c} {_money(v)}" for c, v in facts.items() if v is not None)

    def refuse(status, why):
        return _input(label, None, status, None, [why + (f" (tagged on this date: {tagged})" if tagged else "")])
    if stb is not None and cp is not None:
        return refuse(sq.RECONCILE, "short-term borrowings and commercial paper are both tagged: commercial paper may "
                                    "already be inside short-term borrowings")
    borrowings = stb if stb is not None else cp       # at most one of the two
    if ltd is None and nc is None:
        if dc is None and borrowings is None and cur is None:
            return _input(label, None, sq.UNKNOWN, None, ["no debt tagged on this date (zero debt isn't assumed)"])
        return refuse(sq.RECONCILE, "no long-term debt tagged on this date, so only current items are known and the "
                                    "total can't be confirmed")
    # the current portion of long-term debt: tagged, or implied by total minus noncurrent
    if ltd is not None and nc is not None:
        implied = ltd - nc
        if cur is not None and sq._differs(cur, implied, 0.005) and abs(cur - implied) > 1:
            return refuse(sq.RECONCILE, f"LongTermDebt {_money(ltd)} contradicts noncurrent {_money(nc)} + current "
                                        f"{_money(cur)}")
        if implied < -1:
            return refuse(sq.RECONCILE, f"LongTermDebt {_money(ltd)} is less than its noncurrent part {_money(nc)}")
        current_ltd, long_total, used = max(implied, 0.0), ltd, f"LongTermDebt {_money(ltd)} (noncurrent {_money(nc)})"
    elif nc is not None and cur is not None:
        current_ltd, long_total, used = cur, nc + cur, f"noncurrent {_money(nc)} + current portion {_money(cur)}"
    elif nc is not None and dc is not None:
        current_ltd, long_total, used = None, nc, f"noncurrent {_money(nc)}"
    else:
        return refuse(sq.RECONCILE, "the current portion of long-term debt can't be confirmed" if nc is not None else
                      "LongTermDebt alone: whether it includes the current portion can't be checked")
    if dc is not None:
        # DebtCurrent is all debt due within a year: the current portion plus short-term borrowings
        if current_ltd is not None:
            expected = current_ltd + (borrowings or 0)
            if sq._differs(dc, expected) and abs(dc - expected) > 1:
                return refuse(sq.RECONCILE, f"DebtCurrent {_money(dc)} doesn't match current portion "
                                            f"{_money(current_ltd)} + borrowings {_money(borrowings or 0)}")
            return _input(label, long_total + (borrowings or 0), sq.USABLE,
                          used + f"; due within a year {_money(dc)} (DebtCurrent, consistent)")
        if borrowings is not None and dc < borrowings:
            return refuse(sq.RECONCILE, f"DebtCurrent {_money(dc)} is less than short-term borrowings {_money(borrowings)}")
        return _input(label, long_total + dc, sq.USABLE, used + f" + DebtCurrent {_money(dc)} (all debt due within a year)")
    return _input(label, long_total + (borrowings or 0), sq.USABLE,
                  used + (f" + short-term borrowings {_money(borrowings)}" if borrowings is not None else ""))


def _net_debt(debt: dict, cash: dict, sti: dict) -> dict:
    """Debt - cash - short-term investments, only when all three are usable. With short-term
    investments not usable, the debt-less-cash figure is shown but labelled partial, with no value."""
    name = "Net debt (debt - cash - short-term investments)"
    blocked = _blockers([debt, cash])
    if blocked:
        return {"lens": name, "value": None, "text": "unknown: " + "; ".join(blocked)}
    if sti["status"] != sq.USABLE or sti["value"] is None:
        return {"lens": name, "value": None,
                "text": f"unknown: short-term investments are {sti['status']}. Partial only: debt less cash = "
                        f"{_money(debt['value'] - cash['value'])}"}
    v = debt["value"] - cash["value"] - sti["value"]
    return {"lens": name, "value": v, "text": _money(v)}


def risk_lenses(q: dict, company: dict, price: dict, as_of: date, cfg: dict) -> list[dict]:
    """P/E, owner cash yield, debt against operating cash, and how equipment-heavy the business is."""
    shares = _cover_input(q)
    ni, ocf, capex, sbc, rev, dna = (_ttm_input(q, k) for k in ("net_income", "operating_cash_flow", "capex", "sbc",
                                                                   "revenue", "dna"))
    mcap = price["value"] * shares["value"] if not _blockers([price, shares]) else None
    debt = total_debt(company, as_of, q["balance_sheet"].get("date"))
    cash, sti = _balance_input(q, "cash"), _balance_input(q, "short_term_investments")

    def lens(name, needs, fn, fmt):
        blocked = _blockers(needs)
        if blocked:
            return {"lens": name, "value": None, "text": "unknown: " + "; ".join(blocked)}
        v = fn()
        return {"lens": name, "value": v, "text": fmt(v)}
    lenses = [
        lens("P/E (market cap / TTM net income)", [price, shares, ni], lambda: mcap / ni["value"] if ni["value"] > 0 else None,
             lambda v: f"{v:.0f}x" if v is not None else "n/a: loss over the last twelve months"),
        lens("Owner FCF yield ((OCF - capex - SBC) / market cap)", [price, shares, ocf, capex, sbc],
             lambda: (ocf["value"] - capex["value"] - sbc["value"]) / mcap, lambda v: f"{v:.1%}"),
        lens("Debt / TTM operating cash flow", [debt, ocf], lambda: debt["value"] / ocf["value"] if ocf["value"] > 0 else None,
             lambda v: f"{v:.1f} years of operating cash" if v is not None else "n/a: operating cash flow not positive"),
        _net_debt(debt, cash, sti),
        lens("Capex / revenue (TTM)", [capex, rev], lambda: capex["value"] / rev["value"] if rev["value"] > 0 else None,
             lambda v: "n/a: no revenue over the last twelve months" if v is None else
             f"{v:.0%}" + (" — equipment-heavy" if v > cfg["risk"]["capex_heavy"] else "")),
        lens("Capex / D&A (TTM)", [capex, dna], lambda: capex["value"] / dna["value"] if dna["value"] else None,
             lambda v: f"{v:.1f}x" if v is not None else "n/a"),
    ]
    lenses.append({"lens": "Equipment / GPU useful life and replacement", "value": None,
                   "text": "N/A in 2A-1: depreciation lives aren't collected"})
    return lenses


# ------------------------------------------------------------ per company

def value_company(ticker: str, company: dict, submissions: dict | None, price: dict, as_of: date | None = None,
                  cfg: dict | None = None) -> dict:
    as_of = as_of or date.today()
    cfg = cfg or load_assumptions()
    q = sq.quality_company(ticker, company, submissions, as_of)
    cls = classify(q, company, as_of, cfg)
    family = cls["family"]
    if family == COMPOUNDER:
        model = reverse_valuation(q, company, price, as_of, cfg)
    elif family == CASH_BURN:
        model = runway(q, company, as_of)
    elif family == CYCLICAL:
        model = {"model": "mid-cycle normalization", "status": DEFERRED,
                 "reason": "the cycle-normalized model is part of 2A-2; the cycle evidence is below"}
    elif family == BANK:
        model = {"model": "P/TBV against sustainable ROE", "status": UNAVAILABLE,
                 "reason": "bank inputs aren't collected yet: " + "; ".join(BANK_NEEDS)}
    else:
        model = {"model": "none", "status": UNAVAILABLE, "reason": cls["rule"]}
    lenses = risk_lenses(q, company, price, as_of, cfg) if family in (COMPOUNDER, CYCLICAL, CASH_BURN) else []
    return {"ticker": q["ticker"], "status": "ok", "name": q["name"], "as_of": as_of.isoformat(),
            "assumptions_version": cfg["version"], "classification": cls, "price": price, "model": model,
            "risk": lenses, "data_quality": q["counts"]}


def value_ticker(ticker: str, as_of: date | None = None, price: dict | None = None, cfg: dict | None = None,
                 get=None, lookup=None, price_fn=None) -> dict:
    """Download and value one ticker. Network problems give an "unavailable" entry with the reason."""
    as_of = as_of or date.today()
    get, lookup, price_fn = get or sec._get, lookup or sec.cik_lookup, price_fn or fetch_price
    try:
        cik, why = lookup(ticker)
        if cik is None:
            return {"ticker": ticker.upper(), "status": "unavailable", "reason": why or "no SEC CIK for this ticker"}
        company = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
        try:
            submissions = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        except Exception:
            submissions = None
        return value_company(ticker, company, submissions, price or price_fn(ticker, as_of), as_of, cfg)
    except Exception as e:
        return {"ticker": ticker.upper(), "status": "unavailable", "reason": f"{type(e).__name__}: {e}"}


# ------------------------------------------------------------------ report

def _runway_text(months: float | None) -> str:
    if months is None:
        return "not burning cash over the trailing twelve months"
    if months <= 0:
        return "runway exhausted: no liquidity left at the trailing burn"
    return f"runway about {months:.0f} months at the trailing burn"


def _headline(r: dict) -> str:
    m = r["model"]
    if m["status"] != COMPUTED:
        return f"{m['status']}: {m.get('reason', '')}"
    if "grids" in m:
        cell = next((x for x in m["grids"][0]["rows"] if x["rate"] == 0.10 and x["terminal"] == 0.025), None)
        if cell and cell["growth"] is not None:
            return f"price implies {cell['growth']:+.1%}/yr owner-FCF growth for 5 years (at 10% / 2.5%, sensitivity only)"
        return "see grid"
    return _runway_text(m["months"])


def markdown(reports: list[dict], as_of: date | None = None, cfg: dict | None = None, ua_status: str | None = None) -> str:
    as_of = as_of or date.today()
    cfg = cfg or load_assumptions()
    sm = summary(reports)
    ok = [r for r in reports if r["status"] == "ok"]
    gone = [f"{r['ticker']} ({r['reason']})" for r in reports if r["status"] != "ok"]
    lines = [f"# Valuation research (Phase 2A-1), as of {as_of.isoformat()}", "",
             f"**Status: {sm['status']}**: {sm['available']} of {sm['total']} companies retrieved"
             + (f"; unavailable: {', '.join(gone)}" if gone else "") + ".", "", identification_line(ua_status), "",
             "**Research only.** No fair value, BUY/SELL, score or probability. Inputs come from the Phase 1B "
             "data-quality checks with their status and filing; a critical input that isn't usable makes the model "
             f"unavailable. Assumptions: `valuation_assumptions.yaml` version {cfg['version']}, not adopted as policy.", ""]
    if ok:
        lines += ["| Company | Classification | Model | Result |", "|---|---|---|---|"]
        lines += [f"| {r['ticker']} | {r['classification']['family']} | {r['model']['model']} | {_headline(r)} |" for r in ok]
        lines.append("")
    for r in reports:
        lines += [f"## {r['ticker']}" + (f": {r['name']}" if r.get("name") else ""), ""]
        if r["status"] != "ok":
            lines += [f"Unavailable: {r['reason']}", ""]
            continue
        cls, m = r["classification"], r["model"]
        lines += [f"**Classification: {cls['family']}.** Why: {cls['rule']}.", "",
                  "Not used here: " + "; ".join(cls["not_applicable"]) + ".", ""]
        if cls["evidence"]:
            lines += ["| Fiscal year to | Revenue | Operating income | OCF | Capex | OCF - capex | Periods reported | "
                      "Data issues |", "|---|---|---|---|---|---|---|---|"]
            lines += [f"| {e['end']} | {_money(e['revenue'])} | {_money(e['operating_income'])} | "
                      f"{_money(e['operating_cash_flow'])} | {_money(e['capex'])} | {_money(e['ocf_minus_capex'])} | "
                      f"{'; '.join(e['periods']) or '—'} | {'; '.join(e['issues']) or '—'} |" for e in cls["evidence"]]
            lines.append("")
        lines += [f"### Model: {m['model']} ({m['status']})", ""]
        if m.get("inputs"):
            lines += ["| Input | Value | Status | Source | Notes |", "|---|---|---|---|---|"]
            for i in m["inputs"]:
                v = i["value"]
                shown = "—" if v is None else (f"${v:,.2f}" if i["label"] == "Share price" else
                                               f"{v:,.0f}" if "Shares" in i["label"] else _money(v))
                lines.append(f"| {i['label']} | {shown} | {i['status']} | {i['source'] or '—'} | "
                             f"{'; '.join(i['notes']) or '—'} |")
            lines.append("")
        if m["status"] != COMPUTED:
            lines += [f"Why: {m['reason']}", ""]
        elif "grids" in m:
            lines += [f"Market cap: {_money(m['market_cap'])} (price × cover-page shares).", ""]
            terms = cfg["projection"]["terminal_sensitivity"]
            for g in m["grids"]:
                lines += [f"**{g['basis']}: {_money(g['fcf'])}** (yield {g['yield']:.1%})"
                          + (f"; source {g['source']}" if g["source"] else "") + ".", "",
                          "| Implied growth, years 1-5 | " + " | ".join(f"terminal {t:.1%}" for t in terms) + " |",
                          "|---|" + "---|" * len(terms)]
                for rate in cfg["discount"]["sensitivity_rates"]:
                    cells = [next(x for x in g["rows"] if x["rate"] == rate and x["terminal"] == t) for t in terms]
                    lines.append(f"| discount {rate:.0%} | " + " | ".join(
                        f"{x['growth']:+.1%}/yr (terminal {x['terminal_share']:.0%} of value)" if x["growth"] is not None
                        else x["note"] for x in cells) + " |")
                lines.append("")
            lines += [f"- {n}" for n in m["notes"]] + [""]
        else:
            d = m["dilution"]
            lines += [f"Liquidity {_money(m['liquidity'])}; trailing burn (capex - OCF) {_money(m['burn'])} a year; "
                      + f"**{_runway_text(m['months'])}**.", "",
                      f"Dilution: {d['label']}: " + (f"{d['value']:+.1%} ({d['source']})" if d["value"] is not None
                                                      else f"{d['status']} ({'; '.join(d['notes'])})") + "."]
            a = m["antidilutive"]
            if a and a["source"]:
                lines.append(f"Securities left out of diluted EPS (could dilute later): {a['source']['value']:,.0f} "
                             f"({a['status']}, period to {a['source']['end']}).")
            lines += [""] + [f"- {n}" for n in m["notes"]] + [""]
        if r["risk"]:
            lines += ["### Risk lenses", "", "| Lens | Reading |", "|---|---|"]
            lines += [f"| {x['lens']} | {x['text']} |" for x in r["risk"]] + [""]
    return "\n".join(lines)


def _price_arg(text: str) -> tuple[str, dict]:
    ticker, value = text.split("=", 1)
    return ticker.upper(), _input("Share price", float(value), sq.USABLE, "given on the command line")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Read-only valuation research (Phase 2A-1)")
    p.add_argument("tickers", nargs="+", help="public example tickers only (the repo is public)")
    p.add_argument("--as-of", type=date.fromisoformat, help="use only filings and prices up to this date")
    p.add_argument("--price", action="append", default=[], metavar="TICKER=PRICE",
                   help="use this share price instead of fetching it")
    p.add_argument("--json", help="write the full result as JSON to this file")
    p.add_argument("--markdown", help="write the report as Markdown to this file (default: print it)")
    args = p.parse_args(argv)
    as_of, cfg = args.as_of or date.today(), load_assumptions()
    given = dict(_price_arg(t) for t in args.price)
    reports = [value_ticker(t, as_of, given.get(t.upper()), cfg) for t in args.tickers]
    sm = summary(reports)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(reports, fh, indent=1, default=str)
    report = markdown(reports, as_of, cfg)
    if args.markdown:
        with open(args.markdown, "w") as fh:
            fh.write(report)
    else:
        print(report)
    print(f"Valuation research: {sm['status']} ({sm['available']} of {sm['total']} companies); "
          f"SEC_USER_AGENT {sec.user_agent_status()}", file=sys.stderr)
    return sm["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
