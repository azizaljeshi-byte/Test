"""Small, mid and tiny company screen: python -m stockwatch.smallcap --out folder   (the list rebuilds itself weekly; --universe file.csv overrides it)

Display only. It reads prices and fundamentals and writes two small tables (Shortlist, Log). It never changes a score, signal,
verdict, trade plan, alert or paper account, and the app page never waits on it: run it from its own job.

Steps
  1 one bulk download of daily bars for the whole list (the same call as the S&P scan)
  2 drop what cannot be traded: price under MIN_PRICE, thin dollar volume, too little history
  3 fundamentals, a few dozen per run and kept FUND_TTL_DAYS (they change once a quarter); the whole list is covered over a few runs
  4 qualify: every pillar that is known must pass, at least 3 of 4 known, and the price must not look rich (`fund_check`)
  5 only qualified stocks get the technical row: price, day move, volume, RSI, MACD, ATR with an arrow against about an hour ago,
    nearest support and resistance, and "Moving" or "Quiet"
Missing data is "unknown" (never 0 and never a fail on its own). A stock whose size is unknown is not shown.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


from . import technical

log = logging.getLogger("stockwatch.smallcap")
NY = ZoneInfo("America/New_York")

# --- the owner's words, as numbers (all proposals: change here, nowhere else)
BANDS = {"Tiny": (50e6, 300e6), "Small": (300e6, 2e9), "Mid": (2e9, 10e9)}   # market value in dollars
MIN_PRICE = 1.0
MIN_DOLLAR_VOL = 300_000          # average daily dollars traded; under this you cannot really buy or sell it
MIN_BARS = 60
GROWTH_MIN = 0.08                 # revenue growth for a profitable company: "organic to considerable"
GROWTH_LOSS_MIN = 0.20            # revenue growth for a company with no profit yet: "significant"
DEBT_MAX = 1.5                    # debt to equity, "not deeply in debt"
CURRENT_MIN = 1.2                 # current ratio, "a fairly good balance sheet"
RUNWAY_YEARS = 2.0                # negative cash flow is fine while cash covers this many years of it
PEG_CHEAP, PEG_RICH = 1.5, 2.5
UPSIDE_CHEAP = 0.25               # analyst target over price
PS_CHEAP, PS_RICH = 2.0, 6.0      # price to sales, for companies with no profit
PE_CHEAP, PE_RICH = 15.0, 30.0
MIN_KNOWN_PILLARS = 3
MOVE_ATRS, MOVE_RELVOL = 0.75, 2.0   # "Moving": a day move of this many normal daily swings, or this much volume against normal
FUND_TTL_DAYS = 7
FUND_PER_RUN = 40
ERROR_RETRY_MIN = 60
ARROW_MIN_AGE_MIN = 50            # arrows compare with the newest snapshot at least this old (about an hour)
KEEP_SNAPSHOTS_MIN = 360
MAX_UNIVERSE = 800
KEYS = ("name", "sector", "market_cap", "pe_trailing", "pe_forward", "peg", "revenue_growth", "earnings_growth", "profit_margin",
        "debt_to_equity", "current_ratio", "free_cash_flow", "total_cash", "total_debt", "eps_trailing", "price_to_sales",
        "target_mean_price")


def _n(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _pct(v):
    return "unknown" if v is None else f"{v * 100:+.0f}%"


def _money(v):
    if v is None:
        return "unknown"
    a = abs(v)
    return f"${a / 1e9:.1f}B" if a >= 1e9 else f"${a / 1e6:.0f}M" if a >= 1e6 else f"${a:,.0f}"


# ------------------------------------------------------------------ universe
def load_universe(text: str) -> list[str]:
    """Tickers from the first column of a CSV (header or not). Repeats and odd symbols are dropped; the list is capped."""
    out, seen = [], set()
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        t = re.sub(r"[^A-Za-z0-9.\-]", "", row[0]).upper().replace(".", "-")
        if not t or t in ("TICKER", "SYMBOL") or t in seen or not re.fullmatch(r"[A-Z0-9][A-Z0-9\-]{0,9}", t):
            continue
        seen.add(t)
        out.append(t)
    return out[:MAX_UNIVERSE]



# ---- the weekly list, built from TradingView's public screener (the same unofficial endpoint stockwatch.tradingview uses)
UNIVERSE_DAYS = 7
SCREENER_EXCHANGES = ["NASDAQ", "NYSE", "AMEX"]


def screener_payload(limit: int = MAX_UNIVERSE) -> dict:
    """Common stock on a US exchange, inside the size bands and over MIN_PRICE, the most traded first."""
    lo, hi = min(b[0] for b in BANDS.values()), max(b[1] for b in BANDS.values())
    return {"markets": ["america"], "symbols": {"query": {"types": ["stock"]}, "tickers": []},
            "filter": [{"left": "market_cap_basic", "operation": "in_range", "right": [lo, hi]},
                       {"left": "close", "operation": "greater", "right": MIN_PRICE},
                       {"left": "type", "operation": "equal", "right": "stock"},
                       {"left": "exchange", "operation": "in_range", "right": SCREENER_EXCHANGES}],
            "columns": ["name", "market_cap_basic", "close", "average_volume_30d_calc"],
            "sort": {"sortBy": "average_volume_30d_calc", "sortOrder": "desc"}, "range": [0, limit]}


def fetch_universe(post=None) -> list[str]:
    """Ticker list from the screener. Raises on any failure; the caller keeps the old list."""
    if post is None:
        from .tradingview import _post as post
    data = post(screener_payload())
    rows = (data or {}).get("data")
    if not isinstance(rows, list) or not rows:
        raise ValueError("the screener returned no rows")
    tickers = load_universe("\n".join(str(((r or {}).get("d") or [""])[0]) for r in rows))
    if len(tickers) < 20:
        raise ValueError(f"the screener returned only {len(tickers)} usable tickers")
    return tickers


def universe(store, now: datetime, post=None) -> tuple[list[str], str]:
    """(tickers, note). Rebuilt when the saved list is older than UNIVERSE_DAYS; if the screener fails the saved list is kept
    and the note says so. No saved list and no screener means no run, never a guess."""
    saved = _load(store, "smallcap_universe", {})
    try:
        age = now - datetime.fromisoformat(saved["t"]) if saved.get("t") else None
    except ValueError:
        age = None
    if saved.get("tickers") and age is not None and age < timedelta(days=UNIVERSE_DAYS):
        return saved["tickers"], f"list from {saved['t'][:10]}"
    try:
        tickers = fetch_universe(post)
    except Exception as e:
        if saved.get("tickers"):
            return saved["tickers"], f"screener unavailable ({str(e)[:80]}); kept the list from {saved['t'][:10]}"
        raise RuntimeError(f"No stock list yet and the screener is unavailable ({str(e)[:80]}). "
                           "Give the job a CSV of tickers with --universe.") from e
    _save(store, "smallcap_universe", {"t": now.isoformat(), "tickers": tickers})
    return tickers, f"new list of {len(tickers)} from the screener"


# ------------------------------------------------------------------ fundamentals
def band_of(market_cap) -> str | None:
    mc = _n(market_cap)
    if mc is None:
        return None
    for name, (lo, hi) in BANDS.items():
        if lo <= mc < hi:
            return name
    return None


def value_label(f: dict, price: float | None) -> tuple[str, str]:
    """Cheap, Fair, Rich or unknown, with the reason. Growth-adjusted first, then analyst target, then plain multiples."""
    peg, pe = _n(f.get("peg")), _n(f.get("pe_forward")) or _n(f.get("pe_trailing"))
    tgt = _n(f.get("target_mean_price"))
    if peg is not None and peg > 0:
        return (("Cheap" if peg <= PEG_CHEAP else "Fair" if peg <= PEG_RICH else "Rich"), f"PEG {peg:.1f}")
    if tgt and price and price > 0:
        up = tgt / price - 1
        return (("Cheap" if up >= UPSIDE_CHEAP else "Fair" if up >= 0 else "Rich"), f"analyst target {up * 100:+.0f}% from here")
    eps = _n(f.get("eps_trailing"))
    if pe is not None and pe > 0 and (eps is None or eps > 0):
        return (("Cheap" if pe <= PE_CHEAP else "Fair" if pe <= PE_RICH else "Rich"), f"P/E {pe:.0f}")
    ps = _n(f.get("price_to_sales"))
    if ps is not None and ps > 0:
        return (("Cheap" if ps <= PS_CHEAP else "Fair" if ps <= PS_RICH else "Rich"), f"price to sales {ps:.1f}")
    return "unknown", "no valuation figure available"


def fund_check(f: dict, price: float | None = None) -> dict:
    """The owner's fundamentals test. Each pillar is pass, fail or None (unknown). Qualified = nothing fails, at least
    MIN_KNOWN_PILLARS known, size inside a band, and the price is not Rich. Fundamentals never touch the app's scores."""
    f = f or {}
    rg, eg = _n(f.get("revenue_growth")), _n(f.get("earnings_growth"))
    margin, eps = _n(f.get("profit_margin")), _n(f.get("eps_trailing"))
    profitable = (margin > 0 if margin is not None else eps > 0 if eps is not None else None)
    pillars: dict[str, tuple[bool | None, str]] = {}

    if rg is None:
        pillars["growth"] = (None, "revenue growth unknown")
    else:
        need = GROWTH_LOSS_MIN if profitable is False else GROWTH_MIN
        pillars["growth"] = (rg >= need, f"revenue {_pct(rg)}" + ("" if rg >= need else f" (needs {need * 100:.0f}%+)"))

    if profitable is None:
        pillars["profit"] = (None, "profit unknown")
    elif profitable:
        ok = eg is None or eg > 0
        pillars["profit"] = (ok, "profitable" + ("" if eg is None else f", profit {_pct(eg)}"))
    else:
        ok = rg is not None and rg >= GROWTH_LOSS_MIN
        pillars["profit"] = (ok, "no profit yet" + (", revenue growing fast" if ok else ", and revenue is not growing fast enough"))

    de, cr = _n(f.get("debt_to_equity")), _n(f.get("current_ratio"))
    if de is None and cr is None:
        pillars["debt"] = (None, "debt unknown")
    else:
        bad = (de is not None and de > DEBT_MAX) or (cr is not None and cr < CURRENT_MIN)
        bits = ([f"debt/equity {de:.1f}"] if de is not None else []) + ([f"current ratio {cr:.1f}"] if cr is not None else [])
        pillars["debt"] = (not bad, ", ".join(bits))

    fcf, cash = _n(f.get("free_cash_flow")), _n(f.get("total_cash"))
    if fcf is None:
        pillars["cash"] = (None, "cash flow unknown")
    elif fcf > 0:
        pillars["cash"] = (True, f"cash flow {_money(fcf)} a year")
    elif cash is None:
        pillars["cash"] = (None, "burning cash and cash on hand unknown")
    else:
        years = cash / -fcf if fcf < 0 else math.inf
        pillars["cash"] = (years >= RUNWAY_YEARS, f"burning cash, {years:.1f} years of it in the bank")

    value, value_why = value_label(f, price)
    band = band_of(f.get("market_cap"))
    known = sum(v[0] is not None for v in pillars.values())
    failed = [k for k, v in pillars.items() if v[0] is False]
    if band is None:
        why_not = "size unknown" if _n(f.get("market_cap")) is None else "outside the tiny, small and mid size bands"
    elif failed:
        why_not = "fails: " + ", ".join(failed)
    elif known < MIN_KNOWN_PILLARS:
        why_not = f"only {known} of 4 fundamentals known"
    elif value == "Rich":
        why_not = "looks expensive"
    else:
        why_not = ""
    return {"passed": not why_not, "why_not": why_not, "band": band, "pillars": pillars, "known": known,
            "value": value, "value_why": value_why, "market_cap": _n(f.get("market_cap")),
            "text": "; ".join(v[1] for v in pillars.values()) + f"; value: {value} ({value_why})"}


