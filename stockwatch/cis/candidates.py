"""Automatic CANDIDATE floor/ceiling levels (Issue #31, workstream A). Unreviewed by construction.

Point-in-time: only completed bars up to the as-of session are used, and a swing high/low counts only once
the sessions that confirm it have closed. The method is price/volume first, fully parameterised (Params,
versioned by its hash) and reproducible from its bars.

Recent-structure method (v1), modelled on how the reference floors were described (recent defended lows,
broken resistance and the 50/200-day averages near price), without copying any reference level:
1. Support anchors: swing lows (K_RECENT sessions either side) in the last RECENT sessions; local highs in
   the last FLIP_LOOKBACK sessions (the highest of the FLIP_LEFT sessions before them, known when printed,
   at least FLIP_AGE sessions old) that a later completed close cleared (broken resistance); the 50- and 200-day averages; and the lows of
   the last REF_SESSIONS sessions (recent value, never enough on their own). Only anchors at or below the
   reference (below) count. Anchors cluster into zones at most 2 x TOL x ATR14 wide.
2. Floor: the nearest zone with at least FLOOR_MIN_ANCHORS anchors, one of them a price and one structural
   (a swing low, a broken high or an average), whose top is at or below the highest close of the last
   REF_SESSIONS sessions and within FLOOR_MAX_ATR ATRs of it. The
   reference is the recent high close, not today's close, so a floor that price has just fallen through
   stays the floor (SUPPORT BREAK or worse) instead of a lower support being promoted to look healthy.
3. Failure: below the most recent session low under the floor in the last RECENT sessions (BUFFER x ATR
   lower), else one ATR under the floor (volatility fallback). Major damage: below the lowest low under the
   failure level in the last RECENT sessions, else in the last MAJOR_LOOKBACK sessions, else two ATRs lower
   (fallback). Levels that can't
   be ordered make the floor undetermined: no packet.
4. Ceilings: swing highs (K_CEILING either side, CEILING_LOOKBACK sessions), swing lows a later close fell
   below (broken support) and the averages, above the current close (so a lost floor reappears as a
   ceiling); clustered, ascending, at most MAX_CEILINGS.

Candidates carry level_selection/review_status `code_candidate_unreviewed`, have no scenario weights (none
are invented) and never drive a call: the decision adapter treats them as CIS UNSUPPORTED. Approval runs
through `level_packet.stage`: candidate -> research_reviewed -> owner_accepted.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from . import features, level_packet

METHOD = "cis-candidate-levels-v1"


@dataclass(frozen=True)
class Params:
    k_recent: int = 2              # swing confirmation for recent structure: sessions either side
    recent: int = 15               # sessions of recent structure
    flip_lookback: int = 60        # local highs this recent can become support once a close clears them
    flip_left: int = 10            # a local high is the highest of this many prior sessions
    flip_age: int = 3              # ... and at least this many sessions old, so a fresh pop isn't a floor
    tol_atr: float = 0.5           # anchors within this many ATR14 form one zone
    floor_min_anchors: int = 2
    ref_sessions: int = 5          # the floor is judged against the highest close of these sessions
    floor_max_atr: float = 3.0
    buffer_atr: float = 0.1
    major_lookback: int = 60
    k_ceiling: int = 3
    ceiling_lookback: int = 252
    max_ceilings: int = 8

    def key(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:8]


PARAMS = Params()


def swings(df: pd.DataFrame, k: int, lookback: int) -> list[dict]:
    """Confirmed swing lows/highs whose confirming sessions are all inside df. Row i needs rows i-k..i+k."""
    lo, hi = df["Low"].to_numpy(float), df["High"].to_numpy(float)
    n, out = len(df), []
    for i in range(max(k, n - lookback), n - k):
        w = slice(i - k, i + k + 1)
        if lo[i] == lo[w].min():
            out.append({"i": i, "date": str(df.index[i].date()), "kind": "low", "field": "Low", "price": float(lo[i])})
        if hi[i] == hi[w].max():
            out.append({"i": i, "date": str(df.index[i].date()), "kind": "high", "field": "High", "price": float(hi[i])})
    return out


def cluster(anchors: list[dict], width: float) -> list[dict]:
    """Clusters of anchor prices: each zone spans at most 2 x `width` from its lowest anchor, so a run of
    nearby prices can't chain into one wide band."""
    groups: list[list[dict]] = []
    for x in sorted(anchors, key=lambda a: a["price"]):
        if groups and x["price"] - groups[-1][0]["price"] <= 2 * width:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [{"low": min(x["price"] for x in g), "high": max(x["price"] for x in g), "anchors": g,
             "prices": sum(x["kind"] != "avg" for x in g)} for g in groups]


