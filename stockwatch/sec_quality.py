"""Read-only data-quality checks on SEC XBRL figures (Phase 1B of the valuation work, Issue #2).

Phase 1 (sec_audit) showed which inputs SEC provides. This checks whether the figure each input would
use is fit to use: which fact was selected and from which filing, whether its period is right, whether
it was revised or amended later, whether other tags or duplicate facts disagree, whether it is stale
next to the company's latest report, and, for chosen issuers, whether SEC's figure is the one tagged in
the issuer's own filing.

Every figure gets a status: usable, needs reconciliation, stale, unknown or not applicable. Nothing is
estimated, filled in or normalized into a new number, and there is no valuation, score or signal here.
Nothing in the app imports this module. Run it with explicit public tickers:

    python -m stockwatch.sec_quality MSFT MU RIVN BRK-B JPM AVGO --reconcile MSFT MU AVGO --markdown q.md
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from . import sec
from .sec_audit import (ANNUAL_FORMS, FIELDS, _concept_facts, _days, _money, identification_line, summary)

USABLE, RECONCILE, STALE, UNKNOWN, NOT_APPLICABLE = (
    "usable", "needs reconciliation", "stale", "unknown", "not applicable")
STATUSES = (USABLE, RECONCILE, STALE, UNKNOWN, NOT_APPLICABLE)
_RANK = {USABLE: 0, RECONCILE: 1, STALE: 2, UNKNOWN: 3}

TOLERANCE = 0.005      # two figures more than 0.5% apart disagree
INSTANT_STALE = 10     # days a balance-sheet figure may trail the company's latest balance sheet
FY_STALE = 30          # days a fiscal-year figure may trail the company's latest fiscal year
REPORT_STALE = 200     # days without any new report before every figure counts as stale
CORE_FLOWS = ("revenue", "net_income", "operating_cash_flow")   # what sets the company's latest fiscal year

# Checked against the issuer's own filing when --reconcile names the company
RECONCILE_FIELDS = ("revenue", "net_income", "operating_cash_flow", "capex")
# Reported next to capex for the same period, so gross cash capex isn't mistaken for net, lease-funded
# or maintenance capex. Observed only; nothing is added or subtracted.
CAPEX_CONTEXT = {
    "ProceedsFromSaleOfPropertyPlantAndEquipment": "proceeds from selling PP&E (net capex would subtract these)",
    "PaymentsToAcquireProductiveAssets": "payments for productive assets (can include intangibles)",
    "FinanceLeasePrincipalPayments": "finance-lease principal payments (assets funded by leases, outside capex)",
    "RightOfUseAssetObtainedInExchangeForFinanceLeaseLiability":
        "assets obtained under new finance leases (non-cash, outside capex)",
}
# Tags that measure something wider or narrower than a field's main tag. A different amount from one of
# these is a difference in scope, not a conflict; but when one is the tag selected, a person must check
# it's the definition wanted.
SCOPE = {
    "Revenues": "all revenue, which can include more than revenue from customer contracts",
    "RevenueFromContractWithCustomerIncludingAssessedTax": "includes taxes collected from customers",
    "ProfitLoss": "includes noncontrolling interests",
    "NetIncomeLossAvailableToCommonStockholdersBasic": "after preferred dividends",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations": "continuing operations only",
    "PaymentsToAcquireProductiveAssets": "can include intangibles and other productive assets",
    "AllocatedShareBasedCompensationExpense": "the expense recognized, which can differ from the cash-flow add-back",
    "Depreciation": "depreciation only, without amortization",
    "DepreciationAmortizationAndAccretionNet": "includes accretion",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": "includes restricted cash",
    "LongTermDebt": "total including the current portion",
    "OperatingLeaseLiability": "total including the current portion",
    "FinanceLeaseLiability": "total including the current portion",
    "OperatingLeaseLiabilityNoncurrent": "noncurrent portion only",
    "FinanceLeaseLiabilityNoncurrent": "noncurrent portion only",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": "includes noncontrolling interests",
    "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization":
        "includes finance-lease right-of-use assets",
    "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetBeforeAccumulatedDepreciationAndAmortization":
        "includes finance-lease right-of-use assets",
}
BALANCE = ("cash", "short_term_investments", "debt_current", "debt_long", "operating_leases", "finance_leases")
LEASE_CURRENT = {"operating_leases": "OperatingLeaseLiabilityCurrent", "finance_leases": "FinanceLeaseLiabilityCurrent"}
DILUTION = {
    "options": ("Stock options outstanding",
                "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber"),
    "unvested_awards": ("Unvested share awards (RSUs and similar)",
                        "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber"),
    "antidilutive": ("Securities left out of diluted EPS (antidilutive)",
                     "AntidilutiveSecuritiesExcludedFromComputationOfEarningsPerShareAmount"),
    "convertible": ("Shares issuable on converting debt", "DebtInstrumentConvertibleNumberOfEquityInstruments"),
}

# Generic measures that don't mean the same thing for financial companies
GENERIC_NOT_APPLICABLE = {
    "operating_income": "operating income (EBIT) isn't how a financial company's earnings are measured",
    "operating_cash_flow": "operating cash flow includes lending, deposit, trading or insurance float flows",
    "capex": "capex-based free cash flow doesn't describe a financial company",
    "short_term_investments": "investments are the business itself, not spare cash",
    "debt_current": "borrowing is funding for the business, not capital structure to net against cash",
    "debt_long": "borrowing is funding for the business, not capital structure to net against cash",
}
GENERIC_COMPARISONS = ["free cash flow (operating cash flow minus capex)", "EBIT and operating margin",
                       "net debt and enterprise value", "current ratio", "debt/equity"]
SECTOR_NEEDS = {
    "bank": ["net interest income and noninterest income", "provision for credit losses and net charge-offs",
             "loans and deposits", "tangible common equity and CET1 capital ratio",
             "return on tangible common equity"],
    "insurance": ["premiums earned", "losses and loss-adjustment expenses (combined ratio)",
                  "insurance reserves (float) and the investment portfolio", "investment gains and losses",
                  "book value per share for each share class",
                  "segment results for non-insurance businesses (a conglomerate)"],
    "financial": ["segment revenue and earnings", "book value", "regulatory capital where it applies"],
}


# ------------------------------------------------------------------ helpers

def _differs(a: float, b: float, tol: float = TOLERANCE) -> bool:
    if a == b:
        return False
    return abs(a - b) / max(abs(a), abs(b)) > tol


def _gap(later: str, earlier: str) -> int:
    return (date.fromisoformat(later) - date.fromisoformat(earlier)).days


def _filed_by(facts: list[dict], as_of: date) -> list[dict]:
    """No look-ahead: only facts filed on or before as_of, for periods that had ended by then."""
    day = as_of.isoformat()
    return [f for f in facts if (f.get("filed") or "") <= day and f["end"] <= day]


def _is_annual(f: dict) -> bool:
    return str(f.get("form", "")).startswith(ANNUAL_FORMS) and 350 <= (_days(f) or 0) <= 380


def _candidates(company: dict, concepts: list[str], unit: str, as_of: date) -> tuple[dict, set]:
    """{concept: facts filed by as_of} in priority order, and every unit seen."""
    out, units = {}, set()
    for c in concepts:
        facts, seen = _concept_facts(company, c, unit)
        units |= seen
        facts = _filed_by(facts, as_of)
        if facts:
            out[c] = facts
    return out, units


def _source(f: dict, concept: str) -> dict:
    return {"concept": concept.split(":")[-1], "value": f["val"], "start": f.get("start"), "end": f["end"],
            "form": f.get("form"), "filed": f.get("filed"), "accn": f.get("accn")}


def _fmt(v, unit: str) -> str:
    if v is None:
        return "—"
    if unit == "shares":
        return f"{v:,.0f} shares"
    if unit == "USD/shares":
        return f"${v:,.2f}"
    return _money(v)


def _period(s: dict) -> str:
    if s.get("start"):
        return f"{s['start']} to {s['end']} ({_days(s)} days)"
    return f"on {s['end']}"


def _cite(s: dict) -> str:
    return f"{s['concept']} · {s.get('form') or '—'} filed {s.get('filed') or '—'} · {s.get('accn') or 'no accession'}"


def _pct(alt: float, base: float) -> str:
    return f"{alt / base - 1:+.1%}" if base else "n/a"


def _scope_flag(concept: str, concepts: list[str]) -> tuple[str, str] | None:
    """A fallback tag with a known different scope was selected: a person must check the definition."""
    name = concept.split(":")[-1]
    if concept != concepts[0] and name in SCOPE:
        return RECONCILE, f"selected tag {name} ({SCOPE[name]}): check it's the definition wanted"
    return None


def _behind(f: dict, ref: dict) -> int | None:
    """Days a figure trails the company's latest report: annual-report disclosures against the latest
    fiscal year (they're only published once a year), others against the latest period."""
    base = ref["fy_end"] if str(f.get("form", "")).startswith(ANNUAL_FORMS) and ref["fy_end"] else ref["end"]
    return _gap(base, f["end"]) if base else None


def _status(flags: list[tuple[str, str]]) -> str:
    return max((s for s, _ in flags), key=_RANK.get, default=USABLE)


# --------------------------------------------------------- company reference

def reference(company: dict, as_of: date) -> dict:
    """The company's latest reported period, and its latest fiscal year, from filings made by as_of.
    Staleness is judged against these rather than today's date: an annual figure isn't stale just
    because the next fiscal year hasn't ended yet."""
    ends, fy_ends = [], []
    for key, (_label, _kind, unit, concepts) in FIELDS.items():
        if key == "shares_outstanding":
            continue
        for facts in _candidates(company, concepts, unit, as_of)[0].values():
            ends += [f["end"] for f in facts]
            if key in CORE_FLOWS:
                fy_ends += [f["end"] for f in facts if _is_annual(f)]
    end = max(ends, default=None)
    return {"end": end, "fy_end": max(fy_ends, default=None),
            "age": (as_of - date.fromisoformat(end)).days if end else None}


# ------------------------------------------------------- field selection

def select(company: dict, key: str, as_of: date, ref: dict) -> dict:
    """The figure an input would use, where it came from, and why it can or can't be used as is.

    Flows (income, cash flow, share averages): the latest fiscal year in an annual report. Instants
    (balance sheet, cover-page shares): the latest date. The first concept in FIELDS' priority order
    that reports that period is selected; other concepts reporting the same period are compared."""
    label, kind, unit, concepts = FIELDS[key]
    out = {"key": key, "label": label, "kind": kind, "unit": unit, "selected": None, "first": None,
           "alternatives": [], "carried": []}
    by_concept, units = _candidates(company, concepts, unit, as_of)
    periods = {c: [f for f in fs if kind == "instant" or _is_annual(f)] for c, fs in by_concept.items()}
    periods = {c: fs for c, fs in periods.items() if fs}
    if not periods:
        other = sorted(units - {unit})
        if other:
            why = f"reported only in {', '.join(other)}, not {unit}; nothing is converted"
        elif by_concept:
            why = "no full fiscal-year figure in an annual report (only shorter periods)"
        else:
            why = "not reported under " + ", ".join(c.split(":")[-1] for c in concepts)
            if key == "shares_outstanding":
                why += (" in SEC's company facts (companies with several share classes often report the "
                        "cover-page count per class, which this data leaves out)")
        out.update(status=UNKNOWN, issues=[why])
        return out

    end = max(f["end"] for fs in periods.values() for f in fs)
    concept = next(c for c in concepts if any(f["end"] == end for f in periods.get(c, [])))
    group = sorted((f for f in periods[concept] if f["end"] == end), key=lambda f: f.get("filed") or "")
    first, latest = group[0], group[-1]
    flags: list[tuple[str, str]] = []

    starts = sorted({f.get("start") for f in group if f.get("start")})
    if len(starts) > 1:
        flags.append((RECONCILE, f"{len(starts)} different period starts for the period ending {end} "
                                 f"({', '.join(starts)}): a fiscal-year change or a tagging error"))
        out["carried"].append(flags[-1][1])
    by_filing: dict = {}
    for f in group:
        by_filing.setdefault(f.get("accn"), set()).add(f["val"])
    multi = {a: sorted(v) for a, v in by_filing.items() if len(v) > 1}
    if multi and key == "shares_outstanding":
        vals = next(iter(multi.values()))
        flags.append((RECONCILE, f"{len(vals)} share counts for {end} ({', '.join(f'{v:,.0f}' for v in vals)}): "
                                 "several share classes, not one total; per-share figures need every class "
                                 "and the conversion between them"))
    elif multi:
        flags.append((RECONCILE, "the same filing reports different values for this period: "
                                 + "; ".join(f"{a}: {', '.join(_fmt(v, unit) for v in vs)}" for a, vs in multi.items())))
    if first.get("accn") != latest.get("accn") and _differs(first["val"], latest["val"]):
        out["first"] = _source(first, concept)
        flags.append((RECONCILE, f"revised: first filed as {_fmt(first['val'], unit)} on {first.get('filed')} "
                                 f"({first.get('accn')}), now {_fmt(latest['val'], unit)} "
                                 f"({latest.get('filed')}, {latest.get('accn')})"))
    amended = sorted({f.get("form") for f in group if str(f.get("form", "")).endswith("/A")})
    if amended:
        flags.append((USABLE, f"includes an amended filing ({', '.join(amended)})"))

    for c, fs in periods.items():
        same = sorted((f for f in fs if c != concept and f["end"] == end and f.get("start") == latest.get("start")),
                      key=lambda f: f.get("filed") or "")
        if same:
            out["alternatives"].append({"concept": c.split(":")[-1], "value": same[-1]["val"]})
    name = concept.split(":")[-1]
    differ = [a for a in out["alternatives"] if _differs(a["value"], latest["val"])]
    scoped = [a for a in differ if a["concept"] in SCOPE or name in SCOPE]
    clash = [a for a in differ if a not in scoped]
    if scoped:
        flags.append((USABLE, "other tags with a different scope: " + ", ".join(
            f"{a['concept']} {_fmt(a['value'], unit)} ({_pct(a['value'], latest['val'])}"
            + (f"; {SCOPE[a['concept']]}" if a["concept"] in SCOPE else "") + ")" for a in scoped)
            + (f"; the selected {name} is {SCOPE[name]}" if name in SCOPE else "")))
    if clash:
        flags.append((RECONCILE, "other tags disagree for the same period: " + ", ".join(
            f"{a['concept']} {_fmt(a['value'], unit)} ({_pct(a['value'], latest['val'])})" for a in clash)
            + f" vs {name} {_fmt(latest['val'], unit)}"))
        out["carried"].append(flags[-1][1])
    if (scope := _scope_flag(concept, concepts)):
        flags.append(scope)
        out["carried"].append(scope[1])

    if kind == "instant" and ref["end"] and _gap(ref["end"], end) > INSTANT_STALE:
        flags.append((STALE, f"latest figure is for {end}, {_gap(ref['end'], end)} days before the company's "
                             f"latest report ({ref['end']}); don't use it as current"))
    if kind == "flow" and ref["fy_end"] and _gap(ref["fy_end"], end) > FY_STALE:
        flags.append((STALE, f"latest fiscal year here ends {end}; the company has already reported the year "
                             f"ending {ref['fy_end']} for other figures"))
    if ref["age"] is not None and ref["age"] > REPORT_STALE:
        flags.append((STALE, f"the company's latest report is for {ref['end']}, {ref['age']} days before "
                             f"{as_of.isoformat()}"))

    out.update(selected=_source(latest, concept), status=_status(flags), issues=[t for _, t in flags])
    if multi:
        out["selected"]["value"] = None      # several values for one period: none of them is "the" figure
    return out


def _find(facts: list[dict], end: date, length: int) -> dict | None:
    cands = [f for f in facts if f.get("start") and abs((date.fromisoformat(f["end"]) - end).days) <= 10
             and abs(_days(f) - length) <= 12]
    return max(cands, key=lambda f: f.get("filed") or "") if cands else None


def _contest(facts: list[dict], part: dict, unit: str) -> tuple[str, str] | None:
    """Does any other fact give a different value for this part's exact period? Two values in one filing
    leave no trustworthy number (unknown); a different value in another filing is a revision a person
    must reconcile. Every filing involved is named."""
    same = sorted((f for f in facts if f.get("start") == part.get("start") and f["end"] == part["end"]),
                  key=lambda f: f.get("filed") or "")
    by_filing: dict = {}
    for f in same:
        by_filing.setdefault(f.get("accn"), set()).add(f["val"])
    period = f"{part['start']} to {part['end']}" if part.get("start") else part["end"]
    dup = {a: v for a, v in by_filing.items() if len(v) > 1}
    if dup:
        return UNKNOWN, f"one filing gives several values for {period} (" + "; ".join(
            f"{a}: {', '.join(_fmt(v, unit) for v in sorted(vs))}" for a, vs in dup.items()) + "): no number is trusted"
    vals = [f["val"] for f in same]
    if any(_differs(v, part["val"]) for v in vals):
        return RECONCILE, f"{period} was revised: " + ", ".join(
            f"{_fmt(f['val'], unit)} ({f.get('accn')}, filed {f.get('filed')})" for f in same)
    return None


def ttm(company: dict, key: str, as_of: date, ref: dict, selection: dict | None = None) -> dict:
    """Trailing twelve months with the facts it's built from (the same rule as the app's SEC fallback:
    latest year-to-date + last fiscal year - the same year-to-date a year earlier, one concept).

    A part that was revised, or that one filing contradicts, makes the result needs reconciliation or
    unknown; so do the fiscal year's own problems found by select() (conflicting tags, scope)."""
    _label, _kind, unit, concepts = FIELDS[key]
    by_concept = {c: [f for f in fs if f.get("start")]
                  for c, fs in _candidates(company, concepts, unit, as_of)[0].items()}
    by_concept = {c: fs for c, fs in by_concept.items() if fs}
    if not by_concept:
        return {"status": UNKNOWN, "reason": "no period figures", "concept": None, "end": None, "value": None,
                "parts": []}
    newest = max(max(f["end"] for f in fs) for fs in by_concept.values())
    concept = next(c for c in concepts if c in by_concept and max(f["end"] for f in by_concept[c]) == newest)
    facts = by_concept[concept]
    at_end = [f for f in facts if f["end"] == newest and _days(f) <= 380]
    out = {"concept": concept.split(":")[-1], "end": newest, "value": None, "parts": []}
    if not at_end:
        return out | {"status": UNKNOWN, "reason": f"no period of a year or less ends {newest}"}
    ytd = max(at_end, key=lambda f: (_days(f), f.get("filed") or ""))
    d = _days(ytd)
    flags: list[tuple[str, str]] = []
    if d >= 350:
        fy, chosen = ytd, [("fiscal year", ytd)]
        value = ytd["val"]
    else:
        fy = _find(facts, date.fromisoformat(ytd["start"]) - timedelta(days=1), 365)
        prior = _find(facts, date.fromisoformat(ytd["end"]) - timedelta(days=365), d)
        missing = [name for name, f in (("last fiscal year", fy), (f"same {d}-day period a year earlier", prior))
                   if not f]
        if missing:
            return out | {"status": UNKNOWN, "reason": "can't be built: no " + " and no ".join(missing)}
        chosen = [("year to date", ytd), ("+ last fiscal year", fy), ("- same period a year earlier", prior)]
        value = ytd["val"] + fy["val"] - prior["val"]
        if abs(_gap(prior["start"], fy["start"])) > 10:
            flags.append((RECONCILE, f"the year-earlier period starts {prior['start']}, not with that fiscal year "
                                     f"({fy['start']}): the parts don't line up"))
    for _name, part in chosen:
        if (c := _contest(facts, part, unit)):
            flags.append(c)
    sel = (selection or {}).get("selected")
    if sel and sel["concept"] == out["concept"] and sel["start"] == fy.get("start") and sel["end"] == fy["end"]:
        flags += [(RECONCILE, f"fiscal-year figure: {t}") for t in selection.get("carried", [])]
    if ref["end"] and _gap(ref["end"], newest) > INSTANT_STALE:
        flags.append((STALE, f"ends {newest}; the company's latest report is for {ref['end']}"))
    status = _status(flags)
    out.update(value=None if status == UNKNOWN else value, status=status,
               parts=[(name, _source(f, concept)) for name, f in chosen])
    if flags:
        out["reason"] = "; ".join(t for _, t in flags)
    return out


# ------------------------------------------------- balance sheet and shares

def _at(facts: list[dict], day: str) -> dict | None:
    on = [f for f in facts if f["end"] == day]
    return max(on, key=lambda f: f.get("filed") or "") if on else None


def balance_sheet(company: dict, as_of: date) -> dict:
    """Cash, investments, debt and leases on one date: the company's latest balance sheet. A figure not
    reported for that date is unknown, never carried forward from an older date."""
    days = []
    for key in ("cash", "equity"):
        _l, _k, unit, concepts = FIELDS[key]
        days += [f["end"] for fs in _candidates(company, concepts, unit, as_of)[0].values() for f in fs]
    if not days:
        return {"date": None, "rows": [], "status": UNKNOWN, "reason": "no balance-sheet date (no cash or equity)"}
    day = max(days)
    rows = []
    for key in BALANCE:
        label, _kind, unit, concepts = FIELDS[key]
        by_concept = _candidates(company, concepts, unit, as_of)[0]
        on = [(c, f) for c in concepts if (f := _at(by_concept.get(c, []), day))]
        row = {"key": key, "label": label, "value": None, "concept": None, "notes": []}
        if not on:
            latest = max((f["end"] for fs in by_concept.values() for f in fs), default=None)
            row.update(status=UNKNOWN, notes=[f"not reported for {day}" + (
                f"; latest is for {latest}, not used" if latest else "; never reported")])
            rows.append(row)
            continue
        concept, f = on[0]
        flags: list[tuple[str, str]] = []
        name = concept.split(":")[-1]
        row.update(value=f["val"], concept=name, filed=f.get("filed"), accn=f.get("accn"))
        # the same rule as select(): two values in one filing leave no number, a revision needs a person
        if (contested := _contest(by_concept[concept], f, unit)):
            flags.append(contested)
            if contested[0] == UNKNOWN:
                row["value"] = None
        if len(on) > 1:
            for c, g in on[1:]:
                other = c.split(":")[-1]
                if key == "debt_current":
                    flags.append((RECONCILE, f"also tagged on this date: {other} {_money(g['val'])} "
                                             "(separate items: listed, not added up)"))
                elif _differs(f["val"], g["val"]):
                    scoped = other in SCOPE or name in SCOPE
                    flags.append((USABLE if scoped else RECONCILE,
                                  f"other tags {'with a different scope' if scoped else 'disagree'}: "
                                  f"{other} {_money(g['val'])} vs {name} {_money(f['val'])}"
                                  + (f"; {SCOPE.get(other, SCOPE.get(name))}" if scoped else "")))
        if (scope := _scope_flag(concept, concepts)):
            flags.append(scope)
        if key in LEASE_CURRENT and name.endswith("Noncurrent"):
            cur = _at(_candidates(company, [LEASE_CURRENT[key]], "USD", as_of)[0].get(LEASE_CURRENT[key], []), day)
            flags.append((RECONCILE, "current portion " + (f"{_money(cur['val'])} ({LEASE_CURRENT[key]}), "
                                                           "reported separately" if cur else "not reported")))
        row.update(status=_status(flags), notes=[t for _, t in flags])
        rows.append(row)
    # where both are tagged, total long-term debt should equal its noncurrent plus current portions
    parts = {c: _at(_candidates(company, [c], "USD", as_of)[0].get(c, []), day)
             for c in ("LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtCurrent")}
    contested = [c for c, f in parts.items()
                 if f and _contest(_candidates(company, [c], "USD", as_of)[0][c], f, "USD")]
    if all(parts.values()) and contested:
        next(r for r in rows if r["key"] == "debt_long")["notes"].append(
            "total vs noncurrent + current not checked: " + ", ".join(contested) + " has contested values")
    elif all(parts.values()):
        total, nc, cur = (parts[c]["val"] for c in parts)
        long_row = next(r for r in rows if r["key"] == "debt_long")
        if _differs(total, nc + cur):
            long_row["notes"].append(f"LongTermDebt {_money(total)} doesn't equal noncurrent {_money(nc)} plus current "
                                     f"{_money(cur)} ({_pct(nc + cur, total)})")
            long_row["status"] = max(long_row["status"], RECONCILE, key=_RANK.get)
        else:
            long_row["notes"].append(f"adds up: LongTermDebt {_money(total)} = noncurrent {_money(nc)} + current "
                                     f"{_money(cur)}")
    return {"date": day, "rows": rows, "notes": [
        "Total interest-bearing debt isn't computed: whether leases and each short-term item belong in it is a "
        "methodology choice for Phase 2."]}


def _latest_period(facts: list[dict]) -> dict | None:
    """The latest period, preferring the shortest one ending then (a quarter over year-to-date)."""
    if not facts:
        return None
    end = max(f["end"] for f in facts)
    newest_filed_first = sorted((f for f in facts if f["end"] == end), key=lambda f: f.get("filed") or "", reverse=True)
    return min(newest_filed_first, key=lambda f: _days(f) or 0)


def _observed(key: str, label: str, facts: list[dict], concept: str | None, ref: dict, missing: str) -> dict:
    """The latest period's share or dilution figure. Two values in one filing for that period leave no
    number (unknown); a revision needs reconciliation; an old figure is stale."""
    f = _latest_period(facts)
    if not f:
        return {"key": key, "label": label, "status": UNKNOWN, "source": None, "notes": [missing]}
    row = {"key": key, "label": label, "source": _source(f, concept), "notes": []}
    flags: list[tuple[str, str]] = []
    if (contested := _contest(facts, f, "shares")):
        flags.append(contested)
        if contested[0] == UNKNOWN:
            row["source"]["value"] = None
    behind = _behind(f, ref)
    if behind is not None and behind > INSTANT_STALE:
        flags.append((STALE, f"from {f['end']}, {behind} days before the company's latest "
                             f"{'fiscal year' if str(f.get('form', '')).startswith(ANNUAL_FORMS) else 'report'}; "
                             "not current"))
    row.update(status=_status(flags), notes=[t for _, t in flags])
    return row


def shares(company: dict, as_of: date, ref: dict) -> dict:
    """Share counts and what could dilute them, observed as reported. A fully diluted count is never
    computed: the pieces aren't additive without their terms (strike prices, conversion terms, hedges)."""
    rows = []
    for key in ("basic_shares", "diluted_shares"):
        label, _kind, unit, concepts = FIELDS[key]
        by_concept = _candidates(company, concepts, unit, as_of)[0]
        quarters = {c: [f for f in fs if f.get("start") and 70 <= _days(f) <= 110]
                    for c, fs in by_concept.items()}
        end = max((f["end"] for fs in quarters.values() for f in fs), default=None)
        c = next((c for c in concepts if any(f["end"] == end for f in quarters.get(c, []))), None)
        rows.append(_observed(key, label + " — latest quarter", quarters.get(c, []), c, ref,
                              "no quarter-length weighted-average share count reported (70–110 days)"))
    label, _kind, unit, concepts = FIELDS["shares_outstanding"]
    cover = _candidates(company, concepts, unit, as_of)[0].get(concepts[0], [])
    if cover:
        end = max(f["end"] for f in cover)
        vals = sorted({f["val"] for f in cover if f["end"] == end})
        notes, status = [], USABLE
        if len(vals) > 1:
            status = RECONCILE
            notes.append(f"{len(vals)} counts on this date (share classes): " + ", ".join(f"{v:,.0f}" for v in vals))
        if ref["end"] and _gap(ref["end"], end) > INSTANT_STALE:
            status = STALE
            notes.append(f"from {end}, {_gap(ref['end'], end)} days before the company's latest report; "
                         "don't use it for market cap or per-share figures")
        rows.append({"key": "cover", "label": label, "status": status, "values": vals, "date": end, "notes": notes})
    else:
        rows.append({"key": "cover", "label": label, "status": UNKNOWN, "values": [], "date": None,
                     "notes": ["no cover-page share count"]})
    dilution = []
    for key, (label, concept) in DILUTION.items():
        facts = _candidates(company, [concept], "shares", as_of)[0].get(concept, [])
        dilution.append(_observed(key, label, facts, concept, ref, "not tagged as one company-wide figure"))
    return {"rows": rows, "dilution": dilution, "fully_diluted": {
        "status": UNKNOWN, "reason": "not computed: options, awards and convertibles can't be added to the share "
                                     "count without their terms (strike prices, conversion terms, hedges)"}}


# ------------------------------------------------------- sector applicability

def sector(submissions: dict | None, cover_classes: int) -> dict:
    sub = submissions or {}
    sic = int(sub["sic"]) if str(sub.get("sic") or "").isdigit() else None
    kind = None
    if sic and 6020 <= sic <= 6036:
        kind = "bank"
    elif sic and 6300 <= sic <= 6411:
        kind = "insurance"
    elif sic and 6000 <= sic <= 6799:
        kind = "financial"
    tickers = sub.get("tickers") or []
    notes = []
    if cover_classes > 1 or len(tickers) > 1:
        notes.append(f"SEC lists {len(tickers)} tickers ({', '.join(tickers)})" if len(tickers) > 1 else
                     f"{cover_classes} cover-page share counts")
        notes[-1] += ": there may be several share classes (or listed preferred shares). Per-share figures " \
                     "need each class's count and the conversion between classes, taken from the filing"
    return {"sic": sic, "description": sub.get("sicDescription"), "kind": kind, "multi_class_notes": notes,
            "not_applicable": GENERIC_COMPARISONS if kind else [], "needs": SECTOR_NEEDS.get(kind, [])}


# ------------------------------------------------ check against the filing

XBRLI = "{http://www.xbrl.org/2003/instance}"
ISO4217 = "http://www.xbrl.org/2003/iso4217"


def _archive(cik: int, accn: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}"


def _get_bytes(url: str, limit: int = 100_000_000) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": sec._user_agent()})
    with sec._SEC_SLOTS, urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"file over {limit // 1_000_000} MB")
    return data


