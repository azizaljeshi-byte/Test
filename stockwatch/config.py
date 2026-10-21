from __future__ import annotations

import csv
import io
import os
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATHS = [ROOT / "portfolio.yaml", ROOT / "portfolio.example.yaml"]

DEFAULT_TIERS = {
    1: dict(fundamental_weight=0.65, technical_weight=0.35, stop_loss_pct=25,
            trailing_atr_mult=4.0, max_position_pct=15),
    2: dict(fundamental_weight=0.40, technical_weight=0.60, stop_loss_pct=12,
            trailing_atr_mult=2.5, max_position_pct=7),
}


@dataclass
class TierRules:
    fundamental_weight: float
    technical_weight: float
    stop_loss_pct: float
    trailing_atr_mult: float
    max_position_pct: float


@dataclass
class Holding:
    ticker: str
    tier: int
    shares: float = 0.0
    cost_basis: float | None = None
    target_price: float | None = None
    notes: str | None = None

    @property
    def is_watchlist(self) -> bool:
        return self.shares <= 0


@dataclass
class Settings:
    scan_interval_minutes: int = 15
    alert_cooldown_hours: int = 24
    data_provider: str = "yahoo"
    benchmark: str = "SPY"
    sheet_url: str | None = None      # Google Sheet holding the ticker list (overrides YAML holdings)


@dataclass
class Portfolio:
    holdings: list[Holding]
    tiers: dict[int, TierRules]
    settings: Settings = field(default_factory=Settings)
    source: Path | None = None
    sheet_url: str | None = None       # set when holdings were read from a Google Sheet
    sheet_error: str | None = None     # set when the sheet couldn't be read (YAML holdings used instead)

    def rules(self, tier: int) -> TierRules:
        return self.tiers.get(tier) or self.tiers[2]


def load_portfolio(path: str | Path | None = None) -> Portfolio:
    """Load from `path`, else the STOCKWATCH_PORTFOLIO env var (YAML text, used for
    cloud deployments so positions stay out of the repo), else portfolio.yaml."""
    if path is None and os.getenv("STOCKWATCH_PORTFOLIO"):
        raw, path = yaml.safe_load(os.environ["STOCKWATCH_PORTFOLIO"]) or {}, None
    else:
        if path is None:
            path = next((p for p in DEFAULT_PATHS if p.exists()), None)
            if path is None:
                raise FileNotFoundError("No portfolio.yaml found; copy portfolio.example.yaml")
        path = Path(path)
        raw = yaml.safe_load(path.read_text()) or {}

    tiers = {}
    for tier, defaults in DEFAULT_TIERS.items():
        merged = {**defaults, **(raw.get("tiers", {}).get(tier) or {})}
        tiers[tier] = TierRules(**merged)

    holdings = []
    for h in raw.get("holdings", []):
        tier = int(h.get("tier", 2))
        if tier not in tiers:
            raise ValueError(f"{h.get('ticker')}: tier must be 1 or 2, got {tier}")
        holdings.append(Holding(
            ticker=str(h["ticker"]).upper(),
            tier=tier,
            shares=float(h.get("shares", 0) or 0),
            cost_basis=h.get("cost_basis"),
            target_price=h.get("target_price"),
        ))

    settings = Settings(**(raw.get("settings") or {}))
    portfolio = Portfolio(holdings=holdings, tiers=tiers, settings=settings, source=path)

    sheet = os.getenv("STOCKWATCH_SHEET_URL") or settings.sheet_url
    if sheet:
        try:
            portfolio.holdings = parse_holdings_csv(fetch_sheet_csv(sheet))
            portfolio.sheet_url = sheet
        except Exception as e:  # keep scanning the YAML list rather than nothing
            portfolio.sheet_error = str(e)
    return portfolio


# ------------------------------------------------------------------ Google Sheet holdings

def sheet_csv_url(url_or_id: str) -> str:
    # "Publish to web" CSV links and any other direct CSV URL are used as they are
    if re.search(r"output=csv|format=csv|\.csv($|\?)", url_or_id) or (
            url_or_id.startswith("http") and "docs.google.com/spreadsheets" not in url_or_id):
        return url_or_id
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})", url_or_id)
    sheet_id = m.group(1) if m else url_or_id.strip()
    gid = re.search(r"[#&?]gid=(\d+)", url_or_id)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid.group(1) if gid else 0}"


def sheet_edit_url(url_or_id: str) -> str:
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})", url_or_id)
    return f"https://docs.google.com/spreadsheets/d/{m.group(1) if m else url_or_id.strip()}/edit"


def fetch_sheet_csv(url_or_id: str, timeout: float = 15) -> str:
    """Read the first tab as CSV. Needs General access 'Anyone with the link - Viewer'."""
    with urllib.request.urlopen(sheet_csv_url(url_or_id), timeout=timeout) as r:
        body = r.read().decode("utf-8-sig")
        ctype = r.headers.get("Content-Type", "")
    if "html" in ctype or body.lstrip().startswith("<"):
        raise PermissionError("Google returned a sign-in page: set the sheet's General access to "
                              "'Anyone with the link' (Viewer)")
    return body


_COLUMNS = {
    "ticker": "ticker", "symbol": "ticker", "tier": "tier", "shares": "shares", "quantity": "shares",
    "qty": "shares", "avg cost": "cost_basis", "average cost": "cost_basis", "cost basis": "cost_basis",
    "cost": "cost_basis", "target price": "target_price", "target": "target_price", "notes": "notes",
    "note": "notes",
}


def _number(text: str) -> float | None:
    text = (text or "").replace("$", "").replace(",", "").strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None


def parse_holdings_csv(text: str) -> list[Holding]:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError("The sheet is empty")
    header = [_COLUMNS.get(h.strip().lower()) for h in rows[0]]
    if "ticker" not in header:
        raise ValueError("The first row needs a 'Ticker' column header")
    seen: dict[str, Holding] = {}
    for row in rows[1:]:
        rec = {k: (row[i] if i < len(row) else "") for i, k in enumerate(header) if k}
        ticker = re.sub(r"[^A-Za-z0-9.\-^=]", "", rec.get("ticker", "")).upper()
        if not ticker:
            continue
        tier = _number(rec.get("tier", ""))
        seen[ticker] = Holding(  # a repeated ticker keeps its last row
            ticker=ticker, tier=int(tier) if tier in (1, 2) else 2,
            shares=_number(rec.get("shares", "")) or 0.0,
            cost_basis=_number(rec.get("cost_basis", "")), target_price=_number(rec.get("target_price", "")),
            notes=(rec.get("notes") or "").strip() or None)
    return list(seen.values())


def to_yaml(portfolio: Portfolio) -> str:
    """Holdings as YAML, e.g. to paste into the STOCKWATCH_PORTFOLIO secret."""
    rows = []
    for h in sorted(portfolio.holdings, key=lambda h: (h.is_watchlist, h.tier, h.ticker)):
        row = {"ticker": h.ticker, "tier": h.tier}
        if h.shares:
            row["shares"] = h.shares
        if h.cost_basis:
            row["cost_basis"] = h.cost_basis
        if h.target_price:
            row["target_price"] = h.target_price
        rows.append(row)
    return yaml.safe_dump({"holdings": rows}, sort_keys=False, default_flow_style=None)