# ------------------------------------------------------------------ technicals
def arrow(now, before, tol: float) -> str:
    """▲ up, ▼ down, ▶ about level, · no earlier reading to compare with."""
    a, b = _n(now), _n(before)
    if a is None or b is None:
        return "·"
    return "▲" if a - b > tol else "▼" if b - a > tol else "▶"


def levels_of(hist, now) -> dict:
    """Nearest support and resistance from the app's own level finder; unknown when it cannot place them."""
    try:
        from .cis import candidates, decision          # the same level finder status.py uses
        done, why, _last = decision.current_bars(hist.iloc[-420:], now)
        if done is None:
            log.info("levels unavailable: %s", why)
            return {"support": None, "resistance": None}
        pk, _diag = candidates.extract(done.iloc[-400:], "STATUS", "provider")
        close = float(done["Close"].iloc[-1])
        if pk is None:
            return {"support": None, "resistance": None}
        zone = pk["downside"]["zone"]
        above = [c["zone"] for c in (pk.get("upside") or {}).get("ceilings") or [] if c["zone"]["low"] > close]
        return {"support": _n(zone["high"]), "resistance": _n(min(above, key=lambda z: z["low"])["low"]) if above else None}
    except Exception as e:                                           # a bad candidate is "unknown", never a crash
        log.info("levels unavailable: %s", e)
        return {"support": None, "resistance": None}


