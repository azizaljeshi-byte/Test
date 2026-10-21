from __future__ import annotations

import os
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

    @property
    def is_watchlist(self) -> bool:
        return self.shares <= 0


@dataclass
class Settings:
    scan_interval_minutes: int = 15
    alert_cooldown_hours: int = 24
    data_provider: str = "yahoo"
    benchmark: str = "SPY"


@dataclass
class Portfolio:
    holdings: list[Holding]
    tiers: dict[int, TierRules]
    settings: Settings = field(default_factory=Settings)
    source: Path | None = None

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
    return Portfolio(holdings=holdings, tiers=tiers, settings=settings, source=path)


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
