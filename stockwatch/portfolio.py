"""The Portfolio account (owner, 5-6 Nov 2026): a careful FAKE account that mirrors the stocks the owner holds (his shares at his average cost, read
from his Sheet when the account is seeded) and manages them. It never trades real money and changes no score, signal, verdict or other account.

  * Trims a poor position in steps, never sells one to zero on its own (a full exit is only a PROPOSAL waiting for the owner's yes).
  * Sizes down a position that grew past its cap.
  * Adds only to a stock that is undervalued AND has very strong fundamentals, when the New call (daily) and Quick's timing (intraday) agree.
    The pool is not limited to the holdings: a new name must pass the same tests and starts small.
Sells are judged at 15:45 New York on the daily call, never on an intraday dip. Every action is logged with its reasons.
The thresholds are a first version (owner: try it, adjust as we go); all of them are the constants below.

Money identity (same as the other accounts): realized = cash + cost of open positions - start, whatever was trimmed or added.
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, timedelta

from . import decision, paper_live, quick, ui, volpace
from .data import NY, us_session
from .paper_newcall import BROKEN_CHART, WEAK_CHART, WEAK_MOMENTUM, _call_of, rank_score, today_change, weak_reason

log = logging.getLogger(__name__)

BOOK_KEY, STATE_KEY = "portfolio_book", "portfolio_state"
OVERRIDE = "owner override"

CASH_RESERVE_PCT = 10.0        # cash at the start, as a share of the holdings' cost
# trimming a poor position
TRIM_STEP = 0.25               # of the shares held when the trimming began
TRIM_AUTO_MAX = 0.5            # the account never takes a position below this share of the most shares it ever held (the rest needs the owner's yes)
CONFIRM_DAYS = 2               # the second step needs the position still poor this many checks (days) after the first
CAP_PCT, CAP_HIGH_PCT = 15.0, 8.0     # the largest share of the account one name may be (High or Extreme risk grade: the smaller cap)
REBUY_LOCK_DAYS = 3            # trading days: a trimmed stock is not added to again unless the call is BUY/ADD (adds need that anyway)
# adding
FUND_ADD = 75.0                # "very strong fundamentals" for a holding (owner, 6 Nov: 75)
FUND_NEW = 75.0                # a stock not held yet: the same bar as a holding (owner, 6 Nov: fundamentals 75 for both)
FAIR_UP, ANALYST_UP, MIN_METHODS = 0.15, 0.10, 2      # undervalued: fair value (at least 2 methods) 15% above the price AND analyst target 10% above
RISK_PCT = 1.0                 # account risk per add, from the exit line
ADD_STEP_PCT, NEW_START_PCT = 5.0, 3.0
MAX_ADDS_DAY = 2
MIN_ADD_USD = 25.0             # an add smaller than this is not worth a line (the owner holds fractional shares, so adds may be fractional)
MIN_PACE = 0.8
EARN_DAYS = 2
FIRST_ADD_MIN = 30             # no adds in the opening half hour
KEEP_DAYS = 5                  # "keep it" on a proposal silences it for this many days
MAX_LOG, MAX_BLOCKED = 300, 300


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def _ts(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M")


def new_book() -> dict:
    return {"cash": 0.0, "start": 0.0, "positions": {}, "actions": [], "blocked": [], "proposals": {}, "seeded": None, "next_id": 1,
            "poor": {}, "checked": {}, "locks": {}, "adds_day": {"day": "", "n": 0, "names": []}}


def load_book(store) -> dict:
    raw = store.get_setting(BOOK_KEY)
    try:
        b = json.loads(raw) if raw else None
    except ValueError:
        b = None
    return b if isinstance(b, dict) and "positions" in b else new_book()


def save_book(store, book: dict) -> None:
    book["actions"] = book["actions"][-MAX_LOG:]
    book["blocked"] = book["blocked"][-MAX_BLOCKED:]
    store.set_setting(BOOK_KEY, json.dumps(book, default=str))


def _bdays_after(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def equity(book: dict, prices: dict) -> float:
    return book["cash"] + sum(p["shares"] * (prices.get(t) or p["entry"]) for t, p in book["positions"].items())


def _log(book: dict, now: datetime, ticker: str, action: str, shares: float, price: float | None, why: str, result: float | None = None) -> dict:
    a = {"id": book["next_id"], "time": _ts(now), "ticker": ticker, "action": action, "shares": round(shares, 3), "price": price, "why": why, "result": result}
    book["next_id"] += 1
    book["actions"].append(a)
    return a


def _hold_back(book: dict, now: datetime, ticker: str, price, reason: str) -> None:
    day = now.date().isoformat()
    key = re.sub(r"\d+(\.\d+)?", "#", reason)                      # the numbers change every cycle: one line per stock, day and kind of reason
    if any(b.get("ticker") == ticker and b.get("day") == day and re.sub(r"\d+(\.\d+)?", "#", b.get("reason", "")) == key for b in book["blocked"][-200:]):
        return
    book["blocked"].append({"day": day, "time": _ts(now), "ticker": ticker, "price": price, "reason": reason})


# ---------------------------------------------------------------- seeding

def seed(store, now: datetime | None = None, holdings=None) -> dict:
    """Start (or restart) the account from the owner's holdings: every row with shares above 0, at its average cost, plus a cash reserve.
    The holdings are read from the Sheet now and kept only in the app's own database (never in the repo). A holding with no cost in the Sheet
    is taken at its latest price and said so. Returns {'ok', 'note'}."""
    now = (now or datetime.now(NY)).astimezone(NY)
    if holdings is None:
        from . import live
        holdings = live.current_portfolio(store).holdings
    snaps = {s["ticker"]: s for s in store.latest_snapshots()}
    book = new_book()
    cost_total, noted = 0.0, []
    for h in holdings:
        if not h.shares or h.shares <= 0:
            continue
        cost = h.cost_basis
        if not cost:
            px = (snaps.get(h.ticker) or {}).get("price")
            if not px:
                noted.append(f"{h.ticker} left out: no cost in the Sheet and no price yet")
                continue
            cost = float(px)
            noted.append(f"{h.ticker} taken at its latest price: no cost in the Sheet")
        book["positions"][h.ticker] = {"shares": float(h.shares), "entry": float(cost), "base": float(h.shares), "source": "holding",
                                       "opened": _ts(now), "tier": h.tier}
        cost_total += float(h.shares) * float(cost)
    if not book["positions"]:
        return {"ok": False, "note": "No holdings with shares were found in the Sheet, so nothing was started."}
    book["cash"] = round(cost_total * CASH_RESERVE_PCT / 100, 2)
    book["start"] = round(cost_total + book["cash"], 2)
    book["seeded"] = _ts(now)
    _log(book, now, "—", "SEED", 0.0, None, f"Started from {len(book['positions'])} holdings at cost ({cost_total:,.0f}) plus a {CASH_RESERVE_PCT:.0f}% cash reserve."
         + (" " + "; ".join(noted) + "." if noted else ""))
    save_book(store, book)
    return {"ok": True, "note": f"Started with {len(book['positions'])} holdings and ${book['cash']:,.0f} cash." + (" " + "; ".join(noted) + "." if noted else "")}


# ---------------------------------------------------------------- the tests (pure, so each can be checked alone)

def poor_reason(snap: dict) -> str | None:
    """A position is poor when the New call says EXIT or AVOID on the daily close AND the chart is weak (weakening, testing support or broken)
    or momentum is falling. One without the other is not enough. A missing read never counts."""
    oc = _call_of(snap)
    if not oc or oc.get("call") not in ("EXIT", "AVOID"):
        return None
    ps = ui.price_status(snap) or {}
    code = ps.get("code")
    mo = ((snap.get("payload") or {}).get("technical") or {}).get("momentum")
    weak_mo = isinstance(mo, dict) and mo.get("known") and mo.get("momentum") in WEAK_MOMENTUM
    if code in BROKEN_CHART or code in WEAK_CHART or weak_mo:
        sign = f"the chart reads {str(code).replace('_', ' ')}" if code in BROKEN_CHART or code in WEAK_CHART else f"momentum is {mo['momentum']}"
        return f"the call is {oc['call']} and {sign}"
    return None


def cap_pct(snap: dict) -> float:
    grade = ((_call_of(snap) or {}).get("risk") or {}).get("grade")
    return CAP_HIGH_PCT if grade in ("High", "Extreme") else CAP_PCT


def undervalued(snap: dict, price: float) -> tuple[bool, str]:
    """(passes, why). Fair value (at least two methods) 15% above the price AND the analyst target 10% above; anything unknown fails."""
    p = snap.get("payload") or {}
    fv = ((p.get("research") or {}).get("valuation") or {}).get("fair_value") or {}
    mid, methods = _num(fv.get("mid")), len(fv.get("methods") or {})
    up = _num((p.get("fundamental") or {}).get("analyst_upside"))
    if not mid or not price:
        return False, "fair value is not known"
    if methods < MIN_METHODS:
        return False, f"fair value rests on {methods} method (needs {MIN_METHODS})"
    fair = mid / price - 1
    if fair < FAIR_UP:
        return False, f"fair value only {fair * 100:+.0f}% from the price (needs {FAIR_UP * 100:.0f}%)"
    if up is None:
        return False, "the analyst target is not known"
    if up < ANALYST_UP:
        return False, f"analyst target only {up * 100:+.0f}% above (needs {ANALYST_UP * 100:.0f}%)"
    return True, f"fair value {fair * 100:+.0f}%, analyst target {up * 100:+.0f}%"


def add_check(snap: dict, price: float, held: bool, mins: float | None, late: bool, gate: str, book: dict, now: datetime, chg: float | None,
              pace: float | None) -> tuple[bool, str]:
    """Every test an add must pass, in the order that is cheapest to explain. Returns (passes, why not / why)."""
    t = snap["ticker"]
    fs = _num(snap.get("fundamental_score"))
    need = FUND_ADD if held else FUND_NEW
    if fs is None:
        return False, "fundamentals are not known"
    if fs < need:
        return False, f"fundamentals {fs:.0f}, a {'holding' if held else 'new name'} needs {need:.0f}"
    ok, why = undervalued(snap, price)
    if not ok:
        return False, f"not clearly undervalued: {why}"
    oc = _call_of(snap)
    if not oc or oc.get("call") not in ("BUY", "ADD"):
        return False, f"the New call is {(oc or {}).get('call', 'unknown')}, not BUY or ADD"
    if ((oc.get("risk") or {}).get("grade")) in ("High", "Extreme"):
        return False, f"risk grade {oc['risk']['grade']}"
    days = _num(((snap.get("payload") or {}).get("events") or {}).get("days_to_earnings"))
    if days is not None and 0 <= days <= EARN_DAYS:
        return False, f"earnings in {int(days)} day{'s' if days != 1 else ''}"
    weak = weak_reason(snap)
    if weak:
        return False, weak
    lock = (book.get("locks") or {}).get(t)
    if lock and now.date().isoformat() < lock:
        return False, f"trimmed recently, not added to before {lock}"
    if not price > (oc.get("exit_line") or 0):
        return False, "the price is under the exit line"
    if mins is None or mins < FIRST_ADD_MIN:
        return False, "the opening half hour: no adds yet"
    if late:
        return False, "after 15:45: no new adds"
    if gate:
        return False, gate
    if chg is None:
        return False, "today's move is unknown"
    if chg < 0:
        return False, f"down {abs(chg) * 100:.1f}% today, the turn is not there yet"
    if pace is None:
        return False, "today's volume is not read yet"
    if pace < MIN_PACE:
        return False, f"volume only {pace:.1f}x normal for this time"
    return True, f"{why}; fundamentals {fs:.0f}; the call is {oc['call']}"


def add_size(book: dict, price: float, oc: dict, held: bool, snap: dict, prices: dict) -> float:
    """Shares for one add: about 1% of the account at risk from the exit line, at most 5% of the account in the step (3% for a new name),
    the name never above its cap, and never more than the cash. Fractional (to 0.01), and 0 when the add would be under MIN_ADD_USD."""
    eq = equity(book, prices)
    line = oc["exit_line"]
    sh = eq * RISK_PCT / 100 / (price - line)
    sh = min(sh, eq * (ADD_STEP_PCT if held else NEW_START_PCT) / 100 / price, book["cash"] / price)
    have = book["positions"].get(snap["ticker"], {}).get("shares", 0.0) * price
    sh = min(sh, max(0.0, eq * cap_pct(snap) / 100 - have) / price)
    sh = math.floor(sh * 100) / 100
    return sh if sh * price >= MIN_ADD_USD else 0.0


# ---------------------------------------------------------------- doing things

def _sell(book: dict, ticker: str, n: float, price: float, now: datetime, action: str, why: str) -> dict:
    pos = book["positions"][ticker]
    n = round(min(n, pos["shares"]), 3)
    result = round((price - pos["entry"]) * n, 2)
    book["cash"] = round(book["cash"] + n * price, 2)
    pos["shares"] = round(pos["shares"] - n, 3)
    a = _log(book, now, ticker, action, n, price, why, result)
    if pos["shares"] <= 0.0005:
        del book["positions"][ticker]
    return a


def _buy(book: dict, ticker: str, n: float, price: float, now: datetime, action: str, why: str, snap: dict, source: str) -> dict:
    book["cash"] = round(book["cash"] - n * price, 2)
    pos = book["positions"].get(ticker)
    if pos:
        total = pos["shares"] + n
        pos["entry"] = (pos["shares"] * pos["entry"] + n * price) / total
        pos["shares"] = round(total, 3)
        pos["base"] = max(pos.get("base", 0.0), pos["shares"])
    else:
        book["positions"][ticker] = {"shares": float(n), "entry": float(price), "base": float(n), "source": source, "opened": _ts(now),
                                     "tier": snap.get("tier")}
    return _log(book, now, ticker, action, n, price, why)


def _floor(pos: dict) -> float:
    """The fewest shares the account may leave on its own: half of the most it ever held."""
    return round(pos.get("base", pos["shares"]) * (1 - TRIM_AUTO_MAX), 3)


def _check_position(book: dict, ticker: str, snap: dict, price: float, now: datetime, done: list) -> None:
    """The 15:45 look at one open position: trim if poor, size down if over its cap, propose the rest if it stays poor."""
    pos = book["positions"][ticker]
    day = now.date().isoformat()
    book["checked"][ticker] = day
    prices = {ticker: price}
    eq = equity(book, {**{t: p["entry"] for t, p in book["positions"].items()}, **prices})
    why = poor_reason(snap)
    poor = book["poor"].setdefault(ticker, [])
    if why:
        if day not in poor:
            poor.append(day)
        n_days = len(poor)
        trimmed = pos.get("trims", 0)
        room = max(0.0, pos["shares"] - _floor(pos))
        if trimmed == 0 and n_days >= 1:
            step = min(round(pos["base"] * TRIM_STEP, 3), room)
            if step > 0:
                a = _sell(book, ticker, step, price, now, "TRIM", f"{why}: first trim, a quarter of the position")
                pos = book["positions"].get(ticker, pos)
                pos["trims"] = 1
                pos["trim_day_index"] = n_days
                book["locks"][ticker] = _bdays_after(now.date(), REBUY_LOCK_DAYS).isoformat()
                done.append(a)
            else:
                pos["trims"] = 2                                       # nothing the account may sell on its own is left: straight to the proposal
        elif trimmed == 1 and n_days - pos.get("trim_day_index", 0) >= CONFIRM_DAYS:
            step = min(round(pos["base"] * TRIM_STEP, 3), room)
            if step > 0:
                a = _sell(book, ticker, step, price, now, "TRIM", f"{why}, still poor {CONFIRM_DAYS} checks after the first trim: second trim")
                pos = book["positions"].get(ticker, pos)
                pos["trims"] = 2
                done.append(a)
            else:
                pos["trims"] = 2
        elif trimmed >= 2 and ticker not in book["proposals"] and book["positions"].get(ticker):
            until = book.get("silenced", {}).get(ticker)
            if not until or day >= until:
                book["proposals"][ticker] = {"since": _ts(now), "price": price, "shares": pos["shares"], "why": f"{why}; two trims did not help"}
                done.append(_log(book, now, ticker, "PROPOSE EXIT", pos["shares"], price, f"{why}; two trims did not help. Waiting for the owner."))
    else:
        if poor:
            book["poor"][ticker] = []                       # it recovered: the count starts again
        pos["trims"] = 0                                    # a new poor spell starts its steps again (the floor still holds)
        if ticker in book["proposals"]:
            book["proposals"].pop(ticker)                   # the reason is gone: the proposal is withdrawn
            _log(book, now, ticker, "PROPOSAL WITHDRAWN", pos["shares"], price, "the position is no longer poor")
    pos = book["positions"].get(ticker)
    if pos:
        cap = cap_pct(snap)
        worth = pos["shares"] * price
        if worth > eq * cap / 100 * 1.0001:
            over = (worth - eq * cap / 100) / price
            room = max(0.0, pos["shares"] - _floor(pos))
            n = round(min(over, room, pos["shares"] * 0.5), 3)
            if n > 0.0005:
                done.append(_sell(book, ticker, n, price, now, "SIZE DOWN", f"it is {worth / eq * 100:.0f}% of the account, the cap is {cap:.0f}%"))


def step(book: dict, snaps: dict, prices: dict, now: datetime, gate: str = "") -> list[dict]:
    """One cycle. `snaps`/`prices` hold the stocks with a fresh price; `now` is New York time. Returns what it did."""
    done: list[dict] = []
    mins = decision.minutes_into_session(now)
    late = now.time() >= decision.DECIDE
    day = now.date().isoformat()
    if book["adds_day"].get("day") != day:
        book["adds_day"] = {"day": day, "n": 0, "names": []}
    for ticker in list(book["positions"]):
        snap, price = snaps.get(ticker), prices.get(ticker)
        if not snap or not price or mins is None:
            continue
        if late and book["checked"].get(ticker) != day:
            _check_position(book, ticker, snap, price, now, done)
    if late or mins is None or mins < FIRST_ADD_MIN:
        return done
    cands = []
    for ticker, snap in snaps.items():
        price = prices.get(ticker)
        if not price:
            continue
        held = ticker in book["positions"]
        fs = _num(snap.get("fundamental_score"))
        if fs is None or fs < (FUND_ADD if held else FUND_NEW):
            continue                                                 # most of the market stops here: not worth a line each
        if ticker in book["adds_day"]["names"]:
            continue
        chg, pace = today_change(snap), volpace.pace(snap, mins)
        ok, why = add_check(snap, price, held, mins, late, gate, book, now, chg, pace)
        if not ok:
            if why.startswith("not clearly undervalued") or why.startswith("the New call is"):
                continue                                             # a quality stop, not a timing one: quiet
            _hold_back(book, now, ticker, price, f"ADD held back: {why}")
            continue
        oc = _call_of(snap)
        fv = (((snap.get("payload") or {}).get("research") or {}).get("valuation") or {}).get("fair_value") or {}
        cands.append((rank_score(snap, oc, pace, chg) + (fv.get("mid", price) / price - 1), ticker, snap, oc, price, held, why))
    cands.sort(key=lambda c: -c[0])
    for rank, (score, ticker, snap, oc, price, held, why) in enumerate(cands, 1):
        if book["adds_day"]["n"] >= MAX_ADDS_DAY:
            _hold_back(book, now, ticker, price, f"ADD held back: ranked #{rank} of {len(cands)}; {MAX_ADDS_DAY} adds a day is the limit")
            continue
        n = add_size(book, price, oc, held, snap, prices)
        if n <= 0:
            _hold_back(book, now, ticker, price, f"ADD held back: no room (cap, cash or the risk size leaves under ${MIN_ADD_USD:.0f})")
            continue
        a = _buy(book, ticker, n, price, now, "ADD" if held else "NEW NAME", f"{why}. Risk from the exit line {oc['exit_line']:.2f}.", snap,
                 "holding" if held else "added")
        book["adds_day"]["n"] += 1
        book["adds_day"]["names"].append(ticker)
        done.append(a)
    return done


# ---------------------------------------------------------------- the owner's taps

def sell_by_hand(store, ticker: str, now: datetime | None = None, label: str = "sold by hand") -> dict:
    """The owner sells a whole position at the latest fresh price (also how he approves a proposed exit). Recorded as an owner override."""
    now = (now or datetime.now(NY)).astimezone(NY)
    if us_session() != "REGULAR":
        return {"ok": False, "note": "The market is closed: nothing trades outside the regular session."}
    book = load_book(store)
    if ticker not in book["positions"]:
        return {"ok": False, "note": f"{ticker} is not open any more."}
    snap = store.snapshot(ticker)
    price, why = paper_live.fresh_price(snap, now) if snap else (None, "no reading for this stock")
    if price is None:
        return {"ok": False, "note": f"No fresh price for {ticker} ({why}), so it was not sold. Try again in a minute."}
    a = _sell(book, ticker, book["positions"][ticker]["shares"], price, now, "SELL ALL", f"{OVERRIDE}: {label} at {price:.2f}")
    book["proposals"].pop(ticker, None)
    save_book(store, book)
    return {"ok": True, "note": f"Sold all of {ticker} at {price:.2f}: {a['result']:+,.2f}."}


def keep_it(store, ticker: str, now: datetime | None = None) -> dict:
    """The owner says no to a proposed exit: it is not proposed again for KEEP_DAYS days."""
    now = (now or datetime.now(NY)).astimezone(NY)
    book = load_book(store)
    if book["proposals"].pop(ticker, None) is None:
        return {"ok": False, "note": f"There is no proposal for {ticker}."}
    book.setdefault("silenced", {})[ticker] = _bdays_after(now.date(), KEEP_DAYS).isoformat()
    _log(book, now, ticker, "KEPT", book["positions"].get(ticker, {}).get("shares", 0.0), None, "the owner chose to keep it")
    save_book(store, book)
    return {"ok": True, "note": f"{ticker} is kept. It will not be proposed again before {book['silenced'][ticker]}."}


# ---------------------------------------------------------------- the tracker's cycle and the page

def push(store, did: list[dict]) -> None:
    """One phone message per action (the LOG feed). Display and delivery only."""
    try:
        from . import events
        for a in did:
            who = {"TRIM": "trimmed", "SIZE DOWN": "sized down", "ADD": "added to", "NEW NAME": "bought a new name,", "PROPOSE EXIT": "proposes selling the rest of"}.get(a["action"], a["action"].lower())
            events._push(f"Portfolio {who} {a['ticker']}", [f"{a['why']}"], 3 if a["action"] != "PROPOSE EXIT" else 4, "briefcase", a["ticker"], "log", store)
    except Exception:
        log.exception("portfolio push failed")


def tick(store, now: datetime | None = None, force_session: bool = False) -> dict:
    """One cycle from the tracker thread. Does nothing outside the regular session, or before the account is started (the owner starts it
    with the button, or it seeds itself on the first session)."""
    now = (now or datetime.now(NY)).astimezone(NY)
    state = {"at": now.isoformat(), "watching": 0, "skipped": {}, "did": [], "note": ""}
    if not (force_session or us_session() == "REGULAR"):
        state["note"] = "market closed: nothing trades outside the regular session"
        store.set_setting(STATE_KEY, json.dumps(state))
        return state
    book = load_book(store)
    if not book["positions"] and not book.get("seeded"):
        out = seed(store, now)
        state["note"] = out["note"]
        if not out["ok"]:
            store.set_setting(STATE_KEY, json.dumps(state))
            return state
        book = load_book(store)
    snaps, prices = {}, {}
    for s in store.latest_snapshots():
        t = s["ticker"]
        price, why = paper_live.fresh_price(s, now)
        if price is None:
            if t in book["positions"]:
                state["skipped"][t] = why + ": this position is NOT being checked right now"
            continue
        snaps[t], prices[t] = s, price
    state["watching"] = len(snaps)
    gate = quick.market_gate(snaps)
    state["gate"] = gate
    before = json.dumps(book, default=str, sort_keys=True)
    state["did"] = step(book, snaps, prices, now, gate)
    if state["did"]:
        push(store, state["did"])
    if json.dumps(book, default=str, sort_keys=True) != before:
        save_book(store, book)
    store.set_setting(STATE_KEY, json.dumps(state, default=str))
    return state


def status(store) -> dict:
    raw = store.get_setting(STATE_KEY)
    return {"book": load_book(store), "state": json.loads(raw) if raw else None}


def prices_of(store, tickers) -> dict:
    out = {}
    for t in tickers:
        sn = store.snapshot(t)
        if sn:
            px, _, _live = ui._now(sn)
            if px == px and px is not None:
                out[t] = float(px)
    return out
