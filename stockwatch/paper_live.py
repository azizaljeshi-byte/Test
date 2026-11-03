"""Runs the paper account from the tracker thread (owner, 2026-10-25). Each tracker cycle in the regular session it reads the
test list, takes the latest snapshots and live prices already in the store, applies `paper.step`, saves the book and, when it
changed, pushes it to the Google Sheet. It never fetches market data itself and changes nothing outside the paper account.

The page only reads `status()`: the book comes from the store's settings, so a tap never waits on the Sheet.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

from . import decision, paper, paper_io, transitions
from .data import NY, us_session

log = logging.getLogger("stockwatch.paper")
BOOK_KEY, STATE_KEY = "paper_book", "paper_state"
LIST_TTL, PUSH_MIN_SECONDS, RESTORE_RETRY_SECONDS = 600, 60, 60
MAX_QUOTE_AGE_S, MAX_TRADE_AGE_S = 300, 600      # the stored quote must have been fetched within 5 minutes and traded within 10
_cache: dict = {"list": None, "at": 0.0, "error": None}


def paper_config() -> decision.Config:
    """The paper account's rules. The opening blackout is 0 for now so the test sees the open too (owner, 2026-10-25);
    set STOCKWATCH_PAPER_BLACKOUT_MIN=60 to bring the first-hour wait back. Paper only: live cards do not use this."""
    try:
        mins = int(os.getenv("STOCKWATCH_PAPER_BLACKOUT_MIN", "0"))
    except ValueError:
        mins = 0
    return decision.Config(blackout_min=max(0, mins))


def load_book(store) -> tuple[paper.Book | None, str]:
    """(book, note). The saved book, else the Sheet's, else a new account only when the Sheet says there is none or no Sheet
    is set up. A Sheet that cannot be read gives (None, why): the paper account waits instead of starting over."""
    raw = store.get_setting(BOOK_KEY)
    if raw:
        return paper.Book.from_dict(json.loads(raw)), ""
    cfg = paper_io.configured()
    if cfg["webhook"] and cfg["token"]:
        last = float(store.get_setting("paper_restore_try", "0") or 0)
        if time.time() - last < RESTORE_RETRY_SECONDS:
            return None, store.get_setting("paper_restore_error") or "waiting to read the saved account from the Sheet"
        store.set_setting("paper_restore_try", str(time.time()))
        res = paper_io.pull(cfg["webhook"], cfg["token"])
        if not res["ok"]:
            store.set_setting("paper_restore_error", f"could not read the saved account from the Sheet ({res['error']}); paper trading waits")
            return None, store.get_setting("paper_restore_error")
        store.set_setting("paper_restore_error", "")
        if res["book"]:
            return paper.Book.from_dict(res["book"]), ""
    return paper.Book(), ""


def save_book(store, book: paper.Book) -> None:
    store.set_setting(BOOK_KEY, json.dumps(book.to_dict(), default=str))


def test_list(now: float | None = None) -> tuple[list[str], str | None]:
    """(tickers, error). Cached for ten minutes so the Sheet is not read on every cycle."""
    cfg = paper_io.configured()
    if not cfg["list"]:
        return [], "no test list link set (STOCKWATCH_PAPER_LIST_URL)"
    now = now or time.time()
    if _cache["list"] is not None and now - _cache["at"] < LIST_TTL:
        return _cache["list"], _cache["error"]
    try:
        _cache.update(list=paper_io.load_list(cfg["list"]), at=now, error=None)
    except Exception as e:
        _cache.update(list=_cache["list"] or [], at=now, error=f"could not read the test list: {e}")
    return _cache["list"], _cache["error"]


def fresh_price(snap: dict, now: datetime) -> tuple[float | None, str]:
    """(price, why not). A price counts only if the stored quote is a regular-session trade from today, fetched within
    five minutes and traded within ten. An old, future, wrong-session or untimed quote gives no price."""
    q = (snap.get("payload") or {}).get("quote") or {}
    now_utc = now.astimezone(timezone.utc)
    cur = transitions.current_quote(q, now_utc)
    if not cur or cur[1] != "regular":
        return None, "no live regular-session trade"
    price, _, traded = cur
    try:
        fetched = datetime.fromisoformat(str(q.get("fetched_at")))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None, "the quote has no fetch time"
    if not 0 <= (now_utc - fetched).total_seconds() <= MAX_QUOTE_AGE_S:
        return None, "the stored quote is older than 5 minutes"
    if not -60 <= (now_utc - traded).total_seconds() <= MAX_TRADE_AGE_S:
        return None, "the last trade is older than 10 minutes"
    return float(price), ""


def _open_prices(store, book: paper.Book) -> dict:
    """The last known price of each open position, for the report when the market is closed."""
    out = {}
    for t in book.positions:
        s = store.snapshot(t)
        if s and s.get("price"):
            out[t] = float(s["price"])
    return out


def _flush(store, book: paper.Book, now: datetime, prices: dict, changed: bool) -> None:
    """Keep the Sheet up to date whatever the session: a change stays pending until the Sheet accepts it, and the
    day's report goes out after 4:05 pm New York on a weekday."""
    if changed:
        store.set_setting("paper_dirty", "1")
    cfg = paper_io.configured()
    if not (cfg["webhook"] and cfg["token"]):
        return
    today = now.date().isoformat()
    eod = now.weekday() < 5 and (now.hour, now.minute) >= (16, 5) and store.get_setting("paper_eod_day") != today
    dirty = store.get_setting("paper_dirty") == "1"
    if not (eod or dirty):
        return
    last = float(store.get_setting("paper_try_at", "0") or 0)
    if time.time() - last < PUSH_MIN_SECONDS:
        return
    store.set_setting("paper_try_at", str(time.time()))
    rep = {**paper.report(book, prices or _open_prices(store, book)), "day": today}
    try:
        res = paper_io.push(cfg["webhook"], cfg["token"], book.to_dict(), rep)
        store.set_setting("paper_push_error", "" if res.get("ok") else str(res.get("error", "failed")))
        if res.get("ok"):
            store.set_setting("paper_pushed_at", str(time.time()))
            store.set_setting("paper_dirty", "0")
            if eod:
                store.set_setting("paper_eod_day", today)
    except Exception as e:
        log.warning("paper push failed: %s", e)
        store.set_setting("paper_push_error", str(e)[:200])


