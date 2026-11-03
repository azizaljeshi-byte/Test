"""The trading agent (owner, 31 Oct): it reads the market, picks stocks, watches them and sends instructions to the Quick and New call
fake-money accounts. The accounts carry the instructions out inside the fixed limits in their own code; the agent cannot change them.

How it fits together
  * `tick(store_path)` runs on its OWN thread (an API call can take a minute; it must never hold up the tracker or the stops).
  * One API call per review (every 5 minutes in the first two hours of the regular session, then every 15, settable by env, one morning desk call before the open). The call carries the
    playbook (docs/PLAYBOOK.md), the market's breadth, a short list of candidate stocks with their data packs, the stocks already being
    watched and each account's open positions.
  * The answer is JSON: a market call and instructions (BUY_L1, BUY_L2, ADD, SELL, WAIT, DROP) with the stock's direction state
    (falling, basing, turning, riding), a reason and a confidence. `vet` throws out anything that breaks the code rules below.
  * Orders wait in the settings table (`agent_orders`). `orders_for(store, account, now)` hands each account its fresh orders; a first
    entry is only handed over once the stock has been on the watch list for MIN_WATCH_MIN minutes ("take time to evaluate").
  * Modes (STOCKWATCH_AGENT_MODE): off | shadow (reviews are logged, accounts keep their old rules) | drive (switched on by the owner; the accounts act on the
    agent's orders and their old rules only log what they would have bought). No key, a spent cap or an API error means no new
    entries in drive mode: missing data never trades. Exits and stops keep working.
  * Costs: every call's tokens are counted per day and capped (STOCKWATCH_AGENT_MAX_CALLS / _MAX_IN_TOKENS / _MAX_OUT_TOKENS).
The key is read from the environment (ANTHROPIC_API_KEY, from the owner's private settings file); it is never logged or stored."""
from __future__ import annotations

import json
import logging
import os
import statistics
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import quick, volpace
from .config import ROOT
from .data import NY, us_session

log = logging.getLogger("stockwatch.agent")

API_URL, API_VERSION = "https://api.anthropic.com/v1/messages", "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"
KEY_ORDERS, KEY_WATCH, KEY_JOURNAL, KEY_USAGE, KEY_STATE, KEY_DESK, KEY_SEEN = (
    "agent_orders", "agent_watch", "agent_journal", "agent_usage", "agent_state", "agent_desk", "agent_seen")
SETTLE_AFTER = 3                           # same verdict this many reviews in a row ...
SETTLE_MOVE_ATR = 0.5                      # ... and price within this many daily ranges of the last full look = settled, not sent again
SETTLE_MAX_MIN = 20                        # a settled stock gets a fresh full look after this long (owner, 2 Nov: stop repeating, hunt entries)
EARLY_MIN = 120                            # the first two hours of the session (09:30-11:30 New York) are reviewed often
EARLY_EVERY_S = 300                        # every 5 minutes in that early period
LATE_EVERY_S = 900                         # then every 15 minutes until the close (owner's start-up setting; tighten later)
DESK_FROM_MIN = -15                        # the morning desk runs from 15 minutes before the open (minutes after 9:30)
CANDIDATES = 14                            # stocks sent for review each time, besides open positions and the watch list
WATCH_KEEP_MIN = 90                        # a watched stock the agent has not mentioned for this long is dropped from the list
MIN_WATCH_MIN = {"quick": 15, "newcall": 30}   # a first entry waits until the stock has been watched this long (proposed, owner can change)
ORDER_TTL_MIN = 10                         # an order the account did not take within this long is dropped
MIN_CONFIDENCE = 3                         # an entry needs 3 or more of 5
ACTIONS = ("BUY_L1", "BUY_L2", "ADD", "SELL", "WAIT", "DROP")
STATES = ("falling", "basing", "turning", "riding")
ACCOUNTS = ("quick", "newcall")
JOURNAL_KEEP = 400
FAIL_PUSH_AFTER = 3                        # consecutive failures before the owner is told the agent is offline


# ------------------------------------------------------------------ settings and caps
def mode() -> str:
    """STOCKWATCH_AGENT_MODE: off | shadow | drive. Not set: shadow once a key is in the settings file (the agent watches and journals, the old rules trade), otherwise off (the old rules keep trading)."""
    m = (os.getenv("STOCKWATCH_AGENT_MODE") or "").strip().lower()
    if m in ("off", "shadow", "drive"):
        return m
    return "shadow" if has_key() else "off"


def has_key() -> bool:
    return bool((os.getenv("ANTHROPIC_API_KEY") or "").strip())


def paused() -> bool:
    """A file named data/agent_pause.txt switches the agent off without touching the settings file (owner, 2 Nov: stop it, revisit later). Delete the file to bring it back."""
    try:
        return (ROOT / "data" / "agent_pause.txt").exists()
    except OSError:
        return False


def active() -> bool:
    return mode() != "off" and has_key() and not paused()


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name) or default))
    except ValueError:
        return default


def caps() -> dict:
    return {"calls": _int_env("STOCKWATCH_AGENT_MAX_CALLS", 200), "in": _int_env("STOCKWATCH_AGENT_MAX_IN_TOKENS", 2_500_000),
            "out": _int_env("STOCKWATCH_AGENT_MAX_OUT_TOKENS", 250_000), "usd": _int_env("STOCKWATCH_AGENT_MAX_USD", 5)}