def pick_instance(names: list[str]) -> str | None:
    """The XBRL instance in a filing's folder: the extracted inline-XBRL file (name_htm.xml), else a plain
    instance (.xml that isn't a schema, linkbase or filing summary)."""
    inline = [n for n in names if n.endswith("_htm.xml")]
    if inline:
        return inline[0]
    plain = [n for n in names if n.endswith(".xml") and n != "FilingSummary.xml"
             and not n.endswith(("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml"))]
    return plain[0] if plain else None


def _units(xml: bytes, root) -> dict[str, str]:
    """{unit id: measure} with namespace prefixes resolved, e.g. "{http://www.xbrl.org/2003/iso4217}USD".
    A divided unit (per share) becomes "numerator/denominator"; anything unresolvable is left out."""
    prefixes = {p: uri for _event, (p, uri) in ET.iterparse(io.BytesIO(xml), events=("start-ns",))}

    def resolve(text: str | None) -> str | None:
        text = (text or "").strip()
        if ":" not in text:
            return None
        p, local = text.split(":", 1)
        return f"{{{prefixes[p]}}}{local}" if p in prefixes else None
    units = {}
    for u in root.iter(f"{XBRLI}unit"):
        measures = [resolve(m.text) for m in u.findall(f"{XBRLI}measure")]
        div = u.find(f"{XBRLI}divide")
        if div is not None:
            num, den = ([resolve(m.text) for m in div.findall(f"{XBRLI}{part}/{XBRLI}measure")]
                        for part in ("unitNumerator", "unitDenominator"))
            measures = [f"{num[0]}/{den[0]}"] if len(num) == len(den) == 1 and num[0] and den[0] else [None]
        if len(measures) == 1 and measures[0]:
            units[u.get("id")] = measures[0]
    return units


