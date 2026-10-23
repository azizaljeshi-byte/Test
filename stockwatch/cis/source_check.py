"""Compare two sources' completed daily bars for one stock (Issue #29, deliverable B).

Pure and offline: give it two DataFrames (Date index; Open, High, Low, Close, Volume) that you already have.
There is no provider integration here; adding one needs the owner's approval. Each source's SMA, RSI and
ATR are computed from that source's own bars, so a difference shows up where it starts: coverage (volume),
adjustment (a constant price ratio), a missing or partial session, or the indicators that follow from them.
"""
from __future__ import annotations

import pandas as pd

from . import features

PRICE_TOL = 0.005        # 0.5%: beyond this a price difference is reported
VOLUME_TOL = 0.05        # 5%: IEX-only or single-venue volume is far below consolidated volume


def compare(a: pd.DataFrame, b: pd.DataFrame, names=("A", "B"), through: str | None = None) -> dict:
    """Session-by-session differences and each source's indicators on the last common completed session."""
    if through:
        a, b = features.completed(a, through), features.completed(b, through)
    qa, qb = features.check(a, names[0]), features.check(b, names[1])
    out = {"quality": {names[0]: qa.problems or "ok", names[1]: qb.problems or "ok"},
           "only_in": {names[0]: [str(d.date()) for d in a.index.difference(b.index)][-10:],
                       names[1]: [str(d.date()) for d in b.index.difference(a.index)][-10:]}}
    common = a.index.intersection(b.index)
    if not (qa.usable and qb.usable) or common.empty:
        out["status"] = "NOT COMPARABLE"
        return out
    ra, rb = a.loc[common], b.loc[common]
    ratio = (ra["Close"] / rb["Close"]).astype(float)
    out["close_ratio"] = {"first": float(ratio.iloc[0]), "last": float(ratio.iloc[-1]),
                          "min": float(ratio.min()), "max": float(ratio.max())}
    # a ratio that drifts over time but is steady day to day points at a dividend/split adjustment difference
    out["adjustment_suspected"] = abs(ratio.iloc[0] - ratio.iloc[-1]) > PRICE_TOL
    last = common[-1]
    out["last_session"] = str(last.date())
    rows = {}
    for k in ("Open", "High", "Low", "Close", "Volume"):
        x, y = float(a.at[last, k]), float(b.at[last, k])
        tol = VOLUME_TOL if k == "Volume" else PRICE_TOL
        rows[k] = {names[0]: x, names[1]: y, "diff": None if y == 0 else x / y - 1,
                   "flag": y != 0 and abs(x / y - 1) > tol}
    ma, mb = features.metrics(features.completed(a, last.date())), features.metrics(features.completed(b, last.date()))
    for k in ("ma20", "ma50", "ma200", "rsi", "atr", "rv"):
        x, y = ma[k], mb[k]
        rows[k] = {names[0]: x, names[1]: y, "diff": None if x is None or y in (None, 0) else x / y - 1,
                   "flag": x is not None and y not in (None, 0) and abs(x / y - 1) > PRICE_TOL}
    out["last"] = rows
    out["volume_coverage_gap"] = rows["Volume"]["flag"]
    out["status"] = "DIFFERENCES" if any(r["flag"] for r in rows.values()) or out["adjustment_suspected"] else "MATCH"
    return out