def cadence() -> tuple[int, int, int]:
    """(minutes of the early period, seconds between reviews in it, seconds between reviews after it). Env: STOCKWATCH_AGENT_EARLY_MIN / _EARLY_EVERY_S / _LATE_EVERY_S."""
    return (_int_env("STOCKWATCH_AGENT_EARLY_MIN", EARLY_MIN), _int_env("STOCKWATCH_AGENT_EARLY_EVERY_S", EARLY_EVERY_S),
            _int_env("STOCKWATCH_AGENT_LATE_EVERY_S", LATE_EVERY_S))


def price_per_mtok(model: str | None = None) -> dict:
    """USD per million tokens (list prices, 31 Oct 2026): input, cache write (5 min), cache read, output. Unknown models are priced like Opus, to stay on the safe side."""
    m = (model or os.getenv("STOCKWATCH_AGENT_MODEL") or DEFAULT_MODEL).lower()
    if "haiku" in m:
        return {"in": 0.10, "write": 0.125, "read": 0.01, "out": 0.50}
    if "sonnet" in m:
        return {"in": 2.0, "write": 2.5, "read": 0.10, "out": 10.0}
    if "fable" in m or "mythos" in m:
        return {"in": 10.0, "write": 12.5, "read": 0.25, "out": 50.0}
    return {"in": 4.0, "write": 5.0, "read": 0.20, "out": 20.0}


def _jget(store, key: str, default):
    try:
        v = json.loads(store.get_setting(key) or "null")
    except ValueError:
        return default
    return default if v is None else v


def _jset(store, key: str, value) -> None:
    store.set_setting(key, json.dumps(value, default=str))


def usage_today(store, now: datetime) -> dict:
    u = _jget(store, KEY_USAGE, {})
    day = now.date().isoformat()
    return u if isinstance(u, dict) and u.get("day") == day else {"day": day, "calls": 0, "in": 0, "out": 0, "cached": 0, "usd": 0.0}


def within_caps(store, now: datetime) -> str:
    """'' or why the agent may not call the API now."""
    u, c = usage_today(store, now), caps()
    if u["calls"] >= c["calls"]:
        return f"daily call cap reached ({c['calls']})"
    if u["in"] >= c["in"] or u["out"] >= c["out"]:
        return "daily token cap reached"
    if float(u.get("usd") or 0) >= c["usd"]:
        return f"daily spending cap reached (${c['usd']})"
    return ""