def session_fraction(day, now: datetime | None) -> float:
    """How much of the regular session (9:30 to 16:00 New York) has passed, when `day` is today and the market is open; otherwise 1.
    Used so a morning's partial volume is compared with a normal morning, not with a whole normal day."""
    if now is None:
        return 1.0
    ny = now.astimezone(NY)
    if str(day) != str(ny.date()) or ny.weekday() > 4:
        return 1.0
    minutes = ny.hour * 60 + ny.minute - (9 * 60 + 30)
    return 1.0 if minutes <= 0 or minutes >= 390 else max(0.1, minutes / 390)


def tech_values(hist, now: datetime | None = None) -> dict | None:
    if hist is None or len(hist) < MIN_BARS:
        return None
    ind = technical.indicators(hist)
    last, prev = ind.iloc[-1], ind.iloc[-2]
    close, pclose, atr = _n(last["Close"]), _n(prev["Close"]), _n(last["ATR"])
    if close is None or pclose is None or pclose <= 0 or close <= 0 or atr is None or atr <= 0:
        return None
    avg_vol = _n(last["VolAvg20"])
    vol = _n(last["Volume"])
    frac = session_fraction(str(ind.index[-1])[:10], now)
    return {"price": close, "day": close / pclose - 1, "rsi": _n(last["RSI"]), "macd": _n(last["MACD"] - last["MACD_signal"]),
            "atr": atr, "atr_pct": atr / close, "relvol": (vol / frac / avg_vol if vol is not None and avg_vol else None),
            "avg_dollars": (avg_vol * close if avg_vol else None), "as_of": str(ind.index[-1])[:10]}


