"""Ask the AI about one stock: the data format, saving and reading verdicts.

This file fixes the CONTRACT the screen (Codex) and the AI side (Claude) share.
The AI call itself is added by Claude later; until then `latest()` returns what was
saved, and `sample_verdict()` gives a realistic one so the screen can be built
and tested offline. A verdict places no trade and changes no score.

Verdict dict (every key always present; unknown = None, never 0):
  ticker, name, sector            text
  asked_at                        ISO time, New York clock
  price                           price when asked (None = unknown)
  price_label                     "now" (live trade) or "last close"
  verdict                         "BUY" | "HOLD" | "SELL" | "AVOID"
  confidence                      1..5
  headline                        one plain-English line, at most 30 words
  change_buy / change_hold / change_sell   what would turn it into each verdict
  levels                          [{"label", "price", "kind"}], kind in LEVEL_KINDS,
                                  any order (the screen sorts by price)
  facts                           [{"label", "value", "tone"}], tone in TONES
  scored                          {"plus60": pct or None, "close": pct or None}
  status                          "ready" | "asking" | "failed"
  error                           text when status is "failed", else None
"""
from __future__ import annotations

import json

KEY_VERDICTS = "ai_verdicts"          # setting: {ticker: [verdict, ...]} newest last
KEEP_PER_TICKER = 20
VERDICTS = ("BUY", "HOLD", "SELL", "AVOID")
LEVEL_KINDS = ("exit_line", "price", "resistance", "support")
TONES = ("good", "bad", "neutral")
STATUSES = ("ready", "asking", "failed")


def sample_verdict(ticker: str = "ISRG") -> dict:
    """A realistic verdict for building and testing the screen offline."""
    return {
        "ticker": ticker, "name": "Intuitive Surgical", "sector": "Healthcare",
        "asked_at": "2026-11-03T07:58:00-05:00", "price": 436.87, "price_label": "last close",
        "verdict": "HOLD", "confidence": 2,
        "headline": "Just above a weak level, but under the exit line and only 1% over the 200-day average. The daily call is AVOID.",
        "change_buy": "Closes above 443.48, holds it on a retest, and volume is 1.2x normal or more for the time of day.",
        "change_hold": "Stays between 427.93 and 443.48. Nothing to do.",
        "change_sell": "Loses 427.93 support (high grade, 5 touches) on rising volume. If you own it, this is the exit.",
        "levels": [
            {"label": "Exit line: above this = buy zone", "price": 443.48, "kind": "exit_line"},
            {"label": "Price now", "price": 436.87, "kind": "price"},
            {"label": "Resistance, weak (1 touch)", "price": 434.80, "kind": "resistance"},
            {"label": "Support: below this = sell", "price": 427.93, "kind": "support"},
        ],
        "facts": [
            {"label": "Daily call", "value": "AVOID", "tone": "bad"},
            {"label": "Trend", "value": "mixed", "tone": "neutral"},
            {"label": "RSI", "value": "57", "tone": "neutral"},
            {"label": "Above 200-day", "value": "+1.0%", "tone": "neutral"},
            {"label": "Earnings", "value": "in 80 days", "tone": "neutral"},
            {"label": "Live volume and bars", "value": None, "tone": "neutral"},
        ],
        "scored": {"plus60": None, "close": None},
        "status": "ready", "error": None,
    }


def check(v: dict) -> list[str]:
    """Problems with a verdict dict (empty list = fine). Used by tests and before saving."""
    bad = []
    for k in sample_verdict():
        if k not in v:
            bad.append(f"missing {k}")
    if bad:
        return bad
    if v["status"] not in STATUSES:
        bad.append("status")
    if v["status"] == "ready":
        if v["verdict"] not in VERDICTS:
            bad.append("verdict")
        if not isinstance(v["confidence"], int) or not 1 <= v["confidence"] <= 5:
            bad.append("confidence")
    for lv in v["levels"] or []:
        if lv.get("kind") not in LEVEL_KINDS:
            bad.append(f"level kind {lv.get('kind')}")
    for f in v["facts"] or []:
        if f.get("tone") not in TONES:
            bad.append(f"fact tone {f.get('tone')}")
    return bad


