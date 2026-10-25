"""Runs the paper account from the tracker thread (owner, 2026-10-25). Each tracker cycle in the regular session it reads the
test list, takes the latest snapshots and live prices already in the store, applies `paper.step`, saves the book and, when it
changed, pushes it to the Google Sheet. It never fetches market data itself and changes nothing outside the paper account.

The page only reads `status()`: the book comes from the store's settings, so a tap never waits on the Sheet.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from . import decision, paper, paper_io, ui
from .data import NY, us_session

log = logging.getLogger("stockwatch.paper")
BOOK_KEY, STATE_KEY = "paper_book", "paper_state"
LIST_TTL, PUSH_MIN_SECONDS = 600, 60
_cache: dict = {"list": None, "at": 0.0, "error": None}


def load_book(store) -> paper.Book:
    raw = store.get_setting(BOOK_KEY)
    if raw:
        return paper.Book.from_dict(json.loads(raw))
    cfg = paper_io.configured()
    if cfg["webhook"] and cfg["token"]:
        restored = paper_io.pull(cfg["webhook"], cfg["token"])      # a rebooted app picks up where the Sheet left off
        if restored:
            return paper.Book.from_dict(restored)
    return paper.Book()


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


def tick(store, now: datetime | None = None, force_session: bool = False) -> dict:
    """One cycle. Returns {"did": [...], "skipped": {ticker: why}, "note": str}; always safe to call."""
    now = (now or datetime.now(NY)).astimezone(NY)
    tickers, err = test_list()
    state = {"at": now.isoformat(), "tickers": tickers, "skipped": {}, "did": [], "note": err or "", "session": us_session()}
    if not tickers:
        store.set_setting(STATE_KEY, json.dumps(state))
        return state
    if not force_session and state["session"] != "REGULAR":
        state["note"] = "market closed: nothing trades outside the regular session"
        store.set_setting(STATE_KEY, json.dumps(state))
        return state
    snaps, prices = {}, {}
    for t in tickers:
        s = store.snapshot(t)
        if not s:
            state["skipped"][t] = "not in your tracked list yet, so there is no scan for it"
            continue
        price, _, live = ui._now(s)
        if price is None or price != price or not live:
            state["skipped"][t] = "no live price right now"
            continue
        snaps[t], prices[t] = s, float(price)
    book = load_book(store)
    before = json.dumps(book.to_dict(), default=str, sort_keys=True)
    done = paper.step(book, snaps, prices, now, decision.Config())
    state["did"] = done
    after = json.dumps(book.to_dict(), default=str, sort_keys=True)
    if after != before or not store.get_setting(BOOK_KEY):
        save_book(store, book)
    _maybe_push(store, book, prices, now, changed=after != before)
    store.set_setting(STATE_KEY, json.dumps(state, default=str))
    return state


def _maybe_push(store, book: paper.Book, prices: dict, now: datetime, changed: bool) -> None:
    cfg = paper_io.configured()
    if not (cfg["webhook"] and cfg["token"]):
        return
    last = float(store.get_setting("paper_pushed_at", "0") or 0)
    eod = now.hour == 16 and now.minute >= 5 and store.get_setting("paper_eod_day") != now.date().isoformat()
    if not (eod or (changed and time.time() - last >= PUSH_MIN_SECONDS)):
        return
    rep = {**paper.report(book, prices), "day": now.date().isoformat()}
    try:
        res = paper_io.push(cfg["webhook"], cfg["token"], book.to_dict(), rep)
        store.set_setting("paper_push_error", "" if res.get("ok") else str(res.get("error", "failed")))
        if res.get("ok"):
            store.set_setting("paper_pushed_at", str(time.time()))
            if eod:
                store.set_setting("paper_eod_day", now.date().isoformat())
    except Exception as e:
        log.warning("paper push failed: %s", e)
        store.set_setting("paper_push_error", str(e)[:200])


def status(store) -> dict:
    raw = store.get_setting(STATE_KEY)
    return {"book": paper.Book.from_dict(json.loads(store.get_setting(BOOK_KEY) or "{}")),
            "state": json.loads(raw) if raw else None, "cfg": {k: bool(v) for k, v in paper_io.configured().items()},
            "push_error": store.get_setting("paper_push_error") or None,
            "pushed_at": float(store.get_setting("paper_pushed_at", "0") or 0) or None}