def _anchor(role: str, x: dict, source: str, reason: str) -> dict:
    return {"role": role, "session_date": x["date"], "field": x["field"], "value": x["price"],
            "source_file": source, "reason": reason}


def extract(df: pd.DataFrame, symbol: str, source: str = "provider", p: Params = PARAMS,
            quote: dict | None = None) -> tuple[dict | None, dict]:
    """(candidate packet dict or None, diagnostics). df: completed daily bars up to and including the as-of
    session; nothing after it may be passed in."""
    diag = {"method": METHOD, "params": asdict(p), "params_key": p.key()}
    q = features.check(df, symbol)
    if not q.usable or len(df) < 210:
        diag["why"] = "; ".join(q.problems) or f"only {len(df)} sessions (need 210)"
        return None, diag
    f = features.indicators(df)
    atr = float(f["atr"].iloc[-1])
    if not np.isfinite(atr) or atr <= 0:
        diag["why"] = "ATR unavailable"
        return None, diag
    n = len(df)
    close = df["Close"].to_numpy(float)
    last_close = float(close[-1])
    ref = float(close[-p.ref_sessions:].max())
    avgs = [{"i": n - 1, "date": str(df.index[-1].date()), "kind": "avg", "field": k.upper().replace("MA", "SMA"),
             "price": float(f[k].iloc[-1])} for k in ("ma50", "ma200") if np.isfinite(f[k].iloc[-1])]
    lows = [x for x in swings(df, p.k_recent, p.recent + p.k_recent) if x["kind"] == "low"]
    hi_arr = df["High"].to_numpy(float)
    flipped = []                   # a local high when it printed (highest of the prior FLIP_LEFT sessions)
    for i in range(max(p.flip_left, n - p.flip_lookback), n - p.flip_age):   # ... cleared by a later close
        if hi_arr[i] >= hi_arr[i - p.flip_left:i].max() and (close[i + 1:] > hi_arr[i]).any():
            flipped.append({"i": i, "date": str(df.index[i].date()), "kind": "high", "field": "High",
                            "price": float(hi_arr[i])})
    value = [{"i": i, "date": str(df.index[i].date()), "kind": "session", "field": "Low",
              "price": float(df["Low"].iloc[i])} for i in range(n - p.ref_sessions, n)]
    support = [x for x in lows + flipped + avgs + value if x["price"] <= ref]   # support sits under the reference
    zones = cluster(support, p.tol_atr * atr)
    structural = lambda z: any(x["kind"] in ("low", "high", "avg") for x in z["anchors"])  # noqa: E731
    ok = [z for z in zones if len(z["anchors"]) >= p.floor_min_anchors and z["prices"] >= 1 and structural(z)
          and z["high"] <= ref and ref - z["high"] <= p.floor_max_atr * atr]
    diag.update(atr=atr, ref_close=ref, anchors=len(lows) + len(flipped) + len(avgs), zones=len(zones))
    if not ok:
        diag["why"] = (f"no zone with {p.floor_min_anchors}+ anchors within {p.floor_max_atr:g} ATR below the recent "
                       "high close: floor undetermined")
        return None, diag
    floor = max(ok, key=lambda z: z["high"])
    flo, fhi = floor["low"], floor["high"]
    if fhi - flo < 0.1 * atr:                     # a single-price zone gets a minimal width
        flo, fhi = flo - 0.05 * atr, fhi + 0.05 * atr
    buffer = p.buffer_atr * atr
    window = df.iloc[n - p.recent:]
    under = [(i, float(r.Low)) for i, r in zip(range(n - p.recent, n), window.itertuples()) if r.Low < flo]
    if under:
        i_f, low_f = under[-1]
        anchor_f = {"date": str(df.index[i_f].date()), "field": "Low", "price": low_f}
        failure = low_f - buffer
        f_reason = "below the most recent session low under the floor"
    else:
        anchor_f, failure = None, flo - atr
        f_reason = "no recent low under the floor: one ATR below it (volatility fallback)"
    anchor_m = None
    for span in (p.recent, p.major_lookback):     # the nearest structural low first, then the wider base
        part = df.iloc[max(0, n - span):]
        deeper = part[part["Low"] < failure]
        if len(deeper):
            j = deeper["Low"].idxmin()
            anchor_m = {"date": str(j.date()), "field": "Low", "price": float(deeper["Low"].min())}
            major = anchor_m["price"] - buffer
            m_reason = f"below the lowest low of the last {span} sessions"
            break
    if anchor_m is None:
        major = failure - 2 * atr
        m_reason = "no lower low in the window: two ATR below the failure level (volatility fallback)"
    if not (major < failure < flo < fhi):
        diag["why"] = "levels can't be ordered below the floor"
        return None, diag
    sw = swings(df, p.k_ceiling, p.ceiling_lookback)
    highs = [x for x in sw if x["kind"] == "high"]
    broken = [{**x, "kind": "broken_low"} for x in sw if x["kind"] == "low"    # support a later close fell below
              and (close[x["i"] + 1:] < x["price"]).any()]
    above = [x for x in highs + broken + avgs if x["price"] > last_close]   # below a lost floor, it's a ceiling too
    merged = cluster(above, p.tol_atr * atr)[:p.max_ceilings]
    as_of = str(df.index[-1].date())
    r2 = lambda v: round(float(v), 2)  # noqa: E731
    ceilings = []
    for i, z in enumerate(merged):
        lo, hi = r2(z["low"]), r2(z["high"])
        if hi - lo < 0.01:
            lo, hi = r2(z["low"] - 0.05 * atr), r2(z["high"] + 0.05 * atr)
        if ceilings and lo <= ceilings[-1]["zone"]["high"]:
            lo = round(ceilings[-1]["zone"]["high"] + 0.01, 2)
        if lo >= hi:
            continue
        ceilings.append({"id": f"ceiling-{len(ceilings) + 1}", "zone": {"low": lo, "high": hi},
                         "current_quote_location": "below" if last_close < lo else "inside" if last_close <= hi else "above",
                         "confirmation": "pending",
                         "anchor_evidence": [_anchor("ceiling", x, source, f"{len(z['anchors'])}-anchor resistance zone")
                                             for x in z["anchors"]]})
    floor_anchors = [_anchor("floor", x, source, {"high": "broken resistance", "low": "recent swing low",
                                                  "session": "recent session low"}.get(x["kind"], "moving average confluence"))
                     for x in floor["anchors"]]
    downside = {"zone": {"low": r2(flo), "high": r2(fhi)}, "warning": r2(flo), "failure": r2(failure),
                "major_damage": r2(major),
                "anchor_evidence": floor_anchors
                + ([_anchor("failure", anchor_f, source, f_reason)] if anchor_f else [])
                + ([_anchor("major_damage", anchor_m, source, m_reason)] if anchor_m else [])}
    if not downside["major_damage"] < downside["failure"] < downside["warning"] < downside["zone"]["high"]:
        diag["why"] = "levels collapse after rounding"
        return None, diag
    last = df.iloc[-1]
    pk = {"contract_version": "1.0", "method_id": "independent_chart_judgment_v1",
          "packet_id": f"{symbol}-{as_of}-cand-{p.key()}", "symbol": symbol, "currency": "USD", "timeframe": "daily",
          "level_selection": "code_candidate_unreviewed", "review_status": "code_candidate_unreviewed",
          "action_mode": "explain_only", "as_of_completed_session": as_of, "completed_close": last_close,
          "quote": quote or {"price": last_close, "observed_at_utc": f"{as_of}T20:00:00+00:00", "session": "closed",
                             "is_partial": False},
          "session_range": {"low": float(last["Low"]), "high": float(last["High"]), "is_partial": False},
          "downside": downside, "upside": {"ceilings": ceilings}, "scenarios": None,
          "provenance": {"raw_source_file": source, "evidence_file": "", "calendar_verified": False,
                         "level_rationale": f"{METHOD} {p.key()}: floor = nearest {len(floor['anchors'])}-anchor zone "
                                            f"under the recent high close; failure {f_reason}; major damage {m_reason}. "
                                            "Generated by code, NOT reviewed."},
          "expected": None}
    diag.update(floor_anchors=len(floor["anchors"]), ceilings=len(ceilings),
                failure_fallback=anchor_f is None, major_fallback=anchor_m is None)
    level_packet.Packet(pk)            # validates; raises if the candidate is malformed
    return pk, diag