def _load(store) -> dict:
    try:
        d = json.loads(store.get_setting(KEY_VERDICTS) or "{}")
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def save(store, v: dict) -> None:
    d = _load(store)
    rows = d.get(v["ticker"], [])
    rows.append(v)
    d[v["ticker"]] = rows[-KEEP_PER_TICKER:]
    store.set_setting(KEY_VERDICTS, json.dumps(d, default=str))


def latest(store, ticker: str) -> dict | None:
    """Newest saved verdict for the ticker, or None if it was never asked."""
    rows = _load(store).get(ticker.upper().strip(), [])
    return rows[-1] if rows else None


def history(store, limit: int = 50) -> list[dict]:
    """Newest first, all tickers: the 'How the AI did' table."""
    rows = [r for rs in _load(store).values() for r in rs]
    rows.sort(key=lambda r: r.get("asked_at") or "", reverse=True)
    return rows[:limit]


# ------------------------------------------------------------------ the AI side (Claude): ask, queue, score
import logging
import os
import threading
from datetime import datetime

from . import agent
from .data import NY, us_session

log = logging.getLogger("stockwatch.ask_ai")
KEY_QUEUE = "ai_ask_queue"
DEFAULT_MAX_PER_DAY = 40                  # asks a day (a cost brake; each ask is about one cent or two)
SCORE_AFTER_MIN = 60
SCORE_WINDOW_MIN = 90                     # the +60 reading is only taken while the age is 60..90 minutes
_thread: dict = {"t": None}

ASK_CONTRACT = """
You are asked about ONE stock by the owner, who is deciding now. You place no trade and move no money.
OUTPUT: reply with one JSON object and nothing else.
{"verdict": "BUY|HOLD|SELL|AVOID", "confidence": 1-5,
 "headline": "at most 30 words, plain English, the main reason",
 "change_buy": "what would have to happen for this to become a BUY",
 "change_hold": "what keeps it a HOLD, or what to wait for",
 "change_sell": "what would make it a SELL (if owned, the exit)"}
Meaning: BUY = a clean entry exists now under the playbook; HOLD = if owned keep it, if not wait, not a buy yet; SELL = if owned, leave;
AVOID = do not buy and no reason to own. Use only the numbers in the data, never invent prices or news. Missing data is unknown: say so,
and do not treat it as bad. Name the pattern and its label (forming, confirmed, failed, no clean pattern) when you can. A BUY needs the
stock to be turning or riding with confirmation and confidence 3 or more; otherwise say HOLD or AVOID. Each change_ line is one sentence.
"""


def max_per_day() -> int:
    try:
        return max(1, int(os.getenv("STOCKWATCH_ASK_MAX") or DEFAULT_MAX_PER_DAY))
    except ValueError:
        return DEFAULT_MAX_PER_DAY


