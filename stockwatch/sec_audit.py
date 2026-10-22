"""Read-only audit of the financial-statement data SEC EDGAR provides (Phase 1 of the valuation work, Issue #2).

For each company it reports, field by field, what SEC's XBRL "company facts" actually contain for the
inputs a cash-flow valuation would need, how much history there is, when each figure was filed, and
data-quality problems: unexpected units, restated or amended figures, stock splits, reporting tags
that change over the years, and share counts that don't add up. It also shows which of those fields
the app keeps today.

Nothing in the app imports this module: it changes no score, signal, plan or screen. Run it with
explicit tickers (the repo is public, so don't publish reports on private holdings):

    python -m stockwatch.sec_audit MSFT MU RIVN --markdown audit.md --json audit.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from . import sec

# What a cash-flow valuation needs: key -> (label, flow or instant, unit, candidate concepts in priority order).
# Concepts without a prefix are looked up in us-gaap, then ifrs-full.
FIELDS = {
    "revenue": ("Revenue", "flow", "USD", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                                            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                                            "Revenue"]),
    "operating_income": ("Operating income (EBIT)", "flow", "USD", ["OperatingIncomeLoss",
                                                                    "ProfitLossFromOperatingActivities"]),
    "net_income": ("Net income", "flow", "USD", ["NetIncomeLoss", "ProfitLoss",
                                                 "NetIncomeLossAvailableToCommonStockholdersBasic"]),
    "operating_cash_flow": ("Operating cash flow", "flow", "USD", [
        "NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "CashFlowsFromUsedInOperatingActivities"]),
    "capex": ("Capital expenditure", "flow", "USD", ["PaymentsToAcquirePropertyPlantAndEquipment",
                                                     "PaymentsToAcquireProductiveAssets",
                                                     "PurchaseOfPropertyPlantAndEquipment"]),
    "sbc": ("Stock-based compensation", "flow", "USD", ["ShareBasedCompensation",
                                                        "AllocatedShareBasedCompensationExpense"]),
    "dna": ("Depreciation & amortization", "flow", "USD", ["DepreciationDepletionAndAmortization",
                                                           "DepreciationAndAmortization",
                                                           "DepreciationAmortizationAndAccretionNet",
                                                           "Depreciation"]),
    "interest_expense": ("Interest expense", "flow", "USD", ["InterestExpense", "InterestExpenseDebt",
                                                             "InterestExpenseNonoperating"]),
    "dividends": ("Dividends paid", "flow", "USD", ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"]),
    "buybacks": ("Share buybacks", "flow", "USD", ["PaymentsForRepurchaseOfCommonStock"]),
    "cash": ("Cash & equivalents", "instant", "USD", ["CashAndCashEquivalentsAtCarryingValue",
                                                      "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
                                                      "CashAndCashEquivalents"]),
    "short_term_investments": ("Short-term investments", "instant", "USD", [
        "ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"]),
    "debt_long": ("Long-term debt", "instant", "USD", ["LongTermDebtNoncurrent", "LongTermDebt",
                                                       "NoncurrentPortionOfNoncurrentBorrowings"]),
    "debt_current": ("Short-term debt", "instant", "USD", ["LongTermDebtCurrent", "DebtCurrent",
                                                           "ShortTermBorrowings", "CommercialPaper",
                                                           "CurrentBorrowings"]),
    "operating_leases": ("Operating lease liabilities", "instant", "USD", ["OperatingLeaseLiability",
                                                                           "OperatingLeaseLiabilityNoncurrent"]),
    "finance_leases": ("Finance lease liabilities", "instant", "USD", ["FinanceLeaseLiability",
                                                                       "FinanceLeaseLiabilityNoncurrent"]),
    "ppe_net": ("PP&E, net", "instant", "USD", [
        "PropertyPlantAndEquipmentNet",
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"]),
    "ppe_gross": ("PP&E, gross", "instant", "USD", [
        "PropertyPlantAndEquipmentGross",
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetBeforeAccumulatedDepreciationAndAmortization"]),
    "equity": ("Shareholders' equity", "instant", "USD", [
        "StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "Equity"]),
    "basic_shares": ("Basic shares (weighted average)", "flow", "shares", [
        "WeightedAverageNumberOfSharesOutstandingBasic"]),
    "diluted_shares": ("Diluted shares (weighted average)", "flow", "shares", [
        "WeightedAverageNumberOfDilutedSharesOutstanding"]),
    "eps_diluted": ("Diluted EPS", "flow", "USD/shares", ["EarningsPerShareDiluted"]),
    "shares_outstanding": ("Shares outstanding (cover page)", "instant", "shares",
                           ["dei:EntityCommonStockSharesOutstanding"]),
}

# The app's own SEC extraction (sec.fetch_facts), mapped onto the audit's fields
APP_FIELDS = {"revenue": "revenue", "operating_income": "operating_income", "net_income": "net_income",
              "operating_cash_flow": "operating_cash_flow", "capex": "capex", "equity": "equity",
              "debt_long": "debt_long", "debt_current": "debt_current", "shares_outstanding": "shares"}

ANNUAL_FORMS = ("10-K", "20-F", "40-F")
REPORT_FORMS = ANNUAL_FORMS + ("10-Q",)
RESTATED = 0.005        # a figure re-filed more than 0.5% away from its first filing counts as restated
YEARS_WANTED = 5


def _concept_facts(company: dict, concept: str, unit: str) -> tuple[list[dict], set[str]]:
    """(facts in the wanted unit from 10-K/10-Q/20-F/40-F filings and their amendments, every unit seen)."""
    ns_list = [concept.split(":")[0]] if ":" in concept else ["us-gaap", "ifrs-full"]
    name = concept.split(":")[-1]
    facts, units = [], set()
    for ns in ns_list:
        by_unit = (((company.get("facts") or {}).get(ns) or {}).get(name) or {}).get("units") or {}
        units |= set(by_unit)
        facts += [v for v in by_unit.get(unit) or [] if str(v.get("form", "")).startswith(REPORT_FORMS)]
    return facts, units


def _days(v: dict) -> int | None:
    if not v.get("start"):
        return None
    return (date.fromisoformat(v["end"]) - date.fromisoformat(v["start"])).days


def _rescale(first: float, latest: float) -> float | None:
    """latest / first when a re-filed share or per-share figure moved by a whole multiple (2x, 3x, 10x...),
    else None. On its own that's only a possible split: see _confirm_splits."""
    if not first or not latest or first * latest <= 0:
        return None
    r = latest / first
    k = max(r, 1 / r)
    return r if round(k) >= 2 and abs(k - round(k)) / round(k) <= 0.03 else None


