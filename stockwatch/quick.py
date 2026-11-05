"""The Quick tab's fake account (owner, 2026-10-26): quick trades that read the day's own chart and decide for themselves.

Loose on purpose, to watch how it behaves before any rules are added. It has its own $10,000 account, never touches the Paper
account, the cards, scores, calls or alerts, and trades nothing real.

What it does, every tracker cycle in the regular session, for every stock the app tracks:
  reads    the day's own price path (open, high, low, the last few minutes) against the stock's normal daily range (ATR)
  enters   on a "bounce" (a real drop from the day's high or yesterday's close, a turn up off the low, still rising) or a
           "breakout" (a new high of the day in a stock that is up on the day)
  exits    by trailing: the stop follows the peak at a fraction of the daily range, so a stretched profit is ridden, not capped.
           Also out when the chart turns, when the trade goes nowhere for two hours, or at 3:55 pm New York (no overnight).
  logs     every entry, exit and skipped setup with its reason.
Missing data never trades. Fills are simulated at the latest price, so they are approximate.

The journal also goes to the owner's Google Drive as two sheet files (`Quick trades.csv`, `Quick skipped setups.csv`) in a
"Quick log" folder under the Drive backup folder, rewritten whenever a trade or setup changes. Drive for Desktop syncs them;
Google Sheets opens them. Set STOCKWATCH_QUICK_LOG_DIR to put them elsewhere.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from . import ui, volpace
from .data import NY, us_session

log = logging.getLogger("stockwatch.quick")
BOOK_KEY, MARKS_KEY, STATE_KEY = "quick_book", "quick_marks", "quick_state"
START_CASH = 50_000.0
POSITION_PCT = 5.0            # of the account per trade
MAX_OPEN = 15
SAMPLES = 90                   # about 30 minutes of 20-second samples
MIN_SAMPLE_MIN = 3.0           # minutes of history needed before a chart read counts
DROP_ATR = 0.7                 # the flush behind a bounce, in daily ranges
TURN_ATR = 0.15                # how far off the low the turn must be
TRAIL_ATR = 0.45               # the trailing stop sits this far under the peak
LOCK_ATR = 0.30                # once up this much the stop is at least the entry
MAX_LOSS_PCT = 2.0               # owner, 4 Nov: no trade is held more than this far under its entry, however wide half a daily range is (CYPH sat 7% from its stop)
STOP_ATR = 0.5                 # widest first stop under the entry (was 0.9: every stop hit lost 1.8% on average)
STALL_MIN = 120                # backstop: minutes with no progress before it leaves
NO_PROGRESS_MIN = 60           # leaves after this long if it never got +0.5% (frees the cash for the next setup)
NO_PROGRESS_PCT = 0.5
DRY_MIN = 45                   # leaves after this long if the volume has dried up and the price is not clearly up
DRY_PACE = 0.6
HOLD_MIN = 10.0                # a bounce counts only after the low has held this long, with two higher lows after it
BOUNCE_FIRST_MIN = 5           # owner, 4 Nov: bounce entries too start 5 minutes after the open (was 15)
OPEN_FREE_MIN = 30                # owner, 4 Nov: in the first 30 minutes after the open Quick takes as many entries as the setups give (the other brakes stay) ...
MAX_NEW, NEW_WINDOW_MIN = 3, 10  # ... then at most this many new entries in any window, so one move cannot fill the account
GATE_DOWN_SHARE, GATE_MEDIAN = 0.6, -0.01   # market gate: this share of stocks down and the median at least this far down: no bounces
GATE_MIN_STOCKS = 20
MAX_PER_DAY = 40               # new entries in a day: only a runaway guard now (owner, 2 Nov: 15 missed good ones; was 15 after 30 Oct: 68 trades, 9 wins of 53 closed, -$867). The real brakes stay: MAX_NEW per NEW_WINDOW_MIN and the day-loss stop
DAY_LOSS_PCT = 1.0             # no new entries once today's closed result plus open positions is this far under the start (percent of the account)
SIZE_PCT = {"A": 5.0, "B": 3.0}  # a C setup is not traded
FIRST_MIN, LAST_MIN = 5, 385   # minutes into the session (9:35 to 15:55)
TAKE_PCT = 2.0                 # owner, 4 Nov: once up this much, leave as soon as it stops riding ...
TAKE_STALL_MIN = 10            # ... no new high for this long ...
TAKE_GIVEBACK_PCT = 0.3        # ... and this far under the peak. While it keeps making new highs it is riding and stays.
FIXED_PCT = 2.5                # only to compare riding with a fixed exit; not a rule
LEVEL_PCT = 2.5                # the agent's entries come in levels of this size (percent of the account): level 1, level 2, one more on a pullback
MAX_LEVELS = 3
PULLBACK_ATR = 0.25            # an add after level 2 needs the price this far under the peak
FLY_ATR, FLY_NEAR_PEAK = 0.5, 0.15   # "flying": 0.5 daily ranges above the entry and within 0.15 ranges of the peak: level 2 waits for a pullback


def is_flying(price: float, entry: float, peak: float, atr: float | None) -> bool:
    """The move is running: well above the entry and right at the peak. Level 2 and adds wait for a pullback instead of chasing it."""
    if not atr or atr <= 0:
        return False
    return price - entry >= FLY_ATR * atr and peak - price <= FLY_NEAR_PEAK * atr


def _num(v) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def new_book() -> dict:
    return {"cash": START_CASH, "start": START_CASH, "positions": {}, "trades": [], "skipped": [], "log": [], "next_id": 1, "entry_times": []}


def market_gate(snaps: dict) -> str:
    """'' or why bounces are paused: most tracked stocks are down on the day and the median stock is down a percent or more."""
    ch = sorted(c for c in (_num(((s.get("payload") or {}).get("quote") or {}).get("live_change")) for s in snaps.values()) if c is not None)
    if len(ch) < GATE_MIN_STOCKS:
        return ""                                                 # too few reads to judge the market: no gate, never a guess
    down = sum(1 for c in ch if c < 0) / len(ch)
    med = ch[len(ch) // 2]
    if down >= GATE_DOWN_SHARE and med <= GATE_MEDIAN:
        return f"market gate: {down * 100:.0f}% of stocks are down, the median {med * 100:+.1f}%"
    return ""


def _today_trades(book: dict, now: datetime) -> list[dict]:
    day = now.strftime("%Y-%m-%d")
    return [t for t in book["trades"] if str(t["opened"]).startswith(day)]


def day_result(book: dict, prices: dict, now: datetime) -> float:
    """Today's closed result plus the open positions' result at the latest prices, in dollars."""
    day = now.strftime("%Y-%m-%d")
    closed = sum(t["result"] for t in book["trades"] if str(t.get("closed") or "").startswith(day))
    live = sum((prices.get(tk) or p["entry"]) * p["shares"] - p["entry"] * p["shares"] for tk, p in book["positions"].items())
    return closed + live


def _new_in_window(book: dict, now: datetime) -> int:
    return sum(1 for x in book.get("entry_times", []) if 0 <= (now - datetime.fromisoformat(x)).total_seconds() < NEW_WINDOW_MIN * 60)


def top_up(book: dict) -> bool:
    """One-time: an account that started at $10,000 is lifted to $50,000 (cash +$40,000, trades kept)."""
    if book["start"] < START_CASH:
        book["cash"] += START_CASH - book["start"]
        book["start"] = START_CASH
        return True
    return False


def load_book(store, migrate: bool = True) -> dict:
    raw = store.get_setting(BOOK_KEY)
    book = {**new_book(), **json.loads(raw)} if raw else new_book()
    if migrate:
        top_up(book)
    return book


def save_book(store, book: dict) -> None:
    book["skipped"], book["log"] = book["skipped"][-300:], book["log"][-200:]
    store.set_setting(BOOK_KEY, json.dumps(book, default=str))


TRADE_COLS = [("id", "ID"), ("ticker", "Ticker"), ("kind", "Setup"), ("opened", "Opened"), ("entry", "Entry"), ("shares", "Shares"),
              ("size", "Size $"), ("stop0", "First stop"), ("status", "Status"), ("closed", "Closed"), ("exit", "Exit"),
              ("exit_reason", "Exit reason"), ("result", "Result $"), ("pct", "Result %"), ("best", "Peak %"), ("worst", "Worst %"),
              ("minutes", "Minutes held"), ("grade", "Grade"), ("reason", "Why it entered")]
SKIP_COLS = [("day", "Day"), ("time", "Time (NY)"), ("ticker", "Ticker"), ("kind", "Setup"), ("price", "Price"), ("reason", "Why skipped")]


def log_dir() -> Path:
    env = os.getenv("STOCKWATCH_QUICK_LOG_DIR", "").strip()
    if env:
        return Path(env)
    from . import backup
    return backup.backup_dir() / "Quick log"


def _write_csv(path: Path, cols: list, rows: list) -> None:
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([h for _, h in cols])
        for r in rows:
            w.writerow(["" if r.get(k) is None else r.get(k) for k, _ in cols])
    os.replace(tmp, path)


def export_sheets(book: dict, folder: Path | None = None) -> str:
    """Write the journal as sheet files. Returns '' or why it could not (a missing Drive never stops the trading)."""
    try:
        folder = folder or log_dir()
        if not (folder.parent.is_dir() or folder.is_dir()):
            return f"the Drive folder was not found: {folder.parent}"
        folder.mkdir(exist_ok=True)
        _write_csv(folder / "Quick trades.csv", TRADE_COLS, book["trades"])
        _write_csv(folder / "Quick skipped setups.csv", SKIP_COLS, book["skipped"])
        return ""
    except Exception as e:
        log.warning("quick sheet export failed: %s", e)
        return f"could not write the sheet files: {e}"[:200]


_exp: dict = {"t": None, "done": False, "err": ""}


def export_async(book: dict) -> None:
    """Write the sheet files on their own thread (a slow or missing Drive must never hold up trading). The outcome is picked
    up by the next `tick` through `_exp`."""
    t = _exp["t"]
    if t is not None and t.is_alive():
        return
    snap = json.loads(json.dumps(book, default=str))
    _exp["done"] = False

    def work():
        _exp["err"] = export_sheets(snap)
        _exp["done"] = True
    _exp["t"] = threading.Thread(target=work, name="stockwatch-quick-sheet", daemon=True)
    _exp["t"].start()


def _sheet_outcome(store) -> None:
    if _exp["done"]:
        _exp["done"] = False
        store.set_setting("quick_sheet_ok", "" if _exp["err"] else "1")
        store.set_setting("quick_sheet_error", _exp["err"])


def equity(book: dict, prices: dict) -> float:
    return book["cash"] + sum(p["shares"] * (prices.get(t) or p["entry"]) for t, p in book["positions"].items())


def minutes_in(now: datetime) -> float | None:
    from .decision import minutes_into_session
    return minutes_into_session(now)


def mark(marks: dict, ticker: str, price: float, now: datetime) -> dict:
    """Add this cycle's price to the stock's path for the day and return the path."""
    day = now.date().isoformat()
    m = marks.get(ticker)
    if not m or m.get("day") != day:
        m = {"day": day, "open": price, "hi": price, "lo": price, "s": []}
        marks[ticker] = m
    m["hi"], m["lo"] = max(m["hi"], price), min(m["lo"], price)
    m["s"] = (m["s"] + [[now.timestamp(), price]])[-SAMPLES:]
    return m


def read_chart(m: dict, price: float, prev_close: float | None, atr: float) -> dict:
    """What the day's path says: the flush, the turn and whether it is still rising."""
    s = m["s"]
    span = (s[-1][0] - s[0][0]) / 60 if len(s) > 1 else 0.0
    drop = (m["hi"] - m["lo"]) / atr                              # a fall during the session; a gap down at the open is not a flush
    off_low = (price - m["lo"]) / atr
    recent = [p for _, p in s if s[-1][0] - _ <= 120]             # the last two minutes
    older = [p for _, p in s if 120 < s[-1][0] - _ <= 420]        # the five minutes before that
    rising = bool(recent and older) and min(recent) >= min(older) and price >= recent[0]
    prior_hi = max([p for _, p in s[:-6]], default=None) if len(s) > 6 else None
    up_day = (price - (prev_close or m["open"])) / atr
    low_at = [i for i, (t, px) in enumerate(s) if px <= m["lo"] + 1e-9]
    low_age = (s[-1][0] - s[low_at[-1]][0]) / 60 if low_at else 999.0   # minutes since the day's low (old if it is before the window)
    after = s[low_at[-1] + 1:] if low_at else s
    held = False
    if low_age >= HOLD_MIN and len(after) >= 6:                   # two higher lows after the low: the floor is being tested and holds
        mid = (after[0][0] + after[-1][0]) / 2
        first, second = [px for t, px in after if t <= mid], [px for t, px in after if t > mid]
        held = bool(first and second) and min(first) >= m["lo"] + 0.02 * atr and min(second) > min(first)
    return {"span": span, "drop": drop, "off_low": off_low, "rising": rising, "up_day": up_day, "low_age": low_age, "held": held,
            "new_high": prior_hi is not None and price > prior_hi and price >= m["hi"] and span >= 10}


