"""The "New call" paper account (owner, 2026-10-27): its own $50,000 fake account that trades the technical-first one-call
(`onecall.py`) beside the Paper and whole-watchlist accounts, which are untouched. Nothing real is traded and no alert is sent.

Rules (every stock the app tracks, regular session only, live price must be fresh):
  enter   no position, the call is BUY or ADD, the live price is above the exit line, the opening hour is over, it is before
          15:45 New York, fewer than MAX_POSITIONS are open. Size: an exit-line hit costs about 1% of the account (half size
          for High or Extreme risk), no position over 15% of the account.
          Same-day check: the live price is not below yesterday's close (today's change is 0 or better). An unknown change
          means no entry, with the reason. Held-back buys are listed in the account's "not bought" log.
  exit    the call turns EXIT or AVOID (a completed close under the band): sell all. Or at 15:45 New York the live price is
          under the band line the trade was opened with: sell all (judged late in the day, never in the first hour).
  else    hold. Missing data never trades: a missing price or call gives "nothing", with the reason.

Added 2026-10-30 (owner): no setup, no buy (today's volume at least MIN_PACE of normal for the time of day, else held back with the
reason); RIDING (once up RIDE_ATR daily ranges the stop trails TRAIL_ATR under the peak and never under the entry, any time of day);
BEATEN (live: under the call's exit line by a quarter range, or 1.5 ranges under the entry; added 2026-10-30 after CYPH sat at -15%);
STALLED (from 14:00, a trade open since an earlier day, with a tight day, no volume and no new high since yesterday is sold, locking
whatever profit it has, so the cash can go to the next setup).
"""
from __future__ import annotations

import json
from datetime import datetime

from . import decision, paper, paper_live, quick, volpace
from .data import NY, us_session

BOOK_KEY, STATE_KEY = "paper_newcall_book", "paper_newcall_state"
MAX_POSITIONS = 10
SIZE_CAP_PCT = 15.0
BLACKOUT_MIN = 60
MIN_PACE = 0.8        # no buy unless today's volume is at least this much of normal for the time of day (a setup that is not established)
RIDE_ATR = 1.0        # once up this many daily ranges the stop starts to trail (the trade is "riding")
TRAIL_ATR = 1.0       # the trailing stop sits this far under the peak, never under the entry
TIGHT_ATR = 0.5       # a day's range under this many daily ranges is "tight"
QUIET_PACE = 0.7      # volume under this much of normal is "no volume"
MAX_NEW, NEW_WINDOW_MIN = 3, 15   # at most this many new entries in any window: nine buys at 10:37 on 30 Oct came from one open-hour wait
BEATEN_ATR = 0.25     # BEATEN: under the call's exit line by this many daily ranges (live, not waiting for the daily close)
CUT_ATR = 1.5         # BEATEN: or down this many daily ranges from the entry
BEATEN_FROM_MIN = 30  # not in the first half hour
STALL_FROM_MIN = 270  # the stalled check starts at 14:00 New York, when the day's range has formed
# Added 2026-11-01 (owner): no weak stock, a riding-or-stalled check at +2%, a falling-or-stabilising check at -1%, and ranked entries.
DIP_PCT = 1.0         # down this much from the entry: watch the stock; is it still falling or stabilising?
DIP_WATCH_MIN = 20    # still down, with no bounce off the low, after this many minutes: falling
DIP_SLIDE_PCT = 0.5   # a new low this far under where the watch began, with no bounce: falling
DIP_BOUNCE_PCT = 0.3  # a bounce this far off the low means it is stabilising
UP_PCT = 2.0          # up this much from the entry: is it riding or stalled?
STALL_MIN = 10        # no new high for this long ... (owner, 4 Nov: leave soon after +2% unless it is still riding; was 45)
GIVEBACK_PCT = 0.3    # ... and this far under the peak: stalled (sold, locking the profit; was 0.5)
WEAK_CHART = ("weakening", "testing_support")
WEAK_MOMENTUM = ("falling", "weak", "fading")
BROKEN_CHART = ("breakdown", "deep_breakdown")


