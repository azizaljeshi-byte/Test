"""SEC EDGAR filings: recent forms, 8-K events, offerings, late filings, share-count dilution.

Uses SEC's free JSON APIs (no key). SEC asks automated tools to identify themselves,
so set SEC_USER_AGENT to something like "Your Name you@example.com".
"""
from __future__ import annotations

import functools
import json
import logging
import os
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .signals import OPPORTUNITY, RISK, Signal

log = logging.getLogger(__name__)

UNIVERSE_CSV = Path(__file__).parent / "universe" / "sp500.csv"

# 8-K items worth knowing about: (plain-English label, signal kind or None, severity)
ITEMS_8K = {
    "1.01": ("entered a material agreement", OPPORTUNITY, 1),
    "1.02": ("ended a material agreement", RISK, 1),
    "1.03": ("bankruptcy or receivership", RISK, 3),
    "2.01": ("completed an acquisition or sale of assets", None, 0),
    "2.02": ("reported results", None, 0),
    "2.03": ("took on a material debt obligation", None, 0),
    "2.04": ("a debt acceleration event", RISK, 2),
    "2.05": ("restructuring or exit costs", RISK, 1),
    "2.06": ("a material impairment", RISK, 2),
    "3.01": ("a delisting notice or listing-rule failure", RISK, 3),
    "3.02": ("unregistered sale of shares", RISK, 2),
    "3.03": ("changes to shareholder rights", RISK, 1),
    "4.01": ("a change of auditor", RISK, 2),
    "4.02": ("past financial statements can no longer be relied on", RISK, 3),
    "5.01": ("a change in control", None, 0),
    "5.02": ("a director or officer change", RISK, 1),
    "5.03": ("bylaw or fiscal-year changes", None, 0),
    "5.07": ("shareholder vote results", None, 0),
    "7.01": ("a Regulation FD disclosure", None, 0),
    "8.01": ("other events", None, 0),
    "9.01": ("financial statements and exhibits", None, 0),
}
OFFERING_FORMS = {"S-1", "S-1/A", "S-3", "S-3/A", "S-3ASR", "F-1", "F-3", "F-3ASR",
                  "424B1", "424B2", "424B3", "424B4", "424B5", "424B7"}
LATE_FORMS = {"NT 10-K", "NT 10-Q", "NT 20-F"}
STAKE_FORMS = {"SC 13D", "SC 13D/A", "SCHEDULE 13D", "SCHEDULE 13D/A"}
KEY_FORMS = {"10-K", "10-Q", "8-K", "20-F", "6-K", "DEF 14A", "4"} | OFFERING_FORMS | LATE_FORMS | STAKE_FORMS


def _get(url: str) -> dict:
    ua = os.getenv("SEC_USER_AGENT") or "StockWatch personal research (set SEC_USER_AGENT)"
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


@functools.lru_cache(maxsize=1)
def _ticker_map() -> dict[str, int]:
    """Ticker -> CIK. The S&P file covers most lookups without a request."""
    out = {}
    try:
        df = pd.read_csv(UNIVERSE_CSV)
        out.update({t.upper(): int(c) for t, c in zip(df["ticker"], df["cik"]) if pd.notna(c)})
    except Exception as e:
        log.info("universe CIKs unavailable: %s", e)
    try:
        for row in _get("https://www.sec.gov/files/company_tickers.json").values():
            out.setdefault(str(row["ticker"]).upper().replace(".", "-"), int(row["cik_str"]))
    except Exception as e:
        log.info("SEC ticker map unavailable: %s", e)
    return out


def cik_for(ticker: str) -> int | None:
    return _ticker_map().get(ticker.upper().replace(".", "-"))


def fetch(ticker: str) -> dict:
    """{"cik", "filings": [...], "shares": [{"end", "value"}]} newest first; raises if the ticker has no CIK."""
    cik = cik_for(ticker)
    if cik is None:
        raise LookupError(f"No SEC CIK for {ticker}")
    sub = _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    recent = sub.get("filings", {}).get("recent", {})
    filings = []
    for i, form in enumerate(recent.get("form", [])[:200]):
        if form not in KEY_FORMS:
            continue
        acc = recent["accessionNumber"][i]
        doc = (recent.get("primaryDocument") or [""] * (i + 1))[i]
        filings.append({
            "form": form, "date": recent["filingDate"][i],
            "items": (recent.get("items") or [""] * (i + 1))[i] or "",
            "description": (recent.get("primaryDocDescription") or [""] * (i + 1))[i] or "",
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}" if doc else
                   f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
        })
    shares = []
    try:
        concept = _get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/dei/EntityCommonStockSharesOutstanding.json")
        by_end = {}
        for u in concept.get("units", {}).get("shares", []):
            by_end[u["end"]] = u["val"]  # later filings for the same date overwrite earlier ones
        shares = [{"end": k, "value": float(v)} for k, v in sorted(by_end.items(), reverse=True)]
    except Exception as e:
        log.info("share count unavailable for %s: %s", ticker, e)
    return {"cik": cik, "name": sub.get("name"), "filings": filings, "shares": shares}


