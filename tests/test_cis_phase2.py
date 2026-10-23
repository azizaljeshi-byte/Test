"""CIS phase 2 (Issue #31): candidate levels, approval pipeline, walk-forward validation, watchlist shadow,
Finnhub second source and the private reference data. Synthetic data unless marked needs_data."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from cis_helpers import synthetic
from stockwatch import finnhub
from stockwatch.cis import candidates as C
from stockwatch.cis import decision as D
from stockwatch.cis import level_packet as L
from stockwatch.cis import refdata
from stockwatch.cis import validate as V
from stockwatch.cis import watchlist as W

needs_data = pytest.mark.skipif(not refdata.available(), reason="private CIS reference data not installed")
NOW = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)          # Thursday 11:00 New York


def flat_then_crash(n=320, crash=85.0):
    """Synthetic: ~100 for months (so the 200-day average sits near 100), then one session closes at `crash`."""
    rng = np.random.default_rng(1)
    c = 100 + rng.normal(0, 0.6, n)
    c[-1] = crash
    o = np.r_[c[0], c[:-1]]
    h, lo = np.maximum(o, c) + 0.5, np.minimum(o, c) - 0.5
    return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c, "Volume": 1e6},
                        index=pd.bdate_range("2025-07-01", periods=n))


# ---- candidates

def test_candidate_packets_are_valid_unreviewed_and_carry_no_invented_weights():
    pk, diag = C.extract(synthetic(500), "SYN")
    assert pk is not None, diag
    p = L.Packet(pk)
    assert p["level_selection"] == p["review_status"] == "code_candidate_unreviewed" and not p.reviewed
    assert pk["scenarios"] is None and pk["expected"] is None and L.stage(p) == "candidate"
    dn = pk["downside"]
    assert dn["major_damage"] < dn["failure"] < dn["warning"] == dn["zone"]["low"] < dn["zone"]["high"]
    lows = [c["zone"]["low"] for c in pk["upside"]["ceilings"]]
    assert lows == sorted(lows) and all(z > pk["completed_close"] for z in lows)
    assert pk["packet_id"].endswith(C.PARAMS.key()) and "NOT reviewed" in pk["provenance"]["level_rationale"]
    assert all(a["session_date"] <= pk["as_of_completed_session"] for a in dn["anchor_evidence"])


def test_a_lost_floor_stays_the_floor_instead_of_promoting_a_lower_support():
    pk, diag = C.extract(flat_then_crash(), "SYN")
    assert pk is not None, diag
    floor = pk["downside"]["zone"]
    assert floor["low"] > 95                                               # the ~100 area, not some lower level
    state = D.state.downside_state(pk["completed_close"], pk["downside"])
    assert state in ("warning", "failure", "major_damage")                 # never SUPPORT HOLD after the crash


def test_candidates_are_point_in_time():
    df = synthetic(500)
    a, _ = C.extract(df.iloc[:400], "SYN")
    changed = df.copy()
    changed.iloc[400:, :4] *= 1.5                                           # rewrite the future
    b, _ = C.extract(changed.iloc[:400], "SYN")
    assert a == b
    assert C.extract(df.iloc[:100], "SYN")[0] is None                       # too little history: no candidate


def test_a_candidate_never_drives_a_call():
    pk, _ = C.extract(synthetic(500), "SYN")
    d = D.decide(L.Packet(pk), D.Inputs(pk["completed_close"], pk["as_of_completed_session"]), True, 1)
    assert d["action"] == "CIS UNSUPPORTED" and not d["supported"]


# ---- approval pipeline

def test_pipeline_candidate_to_review_to_acceptance(monkeypatch, tmp_path):
    import json
    pk, _ = C.extract(synthetic(500), "SYN")
    cand = L.Packet(pk)
    with pytest.raises(L.PacketError, match="code candidate can't be accepted"):
        L.acceptance_entry(cand, "x", "2026-10-30")
    weights = {"method": "subjective_not_calibrated", "horizon_trading_sessions": 20, "anchor": 100.0,
               "neutral_band": 2.0, "lower": 98.0, "upper": 102.0,
               "weights_pct": {"up": 35, "sideways": 35, "down": 30}, "confidence": "low"}
    reviewed = L.review_candidate(cand, "SYN-v1", "analyst checked anchors", weights)
    assert L.stage(reviewed) == "research_reviewed" and reviewed["review"]["from_candidate"] == cand.id
    assert reviewed["review"]["candidate_content_sha256"] == L.content_hash(cand.data)
    with pytest.raises(L.PacketError, match="needs its analyst's scenarios"):
        L.Packet({**L.thaw(reviewed.data), "scenarios": None})
    with pytest.raises(L.PacketError, match="only a code candidate"):
        L.review_candidate(reviewed, "SYN-v2", "again")
    accepted = L.thaw(reviewed.data)
    accepted["review_status"] = "user_accepted_in_chat"
    assert L.stage(L.Packet(accepted)) == "research_reviewed"               # status alone is not acceptance
    entry = L.acceptance_entry(reviewed, "owner accepted in chat", "2026-10-30")
    raw = json.loads(L.LEDGER.read_text())
    raw["acceptances"].append(entry)
    (tmp_path / "a.json").write_text(json.dumps(raw))
    monkeypatch.setattr(L, "LEDGER", tmp_path / "a.json")
    assert L.stage(L.Packet(accepted)) == "owner_accepted"


def test_reviewing_without_weights_needs_them_before_it_is_a_valid_packet():
    pk, _ = C.extract(synthetic(500), "SYN")
    with pytest.raises(L.PacketError, match="needs its analyst's scenarios"):
        L.review_candidate(L.Packet(pk), "SYN-v1", "no weights")


# ---- validation

def test_wilson_interval():
    assert V.wilson(0, 0) is None
    lo, hi = V.wilson(5, 10)
    assert lo < 0.5 < hi and 0 <= lo and hi <= 1
    assert V.wilson(10, 10)[1] == 1.0


def test_walk_forward_is_point_in_time_and_leaves_unobserved_outcomes_empty():
    df = synthetic(700)
    rows = V.walk_forward(df)
    assert rows and all(r["date"] for r in rows)
    changed = df.copy()
    changed.iloc[600:, :4] *= 0.5
    again = V.walk_forward(changed)
    for a, b in zip(rows, again):
        t = df.index.get_loc(pd.Timestamp(a["date"]))
        if t + 20 < 600 and a["supported"]:                                 # outcome window ends before the change
            assert a["state"] == b["state"] and a["returns"] == b["returns"]
    last = [r for r in rows if r["supported"]][-1]
    if df.index.get_loc(pd.Timestamp(last["date"])) + 20 >= len(df):
        assert last["returns"]["20"] is None and last["closed_below_failure"] is None


def test_summary_reconciles_counts_and_reports_the_distance_baseline():
    rows = V.walk_forward(synthetic(900))
    for r in rows:
        r["series"] = "SYN"
    s = V.summarise(rows)
    assert s["samples"] == len(rows) == s["supported"] + s["unsupported"]
    assert sum(b["n"] for b in s["by_state"].values()) == s["supported"]
    actual, base = s["distance_baseline"]
    assert 0 <= actual <= 1 and 0 <= base <= 1
    md = "\n".join(V.markdown_summary("SYN", s))
    assert "same ATR distance" in md and "probab" not in md.lower()


@needs_data
def test_reference_comparison_agrees_on_every_state():
    out = V.compare_reference()
    for symbol, r in out.items():
        c = r["comparison"]
        assert c["confirmed_agrees"] and c["provisional_agrees"], symbol
        assert c["ceilings_matched"] == c["ceilings_ref"], symbol


# ---- Finnhub second source and the watchlist shadow

def test_finnhub_quote_mapping(monkeypatch):
    monkeypatch.setattr(finnhub, "_get", lambda path, **kw: {"c": 101.5, "h": 102, "l": 99.5, "o": 100, "pc": 100.2,
                                                              "t": 1793286000} if path == "/quote" else None)
    q = finnhub.quote("SYN")
    assert q == {"price": 101.5, "high": 102, "low": 99.5, "open": 100, "prev_close": 100.2, "time": 1793286000,
                 "source": "Finnhub"}


def _fq(price=101.0, low=99.0, high=102.0, when=NOW):
    return {"price": price, "low": low, "high": high, "time": when.timestamp()}


def test_finnhub_session_rejects_old_future_empty_and_inconsistent_quotes():
    assert W.finnhub_session(_fq(), NOW)["low"] == 99.0
    assert W.finnhub_session(_fq(when=datetime(2026, 10, 28, 19, 0, tzinfo=timezone.utc)), NOW) is None   # yesterday
    assert W.finnhub_session(_fq(when=datetime(2026, 10, 29, 15, 30, tzinfo=timezone.utc)), NOW) is None  # future
    assert W.finnhub_session(_fq(price=0), NOW) is None
    assert W.finnhub_session(_fq(price=105), NOW) is None                    # outside its own high/low
    assert W.finnhub_session(None, NOW) is None


def test_second_source_agreement_and_disagreement():
    yq = {"market_state": "REGULAR", "live_price": 101.2, "live_time": "2026-10-29T14:55:00+00:00"}
    assert W.second_source(yq, _fq(101.0), NOW)["status"] == "agree"
    bad = W.second_source(yq, _fq(105.0, high=106), NOW)
    assert bad["status"].startswith("DISAGREE") and bad["diff"] > 0.03
    assert W.second_source(None, _fq(), NOW)["status"].startswith("not compared")


def _snap(ticker, watch=False, verdict="HOLD", plan=None, tier=2):
    plan = plan or {"stance": "HOLD", "stop": 95.0, "targets": [{"price": 120.0, "label": "2R measured move"}]}
    return {"ticker": ticker, "verdict": verdict, "tier": tier, "payload": {"watchlist": watch, "plan": plan}}


def test_watchlist_row_for_an_unsupported_stock_keeps_the_legacy_call():
    hist = synthetic(500, start="2024-11-20")
    r = W.row(_snap("SYN"), hist, None, None, NOW, packets={})
    assert r["coverage"] == "unsupported" and r["action"] == "CIS UNSUPPORTED"
    assert r["alert_preview"] == "no change (legacy kept)" and r["legacy"]["stance"] == "HOLD"
    assert r["candidate"]["stage"] == "candidate"                              # a diagnostic, never a call
    assert r["discrepancy"]["legacy_target_is_measured_move"] is True


def test_watchlist_row_for_an_approved_packet_uses_finnhub_for_intraday_facts_only_when_sources_agree():
    isrg = D.reviewed_packets()["ISRG"]
    c = isrg["completed_close"]
    idx = pd.bdate_range("2026-06-01", "2026-10-28", tz="America/New_York")
    hist = pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1e6}, index=idx)
    yq = {"market_state": "REGULAR", "live_price": 445.0, "live_time": "2026-10-29T14:55:00+00:00"}
    r = W.row(_snap("ISRG", tier=1), hist, yq, _fq(445.2, low=420.0, high=446.0), NOW)
    assert r["coverage"] == "approved" and r["action"] == "HOLD" and r["second_source"]["status"] == "agree"
    assert any("Intraday: today's low went below 424" in x for x in r["reasons"])
    off = W.row(_snap("ISRG", tier=1), hist, yq, _fq(470.0, low=420.0, high=471.0), NOW)
    assert off["second_source"]["status"].startswith("DISAGREE")
    assert any("not available" in x for x in off["reasons"])                # a disagreeing source isn't used
    only_f = W.row(_snap("ISRG", tier=1), hist, None, _fq(445.2, low=440.0, high=446.0), NOW)
    assert any("Quote from Finnhub" in x for x in only_f["reasons"])


def test_watchlist_run_and_coverage_never_need_finnhub():
    class Prov:
        def history(self, t):
            if t == "BAD":
                raise RuntimeError("no data")
            return synthetic(500, start="2024-11-20")

        def quote(self, t):
            return {}
    rows = W.run([_snap("AAA"), _snap("BAD", watch=True)], Prov(), NOW)
    cov = W.coverage(rows)
    assert cov["unsupported"] == 2 and cov["data problems"] == 1 and cov["candidate available"] == 1
    assert all(r["second_source"]["status"].startswith("not compared") for r in rows)


def test_phase2_modules_stay_out_of_production_paths():
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "stockwatch"
    for name in ("engine.py", "tradeplan.py", "transitions.py", "ci_scan.py", "notify.py", "scanner.py", "live.py",
                 "data.py", "finnhub.py"):
        mods = [n.module or "" for n in ast.walk(ast.parse((root / name).read_text())) if isinstance(n, ast.ImportFrom)]
        assert not any("cis" in m for m in mods), name