def parse_instance(xml: bytes) -> dict[tuple, list[tuple[float, str | None]]]:
    """{(concept, start, end): [(value, unit)]} for facts without dimensions (company-wide totals), the
    same kind of fact SEC's company-facts API serves. The unit is the resolved measure (USD is
    "{http://www.xbrl.org/2003/iso4217}USD"), or None when the filing doesn't declare it."""
    root = ET.fromstring(xml)
    units = _units(xml, root)
    contexts = {}
    for ctx in root.iter(f"{XBRLI}context"):
        if ctx.find(f"{XBRLI}entity/{XBRLI}segment") is not None or ctx.find(f"{XBRLI}scenario") is not None:
            continue
        p = ctx.find(f"{XBRLI}period")
        if p is None:
            continue
        start = (p.findtext(f"{XBRLI}startDate") or "").strip() or None
        end = (p.findtext(f"{XBRLI}endDate") or p.findtext(f"{XBRLI}instant") or "").strip()
        contexts[ctx.get("id")] = (start, end)
    out: dict[tuple, list[tuple[float, str | None]]] = {}
    for el in root:
        ref = el.get("contextRef")
        if ref not in contexts or not el.tag.startswith("{"):
            continue
        ns, name = el.tag[1:].split("}", 1)
        if "us-gaap" not in ns and "ifrs" not in ns:
            continue
        try:
            val = float((el.text or "").strip())
        except ValueError:
            continue
        out.setdefault((name, *contexts[ref]), []).append((val, units.get(el.get("unitRef"))))
    return out