def describe(f: dict) -> str:
    if f["form"] in ("8-K", "8-K/A") and f.get("items"):
        labels = [ITEMS_8K.get(i.strip(), (f"item {i.strip()}", None, 0))[0] for i in f["items"].split(",") if i.strip()]
        labels = [l for l in labels if l != "financial statements and exhibits"] or ["exhibits"]
        return "8-K: " + "; ".join(labels)
    names = {"10-K": "annual report", "10-Q": "quarterly report", "20-F": "annual report (foreign issuer)",
             "6-K": "foreign issuer update", "DEF 14A": "proxy statement", "4": "insider transaction"}
    if f["form"] in OFFERING_FORMS:
        return f"{f['form']}: registration / prospectus for selling securities"
    if f["form"] in LATE_FORMS:
        return f"{f['form']}: notice of late filing"
    if f["form"] in STAKE_FORMS:
        return f"{f['form']}: investor disclosed a 5%+ stake with intent to influence"
    return f"{f['form']}: {names.get(f['form'], f.get('description') or 'filing')}"


COMMON_SPLITS = (2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50)


def _split_ratio(growth: float) -> int | None:
    """A share-count jump that lands on a common split ratio (allowing a little real dilution on
    top) is treated as a split. Real dilution rarely produces an exact multiple."""
    return next((r for r in COMMON_SPLITS if r * 0.97 <= growth <= r * 1.05), None)


def analyze(data: dict, market_cap: float | None = None, today: date | None = None) -> tuple[dict, list[Signal]]:
    today = today or date.today()
    out: list[Signal] = []
    filings = data.get("filings") or []
    m = {"filings": [{**f, "label": describe(f)} for f in filings if f["form"] != "4"][:12],
         "form4_90d": sum(1 for f in filings if f["form"] == "4"
                          and date.fromisoformat(f["date"]) >= today - timedelta(days=90))}
    large = bool(market_cap and market_cap >= 1e10)  # big companies keep shelf registrations as routine

    seen = set()
    for f in filings:
        age = (today - date.fromisoformat(f["date"])).days
        if f["form"] in ("8-K", "8-K/A") and age <= 7:
            for item in (i.strip() for i in f.get("items", "").split(",")):
                label, kind, sev = ITEMS_8K.get(item, (None, None, 0))
                if kind and ("8k", item) not in seen:
                    seen.add(("8k", item))
                    out.append(Signal(kind, "sec", f"8k_{item}", f"8-K filed {f['date']}: {label}", sev))
        elif f["form"] in OFFERING_FORMS and age <= 30 and "offering" not in seen:
            seen.add("offering")
            out.append(Signal(RISK, "sec", "sec_offering",
                              f"{f['form']} filed {f['date']}: registration to sell securities - possible dilution",
                              1 if large else 2))
        elif f["form"] in LATE_FORMS and age <= 45 and "late" not in seen:
            seen.add("late")
            out.append(Signal(RISK, "sec", "sec_late_filing", f"{f['form']} filed {f['date']}: late financial report", 2))
        elif f["form"] in STAKE_FORMS and age <= 30 and "stake" not in seen:
            seen.add("stake")
            out.append(Signal(OPPORTUNITY, "sec", "sec_activist",
                              f"{f['form']} filed {f['date']}: an investor disclosed an active 5%+ stake", 1))

    shares = data.get("shares") or []
    if shares:
        latest = shares[0]
        end = date.fromisoformat(latest["end"])
        year_ago = next((s for s in shares if (end - date.fromisoformat(s["end"])).days >= 330), None)
        m["shares_now"] = latest["value"]
        m["shares_trend"] = shares[:6]
        if year_ago and year_ago["value"]:
            ch = latest["value"] / year_ago["value"] - 1
            m["shares_change_1y"] = ch
            split = _split_ratio(latest["value"] / year_ago["value"])
            if split:
                # SEC share counts aren't split-adjusted: a 10-for-1 split looks like +900%
                m["split"] = split
                m["shares_change_1y"] = ch = latest["value"] / (year_ago["value"] * split) - 1
            if ch >= 0.10:
                out.append(Signal(RISK, "sec", "dilution", f"Share count up {ch:.0%} in a year - holders are being diluted", 2))
            elif ch >= 0.05:
                out.append(Signal(RISK, "sec", "dilution", f"Share count up {ch:.0%} in a year", 1))
            elif ch <= -0.03:
                out.append(Signal(OPPORTUNITY, "sec", "buybacks", f"Share count down {-ch:.0%} in a year (buybacks)", 1))
    return m, out


def demo(ticker: str) -> dict:
    """Synthetic filings for the offline demo."""
    import zlib
    import numpy as np
    rng = np.random.default_rng(zlib.crc32((ticker + ":sec").encode()))
    today = date.today()
    pick = [("10-Q", "", 40), ("8-K", "2.02,9.01", 40), ("4", "", 12), ("8-K", "5.02", 9),
            ("S-3", "", 20), ("10-K", "", 130), ("8-K", "1.01,9.01", 3)]
    filings = [{"form": f, "date": (today - timedelta(days=int(d * rng.uniform(0.5, 1.5)))).isoformat(), "items": it,
                "description": "", "url": "https://www.sec.gov/"} for f, it, d in pick if rng.random() < 0.8]
    filings.sort(key=lambda f: f["date"], reverse=True)
    base = float(rng.uniform(5e7, 5e9))
    growth = float(rng.choice([-0.04, 0.0, 0.02, 0.12]))
    shares = [{"end": (today - timedelta(days=91 * i + 20)).isoformat(), "value": base / (1 + growth) ** (i / 4)}
              for i in range(6)]
    return {"cik": int(rng.integers(1e5, 2e6)), "name": f"{ticker} (demo)", "filings": filings, "shares": shares}