def weak_reason(snap: dict) -> str | None:
    """Why this stock is too weak to buy, or None. Weak is a confirmed breakdown (a completed close under support), or a weak chart
    (weakening or testing support) that a second sign agrees with: falling momentum, or TradingView/Finnhub saying SELL. A weak chart alone
    does not block (the New call buys near support once the fall stops); a missing read never blocks."""
    from . import ui
    ps = ui.price_status(snap)
    if not ps:
        return None
    code = ps.get("code")
    if code in BROKEN_CHART:
        return f"weak: a completed close under support ({str(code).replace('_', ' ')})"
    if code not in WEAK_CHART:
        return None
    signs = []
    mo = ((snap.get("payload") or {}).get("technical") or {}).get("momentum")
    if isinstance(mo, dict) and mo.get("known") and mo.get("momentum") in WEAK_MOMENTUM:
        signs.append(f"momentum is {mo['momentum']}")
    sec = ps.get("second")
    if isinstance(sec, dict) and sec.get("signal") == "sell":
        signs.append(f"{sec.get('source', 'the second opinion')} says SELL")
    return f"weak: the chart reads {str(code).replace('_', ' ')} and " + " and ".join(signs) if signs else None


def rank_score(snap: dict, oc: dict, pace: float, chg: float) -> float:
    """Setup quality, higher is better, used only to pick the order when more stocks qualify than may enter now: volume against normal (0 to 3),
    strength on the day (0 to 1.5), nearness to the exit line, which is a tight risk (0 to 1.5), the risk grade, and the technical score (0 to 2)."""
    s = min(pace, 3.0) + min(max(chg, 0.0) * 100, 3.0) * 0.5
    dist = oc.get("distance_swings")
    s += max(0.0, 1.5 - min(dist if isinstance(dist, (int, float)) else 1.5, 1.5))
    grade = (oc.get("risk") or {}).get("grade")
    s += {"Safe": 1.0, "Moderate": 0.5, "Extreme": -0.5}.get(grade, 0.0)
    ts = snap.get("technical_score")
    if isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts == ts:
        s += max(0.0, min(ts, 100.0)) / 50
    return round(s, 2)


def _minutes_since(iso, now: datetime) -> float | None:
    try:
        return (now - datetime.fromisoformat(str(iso))).total_seconds() / 60
    except (TypeError, ValueError):
        return None


def _dip_check(pos: dict, price: float, move: float, now: datetime, mins: float | None) -> str | None:
    """At DIP_PCT under the entry the stock is watched: still falling (a new low with no bounce, or still down and no bounce after DIP_WATCH_MIN
    minutes) is sold; a bounce off the low means it is stabilising and the watch goes on until it is back above the line. Uses only the prices
    the account already reads each cycle. Not in the first half hour; an unknown time never sells."""
    if mins is None or mins < BEATEN_FROM_MIN:
        return None
    d = pos.get("dip")
    if move > -DIP_PCT:
        pos["dip"] = None                                         # back above the line: stabilised
        return None
    if not d:
        pos["dip"] = {"at": now.isoformat(), "start": price, "low": price}
        pos["read"] = "down 1%: watching, falling or stabilising?"
        return None
    d["low"] = min(d["low"], price)
    waited = _minutes_since(d["at"], now) or 0.0
    slide = (d["start"] - d["low"]) / d["start"] * 100
    bounce = (price - d["low"]) / d["low"] * 100
    if bounce >= DIP_BOUNCE_PCT:
        pos["read"] = f"down {abs(move):.1f}%: stabilising (bounced {bounce:.1f}% off {d['low']:.2f})"
        return None
    if slide >= DIP_SLIDE_PCT:
        return f"falling: {move:+.1f}% and still sliding (new low {d['low']:.2f}), not stabilising"
    if waited >= DIP_WATCH_MIN:
        return f"falling: {move:+.1f}% for {waited:.0f} minutes with no bounce off the low {d['low']:.2f}"
    return None


