"""Read-only check: can ONE bulk download of 5-minute bars cover the whole S&P 500 fast and completely, and what would the
sector / industry funnel have said on the last full trading day? Nothing is bought or saved (only bulk_check_output.txt is written).
Run: bulk_check.bat -> bulk_check_output.txt"""
import statistics
import sys
import time
from pathlib import Path

import pandas as pd

here = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(here))
CHUNK = 100
MIN_NAMES = 3


def breadth_at(frames: dict, meta: pd.DataFrame, day, hhmm: str) -> dict:
    """{(sector, industry): [day changes]} at the first 5-minute bar at or after `hhmm` New York time on `day`.
    Day change = that bar's close against the previous trading day's last close; missing data is skipped, never zero."""
    out = {}
    for t, df in frames.items():
        try:
            prev = df[df.index.date < day]["Close"].dropna()
            cur = df[(df.index.date == day) & (df.index.strftime("%H:%M") <= hhmm)]["Close"].dropna()
        except Exception:
            continue
        if prev.empty or cur.empty or prev.iloc[-1] <= 0 or t not in meta.index:
            continue
        out.setdefault(t, (meta.at[t, "sector"], meta.at[t, "industry"], float(cur.iloc[-1] / prev.iloc[-1] - 1)))
    return out


def healthy(v: list) -> bool | None:
    if len(v) < MIN_NAMES:
        return None
    return sum(x > 0 for x in v) / len(v) >= 0.5 and statistics.median(v) >= 0


def funnel(rows: dict) -> tuple:
    bys, byi = {}, {}
    for s, i, c in rows.values():
        bys.setdefault(s, []).append(c)
    ok = [s for s, v in bys.items() if healthy(v)]
    for s, i, c in rows.values():
        if s in ok:
            byi.setdefault((s, i), []).append(c)
    return bys, ok, [f"{i} ({s})" for (s, i), v in byi.items() if healthy(v)]


def main():
    import yfinance as yf
    from stockwatch.market import load_universe
    uni = load_universe()
    meta = uni.set_index("ticker")[["sector", "industry"]]
    tickers = list(meta.index)
    out = [f"S&P list: {len(tickers)} stocks"]
    frames, t0 = {}, time.time()
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        c0 = time.time()
        df = yf.download(chunk, period="5d", interval="5m", group_by="ticker", auto_adjust=True, threads=True, progress=False)
        got = 0
        for t in chunk:
            try:
                sub = df[t][["Close", "Volume"]].dropna(how="all")
                if len(sub) > 20:
                    idx = pd.to_datetime(sub.index)
                    sub.index = idx.tz_convert("America/New_York") if idx.tz is not None else idx
                    frames[t] = sub
                    got += 1
            except Exception:
                continue
        out.append(f"  chunk {i // CHUNK + 1}: asked {len(chunk)}, got {got}, {time.time() - c0:.1f} s")
    total = time.time() - t0
    out.append(f"TOTAL: {len(frames)} of {len(tickers)} stocks with 5-minute bars in {total:.1f} s")
    days = sorted({d for df in frames.values() for d in set(df.index.date)})
    out.append(f"days in the data: {[str(d) for d in days]}")
    last = [d for d in days if sum(1 for df in frames.values() if (df.index.date == d).sum() >= 70) > len(frames) * 0.8]
    day = last[-1] if last else days[-1]
    ends = {t: df[df.index.date == day].index.max().strftime("%H:%M") for t, df in frames.items() if (df.index.date == day).any()}
    out.append(f"replay day {day}: last bar time seen for most stocks {max(set(ends.values()), key=list(ends.values()).count)} (New York)")
    for hhmm in ("09:45", "10:30", "11:30", "13:00", "14:30", "15:55"):
        rows = breadth_at(frames, meta, day, hhmm)
        allc = [c for _, _, c in rows.values()]
        if not allc:
            out.append(f"{hhmm}: no data")
            continue
        bys, ok, inds = funnel(rows)
        out.append(f"{hhmm} NY: {len(rows)} stocks read, {sum(c > 0 for c in allc) / len(allc):.0%} up | healthy sectors: {ok or 'none'} | healthy industries: {inds or 'none'}")
        if hhmm == "15:55":
            out.append("  close, every sector (names / share up / median):")
            for s, v in sorted(bys.items(), key=lambda x: -statistics.median(x[1])):
                out.append(f"    {s:<24} {len(v):>3}  {sum(x > 0 for x in v) / len(v):>4.0%}  {statistics.median(v) * 100:>6.2f}%")
    Path(here / "bulk_check_output.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