def _annual(facts_by_concept: dict[str, list[dict]], kind: str, per_share: bool) -> list[dict]:
    """One row per fiscal year (newest first), stitched across concepts in priority order: the first
    concept that reports a year wins. Keeps the first-filed and latest-filed figure for that year.
    Rows whose period ends within 300 days of a newer row aren't distinct fiscal years (a fiscal-year
    change, or duplicate periods): they're marked "overlap" and not counted."""
    years: dict[str, dict] = {}
    for concept, facts in facts_by_concept.items():
        annual = [f for f in facts if str(f.get("form", "")).startswith(ANNUAL_FORMS)
                  and (kind == "instant" or 350 <= (_days(f) or 0) <= 380)]
        by_end: dict[str, list[dict]] = {}
        for f in annual:
            by_end.setdefault(f["end"], []).append(f)
        for end, fs in by_end.items():
            if end in years:
                continue
            fs = sorted(fs, key=lambda f: f.get("filed", ""))
            first, latest = fs[0], fs[-1]
            change = (latest["val"] - first["val"]) / abs(first["val"]) if first["val"] else None
            years[end] = {"end": end, "concept": concept, "first": first["val"], "latest": latest["val"],
                          "filed_first": first.get("filed"), "filed_latest": latest.get("filed"),
                          "amended": any(str(f.get("form", "")).endswith("/A") for f in fs),
                          "rescale": _rescale(first["val"], latest["val"]) if per_share else None, "split": None,
                          "restated": bool(change is not None and abs(change) > RESTATED), "overlap": False}
    rows = sorted(years.values(), key=lambda r: r["end"], reverse=True)
    kept = None
    for r in rows:
        if kept and (date.fromisoformat(kept["end"]) - date.fromisoformat(r["end"])).days < 300:
            r["overlap"] = True
        else:
            kept = r
    return rows