def setup(chart: dict) -> tuple[str | None, str]:
    """('bounce' | 'breakout' | None, plain reason)."""
    if chart["span"] < MIN_SAMPLE_MIN:
        return None, "not enough of today's path yet"
    if chart["drop"] >= DROP_ATR and chart["off_low"] >= TURN_ATR and chart["rising"] and chart["off_low"] <= 0.85 * chart["drop"]:
        if not chart.get("held"):
            return None, "turn not confirmed yet"
        return "bounce", (f"dropped {chart['drop']:.1f} daily ranges, turned up off the low ({chart['off_low']:.1f} ranges off it) "
                          "and is still rising")
    if chart["new_high"] and chart["up_day"] >= 0.5 and chart["rising"]:
        return "breakout", f"new high of the day, up {chart['up_day']:.1f} daily ranges on the day, still rising"
    return None, "no setup"


def grade(kind: str, pace: float | None) -> tuple[str | None, str]:
    """('A' | 'B' | None, plain reason). The grade comes from the volume pace; a bounce needs less than a breakout.
    Unknown volume is not graded, so it does not trade."""
    if pace is None:
        return None, "volume not read yet"
    a, b = (1.2, 0.8) if kind == "bounce" else (1.5, 1.0)
    if pace >= a:
        return "A", f"volume {pace:.1f}x normal for this time"
    if pace >= b:
        return "B", f"volume {pace:.1f}x normal for this time"
    return None, f"volume only {pace:.1f}x normal for this time: a weak {kind}"


