"""A second source for daily prices (Stooq, no key), used to catch bad Yahoo data. Display only.

Stooq's free CSV returns daily bars for a US ticker. We compare its closes with the closes our own status was built
from, over the sessions both have. Closes within `TOLERANCE` agree; a bigger gap on any recent session means one of the
two sources is wrong and the screen says so. Nothing in scoring, status or alerts depends on it. Any failure is "no
check" with the reason, never a guess.
"""
from __future__ import annotations

import csv
import io
import logging
import urllib.request

import pandas as pd

log = logging.getLogger(__name__)

URL = "https://stooq.com/q/d/l/?s={sym}.us&i=d"
TOLERANCE = 0.01          # 1%: splits and dividends adjust old closes, so only the recent sessions are compared
SESSIONS = 10
MIN_OVERLAP = 5


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; StockWatch)"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return r.read().decode("utf-8", "replace")


def parse(text: str) -> pd.Series | None:
    """Close prices by date from Stooq's CSV, or None when it isn't price data (it answers 'No data' for unknown tickers)."""
    rows = list(csv.DictReader(io.StringIO(text or "")))
    out = {}
    for r in rows:
        try:
            out[pd.Timestamp(r["Date"]).normalize()] = float(r["Close"])
        except (KeyError, TypeError, ValueError):
            continue
    return pd.Series(out).sort_index() if out else None


def compare(ours: pd.Series, theirs: pd.Series | None) -> dict:
    """How our recent closes line up with Stooq's. `ours` is indexed by date (time zone ignored)."""
    if theirs is None or theirs.empty:
        return {"source": "Stooq", "unavailable": "Stooq has no daily prices for this ticker"}
    idx = ours.index.tz_localize(None) if getattr(ours.index, "tz", None) is not None else ours.index
    mine = pd.Series(ours.values, index=idx.normalize()).dropna()
    both = pd.concat([mine.tail(SESSIONS * 2), theirs], axis=1, join="inner").dropna().tail(SESSIONS)
    if len(both) < MIN_OVERLAP:
        return {"source": "Stooq", "unavailable": f"only {len(both)} sessions overlap with Stooq's data"}
    gap = ((both.iloc[:, 0] - both.iloc[:, 1]).abs() / both.iloc[:, 1]).where(both.iloc[:, 1] > 0)
    worst = float(gap.max())
    when = gap.idxmax().date().isoformat()
    ok = worst <= TOLERANCE
    return {"source": "Stooq", "agrees": ok, "verdict": "matches" if ok else "differs", "sessions": len(both),
            "worst_gap": round(worst, 4), "worst_day": when,
            "note": (f"Closes match over the last {len(both)} sessions." if ok else
                     f"Closes differ by {worst:.1%} on {when}: one of the two price feeds may be wrong.")}


def check(ticker: str, ours: pd.Series) -> dict:
    """The price check for one ticker; always a dict, with `unavailable` and a reason when it could not be done."""
    try:
        return compare(ours, parse(_get(URL.format(sym=ticker.lower().replace(".", "-")))))
    except Exception as e:      # unofficial source: any failure is 'no check', with the reason
        log.info("stooq %s failed: %s", ticker, e)
        return {"source": "Stooq", "unavailable": "Stooq could not be reached"}
