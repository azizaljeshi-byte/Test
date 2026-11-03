"""One technical-first call per stock (SHADOW MODE: shown beside the old labels, drives nothing).

Fixed order, first match wins:
  1 data      history unusable or no exit line -> UNKNOWN, with the reason (never a guess, never 0)
  2 exit      the close is under the exit line (status support-zone low) by more than BAND_ATRS of a normal daily swing
              -> EXIT (held) / AVOID (not held). Inside the band (under the line, above line minus the band) -> ON THE LINE:
              no new buy, no sell yet. The hard line still sizes the position.
  3 entry     close within ENTRY_ATRS normal daily swings of the exit line, the fall has stopped (an up day and RSI
              rising), and earnings are not within EARNINGS_DAYS -> BUY (not held) / ADD (held)
  4 near      close within that distance but not turned yet -> WAIT FOR TURN
  5 otherwise HOLD (held) / WAIT (not held)
Position size over the limit is a note (`over_limit`), not a call: the owner has not decided that yet.
Volume building and a big gap up are flags only (not proven in the back-tests).
Fundamentals never change the call. They only set the risk grade (Safe .. Extreme), which sizes the position.
Timeframe is a rough estimate from the distance to the next ceiling in normal daily swings (random-walk scaling).
Display only: no score, signal, verdict, plan, alert or paper rule reads this.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from . import status, technical
from .cis import decision

ENTRY_ATRS = 1.5
BAND_ATRS = 0.5               # half a normal daily swing under the exit line
EARNINGS_DAYS = 2
RISK_PER_TRADE = 0.01          # an exit-line hit should cost about 1% of the account
VOLUME_BUILD = 1.3             # last 5 sessions' volume vs the 20-day average
GAP_UP = 0.04
GRADES = ("Safe", "Moderate", "High", "Extreme")


def _unknown(why: str) -> dict:
    return {"known": False, "call": "UNKNOWN", "why": why, "exit_line": None, "flags": [], "risk": None,
            "timeframe": None, "size": None, "over_limit": False}


def risk_grade(atr_pct: float, earnings_days: int | None = None, fundamentals: float | None = None,
               drawdown: float | None = None) -> dict:
    """Safe .. Extreme from how wild the stock is plus fundamentals; it only sizes the trade, never blocks it."""
    pts, bits = 0, []
    if atr_pct >= 0.06:
        pts += 3; bits.append(f"moves {atr_pct:.0%} on a normal day")
    elif atr_pct >= 0.04:
        pts += 2; bits.append(f"moves {atr_pct:.0%} on a normal day")
    elif atr_pct >= 0.025:
        pts += 1
    if earnings_days is not None and 0 <= earnings_days <= 7:
        pts += 1; bits.append(f"earnings in {earnings_days} days")
    if fundamentals is None:
        bits.append("fundamentals unknown")
    elif fundamentals < 40:
        pts += 2; bits.append("weak fundamentals")
    elif fundamentals < 55:
        pts += 1; bits.append("middling fundamentals")
    if drawdown is not None and drawdown < -0.30:
        pts += 1; bits.append(f"{-drawdown:.0%} below its high")
    grade = GRADES[0 if pts <= 1 else 1 if pts <= 3 else 2 if pts <= 5 else 3]
    return {"grade": grade, "why": "; ".join(bits) or "calm and sound", "points": pts}


def timeframe(distance_atrs: float | None) -> dict | None:
    """Days for a move of `distance_atrs` normal daily swings (they grow with the square root of time)."""
    if distance_atrs is None or not np.isfinite(distance_atrs) or distance_atrs <= 0:
        return None
    days = max(1, round(distance_atrs ** 2))
    word = "SHORT" if days <= 2 else "MEDIUM" if days <= 10 else "SWING"
    text = {"SHORT": "1 to 2 days", "MEDIUM": "1 to 2 weeks", "SWING": "several weeks"}[word]
    return {"word": word, "days": int(days), "text": text}


def assess(hist, now: datetime | None = None, owned: bool = False, position_pct: float | None = None,
           position_limit: float | None = None, earnings_days: int | None = None,
           fundamentals: float | None = None, account: float | None = None, quote_price: float | None = None,
           st: dict | None = None) -> dict:
    """`st` is a status.assess result the caller already has (the engine passes its own, so the support levels are
    not built twice per stock per sweep)."""
    now = now or datetime.now(timezone.utc)
    st = st if isinstance(st, dict) else status.assess(hist, now=now, quote_price=quote_price, owned=owned)
    if st.get("code") == "unknown" or not st.get("levels"):
        return _unknown(st.get("why") or "price history unusable")
    lv = st["levels"]
    line = lv.get("exit_below")
    if not st.get("floor_known") or line is None:
        return _unknown("No exit line could be built, so no call.")
    done, _note, _last = decision.current_bars(hist.iloc[-420:], now)   # the same completed bars the status used
    ind = technical.indicators(done)
    close = float(ind["Close"].iloc[-1])
    atr = float(ind["ATR"].iloc[-1])
    if not np.isfinite(atr) or atr <= 0:
        return _unknown("Normal daily swing could not be measured.")
    rsi, prev_rsi = float(ind["RSI"].iloc[-1]), float(ind["RSI"].iloc[-2])
    up_day = close > float(ind["Close"].iloc[-2])
    turned = bool(up_day and rsi > prev_rsi)
    dist = (close - line) / atr
    flags = []
    vol5, vol20 = float(ind["Volume"].iloc[-5:].mean()), float(ind["VolAvg20"].iloc[-1])
    if np.isfinite(vol20) and vol20 > 0 and vol5 / vol20 >= VOLUME_BUILD:
        flags.append("volume building (a flag only, not proven)")
    prev_close = float(ind["Close"].iloc[-2])
    if prev_close > 0 and float(ind["Open"].iloc[-1]) / prev_close - 1 >= GAP_UP:
        flags.append("big gap up (a flag only: chasing it is not proven)")
    near_earn = earnings_days is not None and 0 <= earnings_days <= EARNINGS_DAYS
    if near_earn:
        flags.append(f"earnings in {earnings_days} day(s)")

    band = line - BAND_ATRS * atr
    if band <= close < line:
        call = "ON THE LINE"
        why = f"The close {close:.2f} is under the exit line {line:.2f} but inside the band (down to {band:.2f}). No new buy, no sell yet."
    elif close < band:
        call = "EXIT" if owned else "AVOID"
        why = f"The close {close:.2f} is under the exit line {line:.2f} and below the band ({band:.2f})."
    elif dist <= ENTRY_ATRS and turned and not near_earn:
        call = "ADD" if owned else "BUY"
        why = f"Close to the exit line ({dist:.1f} normal swings above {line:.2f}) and turning up."
    elif dist <= ENTRY_ATRS:
        call = "WAIT FOR TURN"
        why = ("Close to the exit line but earnings are too near." if near_earn and turned
               else f"Close to the exit line ({dist:.1f} normal swings above {line:.2f}) but still falling or flat.")
    else:
        call = "HOLD" if owned else "WAIT"
        why = f"{dist:.1f} normal swings above the exit line {line:.2f}: not a low-risk entry."
    up = lv.get("resist_low")
    tf = timeframe((up - close) / atr) if up and up > close else timeframe(2 * max(dist, 1.0))
    risk = risk_grade(atr / close, earnings_days, fundamentals, lv.get("drawdown"))
    size = None
    if account and close > line:
        loss_per_share = close - line
        size = {"shares": int(account * RISK_PER_TRADE * (0.5 if risk["grade"] in ("High", "Extreme") else 1)
                              / loss_per_share), "cost_if_exit": loss_per_share}
    over = bool(owned and position_pct is not None and position_limit and position_pct > position_limit)
    return {"known": True, "call": call, "why": why, "exit_line": round(line, 2), "band_line": round(band, 2), "close": round(close, 2), "distance_swings": round(dist, 2),
            "flags": flags, "risk": risk, "timeframe": tf if call in ("BUY", "ADD", "WAIT FOR TURN") else None,
            "size": size, "over_limit": over, "as_of": lv.get("as_of")}


LOG_COLS = ["day", "ticker", "call", "close", "exit_line", "band_line", "swings_above_line", "held"]
_logged: set = set()


def log_call(ticker: str, oc: dict, owned: bool, folder=None) -> bool:
    """One row per stock per session in `New call log.csv` (hard line and band side by side), so the two exit rules can
    be compared on the whole list later. Never raises; returns whether a row was written."""
    import csv
    from pathlib import Path
    try:
        if not oc or not oc.get("known") or not oc.get("as_of"):
            return False
        key = (ticker, oc["as_of"])
        if key in _logged:
            return False
        from . import quick
        folder = Path(folder) if folder else quick.log_dir().parent / "New call log"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "New call log.csv"
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(LOG_COLS)
            w.writerow([oc["as_of"], ticker, oc["call"], oc["close"], oc["exit_line"], oc["band_line"],
                        oc["distance_swings"], "yes" if owned else "no"])
        _logged.add(key)
        return True
    except Exception:
        return False
