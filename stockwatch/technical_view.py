"""The technical evidence page on Details: pivot points, moving averages and an indicator table, each line a Buy, Sell
or Neutral read, with a summary. Display only: computed from the stock's own daily bars (completed days only), it feeds no
score, call, plan or alert.

Rules for each read are the usual textbook ones and are written next to each indicator below. A line that cannot be
computed (too few bars) is "n/a", never a Buy or Sell. ATR is shown for context and is not counted as a vote.
"""
from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd

from . import technical as ta

BUY, SELL, NEUTRAL, NA = "Buy", "Sell", "Neutral", "n/a"
MA_PERIODS = (5, 10, 20, 50, 100, 200)
CLS = {BUY: "buy", SELL: "sell", NEUTRAL: "neu", NA: "na"}


def completed(hist: pd.DataFrame, today=None, session_open: bool = False) -> pd.DataFrame:
    """Daily bars with today's partial bar dropped while the market is open."""
    h = hist.dropna(subset=["Close"])
    if session_open and today is not None and len(h) and pd.Timestamp(h.index[-1]).date() == today:
        return h.iloc[:-1]
    return h


def pivots(h: pd.DataFrame) -> dict | None:
    """Pivot levels from the last completed bar: classic and Fibonacci (P, S1 to S3, R1 to R3)."""
    if len(h) < 2:
        return None
    last = h.iloc[-1]
    hi, lo, c = float(last["High"]), float(last["Low"]), float(last["Close"])
    p, rng = (hi + lo + c) / 3, hi - lo
    classic = {"S3": lo - 2 * (hi - p), "S2": p - rng, "S1": 2 * p - hi, "P": p, "R1": 2 * p - lo, "R2": p + rng, "R3": hi + 2 * (p - lo)}
    fib = {"S3": p - rng, "S2": p - 0.618 * rng, "S1": p - 0.382 * rng, "P": p, "R1": p + 0.382 * rng, "R2": p + 0.618 * rng, "R3": p + rng}
    return {"classic": classic, "fibonacci": fib, "price": c}


def moving_averages(h: pd.DataFrame) -> list[dict]:
    """[{period, simple, simple_read, exp, exp_read}] price above the average is Buy, below is Sell."""
    c, price = h["Close"], float(h["Close"].iloc[-1])
    out = []
    for n in MA_PERIODS:
        row = {"period": n}
        for key, fn in (("simple", ta.sma), ("exp", ta.ema)):
            v = fn(c, n).iloc[-1] if len(c) >= n else np.nan
            ok = v == v
            row[key] = float(v) if ok else None
            row[key + "_read"] = NA if not ok else BUY if price > v else SELL
        out.append(row)
    return out


def _stoch(h: pd.DataFrame, n: int = 9, smooth: int = 6) -> pd.Series:
    ll, hh = h["Low"].rolling(n).min(), h["High"].rolling(n).max()
    return (100 * (h["Close"] - ll) / (hh - ll).replace(0, np.nan)).rolling(smooth).mean()


