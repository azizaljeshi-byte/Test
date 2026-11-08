"""Print the app's own indicator numbers for one stock, with its last bars, to compare against Investing.com or TradingView.
Run: indicator_check.bat CRM   (writes data/indicator_check.txt). Read only: it changes nothing."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd  # noqa: E402

from stockwatch import data, technical as ta, technical_view as tv  # noqa: E402


def report(h: pd.DataFrame, ticker: str) -> str:
    out = [f"{ticker}: {len(h)} daily bars, last bar {pd.Timestamp(h.index[-1]).date()}", "last 8 bars:",
           h[["Open", "High", "Low", "Close", "Volume"]].tail(8).round(2).to_string()]
    hh = tv.completed(h, None, False)
    c = hh["Close"]
    line, sig = ta.macd(c)
    ll, hi = hh["Low"].rolling(9).min(), hh["High"].rolling(9).max()
    raw = 100 * (c - ll) / (hi - ll)
    out += ["", f"RSI(14)     {float(ta.rsi(c).iloc[-1]):.3f}", f"STOCH(9,6)  {float(tv._stoch(hh).iloc[-1]):.3f}   (raw %K last: {float(raw.iloc[-1]):.2f})",
            f"MACD line   {float(line.iloc[-1]):.3f}   signal {float(sig.iloc[-1]):.3f}   hist {float((line - sig).iloc[-1]):.3f}",
            f"EMA12 {float(ta.ema(c, 12).iloc[-1]):.3f}   EMA26 {float(ta.ema(c, 26).iloc[-1]):.3f}", "raw %K (9), last 8:", raw.tail(8).round(2).to_string(),
            "", "indicator rows as the page shows them:"]
    out += [f"  {r['name']}: {r['value']} -> {r['read']}" for r in tv.indicators(hh)]
    return "\n".join(out)


if __name__ == "__main__":
    t = (sys.argv[1] if len(sys.argv) > 1 else "CRM").upper()
    text = report(data.get_provider("yahoo").history(t), t)
    Path(__file__).resolve().parents[1].joinpath("data", "indicator_check.txt").write_text(text, encoding="utf-8")
    print(text)
