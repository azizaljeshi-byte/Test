"""Ask the AI about one stock: the data format, saving and reading verdicts.

This file fixes the CONTRACT the screen (Codex) and the AI side (Claude) share.
The AI call itself is added by Claude later; until then `latest()` returns what was
saved, and `sample_verdict()` gives a realistic one so the screen can be built
and tested offline. A verdict places no trade and changes no score.

Verdict dict (every key always present; unknown = None, never 0):
  ticker, name, sector            text
  asked_at                        ISO time, New York clock
  price                           price when asked
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
        "asked_at": "2026-11-03T07:58:00-05:00", "price": 436.87,
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