def tick(store, now: datetime | None = None, force_session: bool = False) -> dict:
    """One cycle. Returns {"did": [...], "skipped": {ticker: why}, "note": str}; always safe to call."""
    now = (now or datetime.now(NY)).astimezone(NY)
    tickers, err = test_list()
    state = {"at": now.isoformat(), "tickers": tickers, "skipped": {}, "did": [], "note": err or "", "session": us_session()}
    book, why = load_book(store)
    if book is None:                                             # the saved account could not be read: do nothing
        state["note"] = why
        store.set_setting(STATE_KEY, json.dumps(state))
        return state
    held = [t for t in book.positions if t not in tickers]       # open trades stay watched even if the list drops them
    in_session = force_session or state["session"] == "REGULAR"
    if not in_session:
        if tickers:
            state["note"] = "market closed: nothing trades outside the regular session"
        _flush(store, book, now, {}, changed=False)
        store.set_setting(STATE_KEY, json.dumps(state))
        return state
    if not tickers and not held:
        store.set_setting(STATE_KEY, json.dumps(state))
        return state
    snaps, prices = {}, {}
    for t in tickers + held:
        s = store.snapshot(t)
        if not s:
            state["skipped"][t] = "not in your tracked list yet, so there is no scan for it"
            continue
        price, why_not = fresh_price(s, now)
        if price is None:
            state["skipped"][t] = why_not + (": its open trade's stop is NOT being watched right now" if t in book.positions else "")
            continue
        snaps[t], prices[t] = s, price
    before = json.dumps(book.to_dict(), default=str, sort_keys=True)
    state["did"] = paper.step(book, snaps, prices, now, paper_config(), exit_only=set(held))
    changed = json.dumps(book.to_dict(), default=str, sort_keys=True) != before
    if changed or not store.get_setting(BOOK_KEY):
        save_book(store, book)
    _flush(store, book, now, prices, changed=changed or not store.get_setting("paper_pushed_at"))
    store.set_setting(STATE_KEY, json.dumps(state, default=str))
    return state


def status(store) -> dict:
    raw = store.get_setting(STATE_KEY)
    return {"book": paper.Book.from_dict(json.loads(store.get_setting(BOOK_KEY) or "{}")),
            "state": json.loads(raw) if raw else None, "cfg": {k: bool(v) for k, v in paper_io.configured().items()},
            "push_error": store.get_setting("paper_push_error") or None,
            "pushed_at": float(store.get_setting("paper_pushed_at", "0") or 0) or None}