def _gaps(rows: list[dict]) -> int:
    ends = [date.fromisoformat(r["end"]) for r in rows if not r["overlap"]]
    return sum(1 for a, b in zip(ends, ends[1:]) if (a - b).days > 400)


def audit_field(company: dict, key: str, today: date) -> dict:
    label, kind, unit, concepts = FIELDS[key]
    by_concept, units = {}, set()
    for c in concepts:
        facts, seen = _concept_facts(company, c, unit)
        units |= seen
        if facts:
            by_concept[c] = facts
    out = {"key": key, "label": label, "kind": kind, "unit": unit, "used_by_app": key in APP_FIELDS}
    if not by_concept:
        other = sorted(units - {unit})
        out.update(status="other units only" if other else "missing", units_seen=other, other_units=other, annual=[], issues=(
            [f"reported only in {', '.join(other)}, not {unit}"] if other else [f"not reported under {', '.join(c.split(':')[-1] for c in concepts)}"]))
        return out
    every = [f for fs in by_concept.values() for f in fs]
    latest = max(every, key=lambda f: (f["end"], f.get("filed", "")))
    annual = _annual(by_concept, kind, per_share=unit != "USD")
    ttm = None
    if kind == "flow" and unit == "USD":
        # amounts only (share counts and EPS don't add up across quarters); the same rule as the app:
        # the concept with the most recent data, trailing twelve months
        recent = max(by_concept.values(), key=lambda fs: max(f["end"] for f in fs))
        ttm_val, _, ttm_end = sec._ttm(recent)
        ttm = {"value": ttm_val, "end": ttm_end} if ttm_val is not None else None
    years = sum(1 for r in annual if not r["overlap"])
    age = (today - date.fromisoformat(latest["end"])).days
    # "covered" describes coverage only, not whether the figures are comparable enough to value a company on
    out.update(status="covered" if years >= YEARS_WANTED and age <= 200 else "partial",
               units_seen=sorted(units), other_units=sorted(units - {unit}), age=age, annual=annual, years=years,
               first_year=next((r["end"] for r in reversed(annual) if not r["overlap"]), None),
               latest={"end": latest["end"], "value": latest["val"], "filed": latest.get("filed"),
                       "form": latest.get("form")}, ttm=ttm)
    return out


