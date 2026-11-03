"""Sector health, LOG ONLY (owner, 1 Nov 2026). Nothing is blocked: every new entry of Quick and New call is stamped with what this check
said at the minute it was bought, so the results can be read later ("would it have helped?").

A sector is healthy when enough of its stocks have a live price (MIN_NAMES), at least HALF of them are up on the day (MIN_UP) and the
middle stock is not down (MIN_MEDIAN). Too few names, or no change figure, is "no read", never "unhealthy" (missing data is unknown).
Friday 30 Oct replayed on the saved scans: healthy sectors only = 20 trades +$218; the rest = 54 trades -$719. One day, so log first.
Uses only the snapshots the account already loaded this cycle: no extra fetching.
"""
from __future__ import annotations

import statistics

MIN_NAMES, MIN_UP, MIN_MEDIAN = 3, 0.5, 0.0


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def sector_of(snap: dict) -> str | None:
    s = ((snap.get("payload") or {}).get("profile") or {}).get("sector")
    return s if isinstance(s, str) and s.strip() else None


def read(snaps: dict) -> dict:
    """{sector: {"names", "up_share", "median", "healthy"}} from the day change of every stock with a live price."""
    by: dict[str, list[float]] = {}
    for snap in snaps.values():
        s, ch = sector_of(snap), _num(((snap.get("payload") or {}).get("quote") or {}).get("live_change"))
        if s and ch is not None:
            by.setdefault(s, []).append(ch)
    out = {}
    for s, v in by.items():
        if len(v) < MIN_NAMES:
            out[s] = {"names": len(v), "up_share": None, "median": None, "healthy": None}
            continue
        up, med = sum(x > 0 for x in v) / len(v), statistics.median(v)
        out[s] = {"names": len(v), "up_share": round(up, 2), "median": round(med * 100, 2), "healthy": up >= MIN_UP and med >= MIN_MEDIAN}
    return out


def note(snap: dict, sectors: dict) -> str:
    """One line for the trade record: what the check says about this stock's sector."""
    s = sector_of(snap)
    r = sectors.get(s) if s else None
    if not s:
        return "no read: sector unknown"
    if not r or r["healthy"] is None:
        return f"no read: {s}, only {r['names'] if r else 0} stock(s) with a live change"
    verdict = "healthy" if r["healthy"] else "WOULD BLOCK"
    return f"{verdict}: {s}, {r['up_share']:.0%} of {r['names']} up, median {r['median']:+.2f}%"


def stamp(trades: list, did: list, snaps: dict, store=None) -> None:
    """Write the sector note (tracked stocks) and, when the full-market funnel has a fresh read, the funnel note onto the trade of every
    entry this cycle. Never changes a decision."""
    entries = [d for d in did if d.get("action") == "ENTER"]
    if not entries:
        return
    sectors = read(snaps)
    state = None
    if store is not None:
        try:
            from . import funnel
            state = funnel.load(store)
        except Exception:
            state = None
    for d in entries:
        t = next((x for x in reversed(trades) if x.get("ticker") == d["ticker"] and "sector_gate" not in x), None)
        if t is None:
            continue
        if d["ticker"] in snaps:
            t["sector_gate"] = note(snaps[d["ticker"]], sectors)
        else:
            t["sector_gate"] = "no read: not in the live list"
        try:
            from . import funnel
            v = funnel.verdict(d["ticker"], state)
        except Exception:
            v = None
        t["funnel_gate"] = v or "no read: no fresh full-market picture"