def reconcile(cik: int, company: dict, fields: dict, as_of: date, get_bytes=None) -> dict:
    """Is the figure SEC's API serves the one tagged in the issuer's own filing, for the same period?

    For each selected fiscal-year figure this downloads the filing it came from (its accession number)
    and looks for the same concept and period without dimensions. Inline XBRL tags the numbers printed
    in the filing itself, so a match confirms retrieval and period selection. It doesn't check the
    issuer's accounting, or that the figure suits a valuation."""
    get_bytes = get_bytes or _get_bytes
    filings: dict[str, dict | Exception] = {}
    rows = []
    for key in RECONCILE_FIELDS:
        f = fields[key]
        sel = f.get("selected")
        row = {"key": key, "label": f["label"], "selected": sel}
        if not sel or not sel.get("accn"):
            rows.append(row | {"result": "unverified", "reason": "no fiscal-year figure with an accession number"})
            continue
        if sel["value"] is None:
            rows.append(row | {"result": "unverified", "reason": "SEC's data has several values for this period"})
            continue
        accn = sel["accn"]
        row["filing"] = f"{_archive(cik, accn)}/{accn}-index.htm"
        if accn not in filings:
            try:
                index = json.loads(get_bytes(f"{_archive(cik, accn)}/index.json"))
                names = [i.get("name", "") for i in (index.get("directory") or {}).get("item") or []]
                inst = pick_instance(names)
                if not inst:
                    raise LookupError("no XBRL instance in the filing's folder")
                filings[accn] = {"instance": inst, "facts": parse_instance(get_bytes(f"{_archive(cik, accn)}/{inst}"))}
            except Exception as e:
                filings[accn] = e
        filing = filings[accn]
        if isinstance(filing, Exception):
            rows.append(row | {"result": "unverified", "reason": f"filing not read: {type(filing).__name__}: {filing}"})
            continue
        row["instance"] = filing["instance"]
        found = filing["facts"].get((sel["concept"], sel["start"], sel["end"])) or []
        usd = sorted({v for v, u in found if u == f"{{{ISO4217}}}USD"})
        other = sorted({str(u).split("}")[-1] if u else "an undeclared unit" for v, u in found
                        if u != f"{{{ISO4217}}}USD"})
        if not found:
            rows.append(row | {"result": "unverified", "reason": f"the filing has no company-wide {sel['concept']} "
                                                                  f"for {sel['start']} to {sel['end']}"})
        elif not usd:
            # SEC's figure is in USD: a number in another unit can't confirm it, even if it's equal
            rows.append(row | {"result": "unverified", "filing_values": [],
                               "reason": f"the filing reports it only in {', '.join(other)}, not USD"})
        elif any(not _differs(v, sel["value"], 1e-9) for v in usd):
            rows.append(row | {"result": "matches", "filing_values": usd})
        else:
            rows.append(row | {"result": "differs", "filing_values": usd})
    context = []
    cap = fields["capex"].get("selected")
    if cap:
        for concept, meaning in CAPEX_CONTEXT.items():
            facts = _candidates(company, [concept], "USD", as_of)[0].get(concept, [])
            same = [x for x in facts if x.get("start") == cap["start"] and x["end"] == cap["end"]]
            hit = max(same, key=lambda x: x.get("filed") or "") if same else None
            contested = _contest(same, hit, "USD") if hit else None
            status = contested[0] if contested else (USABLE if hit else UNKNOWN)
            source = _source(hit, concept) if hit else None
            value = hit["val"] if hit and status != UNKNOWN else None
            if source:
                source["value"] = value
            context.append({"concept": concept, "meaning": meaning, "value": value, "status": status,
                            "source": source, "notes": [contested[1]] if contested else (
                                [] if hit else ["not tagged for this period"])})
    return {"rows": rows, "capex_context": context}


