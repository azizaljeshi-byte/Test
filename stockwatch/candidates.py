"""The shared candidates list for Quick and New call (owner, 2026-10-30). Log only: it does not limit what either account trades.

10 minutes before the US open (09:20 New York, so the clock change on 1 November is followed by itself) it scans every stock the app
tracks and writes the ones worth watching today, again half an hour after the open and then every 30 minutes until 15:30. A stock qualifies when
  Quick      it gapped down about GAP_DOWN_ATR daily ranges or more (a bounce candidate) or up GAP_UP_ATR or more (a breakout candidate)
  New call   its New call is BUY or ADD
and it has no earnings within a day. One row per stock and day, with what each account then did with it: bought (grade, price, result),
skipped or held back (why), or nothing yet. A stock either account traded that is not on the list is added as "not on the list".
Missing data never qualifies a stock.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from . import paper_newcall, quick
from .data import NY, us_session

log = logging.getLogger("stockwatch.candidates")
KEY = "candidates_log"
SCAN_PRE_MIN = 9 * 60 + 20          # 09:20 New York
SCAN_REFRESH_MIN = 10 * 60          # 10:00 New York: the first scan after the open
REFRESH_EVERY_MIN = 30              # then again every 30 minutes (owner, 2 Nov: keep the list refreshing) ...
SCAN_LAST_MIN = 15 * 60 + 30        # ... until 15:30 New York
GAP_DOWN_ATR, GAP_UP_ATR = 0.7, 0.5
KEEP_DAYS = 10
COLS = [("day", "Day"), ("ticker", "Ticker"), ("found", "Found"), ("qualified", "Why it qualified"), ("price", "Price"),
        ("move_pct", "Move %"), ("move_atr", "Move (daily ranges)"), ("call", "New call"),
        ("quick", "Quick"), ("quick_result", "Quick result"), ("newcall", "New call account"), ("newcall_result", "New call result")]


def _num(v) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def load(store) -> dict:
    raw = store.get_setting(KEY)
    return json.loads(raw) if raw else {"days": {}}


def _move(p: dict, phase: str) -> tuple[float | None, float | None, float | None]:
    """(price, move as a fraction, move in daily ranges) since yesterday's close: pre-market before the open, live after it."""
    q, atr = p.get("quote") or {}, _num((p.get("technical") or {}).get("atr"))
    if phase == "pre-open":
        if q.get("ext_session") != "pre" or q.get("ext_stale"):
            return None, None, None
        price, prev = _num(q.get("ext_price")), _num(q.get("regular_price"))
    else:
        chg, price = _num(q.get("live_change")), _num(q.get("live_price"))
        prev = price / (1 + chg) if price and chg is not None and chg > -0.9 else None
    if not price or not prev or not atr or atr <= 0:
        return None, None, None
    return price, price / prev - 1, (price - prev) / atr


def qualify(snap: dict, phase: str) -> dict | None:
    p = snap.get("payload") or {}
    days = (p.get("events") or {}).get("days_to_earnings")
    if days is not None and days <= 1:
        return None
    price, move, atr_move = _move(p, phase)
    oc = (p.get("technical") or {}).get("one_call")
    call = oc.get("call") if isinstance(oc, dict) and oc.get("known") else None
    why = []
    if atr_move is not None and atr_move <= -GAP_DOWN_ATR:
        why.append(f"Quick: down {abs(move) * 100:.1f}% = {abs(atr_move):.1f} daily ranges (bounce candidate)")
    elif atr_move is not None and atr_move >= GAP_UP_ATR:
        why.append(f"Quick: up {move * 100:.1f}% = {atr_move:.1f} daily ranges (breakout candidate)")
    if call in ("BUY", "ADD"):
        why.append(f"New call: {call}")
    if not why:
        return None
    return {"qualified": " + ".join(why), "price": price, "move_pct": None if move is None else round(move * 100, 2),
            "move_atr": None if atr_move is None else round(atr_move, 2), "call": call}


def scan(store, snaps: list, now: datetime, phase: str) -> int:
    """Adds stocks that qualify now. A stock already on the list keeps its first "found" time and is never removed."""
    data = load(store)
    day = data["days"].setdefault(now.date().isoformat(), {"rows": {}, "scans": []})
    added = 0
    for s in snaps:
        t = s["ticker"]
        if t in day["rows"]:
            continue
        q = qualify(s, phase)
        if q:
            day["rows"][t] = {"ticker": t, "found": f"{phase} {now.strftime('%H:%M')}", **q}
            added += 1
    day["scans"].append(phase)
    day["last_scan_min"] = now.hour * 60 + now.minute
    _save(store, data)
    return added