def _field_issues(f: dict) -> list[str]:
    annual, issues = f["annual"], []
    counted = [r for r in annual if not r["overlap"]]
    if len({r["concept"] for r in annual}) > 1:
        issues.append("reporting tag changed over the years: " + ", ".join(
            f"{c.split(':')[-1]} ({min(r['end'][:4] for r in annual if r['concept'] == c)}-"
            f"{max(r['end'][:4] for r in annual if r['concept'] == c)})"
            for c in dict.fromkeys(r["concept"] for r in reversed(annual))))
    overlap = [r["end"] for r in annual if r["overlap"]]
    if overlap:
        issues.append("periods overlapping another fiscal year, not counted (fiscal-year change or duplicate "
                      "periods): " + ", ".join(overlap))
    if _gaps(annual):
        issues.append(f"{_gaps(annual)} gap(s) in the yearly history")
    restated = [r["end"][:4] for r in counted if r["restated"]]
    if restated:
        issues.append("figures re-filed more than 0.5% away from the first filing (restated) for FY " + ", ".join(restated))
    amended = [r["end"][:4] for r in counted if r["amended"]]
    if amended:
        issues.append("amended filing (10-K/A) for FY " + ", ".join(amended))
    splits = [f"{r['split']}:1 (FY {r['end'][:4]})" for r in counted if r["split"]]
    if splits:
        issues.append("re-filed after a stock split, confirmed by shares and EPS moving inversely: " + ", ".join(splits))
    possible = [f"{max(r['rescale'], 1 / r['rescale']):.0f}x (FY {r['end'][:4]})" for r in counted
                if r["rescale"] and not r["split"]]
    if possible:
        issues.append("re-filed at a whole multiple, possibly a split but not confirmed by an inverse move in "
                      "shares/EPS, so still counted as restated: " + ", ".join(possible))
    if f["other_units"]:
        issues.append(f"also reported in {', '.join(f['other_units'])}")
    if f["age"] > 200:
        issues.append(f"latest figure is {f['age']} days old")
    if f["kind"] == "flow" and f["unit"] == "USD" and f["ttm"] is None:
        issues.append("trailing twelve months can't be computed from the latest filings")
    return issues


def _confirm_splits(fields: dict) -> None:
    """A split is confirmed for a fiscal year only when shares were re-filed up by a whole multiple and EPS
    down by the same multiple (or the reverse for a reverse split). Then those rows aren't restatements."""
    eps = {r["end"]: r for r in fields["eps_diluted"].get("annual", [])}
    for key in ("diluted_shares", "basic_shares"):
        for r in fields[key].get("annual", []):
            e = eps.get(r["end"])
            if r["rescale"] and e and e["rescale"] and abs(r["rescale"] * e["rescale"] - 1) <= 0.05:
                k = round(max(r["rescale"], 1 / r["rescale"]))
                for row in (r, e):
                    row["split"], row["restated"] = k, False


def app_extraction(company: dict) -> dict:
    """Exactly what sec.fetch_facts keeps today, computed on an already-downloaded company file."""
    out = {}
    for key, names in sec.CONCEPTS.items():
        out[key], _, _ = sec._ttm(sec._facts(company, names))
    for key, names in sec.INSTANT.items():
        out[key] = sec._latest_instant(company, names)
    sv = ((((company.get("facts") or {}).get("dei") or {}).get("EntityCommonStockSharesOutstanding") or {})
          .get("units") or {}).get("shares") or []
    out["shares"] = float(max(sv, key=lambda v: (v["end"], v.get("filed", "")))["val"]) if sv else None
    return out


def share_check(company: dict, fields: dict) -> list[str]:
    """Cover-page shares (what the app's SEC fallback uses for market cap) against weighted-average shares.

    The two aren't the same measure: the cover page counts basic shares on one date, a weighted average
    spans a period. A large difference is worth checking (a missing share class, a split, big buybacks or
    issuance), but on its own it doesn't prove the cover-page count is wrong."""
    notes = []
    sv = ((((company.get("facts") or {}).get("dei") or {}).get("EntityCommonStockSharesOutstanding") or {})
          .get("units") or {}).get("shares") or []
    if sv:
        end = max(v["end"] for v in sv)
        at_end = {v["val"] for v in sv if v["end"] == end}
        if len(at_end) > 1:
            notes.append(f"{len(at_end)} different cover-page share counts for {end} "
                         f"(several share classes?); the app keeps only one of them")
    cover = fields["shares_outstanding"].get("latest")
    basis = "basic" if fields["basic_shares"].get("latest") else "diluted"
    weighted = fields[f"{basis}_shares"].get("latest")
    if cover and weighted and weighted["value"]:
        ratio = cover["value"] / weighted["value"]
        gap = abs((date.fromisoformat(cover["end"]) - date.fromisoformat(weighted["end"])).days)
        if not 0.85 <= ratio <= 1.15:
            notes.append(f"cover-page shares ({cover['value']:,.0f} on {cover['end']}) are {ratio - 1:+.0%} away from "
                         f"{basis} weighted-average shares ({weighted['value']:,.0f}, period ending {weighted['end']}, "
                         f"{gap} days apart). Different dates and bases can explain part of this; a gap this size is "
                         "worth checking for a missing share class, a split, or large buybacks/issuance before "
                         "cover-page shares are used for market cap"
                         + ("; only diluted shares are reported, so the bases differ too" if basis == "diluted" else ""))
    elif cover and not weighted:
        notes.append("no weighted-average share count reported: the cover-page count can't be cross-checked")
    return notes


