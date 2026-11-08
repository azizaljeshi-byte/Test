"""The manual test list (owner, 3 Nov 2026): up to 10 breakout stocks a day, each with an entry, a stop and a profit target.

For the owner to try by hand. Log and display only: it places no trade and changes no score, call or rule of Quick or New call.
A stock goes on the list when, in the regular session (from the 09:45 New York scan), the candidates list finds it as a BREAKOUT (up at
least GAP_UP_ATR daily ranges, so Quick's breakout side would look at it) and
  tier 1  its New call is BUY or ADD        ("both agree")
  tier 2  its New call is not against it (anything but EXIT, AVOID, ON THE LINE; unknown is left out), at most MAX_TIER2 of these
Only stocks the app tracks (an "S&P only" row has no live data) that are NOT on the owner's watchlist or in his holdings (owner, 3 Nov: the
list is for stocks he does not already follow, so they come from the market extras). If the watchlist cannot be read, nothing is added.
Earnings within a day are already left out by the candidates list.
Levels, fixed when the stock is added and never moved:
  entry   the price when it was found
  stop    Quick's first stop: STOP_ATR daily ranges under the entry
  target  entry + RISK_REWARD x the risk, but not above the nearest resistance; if that resistance leaves less than MIN_ROOM x the risk,
          the stock is left out ("no room")
The exit is the point: sell at the target or the stop, whichever comes first, or at 15:50 New York. No hoping for more. The tracker marks each
row "target", "stopped", "time" or "open" from the live price (a missing or old price changes nothing).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from . import agent, paper_live, quick
from .data import NY, us_session

log = logging.getLogger("stockwatch.testlist")
KEY = "test_list"
MAX_ROWS, MAX_TIER2 = 10, 6
RISK_REWARD, MIN_ROOM = 2.0, 1.5
FIRST_MIN, EXIT_MIN = 9 * 60 + 45, 15 * 60 + 50
AGAINST = ("EXIT", "AVOID", "ON THE LINE")
KEEP_DAYS = 10


def load(store) -> dict:
    try:
        d = json.loads(store.get_setting(KEY) or "{}")
    except ValueError:
        d = {}
    d = d if isinstance(d, dict) else {}
    d.setdefault("days", {})
    return d


def _save(store, d: dict) -> None:
    d["days"] = dict(sorted(d["days"].items())[-KEEP_DAYS:])
    store.set_setting(KEY, json.dumps(d))


def levels(snap: dict, entry: float) -> tuple[dict | None, str | None]:
    """({"stop","target","risk","reward_risk","resistance"} or None, why not)."""
    atr = (((snap.get("payload") or {}).get("technical") or {}).get("atr"))
    if not isinstance(atr, (int, float)) or isinstance(atr, bool) or atr != atr or atr <= 0 or not entry or entry <= 0:
        return None, "daily range unknown"
    stop = quick._first_stop("breakout", entry, entry, float(atr))
    risk = entry - stop
    if risk <= 0:
        return None, "no valid stop"
    target = entry + RISK_REWARD * risk
    z = agent._zone_near(((snap.get("payload") or {}).get("technical") or {}).get("zones"), entry) or {}
    res = (z.get("resistance") or {}).get("price")
    res = res if isinstance(res, (int, float)) and not isinstance(res, bool) and res > entry else None
    if res is not None and res < target:
        if res - entry < MIN_ROOM * risk:
            return None, "no room under resistance"
        target = res
    return {"stop": round(stop, 2), "target": round(target, 2), "risk": round(risk, 2),
            "reward_risk": round((target - entry) / risk, 1), "resistance": None if res is None else round(res, 2)}, None


_wl_cache: dict = {"at": 0.0, "set": None}


def _watchlist(store) -> set | None:
    """Tickers on the owner's watchlist and in his holdings, or None when they cannot be read (cached 10 minutes)."""
    if time.time() - _wl_cache["at"] < 600 and _wl_cache["set"] is not None:
        return _wl_cache["set"]
    try:
        from .live import current_portfolio
        got = {h.ticker for h in current_portfolio(store).holdings}
    except Exception:
        log.exception("watchlist could not be read")
        return None
    if not got:
        return None                                  # an empty watchlist is more likely a read problem than the truth
    _wl_cache.update(at=time.time(), set=got)
    return got


def pick(store, now: datetime) -> int:
    """Adds today's breakout stocks that pass (see the module note). Returns how many were added."""
    from . import candidates
    mine = _watchlist(store)
    if mine is None:
        return 0
    rows = (candidates.load(store).get("days") or {}).get(now.date().isoformat(), {}).get("rows") or {}
    d = load(store)
    day = d["days"].setdefault(now.date().isoformat(), {"rows": []})
    have = {r["ticker"] for r in day["rows"]}
    added = 0
    for t, r in sorted(rows.items(), key=lambda kv: str(kv[1].get("found_at") or "")):
        if len(day["rows"]) >= MAX_ROWS or t in have or t in mine or r.get("tracked") != "yes" or "breakout candidate" not in str(r.get("qualified")):
            continue
        try:
            found = datetime.fromisoformat(r["found_at"]).astimezone(NY)
        except (KeyError, TypeError, ValueError):
            continue
        if found.hour * 60 + found.minute < FIRST_MIN or not r.get("price"):
            continue
        call = r.get("call")
        if call in ("BUY", "ADD"):
            tier = 1
        elif call and call not in AGAINST and sum(x["tier"] == 2 for x in day["rows"]) < MAX_TIER2:
            tier = 2
        else:
            continue
        snap = store.snapshot(t)
        lv, _why = levels(snap, float(r["price"])) if snap else (None, "not tracked")
        if not lv:
            continue
        day["rows"].append({"ticker": t, "found_at": r["found_at"], "tier": tier, "call": call, "entry": round(float(r["price"]), 2), **lv,
                            "status": "open", "last": None, "exit_price": None, "exit_at": None, "result_pct": None})
        have.add(t)
        added += 1
    if added:
        _save(store, d)
    return added


def follow(store, now: datetime) -> bool:
    """Marks open rows target / stopped / time from the live price. A missing or old price changes nothing."""
    d = load(store)
    day = d["days"].get(now.date().isoformat())
    if not day:
        return False
    changed = False
    mins = now.hour * 60 + now.minute
    for r in day["rows"]:
        if r["status"] != "open":
            continue
        snap = store.snapshot(r["ticker"])
        px, _why = paper_live.fresh_price(snap, now) if snap else (None, "no snapshot")
        if px is not None and px != r.get("last"):
            r["last"], changed = round(float(px), 2), True
        done = None
        if px is not None and px >= r["target"]:
            done = ("target", r["target"])
        elif px is not None and px <= r["stop"]:
            done = ("stopped", r["stop"])
        elif mins >= EXIT_MIN and r.get("last") is not None:
            done = ("time", r["last"])
        if done:
            r["status"], r["exit_price"], r["exit_at"] = done[0], done[1], now.isoformat(timespec="seconds")
            r["result_pct"] = round((done[1] / r["entry"] - 1) * 100, 2)
            changed = True
    if changed:
        _save(store, d)
    return changed


def tick(store, now: datetime | None = None) -> dict:
    """From the tracker every 20 seconds in the regular session."""
    now = (now or datetime.now(NY)).astimezone(NY)
    if us_session(now) != "REGULAR":
        return {"added": 0}
    return {"added": pick(store, now), "changed": follow(store, now)}
