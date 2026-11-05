"""Market crash flag and the way back (owner, 5 Nov). When the whole market is falling, each paper account (Quick, New call) stops opening
trades and ASKS THE OWNER: stop for today (sell everything open) or keep going. After a stop, when the market recovers, it asks again:
resume or stay stopped. Nothing here decides alone to sell or to resume: it only pauses new entries and asks.

The reading comes from the same tracked stocks as the market gate (today's change vs the previous close). Thresholds are a first version, to be
judged on the logged readings (`crash_<account>` setting, `readings`)."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from .data import NY

log = logging.getLogger(__name__)

CRASH_DOWN_SHARE, CRASH_MEDIAN = 0.75, -0.015   # crash: this share of stocks down and the median stock at least this far down
CRASH_HOLD_MIN = 3                               # ...and it holds for this long, so one bad cycle does not raise the flag
RECOVER_DOWN_SHARE, RECOVER_RISE = 0.6, 0.007    # recovery: under this share down, and the median this far above its low of the day
RECOVER_HOLD_MIN = 5
MIN_STOCKS = 20
KEY = "crash_{}"

# states: watching -> asked -> (stopped | kept); stopped -> reopen_asked -> (resumed | stayed)
HALTED = {"asked": "market is crashing: waiting for the owner to choose stop or keep going",
          "stopped": "stopped for today by the owner",
          "reopen_asked": "stopped for today; the market is recovering, waiting for the owner to resume or not",
          "stayed": "stopped for today by the owner"}
ACCOUNTS = {"quick": "Quick", "newcall": "New call"}


def reading(snaps: dict) -> dict | None:
    """{'down': share down, 'median': median change, 'n': stocks} or None when too few stocks are read (no flag, never a guess)."""
    ch = []
    for s in snaps.values():
        try:
            v = ((s.get("payload") or {}).get("quote") or {}).get("live_change")
            if v is not None:
                ch.append(float(v))
        except (TypeError, ValueError):
            pass
    if len(ch) < MIN_STOCKS:
        return None
    ch.sort()
    return {"down": sum(1 for c in ch if c < 0) / len(ch), "median": ch[len(ch) // 2], "n": len(ch)}


def load(store, acct: str, now: datetime) -> dict:
    day = now.strftime("%Y-%m-%d")
    try:
        st = json.loads(store.get_setting(KEY.format(acct)) or "{}")
    except ValueError:
        st = {}
    if not isinstance(st, dict) or st.get("day") != day:
        st = {"day": day, "state": "watching", "bad_since": None, "good_since": None, "low_median": None, "readings": []}
    return st


def _save(store, acct: str, st: dict) -> None:
    store.set_setting(KEY.format(acct), json.dumps(st, default=str))


def _mins(iso, now: datetime) -> float:
    return (now - datetime.fromisoformat(iso)).total_seconds() / 60 if iso else 0.0


def _text(r: dict) -> str:
    return f"{r['down'] * 100:.0f}% of stocks are down, the median {r['median'] * 100:+.1f}%"


def _push(store, title: str, body: str, priority: int, tags: str) -> None:
    try:
        from . import events
        events._push(title, [body], priority, tags, None, "calls", store)
    except Exception:                                   # a missing push never stops the tracker
        log.exception("crash push failed")


def check(store, acct: str, snaps: dict, now: datetime) -> str:
    """Called every cycle by the account's tick. Moves the state and returns '' (entries allowed) or the reason new entries are paused."""
    st = load(store, acct, now)
    r = reading(snaps)
    state = st["state"]
    if r is not None:
        st["low_median"] = r["median"] if st.get("low_median") is None else min(st["low_median"], r["median"])
        st["last"] = {**r, "at": now.strftime("%H:%M")}
        crashing = r["down"] >= CRASH_DOWN_SHARE and r["median"] <= CRASH_MEDIAN
        recovering = (r["down"] <= RECOVER_DOWN_SHARE and st["low_median"] is not None and r["median"] - st["low_median"] >= RECOVER_RISE)
        st["bad_since"] = (st.get("bad_since") or now.isoformat()) if crashing else None
        st["good_since"] = (st.get("good_since") or now.isoformat()) if recovering else None
        name = ACCOUNTS.get(acct, acct)
        if state == "watching" and crashing and _mins(st["bad_since"], now) >= CRASH_HOLD_MIN:
            st.update(state="asked", asked_at=now.isoformat(), asked_reading=_text(r))
            _push(store, f"{name}: the market is crashing", f"{_text(r)}. New entries are paused. Open the {name} tab: stop for today (sells everything) or keep going?", 4, "rotating_light")
        elif state == "stopped" and recovering and _mins(st["good_since"], now) >= RECOVER_HOLD_MIN:
            st.update(state="reopen_asked", reopen_at=now.isoformat(), reopen_reading=_text(r))
            _push(store, f"{name}: the market is recovering", f"{_text(r)}, up from its low of {st['low_median'] * 100:+.1f}%. Resume trading? Open the {name} tab.", 4, "chart_with_upwards_trend")
        if crashing or state != "watching":
            st["readings"] = (st.get("readings") or [])[-60:] + [[now.strftime("%H:%M"), round(r["down"], 2), round(r["median"], 4)]]
    _save(store, acct, st)
    return HALTED.get(st["state"], "")


def answer(store, acct: str, choice: str, now: datetime | None = None) -> dict:
    """The owner's tap. choice: stop (sell everything open and stop for today), keep, resume, stay. Returns {'ok', 'note'}."""
    now = (now or datetime.now(NY)).astimezone(NY)
    st = load(store, acct, now)
    state = st["state"]
    name = ACCOUNTS.get(acct, acct)
    if choice == "stop" and state in ("asked", "kept", "watching", "stopped"):
        sold = sell_all(store, acct, now)
        st["state"] = "stopped"
        st["stopped_at"] = now.isoformat()
        _save(store, acct, st)
        return {"ok": True, "note": f"{name} stopped for today. {sold['note']}"}
    if choice == "keep" and state == "asked":
        st["state"] = "kept"
        _save(store, acct, st)
        return {"ok": True, "note": f"{name} keeps trading. The market gate still holds back bounces."}
    if choice == "resume" and state == "reopen_asked":
        st["state"] = "resumed"
        _save(store, acct, st)
        return {"ok": True, "note": f"{name} trades again. A stock sold in the stop can be bought again if it qualifies."}
    if choice == "stay" and state == "reopen_asked":
        st["state"] = "stayed"
        _save(store, acct, st)
        return {"ok": True, "note": f"{name} stays stopped for today."}
    return {"ok": False, "note": f"Nothing to do: {name} is in the state '{state}'."}


def sell_all(store, acct: str, now: datetime) -> dict:
    """Sell every open trade of the account at its latest fresh price, recorded as 'owner override: market crash stop'."""
    from . import paper_newcall, quick
    mod = quick if acct == "quick" else paper_newcall
    book = mod.load_book(store, migrate=False) if acct == "quick" else mod.load_book(store)
    tickers = list(book["positions"] if acct == "quick" else book.positions)
    sold, left = [], []
    for t in tickers:
        res = mod.sell_by_hand(store, t, now, label="market crash stop")
        (sold if res.get("ok") else left).append(t)
    note = f"Sold {len(sold)} open trade(s)." if sold or not left else ""
    if left:
        note += f" Not sold yet (no fresh price or the market is closed): {', '.join(left)}. Tap Stop again to retry."
    return {"sold": sold, "left": left, "note": note.strip() or "Nothing was open."}