# ------------------------------------------------------------- per company

def quality_company(ticker: str, company: dict, submissions: dict | None, as_of: date | None = None,
                    reconcile_cik: int | None = None, get_bytes=None) -> dict:
    as_of = as_of or date.today()
    ref = reference(company, as_of)
    fields = {k: select(company, k, as_of, ref) for k in FIELDS}
    for k, f in fields.items():
        if f["kind"] == "flow" and f["unit"] == "USD":
            f["ttm"] = ttm(company, k, as_of, ref, f)
    sh = shares(company, as_of, ref)
    cover = next(r for r in sh["rows"] if r["key"] == "cover")
    sect = sector(submissions, len(cover["values"]))
    bs = balance_sheet(company, as_of)
    if sect["kind"]:
        for k, reason in GENERIC_NOT_APPLICABLE.items():
            f = fields[k]
            f["issues"] = [f"not applicable ({sect['kind']}): {reason}"] + f["issues"]
            f["status"] = NOT_APPLICABLE
            if "ttm" in f:
                t = f["ttm"]
                t["data_status"] = t["status"]
                t["status"] = NOT_APPLICABLE
                t["reason"] = f["issues"][0] + ("; " + t["reason"] if t.get("reason") else "")
        for row in bs["rows"]:
            if row["key"] in GENERIC_NOT_APPLICABLE:
                row["data_status"] = row["status"]
                row["status"] = NOT_APPLICABLE
                row["notes"] = [fields[row["key"]]["issues"][0]] + row["notes"]
    counts = {s: sum(1 for f in fields.values() if f["status"] == s) for s in STATUSES}
    out = {"ticker": ticker.upper(), "status": "ok", "as_of": as_of.isoformat(),
           "name": company.get("entityName") or (submissions or {}).get("name"),
           "cik": company.get("cik") or (submissions or {}).get("cik"), "reference": ref, "fields": fields,
           "counts": counts, "balance_sheet": bs, "shares": sh, "sector": sect,
           "reconciliation": None}
    if reconcile_cik:
        out["reconciliation"] = reconcile(reconcile_cik, company, fields, as_of, get_bytes)
    return out


