from __future__ import annotations

from dataclasses import asdict, dataclass

OPPORTUNITY = "opportunity"
RISK = "risk"


@dataclass
class Signal:
    kind: str        # OPPORTUNITY | RISK
    source: str      # technical | fundamental | position | combined
    code: str        # stable identifier, used to de-duplicate alerts
    message: str
    severity: int = 1  # 1 = info, 2 = notable, 3 = act now

    def to_dict(self) -> dict:
        return asdict(self)