def _profit_check(pos: dict, price: float, move: float, now: datetime, mins: float | None) -> str | None:
    """The mirror of the dip check: once up UP_PCT the trade is read as riding (new highs, or close to the peak) or stalled (no new high for STALL_MIN
    minutes and GIVEBACK_PCT under the peak); a stalled winner is sold, locking what is left. The trailing stop of the riding rule stays."""
    if not pos.get("up2"):
        if move < UP_PCT:
            return None
        pos["up2"] = now.isoformat()
    if mins is None or mins < BEATEN_FROM_MIN:
        return None
    peak = pos.get("peak", price)
    if str(pos.get("peak_at", ""))[:10] == now.date().isoformat():
        idle = _minutes_since(pos.get("peak_at"), now)
    else:
        idle = mins                                               # the peak was an earlier day: count from today's open
    if idle is None:
        return None
    giveback = (peak - price) / peak * 100 if peak else 0.0
    if move > 0 and idle >= STALL_MIN and giveback >= GIVEBACK_PCT:
        return (f"stalled: was up to {peak:.2f}, no new high for {idle:.0f} minutes and {giveback:.1f}% under it; "
                f"locking {move:+.1f}%")
    pos["read"] = f"up {move:.1f}%: riding" if idle < STALL_MIN else f"up {move:.1f}%: holding near the peak"
    return None


def load_book(store) -> paper.Book:
    raw = store.get_setting(BOOK_KEY)
    return paper.Book.from_dict(json.loads(raw)) if raw else paper.Book()


def _call_of(snap: dict) -> dict | None:
    oc = ((snap.get("payload") or {}).get("technical") or {}).get("one_call")
    return oc if isinstance(oc, dict) and oc.get("known") else None


LEVEL_FRAC = 0.5      # the agent's entries come in levels: level 1 is half of the normal size, level 2 the other half, one more add on a pullback
MAX_LEVELS = 3