def moving(v: dict) -> bool:
    return abs(v["price"] - v["price"] / (1 + v["day"])) / v["atr"] >= MOVE_ATRS or (v["relvol"] or 0) >= MOVE_RELVOL


def baseline(snaps: list, now: datetime) -> dict:
    """The newest saved snapshot that is at least ARROW_MIN_AGE_MIN old (about an hour back); empty if there is none yet."""
    for s in reversed(snaps):
        try:
            if now - datetime.fromisoformat(s["t"]) >= timedelta(minutes=ARROW_MIN_AGE_MIN):
                return s.get("v") or {}
        except (KeyError, ValueError):
            continue
    return {}


# ------------------------------------------------------------------ state
def _load(store, key, default):
    try:
        return json.loads(store.get_setting(key) or "") if store else default
    except (TypeError, ValueError):
        return default


def _save(store, key, value):
    if store:
        store.set_setting(key, json.dumps(value))


def refresh_fundamentals(provider, tickers: list[str], cache: dict, now: datetime) -> int:
    """Fetch fundamentals for the oldest or missing entries, at most FUND_PER_RUN. A failed fetch keeps the old entry and is retried
    after ERROR_RETRY_MIN minutes. Returns how many were fetched."""
    def age_min(t):
        e = cache.get(t)
        try:
            return (now - datetime.fromisoformat(e["t"])).total_seconds() / 60 if e else math.inf
        except (KeyError, ValueError):
            return math.inf

    due = [t for t in tickers if (age_min(t) >= FUND_TTL_DAYS * 1440 and not (cache.get(t) or {}).get("err"))
           or (cache.get(t) or {}).get("err") and age_min(t) >= ERROR_RETRY_MIN or t not in cache]
    due.sort(key=lambda t: -age_min(t))
    due = due[:FUND_PER_RUN]

    def get(t):
        try:
            f = provider.fundamentals(t)
            return t, {k: f.get(k) for k in KEYS if f.get(k) is not None}, None
        except Exception as e:
            return t, None, str(e)[:120]

    with ThreadPoolExecutor(max_workers=3) as pool:
        for t, f, err in pool.map(get, due):
            if f is not None:
                cache[t] = {"t": now.isoformat(), "f": f}
            else:
                cache[t] = {"t": now.isoformat(), "f": (cache.get(t) or {}).get("f") or {}, "err": err}
    return len(due)


