"""One decision per stock, from a fixed rule order, for the PAPER trading test only (owner, 2026-10-25). It changes no card,
score, call, plan or alert, and trades nothing real: `paper.py` applies it to a fake account.

Rule order, the first rule that fires decides:
  1. hard stop      the plan's stop. A gap far through it (`gap_atr` times the normal daily range) sells all at once. Any other
                    breach must still be there after `hold_min` minutes and after the first `blackout_min` of the session.
  2. warning exit   a price below the chart's support floor. Judged at the decision time (15:45 New York, 15 minutes before
                    the close), never earlier: during the day it only raises an alert. Sells half (or all if `half_on_warning`
                    is off).
  3. target         the first target sells a third and moves the stop up to the entry, unless the trend is strong. Then it stretches
                    (owner, 2026-10-25): nothing is sold, the stop trails up under the latest chart floor (never below the
                    entry), and it sells all once the trend has turned for `hold_min` minutes, or a third at `stretch_cap_r` times
                    the first risk. A weak or mixed trend at the target sells a third as before.
  4. entry          only with no position: the plan is a buy, no entry gate blocks it (`status.entry_blockers`), earnings are
                    not within `earnings_block_days`, the session is past the opening blackout, and the price is in the entry zone.
  5. otherwise      hold, or nothing.
Missing data never trades: a missing price or level gives "nothing", with the reason.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from . import ui

OPEN, CLOSE, DECIDE = time(9, 30), time(16, 0), time(15, 45)


@dataclass(frozen=True)
class Config:
    blackout_min: int = 60          # no selling and no entry in the first hour of the session
    hold_min: int = 30              # a hard-stop breach must last this long before it sells
    gap_atr: float = 2.0            # a gap this many daily ranges below the stop sells at once
    half_on_warning: bool = True    # the warning exit sells half; False sells all
    earnings_block_days: int = 2
    target_fraction: float = 1 / 3  # sold at the first target
    stretch: bool = True            # a strong trend at the first target is not sold: it is trailed
    stretch_cap_r: float = 3.0      # profit, in times the first risk, at which a stretched trade sells a third anyway


def minutes_into_session(now: datetime) -> float | None:
    """Minutes since 9:30 New York, or None outside the regular session. `now` must be New York time."""
    t = now.time()
    if now.weekday() >= 5 or not (OPEN <= t < CLOSE):
        return None
    return (now.hour * 60 + now.minute + now.second / 60) - (OPEN.hour * 60 + OPEN.minute)


def _num(v) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def _d(action: str, reason: str, fraction: float = 0.0, **extra) -> dict:
    return {"action": action, "fraction": fraction, "reason": reason, **extra}


def trend(ps: dict | None, technical: dict | None) -> str:
    """strong (momentum strong or building and the chart sound), turned (momentum falling, weak or fading, or the chart
    weakening or testing support), else mixed. Missing reads are mixed, never turned."""
    from . import status
    mo = (technical or {}).get("momentum")
    mom = mo.get("momentum") if isinstance(mo, dict) and mo.get("known") else None
    code = (ps or {}).get("code")
    if mom in status.GATE_BAD_MOMENTUM or code in status.GATE_BAD_CHART:
        return "turned"
    return "strong" if mom in ("strong", "building") else "mixed"


def _trail(stop: float, entry: float, support: float | None, price: float) -> float:
    """The stop only moves up, never below the entry, and never to a floor that is not below the price."""
    new = max(stop, entry)
    return max(new, support) if support is not None and support < price else new


def decide(snap: dict, position: dict | None, price: float | None, now: datetime, cfg: Config = Config()) -> dict:
    """{action: ENTER | SELL_ALL | SELL_PART | ALERT | HOLD | NONE, fraction, reason, ...}.
    `position` is None or {shares, entry, stop, stage, t1_done, below_since}; `now` is New York time."""
    p = snap["payload"]
    plan = p.get("plan") or {}
    mins = minutes_into_session(now)
    if _num(price) is None or price <= 0:
        return _d("NONE", "no price")
    if mins is None:
        return _d("HOLD" if position else "NONE", "market closed")
    ps = ui.price_status(snap) or {}
    support = _num((ps.get("levels") or {}).get("support_low"))
    atr = _num((p.get("technical") or {}).get("atr"))

    if position:
        stop = _num(position.get("stop")) or _num(plan.get("stop"))
        if stop is not None and price <= stop:
            far = atr is not None and (stop - price) >= cfg.gap_atr * atr
            if far:
                return _d("SELL_ALL", f"gap far through the stop {stop:.2f}", 1.0, rule="hard stop")
            since = position.get("below_since")
            if since is None:
                return _d("ALERT", f"below the stop {stop:.2f}: confirming for {cfg.hold_min} minutes", rule="hard stop", mark_below=True)
            held = (now - since).total_seconds() / 60
            if mins >= cfg.blackout_min and held >= cfg.hold_min:
                return _d("SELL_ALL", f"below the stop {stop:.2f} for {held:.0f} minutes", 1.0, rule="hard stop")
            return _d("ALERT", f"below the stop {stop:.2f} for {held:.0f} of {cfg.hold_min} minutes", rule="hard stop")
        recovered = {"clear_below": True} if position.get("below_since") else {}
        if support is not None and price < support and position.get("stage") != "half":
            if now.time() >= DECIDE:
                frac = 0.5 if cfg.half_on_warning else 1.0
                return _d("SELL_PART" if frac < 1 else "SELL_ALL", f"closing below the chart floor {support:.2f}", frac, rule="warning exit", **recovered)
            return _d("ALERT", f"below the chart floor {support:.2f}: decided at 3:45 pm", rule="warning exit", **recovered)
        tr = trend(ps, p.get("technical"))
        entry = _num(position.get("entry"))
        if position.get("stretch") and entry is not None:
            risk = entry - (_num(position.get("stop0")) or stop or entry)
            new_stop = _trail(stop or entry, entry, support, price)
            raise_stop = {"set_stop": round(new_stop, 2)} if stop is None or new_stop > stop else {}
            if risk > 0 and price >= entry + cfg.stretch_cap_r * risk:
                return _d("SELL_PART", f"stretch cap: profit reached {cfg.stretch_cap_r:g} times the first risk", cfg.target_fraction,
                          rule="stretch cap", end_stretch=True, move_stop_to_entry=True, **raise_stop, **recovered)
            if tr == "turned":
                since = position.get("weak_since")
                if since is None:
                    return _d("ALERT", "the trend turned while stretching: confirming", rule="stretch", mark_weak=True, **raise_stop, **recovered)
                held = (now - since).total_seconds() / 60
                if mins >= cfg.blackout_min and held >= cfg.hold_min:
                    return _d("SELL_ALL", f"the trend turned and stayed weak for {held:.0f} minutes", 1.0, rule="stretch exit")
                return _d("ALERT", f"the trend is weak for {held:.0f} of {cfg.hold_min} minutes", rule="stretch", **raise_stop, **recovered)
            clear = {"clear_weak": True} if position.get("weak_since") else {}
            return _d("HOLD", "stretching: the trend is still strong, the stop trails the chart floor" if tr == "strong"
                      else "stretching: the trend is mixed, the stop holds", rule="stretch", **raise_stop, **clear, **recovered)
        targets = plan.get("targets") or []
        t1 = _num((targets[0] or {}).get("price")) if targets else None
        if t1 is not None and price >= t1 and not position.get("t1_done"):
            if cfg.stretch and tr == "strong" and entry is not None:
                return _d("HOLD", f"first target {t1:.2f} reached with a strong trend: stretching instead of selling", rule="stretch",
                          start_stretch=True, set_stop=round(_trail(stop or entry, entry, support, price), 2), **recovered)
            return _d("SELL_PART", f"first target {t1:.2f} reached", cfg.target_fraction, rule="target", move_stop_to_entry=True, **recovered)
        return _d("HOLD", "no exit rule fired", **recovered)

    if mins < cfg.blackout_min:
        return _d("NONE", "first hour of the session: no entries")
    from . import status
    if (plan.get("status_exit") or "").startswith("don't buy yet"):
        return _d("NONE", plan["status_exit"], blocked=True, rule="entry gates")
    blockers = status.entry_blockers(ps, p.get("technical"))
    if blockers and plan.get("stance") in status.BUY_STANCES:
        return _d("NONE", "; ".join(blockers), blocked=True, rule="entry gates")
    call = ui.action(snap)[0]
    if call not in ("BUY NOW", "BUY ON DIP", "BUY ON BREAKOUT", "BUY MORE"):
        return _d("NONE", f"the plan says {call.lower()}")
    days = (p.get("events") or {}).get("days_to_earnings")
    if days is not None and days <= cfg.earnings_block_days:
        return _d("NONE", f"earnings in {days} day{'s' if days != 1 else ''}", rule="earnings")
    lo, hi = _num(plan.get("entry_low")), _num(plan.get("entry_high"))
    if lo is None or hi is None or not (lo <= price <= hi):
        return _d("NONE", "price is not in the entry zone")
    return _d("ENTER", f"every entry check agrees; zone {lo:.2f} to {hi:.2f}", rule="entry", limit=round(min(price, hi), 2))
