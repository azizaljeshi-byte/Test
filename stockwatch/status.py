"""One plain-English price status per stock, from record high down to deep breakdown. Display only.

The seven statuses, best to worst (ORDER), each with the rule that puts a stock there:

  record_high      the completed close is at the highest close in the history we hold (5 years by default)
  strong_uptrend   within STRONG_NEAR of that high, above the 50- and 200-day averages
  pullback         above both averages and between STRONG_NEAR and PULLBACK_MAX below the high
  weakening        below the 50-day or the 200-day average, or more than PULLBACK_MAX below the high,
                   and still above the support zone
  testing_support  the completed close is inside the support zone
  breakdown        the completed close is below the support zone (the CIS "warning" and "failure" states)
  deep_breakdown   the completed close is below the deeper level (the CIS "major damage" level)

The support zone and the two lower levels come from `cis.candidates.extract`, the same automatic levels the
rest of the app labels "unreviewed". Nothing here changes a score or a verdict. With EXIT_ON_BREAKDOWN off (the
default) it changes no trade plan and no call either; with it on, a confirmed breakdown on a held stock becomes a
SELL call (see `forces_exit`, `transitions.effective_stance` and `tradeplan.exit_on_breakdown`).

Rules that came from real bugs:
- Only completed daily closes confirm a status. A live quote can only add a `provisional` note
  ("if it closes here it is a breakdown"), never the status itself.
- Missing, stale or too-short data gives status "unknown" with the reason, never a guess.
- If the support levels can't be placed, the trend statuses still work but `floor_known` is False and
  breakdown can't be reported; the reason is in `why`.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from . import technical
from .cis import candidates, decision, features, level_packet, state

STRONG_NEAR = 0.05      # within 5% of the high counts as a strong uptrend
PULLBACK_MAX = 0.15     # more than 15% below the high counts as weakening
RECORD_TOL = 0.001      # the same 0.1% tolerance the 52-week-high signal uses
MIN_SESSIONS = 200      # the 200-day average needs 200 bars
WINDOW = 420            # bars quality-checked and used for the averages and support levels

ORDER = ("record_high", "strong_uptrend", "pullback", "weakening", "testing_support",
         "breakdown", "deep_breakdown")
LABEL = {"record_high": "RECORD HIGH", "strong_uptrend": "STRONG UPTREND", "pullback": "PULLBACK",
         "weakening": "WEAKENING", "testing_support": "TESTING SUPPORT", "breakdown": "BREAKDOWN",
         "deep_breakdown": "DEEP BREAKDOWN", "unknown": "NO READ"}
# the CIS downside state each status comes from, for the three floor-based ones
FROM_FLOOR = {"testing_floor": "testing_support", "warning": "breakdown", "failure": "breakdown",
              "major_damage": "deep_breakdown"}


# The one place that lets a confirmed breakdown change the call shown on the dashboard and sent to Telegram.
# OFF by default: the support levels are the automatic CIS candidates, which docs/CIS_PHASE2.md found carry no
# information beyond volatility (their failure levels are closed below as often as any level the same ATR distance
# away), so the repo keeps them as diagnostics that never become a call. Set True to turn a confirmed breakdown
# on a held stock into a SELL call (plan, dashboard and Telegram together); nothing else needs to change.
EXIT_ON_BREAKDOWN = False
EXIT_CODES = ("breakdown", "deep_breakdown")
# Telegram: message whenever a stock's status changes (record high -> strong uptrend, ... -> breakdown, and back).
# Same safe rules as the call-change alerts: the first reading is a silent baseline, a change must be seen on two
# runs in a row, a failed send is retried. Set False to stop status messages without touching call alerts.
ALERT_ON_CHANGE = True


def forces_exit(price_status: dict | None, watchlist: bool) -> bool:
    """True when a CONFIRMED breakdown (a completed close, never a live quote) means a held stock should be exited.
    Nothing to sell on a watchlist name, and no status (unknown or missing) never forces anything."""
    return bool(EXIT_ON_BREAKDOWN and not watchlist and isinstance(price_status, dict)
                and price_status.get("code") in EXIT_CODES)


BUY_STANCES = ("BUY NOW", "BUY ON PULLBACK", "BUY THE BREAKOUT", "ADD")


ENTRY_GATES = True        # owner, 2026-10-25: tighten buys so fewer turn into losses (docs/TIGHTENING.md section 1). False = old rule.
GATE_BAD_CHART = ("weakening", "testing_support")
GATE_BAD_MOMENTUM = ("falling", "weak", "fading")


def entry_blockers(price_status: dict | None, technical: dict | None = None) -> list[str]:
    """Plain-English reasons a buy or add should wait. A buy shows only when this is empty.
    Gates: 1 chart structure, 2 momentum, 5 independent check (TradingView or Finnhub not SELL, price data not disagreeing).
    A read that is missing is unknown and never blocks (the screen says it was not read)."""
    out: list[str] = []
    if not ENTRY_GATES or not isinstance(price_status, dict):
        return out
    code = price_status.get("code")
    if code in GATE_BAD_CHART:
        out.append(f"the chart reads {LABEL.get(code, code).lower()}")
    mo = (technical or {}).get("momentum")
    if isinstance(mo, dict) and mo.get("known") and mo.get("momentum") in GATE_BAD_MOMENTUM:
        out.append(f"momentum is {mo['momentum']}")
    sec = price_status.get("second")
    if isinstance(sec, dict) and sec.get("signal") == "sell":
        out.append(f"{sec.get('source', 'the second opinion')} says SELL")
    pc = price_status.get("pricecheck")
    if isinstance(pc, dict) and not pc.get("unavailable") and pc.get("agrees") is False:
        out.append("the price data from another source disagrees")
    return out


def blocks_buy(price_status: dict | None, technical: dict | None = None) -> bool:
    """True when a buy or add should not show: a CONFIRMED breakdown (a completed close below support), or, with the
    entry gates on, any `entry_blockers` reason. Always on: it sells nothing, it only stops the app saying 'buy more'
    next to bad evidence. Unknown or missing status never blocks anything."""
    if not isinstance(price_status, dict):
        return False
    return price_status.get("code") in EXIT_CODES or bool(entry_blockers(price_status, technical))


BEARISH = ("weakening", "testing_support", "breakdown", "deep_breakdown")


def second_opinion(code: str | None, raw: dict | None, close: float | None = None) -> dict | None:
    """Compare another source's technical read with our status. Display only: it never changes a status, call or
    alert. `raw` is finnhub.second_opinion(); None or an empty read gives None (the screen says nothing, not a guess).
    Only a clear signal agrees or disagrees: a neutral or split read is 'mixed'."""
    if not isinstance(raw, dict) or code not in ORDER:
        return None
    sig = str(raw.get("signal") or "").lower()
    lv = sorted(float(x) for x in raw.get("levels") or [] if isinstance(x, (int, float)) and np.isfinite(x) and x > 0)
    out = {"source": raw.get("source") or "Finnhub", "signal": sig or None, "buy": raw.get("buy"), "neutral": raw.get("neutral"),
           "sell": raw.get("sell"), "trending": raw.get("trending"), "support": None, "resistance": None, "agrees": None}
    if close is not None and np.isfinite(close):
        below, above = [x for x in lv if x < close], [x for x in lv if x > close]
        out["support"] = below[-1] if below else None
        out["resistance"] = above[0] if above else None
    if sig not in ("buy", "sell", "neutral"):
        out["verdict"] = None
        out["agrees"] = None
        return out if (out["support"] or out["resistance"]) else None
    bearish = code in BEARISH
    if sig == "neutral":
        out["verdict"] = "mixed"
    elif (sig == "sell") == bearish:
        out["verdict"], out["agrees"] = "confirms", True
    else:
        out["verdict"], out["agrees"] = "disagrees", False
    return out


def second_unavailable(key_set: bool) -> dict:
    """Why there is no second opinion, so the screen says it instead of staying silent."""
    return {"source": "TradingView / Finnhub",
            "unavailable": "TradingView answered nothing for this stock" + (
                ", and Finnhub's technical endpoints may need a paid plan" if key_set else ", and no FINNHUB_API_KEY is set")}


def rank(code: str | None) -> int | None:
    """Position in ORDER (higher is worse), or None for unknown."""
    return ORDER.index(code) if code in ORDER else None


def is_worse(new: str | None, old: str | None) -> bool:
    a, b = rank(new), rank(old)
    return a is not None and b is not None and a > b


def _unknown(why: str, **extra) -> dict:
    return {"code": "unknown", "label": LABEL["unknown"], "action": why, "why": why, "floor_known": False,
            "provisional": None, "levels": {}, **extra}


def _action(code: str, lv: dict, owned: bool = True) -> str:
    lo, hi = lv.get("support_low"), lv.get("support_high")
    if not owned:       # a watchlist name: nothing to hold or exit, so say what the level means for a buy
        if code in EXIT_CODES:
            return "Support is broken. Not a buy until it recovers."
        if code == "testing_support":
            return f"Sitting on support ({lo:.2f} to {hi:.2f}). A close below {lo:.2f} breaks it."
        return "Not owned: nothing to exit."
    if code in EXIT_CODES and not EXIT_ON_BREAKDOWN:      # a fact about the price, not an instruction
        level, what = (lv["exit_below"], "support") if code == "breakdown" else (lv["deep_below"], "the deeper level")
        return f"Closed below {what} ({level:.2f}). Automatic level, not reviewed: check the chart before acting."
    if code == "record_high":
        return "Hold. Trail your stop under the recent lows."
    if code == "strong_uptrend":
        return "Hold."
    if code == "pullback":
        return "Hold and watch." + (f" Support starts at {hi:.2f}." if hi else "")
    if code == "weakening":
        return "Tighten the stop." + (f" A close below {lo:.2f} is the exit." if lo else "")
    if code == "testing_support":
        return f"Heads-up: sitting on support ({lo:.2f} to {hi:.2f}). Protect the trade. A close below {lo:.2f} is the exit."
    if code == "breakdown":
        return f"Exit the trade: closed below support ({lo:.2f})."
    return f"Exit now: closed below the deeper level ({lv['deep_below']:.2f})."


def assess(hist, now: datetime | None = None, quote_price: float | None = None, owned: bool = True) -> dict:
    """The status for one stock. hist: daily OHLCV bars (the app's cached history, which may end in a partial
    bar). now: timezone-aware clock for the freshness check. quote_price: a CURRENT live price, only ever used
    for the provisional note. owned: False for a watchlist name, which only changes the wording of `action`."""
    now = now or datetime.now(timezone.utc)
    # Quality-check and use only the recent window (all the averages and support levels need), so one bad bar years
    # ago can't blank the status; the record high below still looks at every completed close we hold.
    recent = hist.iloc[-WINDOW:] if hist is not None and len(hist) else hist
    done, note, last_session = decision.current_bars(recent, now)
    if done is None:
        return _unknown(f"Price history unusable: {note}.")
    if len(done) < MIN_SESSIONS:
        return _unknown(f"Only {len(done)} daily bars; the 200-day average needs {MIN_SESSIONS}.")
    ind = technical.indicators(done)
    close = float(done["Close"].iloc[-1])
    sma50, sma200 = float(ind["SMA50"].iloc[-1]), float(ind["SMA200"].iloc[-1])
    if not (np.isfinite(sma50) and np.isfinite(sma200)):
        return _unknown("The 50- and 200-day averages couldn't be computed.")
    closes = features.completed(hist, done.index[-1].date())["Close"].astype(float)
    closes = closes[np.isfinite(closes) & (closes > 0)]
    high = float(closes.max())
    drawdown = close / high - 1
    levels = {"high": round(high, 2), "drawdown": round(drawdown, 4), "sma50": round(sma50, 2),
              "sma200": round(sma200, 2), "as_of": last_session, "close": round(close, 2),
              "years_of_data": round(len(closes) / 252, 1)}

    pk, diag = None, {}
    try:
        pk, diag = candidates.extract(done.iloc[-400:], "STATUS", "provider")
    except (ValueError, KeyError, level_packet.PacketError) as e:   # a malformed candidate is "no floor", not a crash
        diag = {"why": f"support levels couldn't be built: {e}"}
    floor_known = pk is not None
    down = None
    if floor_known:
        dn = pk["downside"]
        down = {"zone": dn["zone"], "warning": dn["warning"], "failure": dn["failure"],
                "major_damage": dn["major_damage"]}
        levels.update(support_low=dn["zone"]["low"], support_high=dn["zone"]["high"], exit_below=dn["warning"],
                      failure=dn["failure"], deep_below=dn["major_damage"])
        above = [c["zone"] for c in (pk.get("upside") or {}).get("ceilings") or [] if c["zone"]["low"] > close]
        if above:       # the nearest automatic ceiling over the close: the number to watch on the way up
            near = min(above, key=lambda z: z["low"])
            levels.update(resist_low=near["low"], resist_high=near["high"])

    why_floor = "" if floor_known else (f" Support levels unavailable ({diag.get('why', 'unknown reason')}), "
                                        "so a breakdown can't be confirmed.")
    floor_state = state.downside_state(close, down) if floor_known else None
    if floor_state in FROM_FLOOR:
        code = FROM_FLOOR[floor_state]
        why = {"testing_support": "The close is inside the support zone.",
               "breakdown": "The close is below the support zone.",
               "deep_breakdown": "The close is below the deeper level."}[code]
        if drawdown < -STRONG_NEAR:
            why += f" It is already {-drawdown:.0%} below its high."
    elif close >= high * (1 - RECORD_TOL):
        code, why = "record_high", f"The close is the highest in {levels['years_of_data']:g} years of data."
    elif close < sma50 or close < sma200 or drawdown < -PULLBACK_MAX:
        code = "weakening"
        bits = [b for b, hit in (("below the 50-day average", close < sma50),
                                 ("below the 200-day average", close < sma200),
                                 (f"{-drawdown:.0%} below the high", drawdown < -PULLBACK_MAX)) if hit]
        why = "The close is " + " and ".join(bits) + "."
    elif drawdown >= -STRONG_NEAR:
        code, why = "strong_uptrend", f"Within {STRONG_NEAR:.0%} of the high and above both averages."
    else:
        code, why = "pullback", f"{-drawdown:.0%} below the high, above both averages."

    provisional = None
    if floor_known and quote_price is not None and np.isfinite(quote_price):
        q_state = state.downside_state(float(quote_price), down)
        q_code = FROM_FLOOR.get(q_state)
        if q_code and is_worse(q_code, code):
            provisional = {"code": q_code, "label": LABEL[q_code], "price": round(float(quote_price), 2),
                           "note": f"The live price {quote_price:.2f} reads {LABEL[q_code]}. "
                                   "It is confirmed only if a session closes there."}
    return {"code": code, "label": LABEL[code], "action": _action(code, levels, owned), "why": why + why_floor,
            "floor_known": floor_known, "provisional": provisional, "levels": levels}