def _adx(h: pd.DataFrame, n: int = 14) -> tuple[float, float, float]:
    up, down = h["High"].diff(), -h["Low"].diff()
    plus = np.where((up > down) & (up > 0), up, 0.0)
    minus = np.where((down > up) & (down > 0), down, 0.0)
    atr = ta.atr(h, n)
    pdi = 100 * pd.Series(plus, index=h.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus, index=h.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return float(dx.ewm(alpha=1 / n, adjust=False).mean().iloc[-1]), float(pdi.iloc[-1]), float(mdi.iloc[-1])


def _uo(h: pd.DataFrame) -> float:
    prev = h["Close"].shift()
    bp = h["Close"] - np.minimum(h["Low"], prev)
    tr = np.maximum(h["High"], prev) - np.minimum(h["Low"], prev)
    avg = lambda n: bp.rolling(n).sum() / tr.rolling(n).sum().replace(0, np.nan)
    return float((100 * (4 * avg(7) + 2 * avg(14) + avg(28)) / 7).iloc[-1])


def indicators(h: pd.DataFrame) -> list[dict]:
    """[{name, value, read, rule}] the oscillator table. Reads: RSI, Stoch, StochRSI, Williams %R, CCI and Ultimate
    Oscillator are Buy when oversold and Sell when overbought; MACD and ROC by their side of zero; ADX by the stronger
    direction once the trend is real (above 25); Highs/Lows by the close against the average of the last 14 highs;
    Bull/Bear Power by the close against its 13-day average and the power line's direction. ATR is context only."""
    rows: list[dict] = []
    if len(h) < 30:
        return rows
    c, price = h["Close"], float(h["Close"].iloc[-1])

    def add(name, value, read, rule, fmt="{:.2f}"):
        ok = value == value and value is not None
        rows.append({"name": name, "value": fmt.format(value) if ok else "n/a", "read": read if ok else NA, "rule": rule})

    def osc(v, lo, hi):
        return BUY if v < lo else SELL if v > hi else NEUTRAL

    r = float(ta.rsi(c).iloc[-1])
    add("RSI (14)", r, osc(r, 30, 70), "under 30 Buy, over 70 Sell")
    k = float(_stoch(h).iloc[-1])
    add("Stochastic (9,6)", k, osc(k, 20, 80), "under 20 Buy, over 80 Sell")
    rs = ta.rsi(c)
    srsi = float((100 * (rs - rs.rolling(14).min()) / (rs.rolling(14).max() - rs.rolling(14).min()).replace(0, np.nan)).iloc[-1])
    add("Stochastic RSI (14)", srsi, osc(srsi, 20, 80), "under 20 Buy, over 80 Sell")
    m, _ = ta.macd(c)
    mv = float(m.iloc[-1])
    add("MACD (12,26)", mv, BUY if mv > 0 else SELL if mv < 0 else NEUTRAL, "above zero Buy, below zero Sell")
    adx, pdi, mdi = _adx(h)
    add("ADX (14)", adx, (BUY if pdi > mdi else SELL) if adx > 25 else NEUTRAL, "over 25 is a trend: Buy if up-pressure leads, else Sell")
    ll, hh = h["Low"].rolling(14).min(), h["High"].rolling(14).max()
    wr = float((-100 * (hh - c) / (hh - ll).replace(0, np.nan)).iloc[-1])
    add("Williams %R (14)", wr, osc(wr, -80, -20), "under -80 Buy, over -20 Sell")
    tp = (h["High"] + h["Low"] + c) / 3
    dev = (tp - tp.rolling(14).mean()).abs().rolling(14).mean()
    cci = float(((tp - tp.rolling(14).mean()) / (0.015 * dev.replace(0, np.nan))).iloc[-1])
    add("CCI (14)", cci, osc(cci, -100, 100), "under -100 Buy, over 100 Sell")
    atr = float(ta.atr(h).iloc[-1])
    rows.append({"name": "ATR (14)", "value": f"{atr:.2f} ({atr / price * 100:.1f}%)",
                 "read": "High volatility" if atr / price > 0.04 else "Less volatility", "rule": "context only, not a vote"})
    hl = price - float(h["High"].rolling(14).mean().iloc[-1])
    add("Highs/Lows (14)", hl, BUY if hl > 0 else SELL, "close above the average of the last 14 highs: Buy")
    uo = _uo(h)
    add("Ultimate Oscillator", uo, osc(uo, 30, 70), "under 30 Buy, over 70 Sell")
    roc = float((100 * (c / c.shift(12) - 1)).iloc[-1])
    add("ROC (12)", roc, BUY if roc > 0 else SELL if roc < 0 else NEUTRAL, "above zero Buy, below zero Sell", "{:+.2f}%")
    e13 = ta.ema(c, 13)
    bull, bear = h["High"] - e13, h["Low"] - e13
    bb = float((bull + bear).iloc[-1])
    if price > e13.iloc[-1] and bear.iloc[-1] > bear.iloc[-2]:
        read = BUY
    elif price < e13.iloc[-1] and bull.iloc[-1] < bull.iloc[-2]:
        read = SELL
    else:
        read = NEUTRAL
    add("Bull/Bear Power (13)", bb, read, "Buy: above the 13-day average and bear power rising; Sell: below it and bull power falling")
    return rows


def tally(reads: list[str]) -> dict:
    b, s, n = reads.count(BUY), reads.count(SELL), reads.count(NEUTRAL)
    k = b + s + n
    if not k:
        return {"buy": 0, "sell": 0, "neutral": 0, "word": "n/a", "cls": "na"}
    score = (b - s) / k
    word = "Strong buy" if score > 0.5 else "Buy" if score > 0.1 else "Neutral" if score >= -0.1 else "Sell" if score >= -0.5 else "Strong sell"
    return {"buy": b, "sell": s, "neutral": n, "word": word, "cls": "buy" if "uy" in word else "sell" if "ell" in word else "neu"}


def evidence(hist: pd.DataFrame, today=None, session_open: bool = False) -> dict | None:
    h = completed(hist, today, session_open)
    if len(h) < 30:
        return None
    mas = moving_averages(h)
    inds = indicators(h)
    ma_reads = [r[k] for r in mas for k in ("simple_read", "exp_read")]
    ind_reads = [r["read"] for r in inds if r["name"] != "ATR (14)"]
    return {"as_of": str(pd.Timestamp(h.index[-1]).date()), "price": float(h["Close"].iloc[-1]), "pivots": pivots(h), "mas": mas,
            "indicators": inds, "ma_summary": tally(ma_reads), "ind_summary": tally(ind_reads), "overall": tally(ma_reads + ind_reads)}


# ---------------------------------------------------------------- rendering

def _chip(read: str) -> str:
    return f'<span class="tv-r {CLS.get(read, "neu")}">{escape(read)}</span>'


def _summary(title: str, t: dict) -> str:
    k = t["buy"] + t["sell"] + t["neutral"]
    seg = "".join(f'<i class="{c}" style="flex:{max(n, 0)}"></i>' for c, n in (("buy", t["buy"]), ("neu", t["neutral"]), ("sell", t["sell"])) if n)
    return (f'<div class="tv-sum"><small>{escape(title)}</small><b class="{t["cls"]}">{escape(t["word"])}</b>'
            f'<div class="tv-bar">{seg}</div><span>{t["buy"]} buy · {t["neutral"]} neutral · {t["sell"]} sell</span></div>' if k else "")


def _px(v) -> str:
    return "n/a" if v is None else f"${v:,.2f}"


def html(ev: dict | None) -> str:
    if not ev:
        return ('<style>' + CSS + '</style><div class="tv"><div class="tv-h">Technical evidence</div>'
                '<p class="tv-n">Not enough daily bars to read the indicators yet (30 are needed).</p></div>')
    pv = ev["pivots"]
    pr = ev["price"]
    plevels = ""
    if pv:
        names = ("R3", "R2", "R1", "P", "S1", "S2", "S3")
        head = "<tr><th></th><th>Classic</th><th>Fibonacci</th></tr>"
        rows = "".join(f'<tr><th>{n}</th>' + "".join(
            f'<td class="{"r" if n.startswith("R") else "s" if n.startswith("S") else "p"}">{pv[key][n]:,.2f}</td>'
            for key in ("classic", "fibonacci")) + "</tr>" for n in names)
        plevels = f'<div class="tv-t"><table>{head}{rows}</table></div>'
    mrows = "".join(f'<div class="tv-ma"><b>{r["period"]}</b><span>{_px(r["simple"])}</span>{_chip(r["simple_read"])}'
                    f'<span>{_px(r["exp"])}</span>{_chip(r["exp_read"])}</div>' for r in ev["mas"])
    irows = "".join(f'<div class="tv-i"><div><b>{escape(r["name"])}</b><small>{escape(r["rule"])}</small></div>'
                    f'<span class="tv-v">{escape(r["value"])}</span>{_chip(r["read"])}</div>' for r in ev["indicators"])
    return (f'<style>{CSS}</style><div class="tv"><div class="tv-h">Technical evidence</div>'
            f'<div class="tv-sub">From daily bars to {escape(ev["as_of"])}. Evidence only: it does not change the call.</div>'
            f'<div class="tv-sums">{_summary("Overall", ev["overall"])}{_summary("Moving averages", ev["ma_summary"])}{_summary("Indicators", ev["ind_summary"])}</div>'
            f'<details open><summary>Pivot points <small>from the last completed day</small></summary>{plevels}</details>'
            f'<details open><summary>Moving averages <small>price {_px(pr)}</small></summary>'
            f'<div class="tv-ma hd"><b></b><span>Simple</span><span></span><span>Exponential</span><span></span></div>{mrows}</details>'
            f'<details open><summary>Indicators</summary>{irows}</details></div>')


CSS = """
.tv{background:var(--dz-surface,#121a25);border:1px solid var(--dz-line,#243041);border-radius:16px;padding:14px;margin:12px 0;color:var(--dz-ink,#e9eef5)}
.tv-h{font-size:1.1rem;font-weight:800}.tv-sub,.tv-n{font-size:.74rem;color:var(--dz-muted,#8b95a7);margin:2px 0 10px}
.tv-sums{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:6px}
.tv-sum{background:color-mix(in srgb,var(--dz-ink,#e9eef5) 6%,transparent);border-radius:12px;padding:8px}
.tv-sum small{display:block;font-size:.62rem;text-transform:uppercase;letter-spacing:.05em;color:var(--dz-muted,#8b95a7)}
.tv-sum b{display:block;font-size:.98rem;margin:2px 0 5px}.tv-sum span{font-size:.62rem;color:var(--dz-muted,#8b95a7);line-height:1.3;display:block}
.tv b.buy,.tv-r.buy{color:var(--dz-buy,#7be3a8)}.tv b.sell,.tv-r.sell{color:var(--dz-act,#ff7a7a)}.tv b.neu,.tv-r.neu{color:var(--dz-muted,#8b95a7)}.tv-r.na{color:var(--dz-muted,#8b95a7)}
.tv-bar{display:flex;height:6px;border-radius:4px;overflow:hidden;gap:1px;margin-bottom:4px}.tv-bar i{display:block}
.tv-bar .buy{background:var(--dz-buy,#7be3a8)}.tv-bar .neu{background:var(--dz-line,#243041)}.tv-bar .sell{background:var(--dz-act,#ff7a7a)}
.tv details{border-top:1px solid var(--dz-line,#243041);padding:8px 0}.tv summary{cursor:pointer;font-weight:800;font-size:.9rem;list-style:none}
.tv summary::-webkit-details-marker{display:none}.tv summary small{font-weight:400;color:var(--dz-muted,#8b95a7);font-size:.7rem;margin-left:6px}
.tv-t{overflow-x:auto;margin-top:6px}.tv-t table{border-collapse:collapse;width:100%;font-size:.74rem;font-variant-numeric:tabular-nums}
.tv-t th,.tv-t td{padding:5px 4px;text-align:right}.tv-t th{color:var(--dz-muted,#8b95a7);font-weight:600}.tv-t td.r{color:var(--dz-act,#ff7a7a)}.tv-t td.s{color:var(--dz-buy,#7be3a8)}.tv-t td.p{color:var(--dz-ink,#e9eef5);font-weight:800}
.tv-ma{display:grid;grid-template-columns:34px 1fr 54px 1fr 54px;gap:4px;align-items:center;padding:5px 0;font-size:.8rem;border-top:1px solid color-mix(in srgb,var(--dz-line,#243041) 60%,transparent);font-variant-numeric:tabular-nums}
.tv-ma.hd{font-size:.64rem;color:var(--dz-muted,#8b95a7);border-top:0}.tv-r{font-size:.7rem;font-weight:800;text-align:right}
.tv-i{display:grid;grid-template-columns:1fr auto 70px;gap:8px;align-items:center;padding:7px 0;border-top:1px solid color-mix(in srgb,var(--dz-line,#243041) 60%,transparent)}
.tv-i b{font-size:.84rem}.tv-i small{display:block;font-size:.64rem;color:var(--dz-muted,#8b95a7);line-height:1.25}.tv-v{font-size:.82rem;font-variant-numeric:tabular-nums}
"""
