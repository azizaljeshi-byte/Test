"""Debt and cash flow facts for the Details card. Display only: nothing here feeds a score, call, plan or alert.

From the company's own SEC filings (the company-facts file the app already downloads once a day per stock), with Yahoo's
total cash and total debt as the fallback. Cash-flow lines in a 10-Q are year-to-date, so `quarterly` turns them into single
quarters. A figure that cannot be found is None ("not available"), never zero.
"""
from __future__ import annotations

from datetime import date

CASH = ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsAndShortTermInvestments", "CashAndCashEquivalents",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]
SHORT_INVEST = ["MarketableSecuritiesCurrent", "ShortTermInvestments", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"]
INTEREST = ["InterestExpense", "InterestExpenseDebt", "InterestExpenseNonoperating", "InterestAndDebtExpense"]
QUARTERS = 8


def _d(s: str) -> date:
    return date.fromisoformat(s)


def quarterly(vals: list[dict], n: int = QUARTERS) -> list[dict]:
    """Single-quarter values from cash-flow facts that are year-to-date: [{end, value}] newest first.
    A 3-month fact is a quarter; a 6, 9 or 12-month fact minus the shorter fact that starts the same day is one."""
    facts: dict[tuple[str, str], dict] = {}
    for v in vals:
        if not v.get("start") or v.get("val") is None:
            continue
        key = (v["start"], v["end"])
        if key not in facts or v.get("filed", "") > facts[key].get("filed", ""):
            facts[key] = v
    out: dict[str, float] = {}
    for (start, end), v in facts.items():
        days = (_d(end) - _d(start)).days
        if 80 <= days <= 100:
            out.setdefault(end, float(v["val"]))
        elif 170 <= days <= 380:
            prior = [p for (s, e), p in facts.items() if s == start and 70 <= (_d(end) - _d(e)).days <= 105 and e < end]
            if prior:
                earlier = max(prior, key=lambda p: p["end"])
                out.setdefault(end, float(v["val"]) - float(earlier["val"]))
    return [{"end": e, "value": out[e]} for e in sorted(out, reverse=True)[:n]]


def build(f: dict | None, company_facts: dict | None) -> dict:
    """{cash, debt, equity, debt_to_equity, current_ratio, interest_ttm, ebit_ttm, fcf_ttm, cfo_q, capex_q, source, as_of}.
    `company_facts` is `sec.fetch_facts`, which carries the debt-and-cash block; `f` is the Yahoo fundamentals dict."""
    f = f or {}
    sec_block = (company_facts or {}).get("debt_cash") or {}
    out = {k: sec_block.get(k) for k in ("cash", "debt", "equity", "interest_ttm", "ebit_ttm", "cfo_q", "capex_q", "as_of")}
    out["source"] = "company filings" if any(out.get(k) is not None for k in ("cash", "debt")) else None
    if out["cash"] is None and f.get("total_cash") is not None:
        out["cash"], out["source"] = f["total_cash"], out["source"] or "Yahoo"
    if out["debt"] is None and f.get("total_debt") is not None:
        out["debt"], out["source"] = f["total_debt"], out["source"] or "Yahoo"
    out["debt_to_equity"] = f.get("debt_to_equity")
    out["debt_to_equity"] = (out["debt"] / out["equity"] * 1.0 if out["debt"] is not None and out.get("equity") and out["equity"] > 0
                             else None if f.get("debt_to_equity") is None else f["debt_to_equity"] / 100)   # Yahoo gives it in percent
    out["current_ratio"] = f.get("current_ratio")
    cfo, capex = out.get("cfo_q") or [], {q["end"]: q["value"] for q in out.get("capex_q") or []}
    last4 = cfo[:4]
    out["fcf_ttm"] = (sum(q["value"] - abs(capex.get(q["end"], 0.0)) for q in last4) if len(last4) == 4 else f.get("free_cash_flow"))
    return out


def sec_block(company: dict, facts, latest_instant, ttm, concepts) -> dict:
    """The debt-and-cash block inside `sec.fetch_facts` (passed the sec helpers so there is no import loop)."""
    cash = latest_instant(company, CASH)
    short = latest_instant(company, SHORT_INVEST)
    cash_all = None if cash is None and short is None else (cash or 0.0) + (short or 0.0)
    debt_l, debt_c = latest_instant(company, concepts["debt_long"]), latest_instant(company, concepts["debt_current"])
    debt = None if debt_l is None and debt_c is None else (debt_l or 0.0) + (debt_c or 0.0)
    interest, _, _ = ttm(facts(company, INTEREST))
    ebit, _, _ = ttm(facts(company, concepts["operating_income"]))
    return {"cash": cash_all, "debt": debt, "equity": latest_instant(company, concepts["equity"]),
            "interest_ttm": interest, "ebit_ttm": ebit,
            "cfo_q": quarterly(facts(company, concepts["operating_cash_flow"])),
            "capex_q": quarterly(facts(company, concepts["capex"])),
            "as_of": max((v["end"] for v in facts(company, CASH)), default=None)}