def _open(book: paper.Book, ticker: str, oc: dict, price: float, now: datetime, atr: float | None = None, frac: float = 1.0) -> dict | None:
    line = oc["exit_line"]
    if not price > line:
        return None
    equity = book.equity({})
    risk_pct = paper.RISK_PCT * (0.5 if (oc.get("risk") or {}).get("grade") in ("High", "Extreme") else 1.0)
    shares = int(equity * risk_pct / 100 / (price - line))
    shares = min(shares, int(equity * SIZE_CAP_PCT / 100 // price), int(book.cash // price))
    if frac < 1.0:
        shares = max(1, int(shares * frac)) if shares >= 1 else 0
    if shares < 1:
        return None
    cost = shares * price
    book.cash -= cost
    trade = {"id": book.next_id, "ticker": ticker, "opened": paper._ts(now), "entry": price, "shares": shares,
             "size": round(cost, 2), "stop": oc["band_line"], "target1": None,
             "reason": f"{oc['call']}: {oc['why']}", "status": "OPEN", "closed": None, "exit": None, "exit_reason": None,
             "result": 0.0, "r": None, "worst": 0.0, "best": 0.0, "risk": round(shares * (price - line), 2), "sold": 0,
             "proceeds": 0.0, "stretched": False, "at_target": None}
    book.next_id += 1
    book.trades.append(trade)
    book.positions[ticker] = {"trade": trade["id"], "shares": shares, "entry": price, "stop": oc["band_line"],
                              "stage": "full", "t1_done": False, "below_since": None, "opened": now.isoformat(),
                              "stop0": oc["band_line"], "stretch": False, "weak_since": None, "atr": atr, "peak": price,
                              "peak_at": now.isoformat(), "day": now.date().isoformat(), "day_hi": price, "day_lo": price, "trail": None}
    trade["levels"] = 1
    return trade


def _add(book: paper.Book, ticker: str, price: float, line: float | None) -> bool:
    """One more level on an open trade (half of the normal size). The stop stays; the entry becomes the average price."""
    pos = book.positions[ticker]
    trade = next(t for t in book.trades if t["id"] == pos["trade"])
    equity = book.equity({})
    n = int(min(max(1, int(trade["shares"] / max(1, int(trade.get("levels") or 1)))), int(book.cash // price), int(equity * SIZE_CAP_PCT / 100 // price)))
    if n < 1:
        return False
    total = pos["shares"] + n
    pos["entry"] = (pos["entry"] * pos["shares"] + price * n) / total
    pos["shares"] = total
    book.cash -= n * price
    trade["shares"], trade["entry"], trade["size"] = total, pos["entry"], round(trade["size"] + n * price, 2)
    trade["levels"] = int(trade.get("levels") or 1) + 1
    if isinstance(line, (int, float)) and price > line:
        trade["risk"] = round(trade["risk"] + n * (price - line), 2)
    return True


def today_change(snap: dict) -> float | None:
    v = (((snap.get("payload") or {}).get("quote")) or {}).get("live_change")
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def _num(v) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def _beaten(pos: dict, price: float, atr: float | None, oc: dict | None, mins: float | None) -> bool:
    """A losing trade that has broken down is sold now: under the call's exit line by BEATEN_ATR daily ranges, or CUT_ATR ranges under the
    entry. The call itself only turns EXIT on a completed daily close, which can leave a falling stock held for another day.
    An unknown range, line or time never sells."""
    if not atr or atr <= 0 or mins is None or mins < BEATEN_FROM_MIN:
        return False
    line = (oc or {}).get("exit_line")
    under = isinstance(line, (int, float)) and line == line and price < line - BEATEN_ATR * atr and price < pos["entry"]
    return under or price <= pos["entry"] - CUT_ATR * atr


def _stalled(pos: dict, price: float, atr: float | None, snap: dict, mins: float | None, now: datetime, move: float) -> str | None:
    """Sold when the stock has stopped: late in the day, held since an earlier day (or 3 hours), a tight day's range, no volume and no
    new high since yesterday. Unknown range, volume or time never sells."""
    if not atr or mins is None or mins < STALL_FROM_MIN:
        return None
    opened = datetime.fromisoformat(pos["opened"])
    today = now.date().isoformat()
    if opened.date().isoformat() == today and (now - opened).total_seconds() < 3 * 3600:
        return None
    rng = (pos.get("day_hi", price) - pos.get("day_lo", price)) / atr
    pace = volpace.pace(snap, mins)
    peak_day = str(pos.get("peak_at", pos["opened"]))[:10]
    if pace is None or rng >= TIGHT_ATR or pace >= QUIET_PACE or peak_day == today:
        return None
    verb = f"locking {move:+.1f}%" if move > 0 else f"leaving at {move:+.1f}%"
    return (f"stalled: a tight day ({rng:.1f} daily ranges), volume {pace:.1f}x normal, no new high since {peak_day}; "
            f"{verb} to free the cash")


def _new_recently(book: paper.Book, now: datetime) -> int:
    n = 0
    for t in book.trades:
        try:
            at = datetime.strptime(str(t["opened"]), "%Y-%m-%d %H:%M").replace(tzinfo=NY)
        except ValueError:
            continue
        if 0 <= (now - at).total_seconds() < NEW_WINDOW_MIN * 60:
            n += 1
    return n


def _hold_back(book: paper.Book, ticker: str, price: float, now: datetime, reason: str) -> None:
    day = now.date().isoformat()
    if not any(b.get("ticker") == ticker and b.get("day") == day for b in book.blocked[-300:]):     # one line per stock per day
        book.blocked.append({"day": now.date().isoformat(), "time": paper._ts(now), "ticker": ticker, "price": price,
                             "reason": reason})


def _agent_position(book: paper.Book, ticker: str, pos: dict, trade: dict, oc: dict | None, price: float, atr: float | None,
                    orders: list, results: dict, now: datetime) -> str | None:
    """The agent's orders for a held stock: SELL returns the exit reason; level 2 or an add buys more (never while the price is flying)."""
    for o in [x for x in orders if x["ticker"] == ticker]:
        if o["action"] == "SELL":
            results[o["id"]] = ("done", "sold")
            return f"agent: {o['reason']}"
        if o["action"] not in ("BUY_L2", "ADD"):
            continue
        levels = int(trade.get("levels") or 1)
        if levels >= MAX_LEVELS:
            results[o["id"]] = ("rejected", f"already {MAX_LEVELS} levels")
        elif price <= pos["entry"]:
            results[o["id"]] = ("rejected", "price is not above the entry: not riding")
        elif atr and o["action"] == "BUY_L2" and quick.is_flying(price, pos["entry"], pos.get("peak", price), atr):
            results[o["id"]] = ("rejected", "flying: waiting for a pullback before level 2")
        elif atr and o["action"] == "ADD" and pos.get("peak", price) - price < quick.PULLBACK_ATR * atr:
            results[o["id"]] = ("rejected", "not a pullback yet: an add needs the price under the peak")
        elif _add(book, ticker, price, (oc or {}).get("exit_line")):
            results[o["id"]] = ("done", f"level {levels + 1} at {price:.2f}")
            book.log.append({"ticker": ticker, "action": "ADD", "price": price, "reason": f"agent: {o['reason']}", "time": paper._ts(now)})
        else:
            results[o["id"]] = ("rejected", "not enough cash for a share")
    return None


def _agent_entry(book: paper.Book, ticker: str, snap: dict, oc: dict | None, price: float, now: datetime, mins: float, late: bool, gate: str,
                 orders: list, results: dict) -> dict | None:
    """The agent's level 1 order for a stock not held. The old checks stay as hard rules; the old BUY/ADD call is only logged as the baseline."""
    o = next((x for x in orders if x["ticker"] == ticker and x["action"] == "BUY_L1"), None)
    if o is None:
        if oc and oc["call"] in ("BUY", "ADD") and mins >= BLACKOUT_MIN and not late:
            _hold_back(book, ticker, price, now, "baseline: the old rules would have bought; the agent gave no order")
        return None
    why = ""
    if not oc:
        why = "no daily exit line to place a stop"
    elif oc["call"] in ("EXIT", "AVOID"):
        why = f"the daily call is {oc['call']}"
    elif not price > oc["exit_line"]:
        why = "the price is under the exit line"
    elif mins < BLACKOUT_MIN:
        why = "not in the first hour"
    elif late:
        why = "too late in the day"
    elif len(book.positions) >= MAX_POSITIONS:
        why = f"already {MAX_POSITIONS} open"
    elif gate:
        why = gate
    elif weak_reason(snap):
        why = weak_reason(snap)
    elif _new_recently(book, now) >= MAX_NEW:
        why = f"pace limit: {MAX_NEW} new entries in the last {NEW_WINDOW_MIN} minutes"
    else:
        pace, chg = volpace.pace(snap, mins), today_change(snap)
        if pace is None:
            why = "today's volume is not read yet"
        elif pace < MIN_PACE:
            why = f"volume only {pace:.1f}x normal for this time"
        elif chg is None:
            why = "today's move is unknown"
        elif chg < 0:
            why = f"down {abs(chg) * 100:.1f}% today"
    if why:
        results[o["id"]] = ("rejected", why)
        _hold_back(book, ticker, price, now, f"agent order refused: {why}")
        return None
    t = _open(book, ticker, {**oc, "call": oc["call"], "why": f"agent ({o['state']}, confidence {o['confidence']}): {o['reason']}"}, price, now,
              _num(((snap.get("payload") or {}).get("technical") or {}).get("atr")), LEVEL_FRAC)
    if t is None:
        results[o["id"]] = ("rejected", "not enough cash for a share")
        _hold_back(book, ticker, price, now, "agent order refused: not enough cash for a share")
        return None
    results[o["id"]] = ("done", f"bought at {price:.2f}")
    return t


def step(book: paper.Book, snaps: dict, prices: dict, now: datetime, force: bool = False, orders: list | None = None,
         results: dict | None = None) -> list[dict]:
    """`orders` is None for the old rules; a list (maybe empty) means the agent picks the stocks (see quick.step)."""
    done = []
    results = results if results is not None else {}
    mins = decision.minutes_into_session(now)
    late = now.time() >= decision.DECIDE
    gate = quick.market_gate(snaps)                                   # most tracked stocks down and the median down 1% or more
    cands: list = []
    for ticker, snap in snaps.items():
        price, pos, oc = prices.get(ticker), book.positions.get(ticker), _call_of(snap)
        if not price or mins is None:
            continue
        if pos and force:
            reason = "forced sell (owner test)"
            paper._sell(book, ticker, price, 1.0, now, reason)
            done.append({"ticker": ticker, "action": "SELL_ALL", "price": price, "reason": reason, "time": paper._ts(now)})
            continue
        if force:
            continue                                                  # no new entries in the forced cycle; the next cycle picks
        if pos:
            trade = next(t for t in book.trades if t["id"] == pos["trade"])
            move = (price / pos["entry"] - 1) * 100
            trade["worst"], trade["best"] = min(trade["worst"], round(move, 2)), max(trade["best"], round(move, 2))
            reason = None
            atr = pos.get("atr") or _num(((snap.get("payload") or {}).get("technical") or {}).get("atr"))
            day = now.date().isoformat()
            if price > pos.get("peak", pos["entry"]):
                pos["peak"], pos["peak_at"] = price, now.isoformat()
            if pos.get("day") != day:
                pos["day"], pos["day_hi"], pos["day_lo"] = day, price, price
            pos["day_hi"], pos["day_lo"] = max(pos.get("day_hi", price), price), min(pos.get("day_lo", price), price)
            if atr and price >= pos["entry"] + RIDE_ATR * atr:           # riding: the stop follows the peak and locks the profit
                pos["trail"] = round(max(pos.get("trail") or 0.0, pos["entry"], pos["peak"] - TRAIL_ATR * atr), 2)
            if oc and oc["call"] in ("EXIT", "AVOID"):
                reason = f"call turned {oc['call']}: a close under the band"
            elif _beaten(pos, price, atr, oc, mins):
                line = (oc or {}).get("exit_line")
                reason = (f"beaten: {price:.2f} is under the exit line {line:.2f}, {move:+.1f}% from the entry" if line and price < line - BEATEN_ATR * atr
                          else f"beaten: down {abs(price - pos['entry']) / atr:.1f} daily ranges from the entry ({move:+.1f}%)")
            elif pos.get("trail") and price <= pos["trail"]:
                reason = f"trailing stop {pos['trail']:.2f} hit, riding ended ({move:+.1f}%)"
            elif late and price < pos["stop"]:
                reason = f"at 15:45 the price {price:.2f} is under the band line {pos['stop']:.2f}"
            else:
                reason = _dip_check(pos, price, move, now, mins) or _profit_check(pos, price, move, now, mins) or _stalled(pos, price, atr, snap, mins, now, move)
            if reason is None and orders:
                reason = _agent_position(book, ticker, pos, trade, oc, price, atr, orders, results, now)
            if reason:
                paper._sell(book, ticker, price, 1.0, now, reason)
                done.append({"ticker": ticker, "action": "SELL_ALL", "price": price, "reason": reason, "time": paper._ts(now)})
        elif orders is not None:
            t = _agent_entry(book, ticker, snap, oc, price, now, mins, late, gate, orders, results)
            if t:
                done.append({"ticker": ticker, "action": "ENTER", "price": price, "reason": t["reason"], "time": paper._ts(now)})
        elif oc and oc["call"] in ("BUY", "ADD") and mins >= BLACKOUT_MIN and not late and len(book.positions) < MAX_POSITIONS:
            if gate:
                _hold_back(book, ticker, price, now, f"BUY held back: {gate}")
                continue
            weak = weak_reason(snap)
            if weak:
                _hold_back(book, ticker, price, now, f"BUY held back: {weak}")
                continue
            pace = volpace.pace(snap, mins)
            if pace is None:
                _hold_back(book, ticker, price, now, "BUY held back: today's volume is not read yet, so no setup is confirmed")
                continue
            if pace < MIN_PACE:
                _hold_back(book, ticker, price, now, f"BUY held back: volume only {pace:.1f}x normal for this time, no setup is established")
                continue
            chg = today_change(snap)
            if chg is None:
                _hold_back(book, ticker, price, now, "BUY held back: today's move is unknown")
                continue
            if chg < 0:
                _hold_back(book, ticker, price, now, f"BUY held back: down {abs(chg) * 100:.1f}% today, the bounce isn't holding")
                continue
            cands.append((rank_score(snap, oc, pace, chg), ticker, snap, oc, price))      # judged; the order of entry is decided below
    if cands:                                                          # rank the setups that passed, then enter the best first
        cands.sort(key=lambda c: -c[0])
        slots = max(0, min(MAX_NEW - _new_recently(book, now), MAX_POSITIONS - len(book.positions)))
        entered = 0
        for rank, (score, ticker, snap, oc, price) in enumerate(cands, 1):
            if entered >= slots:
                _hold_back(book, ticker, price, now, f"BUY held back: ranked #{rank} of {len(cands)} (score {score:.1f}); pace limit, "
                                                     f"{MAX_NEW} new entries in the last {NEW_WINDOW_MIN} minutes")
                continue
            t = _open(book, ticker, oc, price, now, _num(((snap.get("payload") or {}).get("technical") or {}).get("atr")))
            if t:
                entered += 1
                t["reason"] += f" [ranked #{rank} of {len(cands)}, score {score:.1f}]"
                done.append({"ticker": ticker, "action": "ENTER", "price": price, "reason": t["reason"], "time": paper._ts(now)})
    book.log = (book.log + done)[-200:]
    return done


def force_sell_now(store, now: datetime | None = None) -> dict:
    """The owner's test button: sell every open trade of this account once, at the latest fresh price, so the next cycles show what it
    picks. Runs from the page (no restart, the tracker is left alone); it needs the regular session and a fresh price per trade."""
    now = (now or datetime.now(NY)).astimezone(NY)
    if us_session() != "REGULAR":
        return {"sold": [], "note": "the market is closed: nothing trades outside the regular session"}
    book = load_book(store)
    snaps, prices = {}, {}
    for s in store.latest_snapshots():
        if s["ticker"] in book.positions:
            price, _why = paper_live.fresh_price(s, now)
            if price is not None:
                snaps[s["ticker"]], prices[s["ticker"]] = s, price
    did = step(book, snaps, prices, now, force=True)
    if did:
        store.set_setting(BOOK_KEY, json.dumps(book.to_dict(), default=str))
    left = [t for t in book.positions]
    return {"sold": [d["ticker"] for d in did], "note": f"sold {len(did)}" + (f"; no fresh price yet for {', '.join(left)}" if left else "")}


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
    from . import agent
    orders = agent.orders_for(store, "newcall", now)
    results: dict = {}
    if orders is not None:
        state["note"] = (f"the agent picks: {len(orders)} order(s) ready" if agent.has_key()
                         else "ANTHROPIC_API_KEY is not set: nothing is bought in agent mode")
    state["did"] = step(book, snaps, prices, now, orders=orders, results=results)
    from . import sectors
    sectors.stamp(book.trades, state["did"], snaps, store)              # log only: what the sector check said at each entry
    agent.settle(store, results, now)
    if json.dumps(book.to_dict(), default=str, sort_keys=True) != before or not store.get_setting(BOOK_KEY):
        store.set_setting(BOOK_KEY, json.dumps(book.to_dict(), default=str))
    store.set_setting(STATE_KEY, json.dumps(state, default=str))
    return state


def status(store) -> dict:
    raw = store.get_setting(STATE_KEY)
    return {"book": load_book(store), "state": json.loads(raw) if raw else None,
            "cfg": {"list": True, "webhook": True, "token": True}, "push_error": None, "pushed_at": None}
