"""A second, paid-grade source for daily closes (Massive, formerly Polygon). Display only, like the Stooq check it sits beside.

One request returns every US stock's bar for one date, so we ask for the last few sessions once (the free plan allows five
requests a minute, so one every `GAP` seconds on a background thread) and then every ticker is a lookup. We compare those
closes with the closes our own status was built from, and we also say so when our history stops BEFORE Massive's newest
session (the 26 Oct 2026 case: Yahoo's Monday bar was missing, so every row showed Friday's close). Nothing in scoring,
status or alerts depends on it except the existing "other price source disagrees" entry check. The key is read from the
environment (STOCKWATCH_MASSIVE_KEY, in the owner's private settings file) and is never written anywhere else. Any failure
is "no check" with the reason, never a guess.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from datetime import date, datetime, timedelta

import pandas as pd

from . import stooq
from .data import NY

log = logging.getLogger(__name__)

BASE = "https://api.massive.com"
GROUPED = BASE + "/v2/aggs/grouped/locale/us/market/stocks/{day}?adjusted=true"
SESSIONS = 8              # sessions compared; one request each
GAP = 13.0                # seconds between requests: the free plan allows 5 a minute
RETRY_AFTER = 900         # after a refused or failed request, leave that date alone this long
_days: dict[str, dict[str, float]] = {}       # final daily closes by ISO date ({} = no session that day)
_blocked: dict[str, float] = {}               # date -> time.monotonic() before which we do not ask again
_lock = threading.Lock()
_worker = {"t": None}


def api_key() -> str:
    return os.getenv("STOCKWATCH_MASSIVE_KEY", "").strip()


def enabled() -> bool:
    return bool(api_key())


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key()}", "User-Agent": "StockWatch"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def parse_grouped(text: str) -> dict[str, float] | None:
    """{ticker: close} from one day's grouped bars, {} when that day had no session, None when it isn't price data."""
    try:
        body = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(body, dict) or body.get("status") not in ("OK", "DELAYED"):
        return None
    out = {}
    for r in body.get("results") or []:
        try:
            c = float(r["c"])
            if r["T"] and c > 0:
                out[str(r["T"]).upper()] = c
        except (KeyError, TypeError, ValueError):
            continue
    return out


def wanted_days(ours: pd.Series, today: date | None = None) -> list[str]:
    """Dates worth fetching: our last sessions, plus every weekday after our newest one up to yesterday (that is how we
    notice our history stops early). Never today: the free plan's data is end of day."""
    today = today or datetime.now(NY).date()
    idx = ours.index.tz_localize(None) if getattr(ours.index, "tz", None) is not None else ours.index
    mine = [d.date() for d in idx.normalize().unique() if d.date() < today][-SESSIONS:]
    days = set(mine)
    if mine:
        d = mine[-1] + timedelta(days=1)
        while d < today:
            if d.weekday() < 5:
                days.add(d)
            d += timedelta(days=1)
    return sorted(x.isoformat() for x in days)[-(SESSIONS + 4):]


def _run(days: list[str]) -> None:
    for day in sorted(days, reverse=True):           # newest first: that is the one that matters most
        with _lock:
            if day in _days or _blocked.get(day, 0) > time.monotonic():
                continue
        try:
            got = parse_grouped(_get(GROUPED.format(day=day)))
        except Exception as e:                        # refused, rate limited or unreachable: try again later
            log.info("massive %s failed: %s", day, e)
            got = None
        with _lock:
            if got is None:
                _blocked[day] = time.monotonic() + RETRY_AFTER
            else:
                _days[day] = got
        time.sleep(GAP)


def request(days: list[str]) -> None:
    """Start fetching any missing dates on a background thread (one at a time), so the engine never waits."""
    with _lock:
        missing = [d for d in days if d not in _days and _blocked.get(d, 0) <= time.monotonic()]
    t = _worker["t"]
    if not missing or (t is not None and t.is_alive()):
        return
    _worker["t"] = threading.Thread(target=_run, args=(missing,), name="stockwatch-massive", daemon=True)
    _worker["t"].start()


def series_for(ticker: str, days: list[str]) -> tuple[pd.Series | None, str | None]:
    """(closes for this ticker over the loaded dates, newest loaded date that was a session)."""
    t = ticker.upper().replace("-", ".")
    with _lock:
        loaded = {d: _days[d] for d in days if d in _days}
    sessions = sorted(d for d, m in loaded.items() if m)
    closes = {pd.Timestamp(d): m[t] for d, m in loaded.items() if t in m}
    return (pd.Series(closes).sort_index() if closes else None), (sessions[-1] if sessions else None)


def check(ticker: str, ours: pd.Series, today: date | None = None) -> dict:
    """The Massive check for one ticker; always a dict, with `unavailable` and a reason when it could not be done."""
    src = "Massive"
    if not enabled():
        return {"source": src, "unavailable": "no Massive key is set"}
    try:
        days = wanted_days(ours, today)
        request(days)
        theirs, newest = series_for(ticker, days)
        if newest is None:
            return {"source": src, "unavailable": "Massive's prices are still loading", "retry": True}
        out = stooq.compare(ours, theirs, source=src, sessions=SESSIONS)
        if "unavailable" in out and any(d not in _days for d in days):
            out["retry"] = True          # some dates are still being fetched: ask again in a couple of minutes
        idx = ours.dropna().index
        idx = idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx
        ours_last = idx.max().date().isoformat() if len(idx) else None
        if "unavailable" not in out and ours_last and newest > ours_last:
            out.update(agrees=False, verdict="behind",
                       note=f"Our price history ends {ours_last}; Massive has the close for {newest}. "
                            "The price shown may be a day old.")
        return out
    except Exception as e:
        log.info("massive check %s failed: %s", ticker, e)
        return {"source": src, "unavailable": "Massive could not be reached"}
