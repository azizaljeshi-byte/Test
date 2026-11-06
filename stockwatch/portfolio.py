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
# the owner's picks (owner, 6 Nov): flagged KEEP or PICK in the Notes column of his Sheet ("PICK 3%" sets the starter size). Maximum exposure, never an exit:
CORE_SHARE = 0.5               # half of a pick is the core, which the system never sells (only the owner's hand button does); the other half is traded
STARTER_PCT = 2.0              # a pick not held yet: the starter proposal, as a share of the account
PICK_LOSS_PCT = 10.0           # a pick this far under the owner's cost also gets the daily reminder
REBUY_WAIT_DAYS = 10           # an approved trim waits this many trading days for the dip to turn before the re-buy is dropped
REBUY_CHASE = 1.02             # the re-buy is never above the sale price by more than this (no chasing)
PICKS_EVERY_MIN = 5            # how often the Notes are read again
# stocks the owner flags DIP: add a small fractional piece on weakness (a drop, a weak or broken chart, testing support), never a full entry
DIP_RE = re.compile(r"\bDIP\b(?:\s*(\d+(?:\.\d+)?)\s*%)?", re.I)
DIP_DROP = 0.03                # down this much on the day is a dip
DIP_STEP_PCT = 1.0             # one add: this share of the account (fractional shares), unless the note says "DIP 0.5%"
DIP_MAX_PCT = 3.0              # the most one DIP name may reach, as a share of the account
DIP_SPACING = 0.02             # the next add needs a price this far under the last add
# the hard stop and the profit exit (owner, 6 Nov: no exception, KEEP stocks included; in profit the stop trails the support)
STOP_ATR = 2.0                 # a stop with no usable support under the price sits this many daily ranges below it
STOP_MAX_DROP = 0.15           # a stop is never further than this under the price it is set at
STOP_FALLBACK = 0.92           # no range known: 8% under the price
STOP_MOVE_PCT = 0.5            # the broker stop is "out of date" when the line is this much above what the owner ticked
PICK_RE = re.compile(r"\b(?:KEEP|PICK)\b(?:\s*(\d+(?:\.\d+)?)\s*%)?", re.I)


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def _ts(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M")


def new_book() -> dict:
    return {"cash": 0.0, "start": 0.0, "positions": {}, "actions": [], "blocked": [], "proposals": {}, "seeded": None, "next_id": 1,
            "poor": {}, "checked": {}, "locks": {}, "adds_day": {"day": "", "n": 0, "names": []},
            "picks": {}, "pick_props": {}, "rebuys": {}, "reminded": {}, "dips": {}, "dip_last": {}}


def load_book(store) -> dict:
    raw = store.get_setting(BOOK_KEY)
    try:
        b = json.loads(raw) if raw else None
    except ValueError:
        b = None
    if not (isinstance(b, dict) and "positions" in b):
        return new_book()
    for k, v in new_book().items():
        b.setdefault(k, v)                                          # a book saved by an older version gains the new keys
    return b


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


# ---------------------------------------------------------------- the owner's picks

def parse_picks(holdings) -> dict:
    """{ticker: {'pct': starter size or None}} for every row whose Notes say KEEP or PICK (any case; 'PICK 3%' sets the starter size)."""
    out = {}
    for h in holdings or []:
        m = PICK_RE.search(getattr(h, "notes", None) or "")
        if m:
            out[h.ticker] = {"pct": float(m.group(1)) if m.group(1) else None}
    return out


def parse_dips(holdings) -> dict:
    """{ticker: {'pct': step size or None}} for rows whose Notes say DIP ('DIP 0.5%' sets the step). A KEEP or PICK row is never also a DIP row."""
    out = {}
    for h in holdings or []:
        n = getattr(h, "notes", None) or ""
        m = DIP_RE.search(n)
        if m and not PICK_RE.search(n):
            out[h.ticker] = {"pct": float(m.group(1)) if m.group(1) else None}
    return out


def _apply_picks(book: dict, picks: dict) -> None:
    """Mark the core slice: half of what a pick holds is never sold by the system. Dropping the flag releases it."""
    book["picks"] = picks
    for t, pos in book["positions"].items():
        if t in picks:
            pos.setdefault("core", round(pos["shares"] * CORE_SHARE, 3))
        else:
            pos.pop("core", None)
    for t in [t for t, pr in book["pick_props"].items() if t not in picks and pr.get("kind") != "dip"]:
        book["pick_props"].pop(t)
        book["rebuys"].pop(t, None)


def refresh_picks(store, book: dict, now: datetime) -> bool:
    """Read the Notes again at most every PICKS_EVERY_MIN minutes (a Sheet read is slow). A failed read keeps the last picks."""
    last = book.get("picks_at")
    if last:
        try:
            if (now - datetime.fromisoformat(last)).total_seconds() < PICKS_EVERY_MIN * 60:
                return False
        except ValueError:
            pass
    book["picks_at"] = now.isoformat()
    try:
        from . import live
        hs = live.current_portfolio(store).holdings
        _apply_picks(book, parse_picks(hs))
        book["dips"] = parse_dips(hs)
    except Exception:
        log.exception("portfolio picks read failed")
    return True


def trading_room(pos: dict) -> float:
    """Shares of a pick the system may trade (everything above the core); all of them for a stock that is not a pick."""
    return max(0.0, pos["shares"] - pos.get("core", 0.0))


# ---------------------------------------------------------------- seeding

def seed(store, now: datetime | None = None, holdings=None, cash: float | None = None) -> dict:
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
    _apply_picks(book, parse_picks(holdings))
    book["dips"] = parse_dips(holdings)
    book["picks_at"] = now.isoformat()
    book["cash"] = round(cash, 2) if cash and cash > 0 else round(cost_total * CASH_RESERVE_PCT / 100, 2)    # the owner's real cash when he gives it
    book["start"] = round(cost_total + book["cash"], 2)
    book["seeded"] = _ts(now)
    _log(book, now, "—", "SEED", 0.0, None, f"Started from {len(book['positions'])} holdings at cost ({cost_total:,.0f}) plus " + (f"your cash of {book['cash']:,.2f}." if cash and cash > 0 else f"a {CASH_RESERVE_PCT:.0f}% cash reserve.")
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


# ---------------------------------------------------------------- suggested adds (display only)

SUGGEST_MAX = 8


def suggestions(book: dict, snaps: dict, prices: dict) -> list[dict]:
    """Stocks the account does NOT hold that pass the quality tests (fundamentals, undervalued, risk), with the right entry point. Display only: buying
    is still done by the add rules or by the owner's Approve on a pick. State: 'zone' (price inside the entry zone, call BUY/ADD), 'price' (above
    the zone: wait for it to come down), 'turn' (the call or chart is not there yet: wait for a turn), 'not yet' never shown."""
    out = []
    for t, snap in snaps.items():
        price = prices.get(t)
        if not price or t in book["positions"]:
            continue
        fs = _num(snap.get("fundamental_score"))
        if fs is None or fs < FUND_NEW:
            continue
        ok, why = undervalued(snap, price)
        oc = _call_of(snap) or {}
        if not ok or (oc.get("risk") or {}).get("grade") in ("High", "Extreme"):
            continue
        plan = (snap.get("payload") or {}).get("plan") or {}
        lo, hi, stop = _num(plan.get("entry_low")), _num(plan.get("entry_high")), _num(plan.get("stop"))
        tg = ((plan.get("targets") or [{}])[0] or {}).get("price")
        line = _num(oc.get("exit_line"))
        turned = oc.get("call") in ("BUY", "ADD") and not weak_reason(snap) and (line is None or price > line)
        if lo and hi and price > hi * 1.005:
            state, note = "price", f"Wait for the price: buy between {lo:.2f} and {hi:.2f}"
        elif not turned:
            state, note = "turn", ("Wait for the turn: it needs a close back above " + f"{line:.2f}" if line and price <= line else "Wait for the turn: the call is "
                                   + str(oc.get("call", "unknown")))
        else:
            state, note = "zone", "In the buy zone, the call is " + str(oc.get("call"))
        out.append({"ticker": t, "state": state, "note": note, "price": price, "zone": [lo, hi] if lo and hi else None, "stop": stop, "target": _num(tg),
                    "fund": fs, "why": why, "order": {"zone": 0, "price": 1, "turn": 2}[state] * 1000 - fs})
    out.sort(key=lambda r: r["order"])
    return out[:SUGGEST_MAX]


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
    pos = book["positions"][ticker]
    if pos.get("stop") is None:
        pos["stop"] = stop_candidate(snap, price)
        pos["broker_stop"], pos["broker_stop_at"] = False, None
    return _log(book, now, ticker, action, n, price, why + f" Hard stop {pos['stop']:.2f}.")


def stop_candidate(snap: dict, price: float) -> float:
    """The hard stop for a price: the New call's exit line (the support) when it is under the price, kept within STOP_MAX_DROP of it; otherwise
    STOP_ATR daily ranges under the price, or 8% under when no range is known. Always returns a number: no position is left without a stop."""
    p = (snap.get("payload") or {})
    line = _num(((_call_of(snap) or {}).get("exit_line")))
    atr = _num((p.get("technical") or {}).get("atr"))
    floor = price * (1 - STOP_MAX_DROP)
    if line and line < price * 0.995:
        cand = max(line, floor)
    elif atr:
        cand = max(price - STOP_ATR * atr, floor)
    else:
        cand = price * STOP_FALLBACK
    return round(cand, 2)


def target_candidate(snap: dict, price: float) -> float | None:
    """The profit exit: the nearest resistance above the price (the first target of the trade plan). None when nothing is read above."""
    for t in ((snap.get("payload") or {}).get("plan") or {}).get("targets") or []:
        v = _num((t or {}).get("price"))
        if v and v > price * 1.002:
            return round(v, 2)
    return None


def _levels(pos: dict, snap: dict, price: float) -> None:
    """Keep the position's lines. The stop is set once and only moves UP. While the position is in profit it trails the support AND never sits under
    the owner's cost, so a winner cannot turn into a loss (owner, 6 Nov). A loss-side stop never moves. The profit exit is set when the position is
    in profit and stays."""
    cand = stop_candidate(snap, price)
    if pos.get("stop") is None:
        pos["stop"] = cand
    if price > pos["entry"]:
        pos["stop"] = max(pos["stop"], cand, math.ceil(pos["entry"] * 100) / 100)
        if pos.get("target") is None:
            pos["target"] = target_candidate(snap, price)


def _floor(pos: dict) -> float:
    """The fewest shares the account may leave on its own: half of the most it ever held."""
    return round(pos.get("base", pos["shares"]) * (1 - TRIM_AUTO_MAX), 3)


def _check_position(book: dict, ticker: str, snap: dict, price: float, now: datetime, done: list) -> None:
    """The 15:45 look at one open position: trim if poor, size down if over its cap, propose the rest if it stays poor."""
    pos = book["positions"][ticker]
    day = now.date().isoformat()
    book["checked"][ticker] = day
    if ticker in book.get("picks", {}):
        _check_pick(book, ticker, snap, price, now, done)
        return
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


def _check_pick(book: dict, ticker: str, snap: dict, price: float, now: datetime, done: list) -> None:
    """The 15:45 look at an owner's pick. It never trims or exits by itself: a poor spell becomes a trim PROPOSAL (from the trading slice only) and
    one reminder a day while the stock keeps falling. The core slice is never touched."""
    pos = book["positions"][ticker]
    day = now.date().isoformat()
    why = poor_reason(snap)
    move = (price / pos["entry"] - 1) * 100
    props = book["pick_props"]
    if why or move <= -PICK_LOSS_PCT:
        if book["reminded"].get(ticker) != day:
            book["reminded"][ticker] = day
            note = (f"still falling: {move:+.0f}% from your cost" if move < 0 else "weak right now") + f", {why or 'under your cost'}. Core slice held, nothing sold."
            done.append(_log(book, now, ticker, "REMINDER", pos["shares"], price, note))
    if why:
        room = trading_room(pos)
        until = book.get("silenced", {}).get(ticker)
        if ticker not in props and ticker not in book["rebuys"] and room > 0.0005 and (not until or day >= until):
            n = round(min(pos["base"] * TRIM_STEP, room), 3)
            if n * price >= MIN_ADD_USD or n >= room - 0.0005:
                props[ticker] = {"kind": "trim", "shares": n, "price": price, "since": _ts(now),
                                 "why": f"{why}. Sell {n:g} of the trading slice ({room:g} shares), then buy back when the fall stops"}
                done.append(_log(book, now, ticker, "PROPOSE TRIM", n, price, props[ticker]["why"] + ". Waiting for the owner."))
    elif ticker in props and props[ticker]["kind"] == "trim":
        props.pop(ticker)
        _log(book, now, ticker, "PROPOSAL WITHDRAWN", pos["shares"], price, "the position is no longer poor")


def _starters(book: dict, snaps: dict, prices: dict, now: datetime, done: list) -> None:
    """A pick the account does not hold yet (the owner wants exposure even when the system reads breakdown): one small STARTER proposal."""
    day = now.date().isoformat()
    for t, meta in book.get("picks", {}).items():
        price, snap = prices.get(t), snaps.get(t)
        if t in book["positions"] or t in book["pick_props"] or not price or not snap or day < (book.get("locks") or {}).get(t, ""):
            continue
        until = book.get("silenced", {}).get(t)
        if until and day < until:
            continue
        eq = equity(book, prices)
        pct = meta.get("pct") or STARTER_PCT
        n = math.floor(min(eq * pct / 100, book["cash"]) / price * 100) / 100
        if n * price < MIN_ADD_USD:
            continue
        oc = _call_of(snap) or {}
        read = f"the call is {oc['call']}" if oc.get("call") else "no call yet"
        book["pick_props"][t] = {"kind": "starter", "shares": n, "price": price, "since": _ts(now),
                                 "why": f"your pick, not held yet ({read}). A starter of {pct:g}% of the account: {n:g} shares"}
        done.append(_log(book, now, t, "PROPOSE STARTER", n, price, book["pick_props"][t]["why"] + ". Waiting for the owner."))


def _dips(book: dict, snaps: dict, prices: dict, now: datetime, done: list) -> None:
    """A DIP stock on weakness (down 3% on the day, a weak or broken chart, or testing support): one small fractional add PROPOSAL a day.
    Never a full entry: the name stops at DIP_MAX_PCT of the account, and the next add needs a price 2% under the last one."""
    day = now.date().isoformat()
    for t, meta in book.get("dips", {}).items():
        snap, price = snaps.get(t), prices.get(t)
        if not snap or not price or t in book["pick_props"] or t in book.get("picks", {}) or day < (book.get("locks") or {}).get(t, ""):
            continue
        until = book.get("silenced", {}).get(t)
        if (until and day < until) or book.get("dip_day", {}).get(t) == day:
            continue
        chg = today_change(snap)
        code = (ui.price_status(snap) or {}).get("code")
        reasons = []
        if chg is not None and chg <= -DIP_DROP:
            reasons.append(f"down {abs(chg) * 100:.1f}% today")
        if code in BROKEN_CHART:
            reasons.append(f"the chart reads {str(code).replace('_', ' ')}")
        elif code in WEAK_CHART:
            reasons.append(f"the chart reads {str(code).replace('_', ' ')}")
        if not reasons:
            continue
        last = book["dip_last"].get(t)
        if last and price > last * (1 - DIP_SPACING):
            continue
        eq = equity(book, prices)
        have = book["positions"].get(t, {}).get("shares", 0.0) * price
        room = eq * DIP_MAX_PCT / 100 - have
        pct = meta.get("pct") or DIP_STEP_PCT
        n = math.floor(min(eq * pct / 100, room, book["cash"]) / price * 100) / 100
        if n * price < MIN_ADD_USD:
            continue
        book.setdefault("dip_day", {})[t] = day
        book["pick_props"][t] = {"kind": "dip", "shares": n, "price": price, "since": _ts(now),
                                 "why": f"your DIP stock: {' and '.join(reasons)}. A small piece of {pct:g}% of the account ({n:g} shares), at most {DIP_MAX_PCT:g}% in all"}
        done.append(_log(book, now, t, "PROPOSE DIP", n, price, book["pick_props"][t]["why"] + ". Waiting for the owner."))


def _rebuys(book: dict, snaps: dict, prices: dict, now: datetime, mins, gate: str, done: list) -> None:
    """After an approved trim, buy the sold shares back by itself when the fall has stopped and the stock turns up near its exit line."""
    day = now.date().isoformat()
    for t, rb in list(book["rebuys"].items()):
        if day >= rb["until"]:
            book["rebuys"].pop(t)
            _log(book, now, t, "REBUY DROPPED", rb["shares"], None, "the dip did not turn within the wait; nothing bought back")
            continue
        snap, price = snaps.get(t), prices.get(t)
        if not snap or not price or t not in book["positions"] or gate:
            continue
        if poor_reason(snap) or weak_reason(snap):
            continue
        chg = today_change(snap)
        if chg is None or chg < 0 or price > rb["price"] * REBUY_CHASE:
            continue
        line = (_call_of(snap) or {}).get("exit_line")
        if line and not price > line:
            continue
        n = math.floor(min(rb["shares"], book["cash"] / price) * 100) / 100
        if n * price < MIN_ADD_USD:
            continue
        a = _buy(book, t, n, price, now, "REBUY", f"the fall stopped and it turned up (up {chg * 100:.1f}% today); buying back what the approved trim sold at {rb['price']:.2f}", snap, "holding")
        book["rebuys"].pop(t)
        done.append(a)


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
        pos = book["positions"][ticker]
        _levels(pos, snap, price)
        hit = ("HARD STOP", f"the price {price:.2f} is at or under the hard stop {pos['stop']:.2f}") if price <= pos["stop"] else \
              ("PROFIT EXIT", f"the price {price:.2f} reached the profit exit {pos['target']:.2f}, set from resistance") if pos.get("target") and price >= pos["target"] else None
        if hit:
            done.append(_sell(book, ticker, pos["shares"], price, now, hit[0], hit[1] + ". Sold all, no exception."))
            for k in ("proposals", "pick_props", "rebuys"):
                book[k].pop(ticker, None)
            book["locks"][ticker] = _bdays_after(now.date(), REBUY_LOCK_DAYS).isoformat()
            continue
        if late and book["checked"].get(ticker) != day:
            _check_position(book, ticker, snap, price, now, done)
    if late or mins is None or mins < FIRST_ADD_MIN:
        return done
    _rebuys(book, snaps, prices, now, mins, gate, done)
    _starters(book, snaps, prices, now, done)
    _dips(book, snaps, prices, now, done)
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


SALES = ("TRIM", "SIZE DOWN", "SELL ALL", "HARD STOP", "PROFIT EXIT")


def record_close(store, action_id: int, price: float) -> dict:
    """The owner enters the price his broker really filled a sale at. The fake sale is corrected to it: the result and the cash move by the same difference."""
    book = load_book(store)
    a = next((x for x in book["actions"] if x["id"] == action_id and x["action"] in SALES), None)
    if a is None or not a.get("price"):
        return {"ok": False, "note": "That sale was not found."}
    if not (isinstance(price, (int, float)) and price == price and price > 0):
        return {"ok": False, "note": "Enter the price as a number above zero."}
    delta = round(a["shares"] * (float(price) - a["price"]), 2)
    a.setdefault("fake_price", a["price"])
    a["price"], a["result"] = round(float(price), 4), round((a["result"] or 0.0) + delta, 2)
    book["cash"] = round(book["cash"] + delta, 2)
    save_book(store, book)
    return {"ok": True, "note": f"{a['ticker']} close saved at {price:,.2f} (the account had {a['fake_price']:,.2f}): {delta:+,.2f}."}


def set_broker_stop(store, ticker: str, on: bool) -> dict:
    """The owner's tick: the hard stop is (or is not) set on his broker account. Remembers the line he set it at, so a later move up shows."""
    book = load_book(store)
    pos = book["positions"].get(ticker)
    if not pos:
        return {"ok": False, "note": f"{ticker} is not open."}
    pos["broker_stop"], pos["broker_stop_at"] = bool(on), (pos.get("stop") if on else None)
    save_book(store, book)
    return {"ok": True, "note": f"{ticker}: broker stop {'ticked at ' + format(pos['stop'], '.2f') if on and pos.get('stop') else 'not set'}."}


def stop_summary(book: dict) -> dict:
    """{'set': n, 'total': n, 'none': [tickers with no broker stop], 'move': [(ticker, line, ticked)]} for the top of the tab."""
    pos = book["positions"]
    none = [t for t, p in pos.items() if not p.get("broker_stop")]
    move = [(t, p["stop"], p["broker_stop_at"]) for t, p in pos.items()
            if p.get("broker_stop") and p.get("stop") and p.get("broker_stop_at") and p["stop"] > p["broker_stop_at"] * (1 + STOP_MOVE_PCT / 100)]
    return {"set": len(pos) - len(none), "total": len(pos), "none": none, "move": move}


def set_cash(store, amount: float, now: datetime | None = None) -> dict:
    """The owner sets the account's cash to his real figure. The start moves by the same amount, so profit and loss do not change."""
    now = (now or datetime.now(NY)).astimezone(NY)
    if not (isinstance(amount, (int, float)) and amount == amount and amount >= 0):
        return {"ok": False, "note": "Enter the cash as a number, zero or more."}
    book = load_book(store)
    if not book["positions"]:
        return {"ok": False, "note": "The account is not started yet."}
    delta = round(float(amount) - book["cash"], 2)
    if delta == 0:
        return {"ok": True, "note": f"Cash is already {amount:,.2f}."}
    book["cash"] = round(float(amount), 2)
    book["start"] = round(book["start"] + delta, 2)
    _log(book, now, "—", "CASH", 0.0, None, f"{OVERRIDE}: cash set to {amount:,.2f} ({delta:+,.2f}); the starting amount moved by the same, so profit is unchanged")
    save_book(store, book)
    return {"ok": True, "note": f"Cash is now {amount:,.2f}. Profit and loss are unchanged."}


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


def approve_pick(store, ticker: str, now: datetime | None = None) -> dict:
    """The owner says yes to a proposal on a pick: a trim (sells from the trading slice, then the re-buy is automatic) or a starter."""
    now = (now or datetime.now(NY)).astimezone(NY)
    if us_session() != "REGULAR":
        return {"ok": False, "note": "The market is closed: nothing trades outside the regular session."}
    book = load_book(store)
    prop = book["pick_props"].get(ticker)
    if not prop:
        return {"ok": False, "note": f"There is no proposal for {ticker}."}
    snap = store.snapshot(ticker)
    price, why = paper_live.fresh_price(snap, now) if snap else (None, "no reading for this stock")
    if price is None:
        return {"ok": False, "note": f"No fresh price for {ticker} ({why}). Try again in a minute."}
    if prop["kind"] == "trim":
        pos = book["positions"].get(ticker)
        n = min(prop["shares"], trading_room(pos)) if pos else 0.0
        if n <= 0.0005:
            book["pick_props"].pop(ticker)
            save_book(store, book)
            return {"ok": False, "note": f"Nothing is left in the trading slice of {ticker}."}
        _sell(book, ticker, n, price, now, "TRIM", f"{OVERRIDE}: approved trim of the trading slice at {price:.2f}; the core slice stays")
        book["positions"][ticker]["trims"] = book["positions"][ticker].get("trims", 0) + 1
        book["rebuys"][ticker] = {"shares": round(n, 3), "price": price, "until": _bdays_after(now.date(), REBUY_WAIT_DAYS).isoformat()}
        note = f"Sold {n:g} of {ticker} at {price:.2f}. The core slice stays, and it buys back by itself when the fall stops."
    elif prop["kind"] == "dip":
        n = math.floor(min(prop["shares"], book["cash"] / price) * 100) / 100
        if n * price < MIN_ADD_USD:
            return {"ok": False, "note": f"Not enough cash for a small add in {ticker}."}
        _buy(book, ticker, n, price, now, "DIP ADD", f"{OVERRIDE}: approved small add on weakness at {price:.2f}", snap, "added")
        book["dip_last"][ticker] = price
        note = f"Bought {n:g} {ticker} at {price:.2f}."
    else:
        n = math.floor(min(prop["shares"], book["cash"] / price) * 100) / 100
        if n * price < MIN_ADD_USD:
            return {"ok": False, "note": f"Not enough cash for a starter in {ticker}."}
        _buy(book, ticker, n, price, now, "STARTER", f"{OVERRIDE}: approved starter in your pick at {price:.2f}", snap, "pick")
        book["positions"][ticker]["core"] = round(n * CORE_SHARE, 3)
        note = f"Bought {n:g} {ticker} at {price:.2f}."
    book["pick_props"].pop(ticker, None)
    save_book(store, book)
    return {"ok": True, "note": note}


def skip_pick(store, ticker: str, now: datetime | None = None) -> dict:
    """The owner says no to a proposal on a pick: it is logged (so we can judge it later) and not proposed again before tomorrow's check."""
    now = (now or datetime.now(NY)).astimezone(NY)
    book = load_book(store)
    prop = book["pick_props"].pop(ticker, None)
    if prop is None:
        return {"ok": False, "note": f"There is no proposal for {ticker}."}
    book.setdefault("silenced", {})[ticker] = _bdays_after(now.date(), 1).isoformat()
    _log(book, now, ticker, "SKIPPED", prop["shares"], prop["price"], f"you skipped the {prop['kind']} proposed at {prop['price']:.2f}: {prop['why']}")
    save_book(store, book)
    return {"ok": True, "note": f"Skipped. {ticker} is not proposed again before {book['silenced'][ticker]}."}


# ---------------------------------------------------------------- the tracker's cycle and the page

def push(store, did: list[dict]) -> None:
    """One phone message per action (the LOG feed). Display and delivery only."""
    try:
        from . import events
        for a in did:
            who = {"TRIM": "trimmed", "SIZE DOWN": "sized down", "ADD": "added to", "NEW NAME": "bought a new name,", "PROPOSE EXIT": "proposes selling the rest of",
                   "HARD STOP": "hard stop hit:", "PROFIT EXIT": "profit exit:", "PROPOSE TRIM": "proposes trimming", "PROPOSE STARTER": "proposes a starter in", "PROPOSE DIP": "proposes a small add to", "DIP ADD": "added a small piece of", "REBUY": "bought back", "REMINDER": "reminder:"}.get(a["action"], a["action"].lower())
            events._push(f"Portfolio {who} {a['ticker']}", [f"{a['why']}"], 5 if a["action"] == "HARD STOP" else 4 if a["action"] in ("PROPOSE EXIT", "PROPOSE TRIM", "PROPOSE STARTER", "PROPOSE DIP") else 3, "briefcase", a["ticker"], "log", store)
    except Exception:
        log.exception("portfolio push failed")


def tick(store, now: datetime | None = None, force_session: bool = False) -> dict:
    """One cycle from the tracker thread. Does nothing outside the regular session, or before the account is started (the owner starts it
    with the button, or it seeds itself on the first session)."""
    now = (now or datetime.now(NY)).astimezone(NY)
    state = {"at": now.isoformat(), "watching": 0, "skipped": {}, "did": [], "note": ""}
    if not (force_session or us_session() == "REGULAR"):
        state["note"] = "market closed: nothing trades outside the regular session"
        try:
            ensure_levels(store)
        except Exception:
            log.exception("portfolio levels failed")
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
    try:
        state["suggested"] = suggestions(book, snaps, prices)
    except Exception:
        log.exception("portfolio suggestions failed")
    gate = quick.market_gate(snaps)
    state["gate"] = gate
    before = json.dumps(book, default=str, sort_keys=True)
    refresh_picks(store, book, now)
    state["did"] = step(book, snaps, prices, now, gate)
    if state["did"]:
        push(store, state["did"])
    if json.dumps(book, default=str, sort_keys=True) != before:
        save_book(store, book)
    store.set_setting(STATE_KEY, json.dumps(state, default=str))
    return state


def ensure_levels(store) -> int:
    """Give every open position its stop (and profit exit) from the latest saved reading, even when the market is closed. Display only: it sells
    nothing and never moves a stop that exists. Returns how many positions were given a stop."""
    book = load_book(store)
    new = 0
    for t, pos in book["positions"].items():
        if pos.get("stop") is not None:
            continue
        snap = store.snapshot(t)
        px = None
        if snap:
            px, _, _live = ui._now(snap)
        if not snap or px is None or px != px:
            continue
        _levels(pos, snap, float(px))
        pos.setdefault("broker_stop", False)
        new += 1
    if new:
        save_book(store, book)
    return new


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
