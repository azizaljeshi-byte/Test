"""Is the stock trading on more or less volume than normal *for this time of day*? (Quick and New call accounts, 2026-10-30.)

pace = shares traded so far today / (the 20-day average daily volume x the usual share of the day's volume done by now).
1.0 is normal, 1.5 is busy, 0.5 is dead. The usual share follows the U-shaped US day (heavy at the open and the close).
Unknown volume or average gives None: the callers treat that as "not read", never as a pass.
"""
from __future__ import annotations

# minutes after 9:30 -> share of the whole day's volume usually done by then
CURVE = [(0, 0.0), (15, 0.10), (30, 0.17), (60, 0.27), (120, 0.42), (180, 0.55), (240, 0.67), (300, 0.79), (360, 0.92), (390, 1.0)]


def share_done(mins: float) -> float:
    if mins <= 0:
        return 0.0
    for (m0, f0), (m1, f1) in zip(CURVE, CURVE[1:]):
        if mins <= m1:
            return f0 + (f1 - f0) * (mins - m0) / (m1 - m0)
    return 1.0


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def pace(snap: dict, mins: float | None) -> float | None:
    p = (snap or {}).get("payload") or {}
    vol = _num((p.get("quote") or {}).get("live_volume"))
    avg = _num((p.get("technical") or {}).get("vol_avg20"))
    if mins is None or not vol or not avg or avg <= 0 or mins < 10:
        return None
    return vol / (avg * share_done(mins))