def _save(store, data: dict) -> None:
    for old in sorted(data["days"])[:-KEEP_DAYS]:
        del data["days"][old]
    store.set_setting(KEY, json.dumps(data, default=str))


def _quick_view(qb: dict, t: str, day: str) -> tuple[str, str]:
    tr = [x for x in qb["trades"] if x["ticker"] == t and str(x["opened"]).startswith(day)]
    if tr:
        x = tr[-1]
        out = f"bought {x['opened'][11:]} at {x['entry']:.2f}, grade {x.get('grade') or '?'}, {x['kind']}"
        res = "open" if x["status"] == "OPEN" else f"{x['pct']:+.2f}% ({x['result']:+.0f}$): {x['exit_reason']}"
        return out, res
    sk = [x for x in qb["skipped"] if x["ticker"] == t and x["day"] == day]
    return (f"skipped {sk[-1]['time']}: {sk[-1]['reason']}", "") if sk else ("no setup yet", "")


def _newcall_view(nb, t: str, day: str, call) -> tuple[str, str]:
    tr = [x for x in nb.trades if x["ticker"] == t and str(x["opened"]).startswith(day)]
    if tr:
        x = tr[-1]
        out = f"bought {x['opened'][11:]} at {x['entry']:.2f}"
        res = "open" if x["status"] == "OPEN" else f"{x['result']:+.0f}$: {x['exit_reason']}"
        return out, res
    bl = [x for x in nb.blocked if x.get("ticker") == t and x.get("day") == day]
    if bl:
        return f"held back: {bl[-1]['reason']}", ""
    return ("no entry yet" if call in ("BUY", "ADD") else "not a buy call"), ""


def record(store, now: datetime) -> bool:
    """Fill each row with what the two accounts did. True when the log changed."""
    data = load(store)
    day = now.date().isoformat()
    d = data["days"].get(day)
    qb, nb = quick.load_book(store, migrate=False), paper_newcall.load_book(store)
    if d is None:
        d = data["days"].setdefault(day, {"rows": {}, "scans": []})
    for tr in [x["ticker"] for x in qb["trades"] if str(x["opened"]).startswith(day)] + \
              [x["ticker"] for x in nb.trades if str(x["opened"]).startswith(day)]:
        d["rows"].setdefault(tr, {"ticker": tr, "found": "not on the list", "qualified": "traded, but did not qualify in the scans",
                                  "price": None, "move_pct": None, "move_atr": None, "call": None})
    before = json.dumps(data, sort_keys=True, default=str)
    for t, r in d["rows"].items():
        r["quick"], r["quick_result"] = _quick_view(qb, t, day)
        r["newcall"], r["newcall_result"] = _newcall_view(nb, t, day, r.get("call"))
    changed = json.dumps(data, sort_keys=True, default=str) != before
    if changed:
        _save(store, data)
    return changed


def export(store) -> str:
    try:
        folder = quick.log_dir()
        if not (folder.parent.is_dir() or folder.is_dir()):
            return f"the Drive folder was not found: {folder.parent}"
        folder.mkdir(exist_ok=True)
        rows = [{"day": day, **r} for day, d in sorted(load(store)["days"].items()) for r in d["rows"].values()]
        quick._write_csv(folder / "Candidates log.csv", COLS, rows)
        return ""
    except Exception as e:
        log.warning("candidates export failed: %s", e)
        return str(e)[:200]


def tick(store, now: datetime | None = None) -> dict:
    """From the tracker, every 20 seconds. Scans at 09:20, then at 10:00 and every 30 minutes until 15:30 New York and keeps the rows up to date."""
    now = (now or datetime.now(NY)).astimezone(NY)
    sess, mins = us_session(now), now.hour * 60 + now.minute
    day = load(store)["days"].get(now.date().isoformat(), {})
    done = day.get("scans", [])
    out = {"scanned": None, "added": 0}
    if sess == "PRE" and mins >= SCAN_PRE_MIN and "pre-open" not in done:
        out.update(scanned="pre-open", added=scan(store, store.latest_snapshots(), now, "pre-open"))
    elif sess == "REGULAR" and SCAN_REFRESH_MIN <= mins <= SCAN_LAST_MIN and (
            "refresh" not in done or mins - int(day.get("last_scan_min") or 0) >= REFRESH_EVERY_MIN):
        out.update(scanned="refresh", added=scan(store, store.latest_snapshots(), now, "refresh"))
    if sess == "REGULAR" or out["scanned"]:
        if record(store, now) or out["scanned"]:
            export(store)
    return out