def audit_company(ticker: str, company: dict, submissions: dict | None, today: date | None = None) -> dict:
    today = today or date.today()
    fields = {k: audit_field(company, k, today) for k in FIELDS}
    _confirm_splits(fields)
    for f in fields.values():
        if "issues" not in f:
            f["issues"] = _field_issues(f)
    sub = submissions or {}
    sic = int(sub["sic"]) if str(sub.get("sic") or "").isdigit() else None
    findings = share_check(company, fields)
    if sic and 6000 <= sic <= 6799:
        findings.append(f"financial company (SIC {sic}): free cash flow, current ratio and debt/equity don't "
                        "measure the same things as for other businesses")
    missing = [f["label"] for f in fields.values() if f["status"] in ("missing", "other units only")]
    if missing:
        findings.append("not available in USD: " + ", ".join(missing))
    return {"ticker": ticker.upper(), "status": "ok", "name": company.get("entityName") or sub.get("name"),
            "cik": company.get("cik") or sub.get("cik"), "sic": sic, "sic_description": sub.get("sicDescription"),
            "fiscal_year_end": sub.get("fiscalYearEnd"), "tickers": sub.get("tickers") or [],
            "fields": fields, "app_extraction": app_extraction(company), "findings": findings}


def audit_ticker(ticker: str, today: date | None = None, get=None, cik_for=None) -> dict:
    """Download and audit one ticker. Network problems give an "unavailable" entry, never made-up data."""
    get, cik_for = get or sec._get, cik_for or sec.cik_for
    try:
        cik = cik_for(ticker)
        if cik is None:
            return {"ticker": ticker.upper(), "status": "unavailable", "reason": "no SEC CIK for this ticker"}
        company = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
        try:
            submissions = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        except Exception:
            submissions = None
        return audit_company(ticker, company, submissions, today)
    except Exception as e:
        return {"ticker": ticker.upper(), "status": "unavailable", "reason": f"{type(e).__name__}: {e}"}


# --------------------------------------------------------------------- report

def _money(v) -> str:
    if v is None:
        return "—"
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{'-' if v < 0 else ''}{a / div:.1f}{suf}"
    return f"{v:,.2f}"


def summary(reports: list[dict]) -> dict:
    """COMPLETE (every company retrieved), PARTIAL (some) or NO DATA (none), with the counts."""
    got = sum(1 for r in reports if r["status"] == "ok")
    status = "COMPLETE" if got == len(reports) and got else "PARTIAL" if got else "NO DATA"
    return {"status": status, "total": len(reports), "available": got, "unavailable": len(reports) - got,
            "exit_code": {"COMPLETE": 0, "PARTIAL": 1, "NO DATA": 2}[status]}


