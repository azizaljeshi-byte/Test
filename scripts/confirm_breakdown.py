"""
StockWatch - step 2 test: Confirmation vs Breakdown levels for one stock.

Run:   python confirm_breakdown.py            (defaults to CRDO)
       python confirm_breakdown.py NVDA
Needs: pip install yfinance pandas

Rules (daily bars, judged on the CLOSE, never intraday):

CONFIRMED UP   = close above the 20-day high (resistance)
                 AND volume >= 1.3x its 20-day average
                 AND close above the 20-day average price (EMA20)
                 AND it holds for 2 closes in a row.
BREAKDOWN      = close below the 10-day low (support)
                 OR two closes in a row below EMA20.
Otherwise      = PENDING (between the two levels, waiting).
"""

import sys

import pandas as pd

VOL_MULT = 1.3      # breakout volume vs 20-day average
HOLD_DAYS = 2       # closes needed to hold a breakout
RES_DAYS = 20       # resistance = highest high of the last 20 days
SUP_DAYS = 10       # support = lowest low of the last 10 days


def analyze(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["ema20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["vol_avg"] = df["Volume"].rolling(20).mean()

    # Levels use the days BEFORE the last HOLD_DAYS bars, so a breakout
    # is measured against what existed before it happened.
    base = df.iloc[:-HOLD_DAYS]
    resistance = base["High"].tail(RES_DAYS).max()
    support = df.iloc[:-1]["Low"].tail(SUP_DAYS).min()  # excludes today

    last = df.iloc[-1]
    recent = df.tail(HOLD_DAYS)

    held_above = bool((recent["Close"] > resistance).all())
    vol_ok = bool((recent["Volume"] >= VOL_MULT * recent["vol_avg"]).any())
    above_ema = bool((recent["Close"] > recent["ema20"]).all())
    confirmed = held_above and vol_ok and above_ema

    below_support = bool(last["Close"] < support)
    below_ema_2 = bool((recent["Close"] < recent["ema20"]).all())
    broken = below_support or below_ema_2

    if confirmed:
        status = "CONFIRMED UP"
    elif broken:
        status = "BREAKDOWN"
    else:
        status = "PENDING"

    return {
        "status": status,
        "close": float(last["Close"]),
        "ema20": float(last["ema20"]),
        "resistance": float(resistance),
        "support": float(support),
        "vol_vs_avg": float(last["Volume"] / last["vol_avg"]),
        "checks": {
            f"Closed above ${resistance:.2f} for {HOLD_DAYS} days": held_above,
            f"Volume >= {VOL_MULT}x average": vol_ok,
            "Close above EMA20": above_ema,
            f"Close below support ${support:.2f}": below_support,
            f"{HOLD_DAYS} closes below EMA20": below_ema_2,
        },
    }


def main():
    import yfinance as yf

    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "CRDO"
    df = yf.download(symbol, period="1y", interval="1d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()

    r = analyze(df)
    print(f"\n=== {symbol} ===  last close ${r['close']:.2f}  "
          f"(as of {df.index[-1].date()})")
    print(f"Status:               {r['status']}")
    print(f"To CONFIRM going up:  close above ${r['resistance']:.2f} "
          f"for {HOLD_DAYS} days, volume >= {VOL_MULT}x avg, above EMA20 "
          f"(${r['ema20']:.2f})")
    print(f"BREAKDOWN if:         close below ${r['support']:.2f} "
          f"or {HOLD_DAYS} closes below EMA20 (${r['ema20']:.2f})")
    print(f"Volume today vs avg:  {r['vol_vs_avg']:.2f}x\n")
    for name, ok in r["checks"].items():
        print(f"  [{'x' if ok else ' '}] {name}")


if __name__ == "__main__":
    main()