# ------------------------------------------------------------------ run
def run(provider, tickers: list[str], store=None, now: datetime | None = None, on_result=None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    tickers = list(dict.fromkeys(tickers))[:MAX_UNIVERSE]
    hist = provider.bulk_history(tuple(tickers))
    tech, dropped = {}, {"no prices": 0, "thin trading or under $1": 0}
    for t in tickers:
        v = tech_values(hist.get(t), now)
        if v is None:
            dropped["no prices"] += 1
        elif v["price"] < MIN_PRICE or (v["avg_dollars"] or 0) < MIN_DOLLAR_VOL:
            dropped["thin trading or under $1"] += 1
        else:
            tech[t] = v
    cache = _load(store, "smallcap_fund", {})
    fetched = refresh_fundamentals(provider, list(tech), cache, now)
    _save(store, "smallcap_fund", cache)

    checks = {t: fund_check((cache.get(t) or {}).get("f") or {}, tech[t]["price"]) for t in tech}
    no_fund = [t for t in tech if not (cache.get(t) or {}).get("f")]
    snaps = _load(store, "smallcap_snaps", [])
    base = baseline(snaps, now)
    rows = []
    for t, c in checks.items():
        if not c["passed"]:
            continue
        v, b = tech[t], base.get(t) or {}
        lv = levels_of(hist[t], now)
        is_moving = moving(v)
        direction = "up" if v["day"] > 0 else "down" if v["day"] < 0 else "flat"
        rows.append({
            "ticker": t, "name": ((cache.get(t) or {}).get("f") or {}).get("name") or "", "size": c["band"],
            "price": v["price"], "day": v["day"], "moving": f"Moving {direction}" if is_moving else "Quiet",
            "relvol": v["relvol"], "rsi": v["rsi"], "rsi_arrow": arrow(v["rsi"], b.get("rsi"), 0.5),
            "macd": v["macd"], "macd_arrow": arrow(v["macd"], b.get("macd"), 0.02 * v["atr"]),
            "atr": v["atr"], "atr_arrow": arrow(v["atr"], b.get("atr"), 0.01 * v["atr"]),
            "support": lv["support"], "resistance": lv["resistance"],
            "fundamentals": c["text"], "value": c["value"], "market_cap": c["market_cap"], "as_of": v["as_of"],
            "_moving": is_moving})
    rows.sort(key=lambda r: (not r.pop("_moving"), -abs(r["day"])))

    prev_list = _load(store, "smallcap_list", [])
    now_list = [r["ticker"] for r in rows]
    log_rows = [{"time": now.astimezone(ZoneInfo("Asia/Riyadh")).strftime("%d %b %H:%M"), "ticker": t, "event": "Entered the shortlist"}
                for t in now_list if t not in prev_list] + \
               [{"time": now.astimezone(ZoneInfo("Asia/Riyadh")).strftime("%d %b %H:%M"), "ticker": t, "event": "Left the shortlist"}
                for t in prev_list if t not in now_list] if prev_list or store is None else []
    result = {"as_of": now.isoformat(), "universe": len(tickers), "tradable": len(tech), "dropped": dropped,
              "fundamentals_fetched": fetched, "fundamentals_missing": len(no_fund), "qualified": len(rows),
              "first_hour_no_arrows": not base, "rows": rows, "log": log_rows}
    if on_result:
        on_result(result)  # persist delivery before advancing the event baseline
    if store:
        _save(store, "smallcap_list", now_list)
        last = snaps[-1]["t"] if snaps else None
        if not last or now - datetime.fromisoformat(last) >= timedelta(minutes=10):
            snaps.append({"t": now.isoformat(), "v": {r["ticker"]: {"rsi": r["rsi"], "macd": r["macd"], "atr": r["atr"]} for r in rows}})
        snaps = [s for s in snaps if now - datetime.fromisoformat(s["t"]) <= timedelta(minutes=KEEP_SNAPSHOTS_MIN)]
        _save(store, "smallcap_snaps", snaps)
    return result


# ------------------------------------------------------------------ the two tables
SHORTLIST_HEADER = ["Ticker", "Company", "Size", "Price", "Day", "Moving?", "Volume vs normal", "RSI", "", "MACD", "", "ATR", "",
                    "Support", "Resistance", "Value", "Fundamentals", "Prices as of"]


def _f(v, d=2):
    return "unknown" if v is None else f"{v:,.{d}f}"


def shortlist_rows(result: dict) -> list[list]:
    out = [SHORTLIST_HEADER]
    for r in result["rows"]:
        out.append([r["ticker"], r["name"], r["size"], _f(r["price"]), f"{r['day'] * 100:+.1f}%", r["moving"],
                    "unknown" if r["relvol"] is None else f"{r['relvol']:.1f}x", _f(r["rsi"], 0), r["rsi_arrow"],
                    _f(r["macd"], 3), r["macd_arrow"], _f(r["atr"]), r["atr_arrow"], _f(r["support"]), _f(r["resistance"]),
                    r["value"], r["fundamentals"], r["as_of"]])
    return out


def log_rows(result: dict) -> list[list]:
    return [["Time (Riyadh)", "Ticker", "What happened"]] + [[r["time"], r["ticker"], r["event"]] for r in result["log"]]


def write_csv(result: dict, folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, rows in (("shortlist.csv", shortlist_rows(result)), ("log.csv", log_rows(result))):
        p = folder / name
        with p.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)
        paths.append(p)
    return paths


def main(argv=None):
    from .data import get_provider, us_session
    from .store import Store
    from .smallcap_sheet import connect, deliver, SheetConfigError

    p = argparse.ArgumentParser(description="Screen small, mid and tiny companies during the US session")
    p.add_argument("--universe", help="CSV of tickers; otherwise rebuilt weekly from the screener")
    p.add_argument("--db", default=str(Path(__file__).resolve().parent.parent / "data" / "smallcap.db"),
                   help="persistent database for this job only")
    p.add_argument("--out", help="also export shortlist.csv and log.csv to this folder")
    p.add_argument("--demo", action="store_true", help="synthetic CSV only; never writes the owner's Sheet")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    now = datetime.now(timezone.utc)
    if us_session(now) == "CLOSED":
        print("Outside the US session (weekdays, 4am to 8pm New York); skipped.")
        return 0
    if a.demo and not a.out:
        p.error("--demo requires --out (CSV only)")
    try:
        sheet = None if a.demo else connect()
    except SheetConfigError as e:
        print(str(e))
        return 0
    except Exception:
        print("Cannot open the Google Sheet; check the Sheets API, service-account access and connection.")
        return 1
    # Demo state is separate, so synthetic names never enter the live delivery queue.
    store = Store(str(a.db) + ".demo.db" if a.demo else a.db)

    def save_pending(pending):
        _save(store, "smallcap_sheet_pending", pending)

    def flush(pending):
        deliver(sheet, pending, save_pending)
        _save(store, "smallcap_list", pending["tickers"])
        save_pending(None)

    try:
        pending = _load(store, "smallcap_sheet_pending", None)
        if pending and sheet is not None:
            flush(pending)
            print("Retried the saved Sheet delivery; next hourly run will scan fresh data.")
            return 0
        if a.universe:
            tickers, note = load_universe(Path(a.universe).read_text(encoding="utf-8")), "list from your file"
        else:
            tickers, note = universe(store, now)
        print(note)

        def queue(result):
            save_pending({"shortlist": shortlist_rows(result), "log": log_rows(result),
                          "tickers": [r["ticker"] for r in result["rows"]]})

        res = run(get_provider("demo" if a.demo else "yahoo"), tickers, store, now,
                  on_result=queue if sheet is not None else None)
        if sheet is not None:
            flush(_load(store, "smallcap_sheet_pending", None))
        if a.out:
            write_csv(res, Path(a.out))
        print(f"{res['qualified']} qualified of {res['tradable']} tradable ({res['universe']} listed); "
              f"{res['fundamentals_missing']} still waiting for fundamentals")
        return 0
    except Exception:
        print("Smallcap job failed; saved Sheet deliveries will retry next run. "
              "Check the connection, Sheet access, stock list and local database.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