def markdown(reports: list[dict], today: date | None = None) -> str:
    today = today or date.today()
    ok = [r for r in reports if r["status"] == "ok"]
    sm = summary(reports)
    gone = [f"{r['ticker']} ({r['reason']})" for r in reports if r["status"] != "ok"]
    lines = [f"# SEC financial-data audit ({today.isoformat()})", "",
             f"**Status: {sm['status']}**: {sm['available']} of {sm['total']} companies retrieved from SEC"
             + (f"; unavailable: {', '.join(gone)}" if gone else "") + ".", "",
             "Read-only inventory of SEC XBRL company facts. Figures are as reported to SEC; nothing is estimated. "
             '"Used now" means the app\'s current SEC fallback keeps the field (TTM or latest only).', ""]
    if ok:
        lines += ["## Coverage", "", "| Field | Used now | " + " | ".join(r["ticker"] for r in ok) + " |",
                  "|---|---|" + "---|" * len(ok)]
        for key, (label, *_rest) in FIELDS.items():
            cells = []
            for r in ok:
                f = r["fields"][key]
                if f["status"] in ("covered", "partial"):
                    cell = f"{'✓' if f['status'] == 'covered' else 'partial'} {f['years']}y" + (" ⚠" if f["issues"] else "")
                else:
                    cell = f["status"]
                cells.append(cell)
            lines.append(f"| {label} | {'yes' if key in APP_FIELDS else 'no'} | " + " | ".join(cells) + " |")
        lines += ["", f"✓ = at least {YEARS_WANTED} distinct fiscal years and a figure from the last 200 days. That "
                  "is coverage only: it doesn't establish that the figures are comparable or normalized enough to "
                  "value the company on. ⚠ = see the issues under that company.", ""]
    for r in reports:
        lines += [f"## {r['ticker']}" + (f": {r['name']}" if r.get("name") else ""), ""]
        if r["status"] != "ok":
            lines += [f"Unavailable: {r['reason']}", ""]
            continue
        lines += [f"CIK {r['cik']} · SIC {r['sic'] or '—'} {r['sic_description'] or ''} · fiscal year ends "
                  f"{r['fiscal_year_end'] or '—'} · tickers {', '.join(r['tickers']) or '—'}", ""]
        if r["findings"]:
            lines += ["**Findings**", ""] + [f"- {x}" for x in r["findings"]] + [""]
        lines += ["| Field | Years | Latest (period, filed) | TTM | Issues |", "|---|---|---|---|---|"]
        for f in r["fields"].values():
            if f["status"] in ("missing", "other units only"):
                lines.append(f"| {f['label']} | — | — | — | {'; '.join(f['issues'])} |")
                continue
            lt, ttm = f["latest"], f.get("ttm")
            yrs = f"{f['years']} (FY {f['first_year'][:4]}–{f['annual'][0]['end'][:4]})" if f["annual"] else "0"
            lines.append(f"| {f['label']} | {yrs} | {_money(lt['value'])} ({lt['end']}, {lt['form']} filed "
                         f"{lt['filed']}) | {_money(ttm['value']) + ' to ' + ttm['end'] if ttm else '—'} | "
                         f"{'; '.join(f['issues']) or '—'} |")
        app = r["app_extraction"]
        lines += ["", "What the app keeps today: " + ", ".join(
            f"{k} {_money(v)}" for k, v in app.items()) + ".", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Read-only audit of SEC financial-statement data")
    p.add_argument("tickers", nargs="+", help="tickers to audit (public companies only; the repo is public)")
    p.add_argument("--json", help="write the full audit as JSON to this file")
    p.add_argument("--markdown", help="write the report as Markdown to this file (default: print it)")
    args = p.parse_args(argv)
    reports = [audit_ticker(t) for t in args.tickers]
    sm = summary(reports)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(reports, fh, indent=1, default=str)
    report = markdown(reports)
    if args.markdown:
        with open(args.markdown, "w") as fh:
            fh.write(report)
    else:
        print(report)
    print(f"SEC audit status: {sm['status']} ({sm['available']} of {sm['total']} companies)", file=sys.stderr)
    # 0 complete, 1 partial, 2 no data: the workflow fails on no data so a green run means data was retrieved
    return sm["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
