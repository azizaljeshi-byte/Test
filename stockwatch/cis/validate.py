"""Validation of the automatic candidate levels (Issue #31, workstream A).

1. `compare_reference`: candidates as of 2026-10-22 vs the analyst's reference packets (needs the private
   reference data): zone overlap, level gaps in ATR, ceiling matches and state agreement.
2. `walk_forward`: chronological, point-in-time evaluation on any daily series. Every STEP sessions the
   candidate is rebuilt from bars up to that session only; what followed is then measured over 5/10/20
   sessions. Samples are STEP sessions apart so 20-session outcomes don't overlap. Rates come with Wilson 95%
   intervals; unobserved horizons are None. These describe how the candidate levels behaved in the past.
   They are not calibrated probabilities and not evidence of a profitable strategy.

    python -m stockwatch.cis.validate --reference          # needs the private reference data
    python -m stockwatch.cis.validate --watchlist          # your holdings list; private output, local only
                                                           # (a new 0700 folder, files 0600, never in a Git checkout)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import candidates, features, level_packet, refdata, state

STEP = 20
WARMUP = 260
WINDOW = 400              # sessions handed to the extractor at each step (enough for SMA200 and its lookback)
HORIZONS = (5, 10, 20)
REFERENCE_BARS = {"ISRG": "ISRG-adjusted-daily.csv", "FICO": "FICO-20261023-adjusted.csv",
                  "CRDO": "CRDO-CRDO-20261023-adjusted.csv", "PODD": "PODD-PODD-20261023-adjusted.csv"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def _gap_atr(a: float, b: float, atr: float) -> float:
    return abs(a - b) / atr


def _overlap(a: dict, b: dict) -> float:
    """Intersection over union of two price intervals."""
    inter = max(0.0, min(a["high"], b["high"]) - max(a["low"], b["low"]))
    union = max(a["high"], b["high"]) - min(a["low"], b["low"])
    return inter / union if union > 0 else 0.0


def compare(candidate: dict, reference, atr: float) -> dict:
    """How far a candidate packet is from a reference packet, in ATR, plus state agreement."""
    cd, rd = candidate["downside"], reference["downside"]
    cp = level_packet.Packet(candidate)
    close, quote = reference["completed_close"], reference["quote"]["price"]
    ce, re_ = state.evaluate(cp, close, quote, reference["session_range"]["low"]), state.evaluate(reference)
    ref_ceil = [dict(c["zone"]) for c in reference.ceilings]
    cand_ceil = [c["zone"] for c in candidate["upside"]["ceilings"]]

    def nearest(z):
        if not cand_ceil:
            return None
        return min(0.0 if _overlap(z, c) > 0 else min(_gap_atr(z["low"], c["high"], atr), _gap_atr(z["high"], c["low"], atr))
                   for c in cand_ceil)

    gaps = [nearest(z) for z in ref_ceil]
    return {"floor_iou": _overlap(dict(cd["zone"]), dict(rd["zone"])),
            "floor_top_gap_atr": _gap_atr(cd["zone"]["high"], rd["zone"]["high"], atr),
            "failure_gap_atr": _gap_atr(cd["failure"], rd["failure"], atr),
            "major_gap_atr": _gap_atr(cd["major_damage"], rd["major_damage"], atr),
            "confirmed_agrees": ce["confirmed_state"] == re_["confirmed_state"],
            "provisional_agrees": ce["quote_state"] == re_["quote_state"],
            "states": (ce["confirmed_state"], re_["confirmed_state"], ce["quote_state"], re_["quote_state"]),
            "ceilings_ref": len(ref_ceil), "ceilings_cand": len(cand_ceil),
            "ceilings_matched": sum(g is not None and g <= 0.5 for g in gaps),
            "ceiling_gaps_atr": gaps}


def compare_reference(p: candidates.Params = candidates.PARAMS) -> dict:
    refs = level_packet.load_acceptance()["packets"]
    out = {}
    for symbol, name in REFERENCE_BARS.items():
        df = features.completed(refdata.bars(name), refs[symbol]["as_of_completed_session"])
        pk, diag = candidates.extract(df, symbol, name, p)
        atr = float(features.indicators(df)["atr"].iloc[-1])
        out[symbol] = {"candidate": pk, "diag": diag,
                       "comparison": compare(pk, refs[symbol], atr) if pk else None}
    return out


def walk_forward(df: pd.DataFrame, regime: pd.Series | None = None, p: candidates.Params = candidates.PARAMS,
                 step: int = STEP, warmup: int = WARMUP) -> list[dict]:
    """One row per sample date: the candidate's state then, and what followed. `regime`: a boolean Series
    (True = benchmark above its 200-day average) known at each date, or None."""
    c, h, lo = (df[k].to_numpy(float) for k in ("Close", "High", "Low"))
    n, rows = len(df), []
    for t in range(warmup, n, step):
        sub = df.iloc[max(0, t + 1 - WINDOW):t + 1]
        pk, diag = candidates.extract(sub, "X", "walk-forward", p)
        date = df.index[t]
        row = {"date": str(date.date()), "supported": pk is not None, "why": diag.get("why"),
               "regime": None if regime is None or date not in regime.index else bool(regime.loc[date])}
        if pk is None:
            rows.append(row)
            continue
        dn = pk["downside"]
        p0, atr = c[t], diag["atr"]
        row["state"] = state.downside_state(p0, dn)
        row["floor_dist_atr"] = (p0 - dn["zone"]["high"]) / atr
        fut = slice(t + 1, min(n, t + 1 + max(HORIZONS)))
        observed = t + max(HORIZONS) < n
        row["returns"] = {str(k): (c[t + k] / p0 - 1 if t + k < n else None) for k in HORIZONS}
        row["mfe"] = float(h[fut].max() / p0 - 1) if observed else None
        row["mae"] = float(lo[fut].min() / p0 - 1) if observed else None
        closes = c[fut]
        row["closed_below_failure"] = bool((closes < dn["failure"]).any()) if observed else None
        row["failure_dist_atr"] = (p0 - dn["failure"]) / atr
        row["min_close_atr"] = float((closes.min() - p0) / atr) if observed else None
        row["closed_below_warning"] = bool((closes < dn["warning"]).any()) if observed else None
        first = next((z for z in pk["upside"]["ceilings"] if z["zone"]["low"] > p0), None)
        if first and observed:
            bars = [{"session": str(df.index[i].date()), "high": h[i], "low": lo[i], "close": c[i], "completed": True}
                    for i in range(t + 1, t + 1 + max(HORIZONS))]
            cs = state.ceiling_state(first["zone"], bars)
            row["breakout"] = any(e == "close_above" for _, e in cs["events"])
            row["failed_breakout"] = any(e == "failed_breakout" for _, e in cs["events"])
            row["first_ceiling_dist_atr"] = (first["zone"]["low"] - p0) / atr
        rows.append(row)
    return rows


def distance_baseline(rows: list[dict]) -> tuple[float, float] | None:
    """(actual, baseline) share of samples that closed below the failure level within 20 sessions, where the
    baseline puts a level the same number of ATRs below price on every OTHER sample date of the same series.
    If the two are close, the structure adds little beyond volatility distance."""
    obs = [r for r in rows if r.get("min_close_atr") is not None]
    if len(obs) < 2:
        return None
    actual = float(np.mean([r["closed_below_failure"] for r in obs]))
    base = []
    for r in obs:
        others = [o["min_close_atr"] for o in obs if o is not r and o.get("series") == r.get("series")]
        if others:
            base.append(np.mean([m < -r["failure_dist_atr"] for m in others]))
    return actual, float(np.mean(base)) if base else None


def summarise(rows: list[dict]) -> dict:
    """Counts, rates with Wilson intervals and median returns, overall and by state and regime."""
    def block(rs):
        obs = [r for r in rs if r.get("closed_below_failure") is not None]
        k = sum(r["closed_below_failure"] for r in obs)
        kw = sum(r["closed_below_warning"] for r in obs)
        bo = [r for r in obs if "breakout" in r]
        kb = sum(r["breakout"] for r in bo)
        kf = sum(r["failed_breakout"] for r in bo if r["breakout"])
        r20 = [r["returns"]["20"] for r in obs if r["returns"]["20"] is not None]
        return {"n": len(rs), "observed": len(obs),
                "closed_below_failure_20": (k, wilson(k, len(obs))), "closed_below_warning_20": (kw, wilson(kw, len(obs))),
                "breakout_20": (kb, wilson(kb, len(bo))), "failed_after_breakout": (kf, wilson(kf, kb)),
                "median_return_20": float(np.median(r20)) if r20 else None,
                "median_mae": float(np.median([r["mae"] for r in obs])) if obs else None}
    sup = [r for r in rows if r["supported"]]
    dists = [r["failure_dist_atr"] for r in sup if "failure_dist_atr" in r]
    out = {"samples": len(rows), "supported": len(sup), "unsupported": len(rows) - len(sup),
           "median_failure_dist_atr": float(np.median(dists)) if dists else None,
           "distance_baseline": distance_baseline(sup),
           "unsupported_reasons": pd.Series([r["why"] for r in rows if not r["supported"]]).value_counts().to_dict(),
           "all": block(sup), "by_state": {}, "by_regime": {}}
    for s in ("above_floor", "testing_floor", "warning", "failure", "major_damage"):
        rs = [r for r in sup if r["state"] == s]
        if rs:
            out["by_state"][s] = block(rs)
    for flag, label in ((True, "SPY above 200-day"), (False, "SPY below 200-day")):
        rs = [r for r in sup if r["regime"] is flag]
        if rs:
            out["by_regime"][label] = block(rs)
    return out


VARIANTS = {"default": candidates.PARAMS,
            "tighter zones (tol 0.35)": replace(candidates.PARAMS, tol_atr=0.35),
            "wider zones (tol 0.75)": replace(candidates.PARAMS, tol_atr=0.75),
            "swing k=1": replace(candidates.PARAMS, k_recent=1),
            "swing k=3": replace(candidates.PARAMS, k_recent=3),
            "reference 10 sessions": replace(candidates.PARAMS, ref_sessions=10)}


def _rate(x) -> str:
    k, ci = x
    return "—" if ci is None else f"{k} ({ci[0]:.0%}–{ci[1]:.0%})"


def markdown_summary(name: str, s: dict) -> list[str]:
    base = s.get("distance_baseline")
    out = [f"**{name}**: {s['samples']} samples, {s['supported']} with a candidate, {s['unsupported']} without. "
           + ("" if s.get("median_failure_dist_atr") is None else
              f"Median failure level {s['median_failure_dist_atr']:.2f} ATR below price. ")
           + ("" if not base or base[1] is None else
              f"Closed below it within 20 sessions: {base[0]:.0%}; a level the same ATR distance below price on other "
              f"dates: {base[1]:.0%}."),
           "", "| Group | n | Closed below failure within 20 | Closed below warning within 20 | Breakout of first ceiling | "
           "Failed after breakout | Median 20-session return | Median worst excursion |", "|---|---|---|---|---|---|---|---|"]
    def line(label, b):
        med = "—" if b["median_return_20"] is None else f"{b['median_return_20']:+.1%}"
        mae = "—" if b["median_mae"] is None else f"{b['median_mae']:+.1%}"
        return (f"| {label} | {b['observed']} | {_rate(b['closed_below_failure_20'])} | {_rate(b['closed_below_warning_20'])} | "
                f"{_rate(b['breakout_20'])} | {_rate(b['failed_after_breakout'])} | {med} | {mae} |")
    out.append(line("all", s["all"]))
    for k, b in s["by_state"].items():
        out.append(line(k, b))
    for k, b in s["by_regime"].items():
        out.append(line(k, b))
    return out


class UnsafeOutput(Exception):
    """The private report can't be written there. Messages never include the path or the report's contents."""


def write_private(directory: str | Path, files: dict[str, str]) -> Path:
    """Write a private report into a NEW owner-only directory (0700, files 0600), outside any Git checkout and
    with no symlink in the path, like the private portfolio runner. Each file is written to a temporary name
    and renamed, so a report is either complete or absent. Existing directories are never reused."""
    path = Path(directory).expanduser().absolute()
    chain = (path, *path.parents)
    if any(p.is_symlink() for p in chain):
        raise UnsafeOutput("refusing: the output path goes through a symlink")
    if any((p / ".git").exists() for p in chain):
        raise UnsafeOutput("refusing: the output path is inside a Git checkout")
    if path.exists():
        raise UnsafeOutput("refusing: the output directory already exists; give a new one")
    if not path.parent.is_dir():
        raise UnsafeOutput("refusing: the output directory's parent doesn't exist")
    old = os.umask(0o077)
    try:
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
        for name, body in files.items():
            if "/" in name or name.startswith("."):
                raise UnsafeOutput("refusing: report file names must be plain")
            tmp = path / f".{name}.tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(body)
            os.replace(tmp, path / name)
    finally:
        os.umask(old)
    return path


def _refuse_in_ci() -> None:
    if os.getenv("GITHUB_ACTIONS") or os.getenv("CI"):
        sys.exit("refusing to run in CI: this report is private (it names your holdings)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reference", action="store_true", help="compare candidates with the four reference packets")
    ap.add_argument("--watchlist", action="store_true", help="walk forward on every ticker in your holdings list")
    ap.add_argument("--out", help="a NEW private directory outside any Git checkout "
                                   "(default: a new timestamped folder under ~/.stockwatch/cis-reports)")
    a = ap.parse_args(argv)
    if a.reference:
        for sym, r in compare_reference().items():
            print(sym, json.dumps(r["comparison"], default=str))
    if a.watchlist:
        _refuse_in_ci()
        from ..config import load_portfolio
        from ..data import get_provider
        pf, prov = load_portfolio(), get_provider("yahoo")
        spy = prov.history("SPY", period="max")
        regime = spy["Close"] > spy["Close"].rolling(200).mean()
        regime.index = regime.index.tz_localize(None) if getattr(regime.index, "tz", None) else regime.index
        if a.out:
            out = Path(a.out)
        else:
            base = Path.home() / ".stockwatch" / "cis-reports"
            base.mkdir(mode=0o700, parents=True, exist_ok=True)
            out = base / datetime.now(timezone.utc).strftime("walk-forward-%Y%m%d-%H%M%S")
        lines = []
        for h in pf.holdings:
            try:
                df = prov.history(h.ticker, period="max")
                df.index = df.index.tz_localize(None) if getattr(df.index, "tz", None) else df.index
                rows = walk_forward(df, regime)
            except Exception as e:
                lines += [f"**{h.ticker}**: unavailable ({e})", ""]
                continue
            lines += markdown_summary(h.ticker, summarise(rows)) + [""]
        try:
            written = write_private(out, {"cis-walk-forward.md": "\n".join(lines)})
        except UnsafeOutput as e:
            sys.exit(str(e))
        print(f"wrote a private report for {len(pf.holdings)} tickers to {written}; keep it private")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