def quality_ticker(ticker: str, as_of: date | None = None, check_filing: bool = False, get=None,
                   get_bytes=None, lookup=None) -> dict:
    """Download and check one ticker. Network problems give an "unavailable" entry with the reason."""
    get, lookup = get or sec._get, lookup or sec.cik_lookup
    try:
        cik, why = lookup(ticker)
        if cik is None:
            return {"ticker": ticker.upper(), "status": "unavailable", "reason": why or "no SEC CIK for this ticker"}
        company = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
        try:
            submissions = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        except Exception:
            submissions = None
        return quality_company(ticker, company, submissions, as_of, cik if check_filing else None, get_bytes)
    except Exception as e:
        return {"ticker": ticker.upper(), "status": "unavailable", "reason": f"{type(e).__name__}: {e}"}


# ------------------------------------------------------------------- report

def _filing_result(rec: dict | None) -> str:
    if not rec:
        return "not requested"
    results = [r["result"] for r in rec["rows"]]
    parts = [f"{results.count(x)} {x}" for x in ("matches", "differs", "unverified") if results.count(x)]
    return f"{', '.join(parts)} (of {len(results)})"


def markdown(reports: list[dict], as_of: date | None = None, ua_status: str | None = None) -> str:
    as_of = as_of or date.today()
    sm = summary(reports)
    gone = [f"{r['ticker']} ({r['reason']})" for r in reports if r["status"] != "ok"]
    ok = [r for r in reports if r["status"] == "ok"]
    lines = [f"# SEC data quality (Phase 1B), as of {as_of.isoformat()}", "",
             f"**Status: {sm['status']}**: {sm['available']} of {sm['total']} companies retrieved from SEC"
             + (f"; unavailable: {', '.join(gone)}" if gone else "") + ".", "", identification_line(ua_status), "",
             "Read-only. Each figure is the one an input would use, with where it came from. Nothing is estimated, "
             "filled in or normalized, and there is no valuation here. Only filings made by the as-of date are used.",
             "", "Statuses: **usable** (no problem found; not the same as valuation-ready) · "
             "**needs reconciliation** (revised, conflicting tags or duplicate facts, or a choice a person must "
             "make) · **stale** (older than the company's latest report) · **unknown** (not reported, or not in "
             "USD) · **not applicable** (a generic measure that doesn't fit this kind of company).", ""]
    if ok:
        lines += ["| Company | Latest report | Usable | Needs reconciliation | Stale | Unknown | Not applicable | "
                  "Filing check |", "|---|---|---|---|---|---|---|---|"]
        for r in ok:
            c = r["counts"]
            lines.append(f"| {r['ticker']} | {r['reference']['end'] or '—'} | {c[USABLE]} | {c[RECONCILE]} | "
                         f"{c[STALE]} | {c[UNKNOWN]} | {c[NOT_APPLICABLE]} | {_filing_result(r['reconciliation'])} |")
        lines.append("")
    for r in reports:
        lines += [f"## {r['ticker']}" + (f": {r['name']}" if r.get("name") else ""), ""]
        if r["status"] != "ok":
            lines += [f"Unavailable: {r['reason']}", ""]
            continue
        ref, sect = r["reference"], r["sector"]
        lines += [f"CIK {r['cik']} · SIC {sect['sic'] or '—'} {sect['description'] or ''} · latest report for "
                  f"{ref['end'] or '—'} · latest fiscal year ends {ref['fy_end'] or '—'}", ""]
        lines += ["### Figures selected", "", "| Figure | Status | Value | Period | Source | Notes |",
                  "|---|---|---|---|---|---|"]
        for f in r["fields"].values():
            s = f["selected"]
            lines.append(f"| {f['label']} | {f['status']} | {_fmt(s['value'], f['unit']) if s else '—'} | "
                         f"{_period(s) if s else '—'} | {_cite(s) if s else '—'} | {'; '.join(f['issues']) or '—'} |")
        lines += ["", "### Trailing twelve months", "", "| Figure | Status | TTM | Built from |", "|---|---|---|---|"]
        for f in r["fields"].values():
            t = f.get("ttm")
            if t is None:
                continue
            built = "; ".join(f"{name}: {_money(p['value'])} ({p['start']} to {p['end']}, {p['form']} {p['accn']})"
                              for name, p in t.get("parts", []))
            lines.append(f"| {f['label']} | {t['status']} | {_money(t['value'])} | "
                         f"{'; '.join(x for x in (built, t.get('reason')) if x) or '—'} |")
        rec = r["reconciliation"]
        if rec:
            lines += ["", "### Checked against the filing", "",
                      "Each fiscal-year figure looked up in the issuer's own filing (its XBRL instance), same "
                      "concept and period, company-wide only. A match confirms retrieval and period selection, not "
                      "the issuer's accounting.", "", "| Figure | Period | SEC API | In the filing | Result | Filing |",
                      "|---|---|---|---|---|---|"]
            for x in rec["rows"]:
                s = x["selected"]
                seen = ", ".join(_money(v) for v in x.get("filing_values", [])) or "—"
                lines.append(f"| {x['label']} | {_period(s) if s else '—'} | {_money(s['value']) if s else '—'} | "
                             f"{seen} | {x['result']}{': ' + x['reason'] if x.get('reason') else ''} | "
                             f"{x.get('filing', '—')} |")
            if rec["capex_context"]:
                lines += ["", "Capex above is cash paid for property and equipment (gross), as tagged. It isn't "
                          "maintenance capex, and it leaves out assets funded by leases. Reported for the same period:"]
                lines += [f"- {c['meaning']}: {_money(c['value']) if c['value'] is not None else 'unknown'} "
                          f"({c['status']}); " + "; ".join(c['notes'] + ([_cite(c['source'])] if c['source'] else []))
                          for c in rec["capex_context"]]
        bs = r["balance_sheet"]
        lines += ["", f"### Balance sheet on {bs['date'] or '—'}", ""]
        if bs["date"]:
            lines += ["| Item | Status | Value | Tag | Notes |", "|---|---|---|---|---|"]
            lines += [f"| {x['label']} | {x['status']} | {_money(x['value'])} | {x['concept'] or '—'} | "
                      f"{'; '.join(x['notes']) or '—'} |" for x in bs["rows"]]
            lines += [""] + bs["notes"]
        else:
            lines.append(bs["reason"])
        sh = r["shares"]
        lines += ["", "### Shares and dilution", "", "| Item | Status | Value | Period | Notes |", "|---|---|---|---|---|"]
        for x in sh["rows"]:
            if x["key"] == "cover":
                val = ", ".join(f"{v:,.0f}" for v in x["values"]) or "—"
                lines.append(f"| {x['label']} | {x['status']} | {val} | {x['date'] or '—'} | "
                             f"{'; '.join(x['notes']) or '—'} |")
            else:
                s = x["source"]
                lines.append(f"| {x['label']} | {x['status']} | {_fmt(s['value'], 'shares') if s else '—'} | "
                             f"{_period(s) if s else '—'} | {'; '.join(x['notes'] + ([_cite(s)] if s else [])) or '—'} |")
        for x in sh["dilution"]:
            s = x["source"]
            lines.append(f"| {x['label']} | {x['status']} | {_fmt(s['value'], 'shares') if s else '—'} | "
                         f"{_period(s) if s else '—'} | {'; '.join(x['notes'] + ([_cite(s)] if s else [])) or '—'} |")
        lines.append(f"| Fully diluted shares | {sh['fully_diluted']['status']} | — | — | "
                     f"{sh['fully_diluted']['reason']} |")
        if sect["kind"] or sect["multi_class_notes"]:
            lines += ["", "### Sector and share classes", ""]
            if sect["kind"]:
                lines += [f"Financial company ({sect['kind']}, SIC {sect['sic']}). Not applicable here: "
                          + ", ".join(sect["not_applicable"]) + ".", "",
                          "Needed instead (not collected yet): " + "; ".join(sect["needs"]) + "."]
            lines += [f"- {n}" for n in sect["multi_class_notes"]]
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Read-only data-quality checks on SEC financial-statement data")
    p.add_argument("tickers", nargs="+", help="tickers to check (public companies only; the repo is public)")
    p.add_argument("--reconcile", nargs="*", default=[],
                   help="tickers whose fiscal-year figures are also checked against the filing itself")
    p.add_argument("--as-of", type=date.fromisoformat, help="use only filings made by this date (default: today)")
    p.add_argument("--json", help="write the full result as JSON to this file")
    p.add_argument("--markdown", help="write the report as Markdown to this file (default: print it)")
    args = p.parse_args(argv)
    check = {t.upper() for t in args.reconcile}
    reports = [quality_ticker(t, args.as_of, t.upper() in check) for t in args.tickers]
    sm = summary(reports)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(reports, fh, indent=1, default=str)
    report = markdown(reports, args.as_of)
    if args.markdown:
        with open(args.markdown, "w") as fh:
            fh.write(report)
    else:
        print(report)
    print(f"SEC data quality: {sm['status']} ({sm['available']} of {sm['total']} companies); "
          f"SEC_USER_AGENT {sec.user_agent_status()}", file=sys.stderr)
    return sm["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