def _add_usage(store, now: datetime, usage: dict) -> None:
    u = usage_today(store, now)
    u["calls"] += 1
    u["in"] += int(usage.get("input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0)
    u["cached"] += int(usage.get("cache_read_input_tokens") or 0)
    u["out"] += int(usage.get("output_tokens") or 0)
    p = price_per_mtok()
    u["usd"] = round(float(u.get("usd") or 0) + (int(usage.get("input_tokens") or 0) * p["in"] + int(usage.get("cache_creation_input_tokens") or 0) * p["write"]
                                                 + int(usage.get("cache_read_input_tokens") or 0) * p["read"] + int(usage.get("output_tokens") or 0) * p["out"]) / 1e6, 4)
    _jset(store, KEY_USAGE, u)


# ------------------------------------------------------------------ the API
class AgentError(Exception):
    pass


_last_call: dict = {"stop": ""}          # why the last answer ended ("max_tokens" = it was cut off)


def call_api(system: str, user: str, max_tokens: int = 6000, timeout: int = 120) -> tuple[str, dict]:
    """One Anthropic messages call. Returns (text, usage). The key never appears in an error message."""
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise AgentError("no ANTHROPIC_API_KEY in the settings file")
    body = {"model": (os.getenv("STOCKWATCH_AGENT_MODEL") or DEFAULT_MODEL).strip(), "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}]}
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise AgentError(f"API HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise AgentError(f"API unreachable: {type(e).__name__}") from None
    text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
    _last_call["stop"] = str(data.get("stop_reason") or "")
    return text, data.get("usage") or {}


def playbook_text() -> str:
    f = Path(__file__).resolve().parent.parent / "docs" / "PLAYBOOK.md"
    try:
        return f.read_text(encoding="utf-8")
    except OSError:
        return ""


CONTRACT = """
OUTPUT: reply with one JSON object and nothing else.
{"market": {"call": "bounce day|trend day|falling-knife day|mixed", "note": "one sentence"},
 "instructions": [{"account": "quick|newcall", "ticker": "XYZ", "action": "BUY_L1|BUY_L2|ADD|SELL|WAIT|DROP",
   "state": "falling|basing|turning|riding", "reason": "one short line, at most 25 words, naming what you saw", "confidence": 1-5}]}
Stocks in "settled_not_resent" got the same verdict several reviews running and have not moved: do not answer for them; spend the effort on finding entries among the others. Rules for the answer: use only tickers given in the data; BUY_L1 only when state is turning or riding; BUY_L2 or ADD only for a stock the
account already holds and only when state is riding; SELL only for a stock the account holds; WAIT keeps a stock on the watch list;
DROP removes it. Missing or unclear data means WAIT. Never invent prices or news. At most 12 instructions.
"""



# ------------------------------------------------------------------ intraday features: opening range, VWAP, volume against the clock
def _download_5m(names: list[str]):
    """One bulk download of 5-minute bars (about 5 sessions) for the names under review. Goes through the Yahoo throttle."""
    from . import data

    @data._yahoo
    def go():
        import yfinance as yf
        return yf.download(list(names), period="5d", interval="5m", prepost=False, group_by="ticker", threads=True, progress=False, auto_adjust=False)
    return go()


def _bars_of(df, t: str, many: bool = True):
    sub = df[t] if getattr(df.columns, "nlevels", 1) > 1 else df
    sub = sub[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
    if sub.empty:
        return None
    idx = sub.index
    sub.index = idx.tz_localize("UTC").tz_convert(NY) if idx.tz is None else idx.tz_convert(NY)
    return sub


def _wilder(x, n: int):
    """Wilder smoothing, the standard way: the first value is the simple average of the first n readings, then
    (previous * (n - 1) + new) / n. Leading NaN readings are skipped; values before the seed are NaN."""
    import numpy as np
    import pandas as pd
    v = x.to_numpy(dtype=float)
    out = np.full(len(v), np.nan)
    valid = np.flatnonzero(~np.isnan(v))
    if len(valid) < n:
        return pd.Series(out, index=x.index)
    start = valid[0] + n - 1
    out[start] = v[valid[0]:start + 1].mean()
    for i in range(start + 1, len(v)):
        out[i] = (out[i - 1] * (n - 1) + v[i]) / n if not np.isnan(v[i]) else out[i - 1]
    return pd.Series(out, index=x.index)


def indicator_block(closed) -> dict:
    """EMA 8/20, RSI(14) and ADX(14) on COMPLETED regular-session 5-minute bars (this session plus the earlier sessions in the
    download, for warm-up; the overnight gap is not removed). A value without enough bars is None (unknown), never 0.
    Context only: a crossover or a level is not an entry."""
    import pandas as pd
    c, h, lo = closed["Close"].astype(float), closed["High"].astype(float), closed["Low"].astype(float)
    n = len(c)
    out: dict = {"ema8": None, "ema20": None, "ema8_above_ema20": None, "ema20_slope_pct_3bars": None, "rsi14": None, "adx14": None}
    if n >= 20:
        e8, e20 = c.ewm(span=8, adjust=False).mean(), c.ewm(span=20, adjust=False).mean()
        out["ema8"], out["ema20"] = _r(e8.iloc[-1]), _r(e20.iloc[-1])
        out["ema8_above_ema20"] = bool(e8.iloc[-1] > e20.iloc[-1])
        if n >= 23 and e20.iloc[-4]:
            out["ema20_slope_pct_3bars"] = _r((e20.iloc[-1] / e20.iloc[-4] - 1) * 100, 3)
    if n >= 15:
        d = c.diff()
        up, dn = _wilder(d.clip(lower=0), 14), _wilder((-d).clip(lower=0), 14)
        last_up, last_dn = float(up.iloc[-1]), float(dn.iloc[-1])
        if last_up == last_up and last_dn == last_dn:
            out["rsi14"] = _r(100.0 if last_dn == 0 and last_up > 0 else 50.0 if last_dn == 0 else 100 - 100 / (1 + last_up / last_dn), 1)
    if n >= 29:
        upm, dnm = h.diff(), -lo.diff()
        pdm = upm.where((upm > dnm) & (upm > 0), 0.0)
        mdm = dnm.where((dnm > upm) & (dnm > 0), 0.0)
        tr = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
        atr = _wilder(tr, 14)
        pdi, mdi = 100 * _wilder(pdm, 14) / atr, 100 * _wilder(mdm, 14) / atr
        dx = (100 * (pdi - mdi).abs() / (pdi + mdi)).where((pdi + mdi) > 0)
        adx = _wilder(dx.dropna(), 14)
        if len(adx) and adx.iloc[-1] == adx.iloc[-1]:
            out["adx14"] = _r(adx.iloc[-1], 1)
    return out


def features_for(bars, now: datetime, last_n: int = 12) -> dict | None:
    """Opening range (frozen after 09:45), session VWAP, VWAP crossings and volume against the same time of day, from COMPLETED 5-minute bars.
    None when there are no bars for today. Nothing here looks past `now`."""
    if bars is None or not len(bars):
        return None
    now = now.astimezone(NY)
    day = now.strftime("%Y-%m-%d")
    hhmm = bars.index.strftime("%H:%M")
    inside = (hhmm >= "09:30") & (hhmm < "16:00")
    done = bars.index + timedelta(minutes=5) <= now                       # a bar counts only once it has closed
    today = bars[(bars.index.strftime("%Y-%m-%d") == day) & inside & done]
    if today.empty:
        return None
    prior_days = sorted({d for d in bars.index.strftime("%Y-%m-%d") if d < day})
    slot: dict[str, list[float]] = {}
    for d in prior_days:
        pb = bars[(bars.index.strftime("%Y-%m-%d") == d) & inside]
        for i, v in zip(pb.index.strftime("%H:%M"), pb["Volume"]):
            slot.setdefault(i, []).append(float(v))
    typical = (today["High"] + today["Low"] + today["Close"]) / 3
    cumv = today["Volume"].cumsum()
    vwap = (typical * today["Volume"]).cumsum() / cumv.where(cumv > 0)
    rows = []
    for (i, r), vw in zip(today.iterrows(), vwap):
        key = i.strftime("%H:%M")
        base = slot.get(key)
        vs = round(float(r.Volume) / (sum(base) / len(base)), 2) if base and sum(base) > 0 else None
        rows.append([key, _r(r.Open), _r(r.High), _r(r.Low), _r(r.Close), round(float(r.Volume) / 1000), _r(vw), vs])
    out: dict = {"bars_so_far": len(today), "last_bars": rows[-last_n:]}
    first = today[today.index.strftime("%H:%M") < "09:45"]
    if len(first) >= 3:
        out["opening_range"] = {"high": _r(first.High.max()), "low": _r(first.Low.min()), "frozen": True}
        later = today[today.index.strftime("%H:%M") >= "09:45"]
        out["closes_above_range_high"] = int((later.Close > first.High.max()).sum())
        out["closes_below_range_low"] = int((later.Close < first.Low.min()).sum())
    else:
        out["opening_range"] = None                                        # not frozen yet: nothing opening-range may be traded
    last_vwap, last_close = float(vwap.iloc[-1]), float(today.Close.iloc[-1])
    out["vwap"] = _r(last_vwap)
    out["close_vs_vwap_pct"] = _r((last_close / last_vwap - 1) * 100) if last_vwap else None
    side = (today.Close.tail(last_n + 1) > vwap.tail(last_n + 1)).astype(int)
    out["vwap_crossings_last_12"] = int((side.diff().abs() == 1).sum())
    out["bars_above_vwap_last_12"] = int(side.tail(last_n).sum())
    cum_now = float(cumv.iloc[-1])
    last_key = today.index[-1].strftime("%H:%M")
    ref = []
    for d in prior_days:
        pb = bars[(bars.index.strftime("%Y-%m-%d") == d) & inside & (bars.index.strftime("%H:%M") <= last_key)]
        if len(pb):
            ref.append(float(pb["Volume"].sum()))
    out["cum_volume_vs_same_time"] = round(cum_now / (sum(ref) / len(ref)), 2) if ref and sum(ref) > 0 else None
    if _int_env("STOCKWATCH_AGENT_INDICATORS", 0):                          # OFF by default (owner, 1 Nov): EMA 8/20, RSI, ADX only once he decides
        done_all = bars[inside & done]
        done_all = done_all[done_all.index <= today.index[-1]]
        try:
            out["indicators"] = indicator_block(done_all)
        except Exception:
            log.warning("indicator block failed")
            out["indicators"] = None
    return out


def intraday_features(names: list[str], now: datetime, fetch=None) -> dict:
    """{ticker: features or None}. Never raises: a failed download means the fields are simply absent (unknown)."""
    if not names:
        return {}
    try:
        df = (fetch or _download_5m)(list(names))
        many = len(names) > 1
        out = {}
        for t in names:
            try:
                out[t] = features_for(_bars_of(df, t, many), now)
            except Exception:
                out[t] = None
        return out
    except Exception:
        log.warning("intraday features unavailable")
        return {}


# ------------------------------------------------------------------ the data pack
def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def _r(v, n=2):
    v = _num(v)
    return None if v is None else round(float(v), n)


def _zone_near(zones: dict | None, price: float) -> dict:
    out = {}
    if not isinstance(zones, dict) or not zones.get("known"):
        return out
    sup = [z for z in zones.get("support") or [] if _num(z.get("high")) is not None and z["high"] <= price * 1.005]
    res = [z for z in zones.get("resistance") or [] if _num(z.get("low")) is not None and z["low"] >= price * 0.995]
    if sup:
        z = max(sup, key=lambda z: z["high"])
        out["support"] = {"price": _r((z["low"] + z["high"]) / 2), "grade": z.get("grade"), "touches": z.get("touches")}
    if res:
        z = min(res, key=lambda z: z["low"])
        out["resistance"] = {"price": _r((z["low"] + z["high"]) / 2), "grade": z.get("grade"), "touches": z.get("touches")}
    return out


def path_points(m: dict | None, n: int = 24) -> list:
    """The day's samples as percent from the open, thinned to about n points: [[minutes since the first sample, % from open], ...]."""
    if not m or not m.get("s") or not _num(m.get("open")):
        return []
    s, o = m["s"], m["open"]
    step = max(1, len(s) // n)
    t0 = s[0][0]
    pts = [[round((t - t0) / 60, 1), round((px / o - 1) * 100, 2)] for t, px in s[::step]]
    last = [round((s[-1][0] - t0) / 60, 1), round((s[-1][1] / o - 1) * 100, 2)]
    return pts if pts and pts[-1] == last else pts + [last]


def pack(snap: dict, m: dict | None, mins: float | None, price: float) -> dict:
    p = snap.get("payload") or {}
    t, q, ev = p.get("technical") or {}, p.get("quote") or {}, p.get("events") or {}
    atr = _num(t.get("atr"))
    oc = t.get("one_call") if isinstance(t.get("one_call"), dict) and t["one_call"].get("known") else None
    d = {"ticker": snap["ticker"], "name": ((p.get("profile") or {}).get("name") or p.get("name") or "")[:40],
         "sector": (p.get("profile") or {}).get("sector"), "price": _r(price), "day_change_pct": _r((_num(q.get("live_change")) or 0) * 100),
         "volume_pace": _r(volpace.pace(snap, mins)), "atr_pct": _r(atr / price * 100) if atr and price else None,
         "rsi": _r(t.get("rsi"), 0), "trend": t.get("trend"), "vs_sma50_pct": _r((price / t["sma50"] - 1) * 100, 1) if _num(t.get("sma50")) else None,
         "vs_sma200_pct": _r((price / t["sma200"] - 1) * 100, 1) if _num(t.get("sma200")) else None,
         "zones": _zone_near(t.get("zones"), price), "earnings_in_days": ev.get("days_to_earnings"),
         "headlines": [str(n.get("title"))[:110] for n in (ev.get("news") or [])[:3] if isinstance(n, dict) and n.get("title")]}
    if oc:
        d["daily_call"] = {"call": oc.get("call"), "exit_line": _r(oc.get("exit_line")), "swings_above_line": _r(oc.get("distance_swings"), 1)}
    if m and atr and price:
        try:
            c = quick.read_chart(m, price, None, atr)
            d["chart"] = {"drop_ranges": _r(c["drop"]), "off_low_ranges": _r(c["off_low"]), "rising_now": c["rising"], "low_held": c["held"],
                          "minutes_since_low": _r(c["low_age"], 0), "new_high": c["new_high"], "day_low": _r(m["lo"]), "day_high": _r(m["hi"])}
        except Exception:
            pass
        d["path"] = path_points(m)
    return d


def market_pack(snaps: dict, mins: float | None) -> dict:
    ch = sorted(c for c in (_num(((s.get("payload") or {}).get("quote") or {}).get("live_change")) for s in snaps.values()) if c is not None)
    if not ch:
        return {"stocks_read": 0}
    return {"stocks_read": len(ch), "share_down_pct": round(100 * sum(1 for c in ch if c < 0) / len(ch)),
            "median_change_pct": round(statistics.median(ch) * 100, 2), "up_over_1pct": sum(1 for c in ch if c >= 0.01),
            "down_over_1pct": sum(1 for c in ch if c <= -0.01), "market_gate": quick.market_gate(snaps) or "open",
            "minutes_into_session": None if mins is None else round(mins)}


def shortlist(snaps: dict, prices: dict, marks: dict, mins: float | None, skip: set, n: int = CANDIDATES) -> list[str]:
    """A cheap pre-filter, not a decision: the stocks with the most going on, so the agent reads ten, not a hundred and eighty."""
    scored = []
    for tk, s in snaps.items():
        if tk in skip or tk not in prices:
            continue
        p = s.get("payload") or {}
        chg = _num((p.get("quote") or {}).get("live_change"))
        pace = volpace.pace(s, mins)
        atr = _num((p.get("technical") or {}).get("atr"))
        if chg is None or atr is None:
            continue
        oc = (p.get("technical") or {}).get("one_call") or {}
        flush = 0.0
        m = marks.get(tk)
        if m and atr:
            flush = (m["hi"] - m["lo"]) / atr
        interesting = abs(chg) >= 0.015 or flush >= quick.DROP_ATR or (oc.get("known") and oc.get("call") in ("BUY", "ADD"))
        if not interesting:
            continue
        scored.append((min(pace or 0.5, 4.0) * (abs(chg) * 100 + flush * 2 + 1), tk))
    return [tk for _, tk in sorted(scored, reverse=True)[:n]]


# ------------------------------------------------------------------ a plain-text log to read between sessions
LOG_DIR = ROOT / "data" / "agent_log"                      # one file a day; data/ is private (not in the public repo) and is in the nightly backup


def _cost_of(usage: dict) -> float:
    p = price_per_mtok()
    return (int(usage.get("input_tokens") or 0) * p["in"] + int(usage.get("cache_creation_input_tokens") or 0) * p["write"]
            + int(usage.get("cache_read_input_tokens") or 0) * p["read"] + int(usage.get("output_tokens") or 0) * p["out"]) / 1e6


def write_log(now: datetime, text: str) -> None:
    """Append to data/agent_log/<New York date>.txt. Never raises: a log must never stop the agent."""
    try:
        d = Path(os.getenv("STOCKWATCH_AGENT_LOG_DIR") or LOG_DIR)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / f"{now.date().isoformat()}.txt", "a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")
    except Exception:
        log.warning("could not write the agent log")


def _stamp(now: datetime) -> str:
    return f"{now:%H:%M} NY ({now.astimezone(timezone(timedelta(hours=3))):%H:%M} Riyadh)"


def log_review(store, now: datetime, kind: str, answer: dict, res: dict, held: dict, usage: dict, bad: list | None = None) -> None:
    u = usage_today(store, now)
    m = answer.get("market") if isinstance(answer.get("market"), dict) else {}
    lines = [f"\n== {_stamp(now)}  {kind}  [{mode()}]  this call ${_cost_of(usage):.3f}; today {u['calls']} calls, ${float(u.get('usd') or 0):.2f}",
             f"market: {m.get('call', '?')} - {m.get('note', '')}",
             "held: quick " + (", ".join(sorted(held.get("quick") or [])) or "nothing") + " | new call " + (", ".join(sorted(held.get("newcall") or [])) or "nothing")]
    ins = [i for i in (answer.get("instructions") or []) if isinstance(i, dict)]
    if not ins:
        lines.append("instructions: none (no clean setup)")
    for i in ins:
        lines.append(f"  {i.get('account', '?'):7} {i.get('action', '?'):7} {i.get('ticker', '?'):6} {i.get('state', '') or '':8} conf {i.get('confidence', '?')}: {i.get('reason', '')}")
    if res.get("thrown_out"):
        lines.append(f"thrown out by the code rules: {res['thrown_out']}")
    write_log(now, "\n".join(lines))


# ------------------------------------------------------------------ journal, watch list, orders
def journal(store, entry: dict) -> None:
    rows = _jget(store, KEY_JOURNAL, [])
    rows = (rows if isinstance(rows, list) else []) + [entry]
    _jset(store, KEY_JOURNAL, rows[-JOURNAL_KEEP:])


def vet(ins: dict, held: dict, known: set) -> tuple[dict | None, str]:
    """(clean instruction, '') or (None, why it was thrown out). The code rules for the agent's answer."""
    if not isinstance(ins, dict):
        return None, "not an object"
    acct, tk, act = str(ins.get("account", "")).lower(), str(ins.get("ticker", "")).upper(), str(ins.get("action", "")).upper()
    state, reason = str(ins.get("state", "")).lower(), str(ins.get("reason", "")).strip()
    try:
        conf = int(ins.get("confidence"))
    except (TypeError, ValueError):
        conf = 0
    if acct not in ACCOUNTS:
        return None, f"unknown account {acct!r}"
    if tk not in known:
        return None, f"{tk} is not in the data given"
    if act not in ACTIONS:
        return None, f"unknown action {act!r}"
    if state not in STATES:
        return None, f"{tk}: state {state!r} is not one of {STATES}"
    if not reason:
        return None, f"{tk}: no reason given"
    own = tk in (held.get(acct) or set())
    if act == "BUY_L1" and (state not in ("turning", "riding") or own or conf < MIN_CONFIDENCE):
        return None, f"{tk}: BUY_L1 needs state turning or riding, confidence {MIN_CONFIDENCE}+, and no open position"
    if act in ("BUY_L2", "ADD") and (state != "riding" or not own or conf < MIN_CONFIDENCE):
        return None, f"{tk}: {act} needs an open position, state riding and confidence {MIN_CONFIDENCE}+"
    if act == "SELL" and not own:
        return None, f"{tk}: SELL without an open position"
    return {"account": acct, "ticker": tk, "action": act, "state": state, "reason": reason[:240], "confidence": max(1, min(5, conf))}, ""


def parse(text: str) -> dict:
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise AgentError("the answer held no JSON")
    try:
        return json.loads(text[a:b + 1])
    except ValueError:
        raise AgentError("the answer was not valid JSON") from None


def is_settled(seen: dict, tk: str, owned: bool, price, atr, now: datetime) -> bool:
    """True when the agent has said the same thing about this stock SETTLE_AFTER reviews running and nothing has moved."""
    s = seen.get(tk) if isinstance(seen, dict) else None
    if not isinstance(s, dict) or int(s.get("streak") or 0) < SETTLE_AFTER or bool(s.get("own")) != owned:
        return False
    p0 = _num(s.get("price"))
    if _num(price) is None or p0 is None or _num(atr) is None or atr <= 0:
        return False
    if abs(price - p0) / atr >= SETTLE_MOVE_ATR:
        return False
    return (now - _ts(s.get("at"))).total_seconds() / 60 < SETTLE_MAX_MIN


def update_seen(seen: dict, answer: dict, own: set, prices: dict, now: datetime) -> dict:
    """Count how many reviews in a row each stock got the same action, state and ownership."""
    for raw in (answer.get("instructions") or [])[:12]:
        if not isinstance(raw, dict):
            continue
        tk, key = str(raw.get("ticker", "")).upper(), (str(raw.get("action", "")).upper(), str(raw.get("state", "")).lower())
        if not tk:
            continue
        prev = seen.get(tk) if isinstance(seen.get(tk), dict) else {}
        same = (prev.get("act"), prev.get("state")) == key and bool(prev.get("own")) == (tk in own)
        seen[tk] = {"act": key[0], "state": key[1], "own": tk in own, "streak": int(prev.get("streak") or 0) + 1 if same else 1,
                    "price": _num(prices.get(tk)), "at": now.isoformat(timespec="seconds")}
    return seen


def _watch_age_min(watch: dict, tk: str, now: datetime) -> float:
    w = watch.get(tk)
    if not w:
        return 0.0
    return (now - datetime.fromisoformat(w["first_seen"])).total_seconds() / 60


def apply_answer(store, now: datetime, answer: dict, held: dict, known: set, source: str) -> dict:
    """Record the market call, update the watch list, queue the orders; return counts."""
    watch = _jget(store, KEY_WATCH, {})
    watch = watch if isinstance(watch, dict) else {}
    orders = [o for o in _jget(store, KEY_ORDERS, []) if isinstance(o, dict)]
    ok, bad = [], []
    for raw in (answer.get("instructions") or [])[:12]:
        ins, why = vet(raw, held, known)
        if ins is None:
            bad.append(why)
            continue
        ok.append(ins)
        tk = ins["ticker"]
        if ins["action"] == "DROP":
            watch.pop(tk, None)
        elif ins["action"] in ("WAIT", "BUY_L1"):
            w = watch.get(tk) or {"first_seen": now.isoformat(timespec="seconds")}
            w.update(last_seen=now.isoformat(timespec="seconds"), state=ins["state"], why=ins["reason"], account=ins["account"])
            watch[tk] = w
        if ins["action"] in ("BUY_L1", "BUY_L2", "ADD", "SELL"):
            orders.append({"id": f"{now.strftime('%Y%m%d%H%M%S')}-{ins['account']}-{tk}-{ins['action']}", "ts": now.isoformat(timespec="seconds"),
                           "status": "new", "mode": mode(), "source": source, **ins})
    for tk, w in list(watch.items()):                                # a stock nobody mentioned for a while is dropped
        try:
            if (now - datetime.fromisoformat(w.get("last_seen") or w["first_seen"])).total_seconds() > WATCH_KEEP_MIN * 60:
                watch.pop(tk)
        except (KeyError, ValueError):
            watch.pop(tk, None)
    cutoff = now - timedelta(hours=36)
    orders = [o for o in orders if _ts(o.get("ts")) >= cutoff][-120:]
    _jset(store, KEY_WATCH, watch)
    _jset(store, KEY_ORDERS, orders)
    m = answer.get("market") if isinstance(answer.get("market"), dict) else {}
    journal(store, {"at": now.isoformat(timespec="seconds"), "source": source, "market": m, "instructions": ok, "thrown_out": bad})
    return {"accepted": len(ok), "thrown_out": len(bad)}


def _ts(v) -> datetime:
    try:
        return datetime.fromisoformat(v)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=NY)


def orders_for(store, account: str, now: datetime) -> list[dict] | None:
    """What the account may act on now. None = the legacy rules decide (mode off or shadow). A list (maybe empty) = drive mode: only
    these orders can open or add to a position. A first entry only counts once the stock has been watched MIN_WATCH_MIN minutes."""
    if mode() != "drive":
        return None
    watch = _jget(store, KEY_WATCH, {})
    out = []
    for o in _jget(store, KEY_ORDERS, []):
        if o.get("account") != account or o.get("status") != "new" or o.get("mode") != "drive":
            continue
        age = (now - _ts(o.get("ts"))).total_seconds() / 60
        if age < 0 or age > ORDER_TTL_MIN:
            continue
        if o["action"] == "BUY_L1" and _watch_age_min(watch if isinstance(watch, dict) else {}, o["ticker"], now) < MIN_WATCH_MIN[account]:
            continue                                                     # not watched long enough yet: it stays queued until it is or it expires
        out.append(o)
    return out


def settle(store, results: dict, now: datetime) -> None:
    """results: {order id: ('done' | 'rejected', why)}. Marks the orders and writes the outcome to the journal."""
    if not results:
        return
    orders = _jget(store, KEY_ORDERS, [])
    for o in orders:
        if o.get("id") in results:
            o["status"], o["outcome"] = results[o["id"]]
            journal(store, {"at": now.isoformat(timespec="seconds"), "source": "account", "order": o["id"], "status": o["status"], "outcome": o["outcome"]})
    _jset(store, KEY_ORDERS, orders)


# ------------------------------------------------------------------ one review
def _accounts_view(store, prices: dict, now: datetime) -> tuple[dict, dict]:
    from . import paper_newcall
    held, view = {}, {}
    qb = quick.load_book(store, migrate=False)
    held["quick"] = set(qb["positions"])
    day = now.strftime("%Y-%m-%d")
    view["quick"] = {"open": [{"ticker": t, "entry": _r(p["entry"]), "now": _r(prices.get(t)), "pct": _r(((prices.get(t) or p["entry"]) / p["entry"] - 1) * 100),
                               "stop": p["stop"], "minutes_held": round((now - datetime.fromisoformat(p["opened"])).total_seconds() / 60)}
                              for t, p in qb["positions"].items()],
                     "entries_today": len([t for t in qb["trades"] if str(t["opened"]).startswith(day)]),
                     "day_result_usd": round(quick.day_result(qb, prices, now))}
    nb = paper_newcall.load_book(store)
    held["newcall"] = set(nb.positions)
    view["newcall"] = {"open": [{"ticker": t, "entry": _r(p["entry"]), "now": _r(prices.get(t)), "pct": _r(((prices.get(t) or p["entry"]) / p["entry"] - 1) * 100),
                                 "stop": p.get("stop")} for t, p in nb.positions.items()],
                       "entries_today": len([t for t in nb.trades if str(t["opened"]).startswith(day)])}
    return held, view


def _live_inputs(store, now: datetime, desk: bool = False):
    """(snaps, prices, marks). In the regular session only stocks with a fresh live trade count. For the morning desk the pre-market quote
    stands in (the move shown is the pre-market move), and yesterday's path is not sent."""
    from . import paper_live
    snaps, prices = {}, {}
    if desk:
        for s in store.latest_snapshots():
            q = (s.get("payload") or {}).get("quote") or {}
            px, chg = _num(q.get("ext_price")), _num(q.get("ext_change"))
            if q.get("ext_session") != "pre" or q.get("ext_stale") or px is None or chg is None:
                continue
            payload = {**(s.get("payload") or {}), "quote": {**q, "live_change": chg, "live_volume": None}}
            snaps[s["ticker"]], prices[s["ticker"]] = {**s, "payload": payload}, px
        return snaps, prices, {}
    marks = _jget(store, quick.MARKS_KEY, {})
    for s in store.latest_snapshots():
        price, _why = paper_live.fresh_price(s, now)
        if price is not None:
            snaps[s["ticker"]], prices[s["ticker"]] = s, price
    return snaps, prices, marks if isinstance(marks, dict) else {}


def review(store, now: datetime | None = None, desk: bool = False, caller=call_api, fetch=None) -> dict:
    """One review (or the morning desk). Returns {"ok": bool, "note": str, ...}. Never raises."""
    now = (now or datetime.now(NY)).astimezone(NY)
    out = {"ok": False, "note": ""}
    try:
        why = within_caps(store, now)
        if why:
            out["note"] = why
            return out
        snaps, prices, marks = _live_inputs(store, now, desk)
        mins = None if desk else quick.minutes_in(now)
        held, view = _accounts_view(store, prices, now)
        watch = _jget(store, KEY_WATCH, {})
        watch = watch if isinstance(watch, dict) else {}
        own = held["quick"] | held["newcall"]
        names = list(dict.fromkeys(list(own) + [t for t in watch if t in snaps] + shortlist(snaps, prices, marks, mins, own | set(watch))))
        if not names:
            out["note"] = "nothing to review"
            return out
        seen = _jget(store, KEY_SEEN, {})
        seen = seen if isinstance(seen, dict) else {}
        settled = []
        if not desk:
            for t in list(names):
                if t in snaps and is_settled(seen, t, t in own, _num(prices.get(t)), _num(((snaps[t].get("payload") or {}).get("technical") or {}).get("atr")), now):
                    settled.append(t)
            names = [t for t in names if t not in settled]
            if not names:
                out["note"] = f"nothing new: {len(settled)} stocks unchanged since their last review"
                return out
        feats = {} if desk else intraday_features([t for t in names if t in snaps], now, fetch)
        stocks = []
        for t in names:
            if t in snaps:
                d = pack(snaps[t], marks.get(t), mins, prices[t])
                if feats.get(t):
                    d["intraday"] = feats[t]
                stocks.append(d)
        data = {"now_ny": now.strftime("%Y-%m-%d %H:%M"), "task": "morning desk before the open: call the day and pick" if desk else "review",
                "market": market_pack(snaps, mins), "accounts": view,
                "watching": [{"ticker": t, "minutes_watched": round(_watch_age_min(watch, t, now)), "last_state": w.get("state"), "why": w.get("why")}
                             for t, w in watch.items()],
                "settled_not_resent": [{"ticker": t, "action": seen[t].get("act"), "state": seen[t].get("state"), "times_in_a_row": seen[t].get("streak")} for t in settled],
                "stocks": stocks}
        text, usage = caller(playbook_text() + "\n" + CONTRACT, json.dumps(data, default=str, separators=(",", ":")))
        _add_usage(store, now, usage)
        try:
            answer = parse(text)
        except AgentError as e:
            stop = _last_call.get("stop") or "unknown"
            write_log(now, f"\n== {_stamp(now)}  unreadable answer ({e}); the model stopped because: {stop}; {len(text)} characters. Start of it:\n{text[:600]}\n... end of it:\n{text[-300:]}")
            raise AgentError(f"{e} (model stopped: {stop})") from None
        res = apply_answer(store, now, answer, held, set(names), "desk" if desk else "review")
        if not desk:
            _jset(store, KEY_SEEN, update_seen(seen, answer, own, prices, now))
        log_review(store, now, "desk" if desk else "review", answer, res, held, usage)
        out.update(ok=True, note=f"{res['accepted']} instructions, {res['thrown_out']} thrown out", **res)
        if desk:
            _jset(store, KEY_DESK, {"day": now.date().isoformat(), "market": answer.get("market"), "picks": [i for i in (answer.get("instructions") or [])][:12]})
    except AgentError as e:
        out["note"] = f"agent error: {e}"
    except Exception as e:                                           # never stop the tracker
        log.exception("agent review failed")
        out["note"] = f"agent error: {type(e).__name__}"
    return out


# ------------------------------------------------------------------ the thread
_thread: dict = {"t": None}


def _note_state(store, now: datetime, res: dict) -> None:
    st = _jget(store, KEY_STATE, {})
    st = st if isinstance(st, dict) else {}
    st.update(last_run=now.isoformat(timespec="seconds"), last_note=res.get("note", ""), mode=mode(), key=has_key())
    if not res.get("ok"):
        write_log(now, f"\n== {_stamp(now)}  no call: {res.get('note', '')}")
    if res.get("ok"):
        st["fails"] = 0
    elif res.get("note", "").startswith("agent error"):
        st["fails"] = int(st.get("fails") or 0) + 1
        if st["fails"] == FAIL_PUSH_AFTER:                          # tell the owner once, when it keeps failing
            try:
                from . import events
                events._push("StockWatch agent offline", [res["note"], "Quick and New call open no new trades until it is back."], 4, "warning",
                             None, "log", store)
            except Exception:
                log.exception("could not push the agent-offline note")
    _jset(store, KEY_STATE, st)


def since_open(now: datetime) -> float:
    """Minutes since 9:30 New York (negative before the open)."""
    return now.hour * 60 + now.minute - (9 * 60 + 30)


def due(store, now: datetime) -> str:
    """'' (nothing now), 'desk' or 'review'."""
    if not active():
        return ""
    st = _jget(store, KEY_STATE, {})
    st = st if isinstance(st, dict) else {}
    sess = us_session(now)
    if sess == "PRE" and DESK_FROM_MIN <= since_open(now) < 0:
        return "desk" if (_jget(store, KEY_DESK, {}) or {}).get("day") != now.date().isoformat() else ""
    if sess != "REGULAR":
        return ""
    last = _ts(st.get("last_run")) if st.get("last_run") else None
    early_min, early_s, late_s = cadence()
    every = early_s if since_open(now) < early_min else late_s
    if last is None or (now - last).total_seconds() >= every:
        return "review"
    return ""


def tick(store_path=None, now: datetime | None = None) -> None:
    """Called from the tracker's 20-second block. Starts at most one worker thread; returns at once."""
    t = _thread["t"]
    if t is not None and t.is_alive():
        return

    def work():
        from .store import Store
        store = Store(store_path) if store_path else Store()
        n = (now or datetime.now(NY)).astimezone(NY)
        kind = due(store, n)
        if not kind:
            return
        # a failed desk is retried on the next tick, but a review is paced by `last_run`, which `_note_state` always sets
        res = review(store, n, desk=(kind == "desk"))
        if kind == "desk" and not res.get("ok"):
            _jset(store, KEY_DESK, {"day": n.date().isoformat(), "market": None, "picks": [], "error": res.get("note")})   # one attempt a day
        _note_state(store, n, res)

    _thread["t"] = threading.Thread(target=work, name="stockwatch-agent", daemon=True)
    _thread["t"].start()


def status(store, now: datetime | None = None) -> dict:
    now = (now or datetime.now(NY)).astimezone(NY)
    st = _jget(store, KEY_STATE, {})
    return {"mode": mode(), "key": has_key(), "state": st if isinstance(st, dict) else {}, "usage": usage_today(store, now), "caps": caps(),
            "watch": _jget(store, KEY_WATCH, {}), "journal": (_jget(store, KEY_JOURNAL, []) or [])[-40:], "desk": _jget(store, KEY_DESK, None)}