def _txt(v, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def _tone(call) -> str:
    c = str(call or "").upper()
    if c in ("AVOID", "EXIT", "SELL", "WEAK"):
        return "bad"
    if c in ("BUY", "ADD", "STRONG"):
        return "good"
    return "neutral"


def build_levels(d: dict, price) -> list[dict]:
    """Price ladder from the data we hold (never from the AI): exit line, support, resistance, price now."""
    out = []
    dc = d.get("daily_call") or {}
    if dc.get("exit_line") is not None:
        out.append({"label": "Exit line: above this = buy zone", "price": dc["exit_line"], "kind": "exit_line"})
    z = d.get("zones") or {}
    if z.get("resistance"):
        r = z["resistance"]
        out.append({"label": f"Resistance, {str(r.get('grade') or 'unknown').lower()} ({r.get('touches') or '?'} touches)", "price": r["price"], "kind": "resistance"})
    if z.get("support"):
        r = z["support"]
        out.append({"label": f"Support: below this = sell ({str(r.get('grade') or 'unknown').lower()}, {r.get('touches') or '?'} touches)", "price": r["price"], "kind": "support"})
    if price is not None:
        out.append({"label": "Price now", "price": price, "kind": "price"})
    return out


def build_facts(d: dict, live: bool) -> list[dict]:
    f = []
    dc = d.get("daily_call") or {}
    f.append({"label": "Daily call", "value": dc.get("call"), "tone": _tone(dc.get("call"))})
    f.append({"label": "Trend", "value": d.get("trend"), "tone": "neutral"})
    f.append({"label": "RSI", "value": None if d.get("rsi") is None else str(int(d["rsi"])), "tone": "neutral"})
    v = d.get("vs_sma200_pct")
    f.append({"label": "Above 200-day", "value": None if v is None else f"{v:+.1f}%", "tone": "neutral" if v is None else ("good" if v > 0 else "bad")})
    e = d.get("earnings_in_days")
    f.append({"label": "Earnings", "value": None if e is None else f"in {int(e)} days", "tone": "bad" if isinstance(e, (int, float)) and e <= 3 else "neutral"})
    pace = d.get("volume_pace")
    f.append({"label": "Volume vs normal", "value": None if (pace is None or not live) else f"{pace:.1f}x", "tone": "neutral"})
    return f


def _price_for(snap: dict, now: datetime):
    from . import paper_live
    px, _why = paper_live.fresh_price(snap, now)
    if px is not None:
        return float(px), "now"
    q = (snap.get("payload") or {}).get("quote") or {}
    for k in ("regular_price", "live_price"):
        v = agent._num(q.get(k))
        if v:
            return float(v), "last close"
    return None, "last close"


def parse_answer(text: str) -> dict:
    a = agent.parse(text)
    verdict = str(a.get("verdict") or "").upper().strip()
    if verdict not in VERDICTS:
        raise agent.AgentError(f"the AI gave verdict {verdict!r}")
    try:
        conf = int(round(float(a.get("confidence"))))
    except (TypeError, ValueError):
        conf = 1
    return {"verdict": verdict, "confidence": min(5, max(1, conf)), "headline": _txt(a.get("headline"), 260),
            "change_buy": _txt(a.get("change_buy"), 240), "change_hold": _txt(a.get("change_hold"), 240),
            "change_sell": _txt(a.get("change_sell"), 240)}


def _blank(ticker: str, now: datetime, status: str, error: str | None = None) -> dict:
    v = sample_verdict(ticker)
    v.update(name="", sector=None, asked_at=now.isoformat(timespec="seconds"), price=None, price_label="last close",
             verdict="HOLD", confidence=1, headline="", change_buy="", change_hold="", change_sell="", levels=[], facts=[],
             scored={"plus60": None, "close": None}, status=status, error=error)
    return v


def asks_today(store, now: datetime) -> int:
    day = now.date().isoformat()
    return sum(1 for r in history(store, 500) if str(r.get("asked_at", "")).startswith(day) and r.get("status") == "ready")


def ask(store, ticker: str, now: datetime | None = None, caller=None, fetch=None) -> dict:
    """Answer for one stock and save it. Never raises: a failure is saved as status 'failed' with the reason."""
    now = (now or datetime.now(NY)).astimezone(NY)
    ticker = ticker.upper().strip()
    caller = caller or agent.call_api
    snap = store.snapshot(ticker)
    if not snap:
        v = _blank(ticker, now, "failed", f"{ticker} is not tracked yet. Add it to the watchlist first, then ask again.")
    elif not agent.has_key():
        v = _blank(ticker, now, "failed", "No Anthropic key in the settings file, so the AI cannot be asked.")
    elif asks_today(store, now) >= max_per_day():
        v = _blank(ticker, now, "failed", f"Daily limit of {max_per_day()} asks reached.")
    else:
        try:
            v = _answer(store, snap, ticker, now, caller, fetch)
        except Exception as e:                      # the page must never break on this
            log.exception("ask failed for %s", ticker)
            v = _blank(ticker, now, "failed", _txt(f"The AI did not answer: {e}", 200))
    save(store, v)
    return v


def _answer(store, snap: dict, ticker: str, now: datetime, caller, fetch) -> dict:
    live = us_session(now) == "REGULAR"
    price, label = _price_for(snap, now)
    marks = agent._jget(store, agent.quick.MARKS_KEY, {})
    mins = agent.quick.minutes_in(now) if live else None
    d = agent.pack(snap, (marks or {}).get(ticker), mins, price) if price else agent.pack(snap, None, mins, 0.0)
    if price is None:
        d["price"] = None
    if live:
        d["intraday"] = (agent.intraday_features([ticker], now, fetch) or {}).get(ticker)
    d["session"] = "regular session, live" if live else f"market not in regular session ({us_session(now)}); price is the last close; live bars unknown"
    system = agent.playbook_text() + "\n" + ASK_CONTRACT
    text, usage = caller(system, json.dumps({"stock": d, "now_new_york": now.isoformat(timespec="minutes")}, default=str), 1500, 90)
    try:
        agent._add_usage(store, now, usage)
    except Exception:
        pass
    a = parse_answer(text)
    p = d.get("price")
    return {"ticker": ticker, "name": d.get("name") or "", "sector": d.get("sector"), "asked_at": now.isoformat(timespec="seconds"),
            "price": p, "price_label": label, **a, "levels": build_levels(d, p), "facts": build_facts(d, live),
            "scored": {"plus60": None, "close": None}, "status": "ready", "error": None}


def request(store, ticker: str, now: datetime | None = None) -> None:
    """Called from the page: returns at once. Saves an 'asking' placeholder and queues the ticker for the tracker thread."""
    now = (now or datetime.now(NY)).astimezone(NY)
    ticker = ticker.upper().strip()
    if not ticker or not ticker.replace(".", "").replace("-", "").isalnum() or len(ticker) > 10:
        return
    q = _queue(store)
    if ticker not in q:
        save(store, _blank(ticker, now, "asking"))
        q.append(ticker)
        store.set_setting(KEY_QUEUE, json.dumps(q))


def _queue(store) -> list:
    try:
        q = json.loads(store.get_setting(KEY_QUEUE) or "[]")
    except ValueError:
        return []
    return [t for t in q if isinstance(t, str)] if isinstance(q, list) else []


def _replace(store, v: dict) -> None:
    d = _load(store)
    rows = d.get(v["ticker"], [])
    for i, r in enumerate(rows):
        if r.get("asked_at") == v["asked_at"]:
            rows[i] = v
            break
    d[v["ticker"]] = rows
    store.set_setting(KEY_VERDICTS, json.dumps(d, default=str))


def score(store, now: datetime | None = None) -> int:
    """Fill the +60 min and close readings on today's verdicts. Returns how many cells were filled."""
    now = (now or datetime.now(NY)).astimezone(NY)
    snaps = {s["ticker"]: s for s in store.latest_snapshots()}
    n = 0
    for v in history(store, 500):
        if v.get("status") != "ready" or not v.get("price") or v["ticker"] not in snaps:
            continue
        try:
            at = datetime.fromisoformat(v["asked_at"]).astimezone(NY)
        except ValueError:
            continue
        age = (now - at).total_seconds() / 60
        sc = dict(v.get("scored") or {"plus60": None, "close": None})
        px, _why = _price_for(snaps[v["ticker"]], now)
        q = (snaps[v["ticker"]].get("payload") or {}).get("quote") or {}
        if sc.get("plus60") is None and SCORE_AFTER_MIN <= age <= SCORE_WINDOW_MIN and px and _price_for(snaps[v["ticker"]], now)[1] == "now":
            sc["plus60"] = round((px / v["price"] - 1) * 100, 2)
            n += 1
        close_t = at.replace(hour=16, minute=0, second=0, microsecond=0)
        reg = agent._num(q.get("regular_price"))
        try:
            fetched = datetime.fromisoformat(str(q.get("fetched_at"))).astimezone(NY)
        except ValueError:
            fetched = None
        if sc.get("close") is None and now >= close_t and at < close_t and reg and fetched and fetched >= close_t and fetched.date() == at.date():
            sc["close"] = round((reg / v["price"] - 1) * 100, 2)
            n += 1
        if sc != v.get("scored"):
            _replace(store, {**v, "scored": sc})
    return n


def tick(store_path=None, now: datetime | None = None, caller=None) -> None:
    """Called from the tracker's 20-second block. Starts at most one worker thread; returns at once."""
    t = _thread["t"]
    if t is not None and t.is_alive():
        return

    def work():
        from .store import Store
        store = Store(store_path) if store_path else Store()
        n = (now or datetime.now(NY)).astimezone(NY)
        q = _queue(store)
        for tk in q[:3]:
            ask(store, tk, n, caller)
        if q:
            store.set_setting(KEY_QUEUE, json.dumps([t for t in _queue(store) if t not in q[:3]]))
        score(store, n)

    _thread["t"] = threading.Thread(target=work, name="stockwatch-ask-ai", daemon=True)
    _thread["t"].start()
