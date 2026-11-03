"""The whole-watchlist paper account (owner, 2026-10-26): the same paper rules (`decision.decide` through `paper.step`, the same
sizing) applied to every stock the app tracks, in its own $50,000 account kept apart from the main Paper account. Nothing in
the main account, the cards, scores, calls or alerts changes, and nothing real is traded. It is kept in the app's database only
(the Drive backup copies it)."""
from __future__ import annotations

import json
from datetime import datetime

from . import paper, paper_live
from .data import NY, us_session

BOOK_KEY, STATE_KEY = "paper_wide_book", "paper_wide_state"


def load_book(store) -> paper.Book:
    raw = store.get_setting(BOOK_KEY)
    return paper.Book.from_dict(json.loads(raw)) if raw else paper.Book()


def tick(store, now: datetime | None = None, force_session: bool = False) -> dict:
    now = (now or datetime.now(NY)).astimezone(NY)
    state = {"at": now.isoformat(), "tickers": [], "skipped": {}, "did": [], "note": "", "session": us_session()}
    if not (force_session or state["session"] == "REGULAR"):
        state["note"] = "market closed: nothing trades outside the regular session"
        store.set_setting(STATE_KEY, json.dumps(state))
        return state
    book = load_book(store)
    snaps, prices = {}, {}
    for s in store.latest_snapshots():
        t = s["ticker"]
        price, why = paper_live.fresh_price(s, now)
        if price is None:
            if t in book.positions:
                state["skipped"][t] = why + ": its open trade's stop is NOT being watched right now"
            continue
        snaps[t], prices[t] = s, price
    state["tickers"] = list(snaps)
    before = json.dumps(book.to_dict(), default=str, sort_keys=True)
    state["did"] = paper.step(book, snaps, prices, now, paper_live.paper_config())
    if json.dumps(book.to_dict(), default=str, sort_keys=True) != before or not store.get_setting(BOOK_KEY):
        store.set_setting(BOOK_KEY, json.dumps(book.to_dict(), default=str))
    store.set_setting(STATE_KEY, json.dumps(state, default=str))
    return state


def status(store) -> dict:
    raw = store.get_setting(STATE_KEY)
    return {"book": load_book(store), "state": json.loads(raw) if raw else None,
            "cfg": {"list": True, "webhook": True, "token": True}, "push_error": None, "pushed_at": None}