def _first_stop(kind: str, price: float, lo: float, atr: float) -> float:
    base = lo - 0.1 * atr if kind == "bounce" else price - 0.6 * atr
    return round(max(base, price - STOP_ATR * atr, price * (1 - MAX_LOSS_PCT / 100)), 2)


def _enter(book: dict, ticker: str, kind: str, why: str, price: float, lo: float, atr: float, now: datetime, pct: float = POSITION_PCT,
           grade_: str = "") -> dict | None:
    size = equity(book, {}) * pct / 100
    shares = int(min(size, book["cash"]) // price)
    if shares < 1:
        return None
    stop = _first_stop(kind, price, lo, atr)
    if stop >= price:
        return None
    book["cash"] -= shares * price
    t = {"id": book["next_id"], "ticker": ticker, "kind": kind, "opened": now.strftime("%Y-%m-%d %H:%M"), "entry": price, "shares": shares,
         "size": round(shares * price, 2), "stop0": stop, "reason": why, "status": "OPEN", "closed": None, "exit": None,
         "exit_reason": None, "result": 0.0, "pct": None, "best": 0.0, "worst": 0.0, "atr": round(atr, 4), "minutes": None,
         "grade": grade_, "levels": 1}
    same = [x for x in book["trades"] if x["ticker"] == ticker and str(x["opened"])[:10] == t["opened"][:10]]
    if same:                                                      # a re-entry (owner, 5 Nov: allowed, but logged so a failed second try can be studied)
        t["nth_today"] = len(same) + 1
        t["prev_result"], t["prev_exit"] = same[-1].get("result"), same[-1].get("exit_reason")
    book["next_id"] += 1
    book.setdefault("entry_times", []).append(now.isoformat())
    book["entry_times"] = book["entry_times"][-50:]
    book["trades"].append(t)
    book["positions"][ticker] = {"trade": t["id"], "shares": shares, "entry": price, "stop": stop, "peak": price, "atr": atr,
                                 "opened": now.isoformat(), "best_at": now.isoformat()}
    return t


def _exit(book: dict, ticker: str, price: float, now: datetime, reason: str) -> None:
    pos = book["positions"].pop(ticker)
    t = next(x for x in book["trades"] if x["id"] == pos["trade"])
    book["cash"] += pos["shares"] * price
    t["status"], t["closed"], t["exit"], t["exit_reason"] = "CLOSED", now.strftime("%Y-%m-%d %H:%M"), price, reason
    t["result"] = round((price - t["entry"]) * t["shares"], 2)
    t["pct"] = round((price / t["entry"] - 1) * 100, 2)
    t["minutes"] = round((now - datetime.fromisoformat(pos["opened"])).total_seconds() / 60)


def _add(book: dict, ticker: str, price: float, pct: float) -> bool:
    """One more level on an open position, at `pct` of the account, bought at `price`. The stop stays where it is; the entry becomes the
    average price. False when there is not enough cash for a share."""
    pos = book["positions"][ticker]
    t = next(x for x in book["trades"] if x["id"] == pos["trade"])
    n = int(min(equity(book, {}) * pct / 100, book["cash"]) // price)
    if n < 1:
        return False
    total = pos["shares"] + n
    pos["entry"] = (pos["entry"] * pos["shares"] + price * n) / total
    pos["shares"] = total
    book["cash"] -= n * price
    t["shares"], t["entry"], t["size"] = total, pos["entry"], round(t["size"] + n * price, 2)
    t["levels"] = int(t.get("levels") or 1) + 1
    return True


def _skip(book: dict, ticker: str, kind: str, reason: str, price: float, now: datetime) -> None:
    day = now.date().isoformat()
    if any(s["ticker"] == ticker and s["day"] == day and s["reason"] == reason for s in book["skipped"][-40:]):
        return                                                   # logged once per stock, day and reason
    book["skipped"].append({"day": day, "time": now.strftime("%H:%M"), "ticker": ticker, "kind": kind, "price": price, "reason": reason})


def _agent_position(book: dict, ticker: str, pos: dict, t: dict, price: float, atr: float, orders: list, results: dict, now: datetime) -> str | None:
    """The agent's orders for a stock already held: a SELL returns the exit reason; level 2 or an add buys more and returns None."""
    for o in [x for x in orders if x["ticker"] == ticker]:
        if o["action"] == "SELL":
            results[o["id"]] = ("done", "sold")
            return f"agent: {o['reason']}"
        if o["action"] not in ("BUY_L2", "ADD"):
            continue
        levels = int(t.get("levels") or 1)
        if levels >= MAX_LEVELS:
            results[o["id"]] = ("rejected", f"already {MAX_LEVELS} levels")
        elif price <= pos["entry"]:
            results[o["id"]] = ("rejected", "price is not above the entry: not riding")
        elif o["action"] == "BUY_L2" and is_flying(price, pos["entry"], pos["peak"], atr):
            results[o["id"]] = ("rejected", "flying: waiting for a pullback before level 2")
        elif o["action"] == "ADD" and pos["peak"] - price < PULLBACK_ATR * atr:
            results[o["id"]] = ("rejected", "not a pullback yet: an add needs the price under the peak")
        elif _add(book, ticker, price, LEVEL_PCT):
            results[o["id"]] = ("done", f"level {levels + 1} at {price:.2f}")
            book["log"].append({"ticker": ticker, "action": "ADD", "price": price, "reason": f"agent: {o['reason']}", "time": now.strftime("%H:%M")})
        else:
            results[o["id"]] = ("rejected", "not enough cash for a share")
    return None


def _agent_entry(book: dict, ticker: str, kind: str, why: str, m: dict, price: float, atr: float, mins: float, gate: str, prices: dict,
                 now: datetime, days, orders: list, results: dict) -> dict | None:
    """The agent's level 1 order for a stock not held. Every limit still applies. The old rules' setup (`kind`) is only logged as the baseline."""
    o = next((x for x in orders if x["ticker"] == ticker and x["action"] == "BUY_L1"), None)
    if o is None:
        if kind:                                                   # what the old rules would have bought, for the comparison
            base = book.setdefault("baseline", [])
            if not any(b["ticker"] == ticker and b["day"] == now.date().isoformat() and b["kind"] == kind for b in base[-60:]):
                base.append({"day": now.date().isoformat(), "time": now.strftime("%H:%M"), "ticker": ticker, "kind": kind, "price": price, "why": why})
                book["baseline"] = base[-300:]
        return None
    today = _today_trades(book, now)
    lost = day_result(book, prices, now)
    turning = o["state"] == "turning"
    if lost <= -book["start"] * DAY_LOSS_PCT / 100:
        no = f"daily loss stop: down ${abs(lost):,.0f} today"
    elif len(today) >= MAX_PER_DAY:
        no = f"day limit: {MAX_PER_DAY} entries today"
    elif turning and mins < BOUNCE_FIRST_MIN:
        no = "no bounce entries in the first 15 minutes"
    elif turning and gate:
        no = f"no bounce: {gate}"
    elif days is not None and days <= 1:
        no = f"earnings in {days} day{'s' if days != 1 else ''}"
    elif mins >= OPEN_FREE_MIN and _new_in_window(book, now) >= MAX_NEW:
        no = f"pace limit: {MAX_NEW} new entries in the last {NEW_WINDOW_MIN} minutes"
    elif len(book["positions"]) >= MAX_OPEN:
        no = f"already {MAX_OPEN} open"
    else:
        no = ""
    if no:
        results[o["id"]] = ("rejected", no)
        _skip(book, ticker, "agent", f"agent order refused: {no}", price, now)
        return None
    t = _enter(book, ticker, "bounce" if turning else "breakout", f"agent ({o['state']}, confidence {o['confidence']}): {o['reason']}",
               price, m["lo"], atr, now, LEVEL_PCT, "")
    if t is None:
        results[o["id"]] = ("rejected", "not enough cash for a share, or no room for a stop")
        _skip(book, ticker, "agent", "agent order refused: not enough cash for a share", price, now)
        return None
    results[o["id"]] = ("done", f"bought at {price:.2f}")
    return t


def step(book: dict, marks: dict, snaps: dict, prices: dict, now: datetime, setups: dict | None = None,
         orders: list | None = None, results: dict | None = None) -> list[dict]:
    """One cycle for every stock in `snaps` with a price in `prices`. `now` is New York time. Returns what it did.
    `orders` is None for the old rules (they pick the stocks); a list (maybe empty) means the agent picks: entries open only on its
    orders, and the old setups are logged in book["baseline"]. Exits, stops and every limit work the same either way."""
    done = []
    results = results if results is not None else {}
    mins = minutes_in(now)
    gate = market_gate(snaps)
    by_hand = {t["ticker"] for t in book["trades"] if str(t.get("exit_reason") or "").startswith("owner override")
               and str(t.get("closed") or "").startswith(now.strftime("%Y-%m-%d"))}
    for ticker, snap in snaps.items():
        price = prices[ticker]
        m = mark(marks, ticker, price, now)
        p = snap["payload"]
        pos = book["positions"].get(ticker)
        atr = _num((p.get("technical") or {}).get("atr"))
        if pos:
            atr = pos["atr"]
            t = next(x for x in book["trades"] if x["id"] == pos["trade"])
            move = (price / pos["entry"] - 1) * 100
            t["best"], t["worst"] = max(t["best"], round(move, 2)), min(t["worst"], round(move, 2))
            if price > pos["peak"]:
                pos["peak"], pos["best_at"] = price, now.isoformat()
            pos["stop"] = max(pos["stop"], round(pos["entry"] * (1 - MAX_LOSS_PCT / 100), 2))      # also for trades opened before the cap
            if price >= pos["entry"] + LOCK_ATR * atr:
                pos["stop"] = round(max(pos["stop"], pos["entry"], pos["peak"] - TRAIL_ATR * atr), 2)
            held = (now - datetime.fromisoformat(pos["opened"])).total_seconds() / 60
            since_best = (now - datetime.fromisoformat(pos["best_at"])).total_seconds() / 60
            if price <= pos["stop"]:
                reason = "trailing stop hit, riding ended" if pos["stop"] > pos["entry"] else f"stop hit ({move:+.1f}%)"
            elif mins is not None and mins >= LAST_MIN:
                reason = "end of day: no overnight"
            elif held >= NO_PROGRESS_MIN and t["best"] < NO_PROGRESS_PCT and price < pos["entry"] + 0.2 * atr:
                reason = f"no progress: never reached +{NO_PROGRESS_PCT}% in {held:.0f} minutes"
            elif held >= DRY_MIN and (volpace.pace(snap, mins) or 9) < DRY_PACE and price < pos["entry"] + 0.3 * atr:
                reason = f"volume dried up after {held:.0f} minutes and the price is not moving"
            elif held >= STALL_MIN and price < pos["entry"] + 0.2 * atr:
                reason = f"went nowhere for {held:.0f} minutes"
            elif t["best"] >= TAKE_PCT and since_best >= TAKE_STALL_MIN and price < pos["peak"] * (1 - TAKE_GIVEBACK_PCT / 100) and price > pos["entry"]:
                reason = f"took the profit: was up {t['best']:.1f}%, no new high for {since_best:.0f} minutes and not riding any more ({move:+.1f}%)"
            elif since_best >= 45 and price < pos["peak"] - 0.25 * atr and price > pos["entry"]:
                reason = "momentum faded: no new high for 45 minutes"
            elif orders:
                reason = _agent_position(book, ticker, pos, t, price, atr, orders, results, now)
                if reason is None:
                    continue
            else:
                continue
            _exit(book, ticker, price, now, reason)
            done.append({"ticker": ticker, "action": "EXIT", "price": price, "reason": reason, "time": now.strftime("%H:%M")})
            continue
        if mins is None or mins < FIRST_MIN or mins >= LAST_MIN - 15:
            continue
        if atr is None or atr <= 0:
            continue                                             # unknown range: no read, never a guess
        q = p.get("quote") or {}
        chg = _num(q.get("live_change"))
        prev = price / (1 + chg) if chg is not None and chg > -0.9 else None
        kind, why = setup(read_chart(m, price, prev, atr))
        if orders is not None:
            t = _agent_entry(book, ticker, kind, why, m, price, atr, mins, gate, prices, now, (p.get("events") or {}).get("days_to_earnings"),
                             orders, results)
            if t:
                done.append({"ticker": ticker, "action": "ENTER", "price": price, "reason": f"agent: {t['reason']}", "time": now.strftime("%H:%M")})
            continue
        if not kind:
            continue
        if setups is not None:
            setups[ticker] = kind
        if kind == "bounce" and mins < BOUNCE_FIRST_MIN:
            continue                                             # the opening move: not a floor yet
        g, g_why = grade(kind, volpace.pace(snap, mins))
        days = (p.get("events") or {}).get("days_to_earnings")
        today = _today_trades(book, now)
        lost = day_result(book, prices, now)
        if ticker in by_hand:
            _skip(book, ticker, kind, "you sold it by hand today", price, now)
        elif lost <= -book["start"] * DAY_LOSS_PCT / 100:
            _skip(book, ticker, kind, f"daily loss stop: down ${abs(lost):,.0f} today (limit ${book['start'] * DAY_LOSS_PCT / 100:,.0f})", price, now)
        elif len(today) >= MAX_PER_DAY:
            _skip(book, ticker, kind, f"day limit: {MAX_PER_DAY} entries today", price, now)
        elif kind == "bounce" and gate:
            _skip(book, ticker, kind, f"no bounce: {gate}", price, now)
        elif g is None:
            _skip(book, ticker, kind, f"no trade: {g_why}", price, now)
        elif mins >= OPEN_FREE_MIN and _new_in_window(book, now) >= MAX_NEW:
            _skip(book, ticker, kind, f"pace limit: {MAX_NEW} new entries in the last {NEW_WINDOW_MIN} minutes", price, now)
        elif days is not None and days <= 1:
            _skip(book, ticker, kind, f"earnings in {days} day{'s' if days != 1 else ''}", price, now)
        elif len(book["positions"]) >= MAX_OPEN:
            _skip(book, ticker, kind, f"already {MAX_OPEN} open", price, now)
        else:
            t = _enter(book, ticker, kind, f"{why}; {g_why}", price, m["lo"], atr, now, SIZE_PCT[g], g)
            if t:
                done.append({"ticker": ticker, "action": "ENTER", "price": price, "reason": f"{kind} (grade {g}): {why}; {g_why}", "time": now.strftime("%H:%M")})
            else:
                _skip(book, ticker, kind, "not enough cash for a share", price, now)
    book["log"] = (book["log"] + done)[-200:]
    return done


def tick(store, now: datetime | None = None, force_session: bool = False) -> dict:
    """One cycle from the tracker thread. Always safe to call; outside the regular session it does nothing."""
    from . import paper_live
    now = (now or datetime.now(NY)).astimezone(NY)
    state = {"at": now.isoformat(), "watching": 0, "skipped": {}, "did": [], "note": ""}
    if not (force_session or us_session() == "REGULAR"):
        state["note"] = "market closed: nothing trades outside the regular session"
        store.set_setting(STATE_KEY, json.dumps(state))
        _sheet_outcome(store)
        if not store.get_setting("quick_sheet_ok"):                # the sheet files appear even before the next session
            export_async(load_book(store))
        return state
    book = load_book(store, migrate=False)
    topped = top_up(book)
    raw = store.get_setting(MARKS_KEY)
    marks = json.loads(raw) if raw else {}
    snaps, prices = {}, {}
    for s in store.latest_snapshots():
        t = s["ticker"]
        price, why = paper_live.fresh_price(s, now)
        if price is None:
            if t in book["positions"]:
                state["skipped"][t] = why + ": its open trade is NOT being watched right now"
            continue
        snaps[t], prices[t] = s, price
    state["watching"] = len(snaps)
    before = json.dumps(book, default=str, sort_keys=True)
    state["setups"] = {}
    from . import agent
    orders = agent.orders_for(store, "quick", now)
    results: dict = {}
    if orders is not None:
        state["note"] = (f"the agent picks: {len(orders)} order(s) ready" if agent.has_key()
                         else "ANTHROPIC_API_KEY is not set: nothing is bought in agent mode")
    state["did"] = step(book, marks, snaps, prices, now, state["setups"], orders, results)
    from . import sectors
    sectors.stamp(book["trades"], state["did"], snaps, store)           # log only: what the sector check said at each entry
    agent.settle(store, results, now)
    changed = topped or json.dumps(book, default=str, sort_keys=True) != before
    if changed:
        save_book(store, book)
    _sheet_outcome(store)
    if changed or not store.get_setting("quick_sheet_ok"):
        export_async(book)
    store.set_setting(MARKS_KEY, json.dumps(marks))
    store.set_setting(STATE_KEY, json.dumps(state, default=str))
    return state


def sell_by_hand(store, ticker: str, now: datetime | None = None) -> dict:
    """The owner's override (5 Nov): sell one open trade at the latest fresh price because the entry looked like a mistake. It is recorded as
    'owner override', apart from the rules, so the rules' results and the overrides can be studied separately. Quick never re-enters a stock on
    the day it traded, so the stock is not bought back. Runs from the page; needs the regular session and a fresh price."""
    from . import paper_live
    now = (now or datetime.now(NY)).astimezone(NY)
    if us_session() != "REGULAR":
        return {"ok": False, "note": "The market is closed: nothing trades outside the regular session."}
    book = load_book(store, migrate=False)
    if ticker not in book["positions"]:
        return {"ok": False, "note": f"{ticker} is not open any more."}
    snap = store.snapshot(ticker)
    price, why = paper_live.fresh_price(snap, now) if snap else (None, "no reading for this stock")
    if price is None:
        return {"ok": False, "note": f"No fresh price for {ticker} ({why}), so it was not sold. Try again in a minute."}
    _exit(book, ticker, price, now, f"owner override: sold by hand at {price:.2f}")
    save_book(store, book)
    t = next(x for x in book["trades"] if x["ticker"] == ticker and x["status"] == "CLOSED" and x["closed"] == now.strftime("%Y-%m-%d %H:%M"))
    return {"ok": True, "note": f"Sold {ticker} by hand at {price:.2f}: {t['result']:+,.2f} ({t['pct']:+.1f}%)."}


def report(book: dict, prices: dict | None = None) -> dict:
    closed = [t for t in book["trades"] if t["status"] == "CLOSED"]
    wins = [t for t in closed if t["result"] > 0]
    losses = [t for t in closed if t["result"] <= 0]
    avg = lambda xs: sum(xs) / len(xs) if xs else None            # noqa: E731
    fixed = sum((t["entry"] * t["shares"] * FIXED_PCT / 100) - t["result"] for t in closed if t["best"] >= FIXED_PCT)
    return {"closed": len(closed), "open": len(book["positions"]), "wins": len(wins), "win_rate": len(wins) / len(closed) if closed else None,
            "avg_win": avg([t["pct"] for t in wins]), "avg_loss": avg([t["pct"] for t in losses]),
            "result": round(sum(t["result"] for t in closed), 2), "equity": round(equity(book, prices or {}), 2),
            "avg_minutes": avg([t["minutes"] for t in closed if t["minutes"] is not None]),
            "rode": len([t for t in closed if t["best"] >= FIXED_PCT]), "vs_fixed": round(-fixed, 2) if closed else None,
            "skipped": len(book["skipped"])}


def status(store) -> dict:
    raw = store.get_setting(STATE_KEY)
    return {"book": load_book(store), "state": json.loads(raw) if raw else None, "sheet_error": store.get_setting("quick_sheet_error") or None}


def prices_of(store, tickers) -> dict:
    out = {}
    for t in tickers:
        sn = store.snapshot(t)
        if sn:
            px = ui._now(sn)[0]
            if px == px and px is not None:
                out[t] = float(px)
    return out
