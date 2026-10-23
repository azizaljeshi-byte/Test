"""CIS chart framework v1: frozen-fixture acceptance and the method's invariants. No network."""
import json
import math

import numpy as np
import pandas as pd
import pytest

from stockwatch.cis import features as F
from stockwatch.cis import history as H
from stockwatch.cis import level_packet as L
from stockwatch.cis import state as S

FIX = L.FIXTURES
BOUNDARY = "2026-10-22"
STOCK_CSV = {"ISRG": "ISRG-adjusted-daily.csv", "FICO": "FICO-20261023-adjusted.csv",
             "CRDO": "CRDO-CRDO-20261023-adjusted.csv", "PODD": "PODD-PODD-20261023-adjusted.csv"}
BENCH_CSV = {"FICO": ("SPY-20261023-adjusted.csv", "XLK", "XLK-20261023-adjusted.csv"),
             "CRDO": ("CRDO-SPY-20261023-adjusted.csv", "XLK", "CRDO-XLK-20261023-adjusted.csv"),
             "PODD": ("PODD-SPY-20261023-adjusted.csv", "XLV", "PODD-XLV-20261023-adjusted.csv")}
ACC = L.load_acceptance()


def bars(symbol, through=BOUNDARY):
    return F.completed(F.read_csv(FIX / STOCK_CSV[symbol]), through)


def evidence(symbol):
    return json.loads((FIX / f"{symbol}-independent-evidence.json").read_text())


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol * max(1.0, abs(b))


# ---- provenance and data quality

def test_fixture_files_match_the_handoff_manifest():
    manifest = json.loads((FIX / "CIS-handoff-manifest.json").read_text())
    shipped = {f["name"]: f["sha256"] for f in manifest["files"] if (FIX / f["name"]).exists()}
    assert len(shipped) >= 20
    for name, digest in shipped.items():
        assert F.sha256_file(FIX / name) == digest, name


@pytest.mark.parametrize("symbol", sorted(STOCK_CSV))
def test_reference_series_pass_the_quality_checks(symbol):
    q = F.check(F.read_csv(FIX / STOCK_CSV[symbol]), symbol)
    assert q.usable and q.problems == [] and q.first and q.last == "2026-10-23"


def test_malformed_bars_are_refused_not_repaired():
    good = bars("PODD").iloc[-30:].copy()
    cases = {
        "non-finite or non-positive prices": lambda d: d.assign(Close=d.Close.where(d.index != d.index[5], -1.0)),
        "high/low don't contain open and close": lambda d: d.assign(High=d.High.where(d.index != d.index[3], d.Low - 1)),
        "missing or negative volume": lambda d: d.assign(Volume=d.Volume.where(d.index != d.index[2], -5)),
        "duplicate dates": lambda d: pd.concat([d, d.iloc[[-1]]]),
        "dates not in ascending order": lambda d: d.iloc[::-1],
        "not daily bars": lambda d: d.iloc[::21],
    }
    for why, broken in cases.items():
        q = F.check(broken(good), "PODD")
        assert not q.usable and any(why in p for p in q.problems), why
    zero = good.assign(Volume=good.Volume.where(good.index != good.index[4], 0))
    q = F.check(zero, "PODD")
    assert q.usable and "zero-volume" in q.limitations[0]          # flagged, not filled


def test_the_forming_session_never_enters_completed_indicators():
    raw = F.read_csv(FIX / STOCK_CSV["PODD"])
    assert str(raw.index[-1].date()) == "2026-10-23"                 # the partial 23 Oct bar is in the file
    done = F.completed(raw, BOUNDARY)
    assert str(done.index[-1].date()) == BOUNDARY
    now = pd.Timestamp("2026-10-23T16:22:12Z").to_pydatetime()
    assert str(F.default_boundary(raw.index, now)) == BOUNDARY


# ---- indicators

@pytest.mark.parametrize("symbol", sorted(STOCK_CSV))
def test_indicators_reproduce_the_reference_metrics(symbol):
    m, ev = F.metrics(bars(symbol)), evidence(symbol)["metrics"]
    for k, v in ev.items():
        assert close(m[k], v), (k, m[k], v)


@pytest.mark.parametrize("symbol", sorted(BENCH_CSV))
def test_relative_returns_against_spy_and_the_sector_proxy(symbol):
    spy_file, sector, sector_file = BENCH_CSV[symbol]
    rs = evidence(symbol)["rs"]
    for name, f in (("SPY", spy_file), (sector, sector_file)):
        bench = F.completed(F.read_csv(FIX / f), BOUNDARY)
        for n in (21, 63):
            assert close(F.relative_return(bars(symbol), bench, n), rs[f"{name}{n}"])
    assert F.relative_return(bars(symbol), None, 21) is None                # missing benchmark stays unknown


@pytest.mark.parametrize("symbol", sorted(STOCK_CSV))
def test_weekly_bars_match_and_the_current_week_is_flagged_incomplete(symbol):
    wk = F.weekly(bars(symbol))
    assert bool(wk["incomplete"].iloc[-1])                                  # Thursday 22 Oct: week not done
    done = wk[~wk["incomplete"]]
    for row in evidence(symbol)["weekly"]:
        r = done.loc[row[0]]
        assert [round(r.Open, 2), round(r.High, 2), round(r.Low, 2), round(r.Close, 2)] == pytest.approx(row[1:5], abs=0.006)
        assert r.Volume == row[5]


def test_rsi_edge_conventions_and_unavailable_history():
    up = pd.Series(np.arange(1.0, 31.0))
    down, flat = up[::-1].reset_index(drop=True), pd.Series([5.0] * 30)
    assert F.rsi(up).iloc[-1] == 100 and F.rsi(down).iloc[-1] == 0 and F.rsi(flat).iloc[-1] == 50
    assert F.rsi(up).iloc[:14].isna().all()                                 # fewer than 14 changes
    m = F.metrics(bars("PODD").iloc[:30])
    assert m["ma50"] is None and m["ma200"] is None and m["rsi"] is not None  # unknown, never 0


def test_relative_volume_excludes_the_signal_day():
    df = bars("PODD")
    m = F.metrics(df)
    prior = df["Volume"].iloc[-21:-1].mean()
    assert m["volavg20"] == prior and m["rv"] == df["Volume"].iloc[-1] / prior


def test_future_rows_cannot_change_past_indicators():
    full, cut = F.indicators(bars("CRDO")), F.indicators(bars("CRDO", "2026-06-30"))
    common = cut.index
    pd.testing.assert_frame_equal(full.loc[common], cut)


# ---- level packets

def test_reference_packets_validate_and_reproduce_their_states():
    for symbol, p in ACC["packets"].items():
        r, e = S.evaluate(p), p["expected"]
        assert (r["confirmed_state"], r["quote_state"]) == (e["confirmed_state"], e["quote_state"]), symbol
        assert r["session_extreme_breaches"] == L.thaw(e["session_extreme_breaches"]), symbol
        assert [x["location"] for x in S.ladder(p)] == [c["current_quote_location"] for c in p.ceilings]
        assert p["completed_close"] == pytest.approx(bars(symbol)["Close"].iloc[-1])


def test_crdo_keeps_confirmed_provisional_and_intraday_facts_apart():
    r = S.evaluate(ACC["packets"]["CRDO"])
    assert r["confirmed_state"] == "warning" and r["quote_state"] == "failure" and r["quote_is_provisional"]
    major = next(b for b in r["session_extreme_breaches"] if b["threshold"] == "major_damage")
    assert major["crossed_below"] and major["quote_recovered_at_or_above"]  # wick below 149, quote back above


def test_podd_is_above_its_floor_but_under_its_first_ceiling():
    p = ACC["packets"]["PODD"]
    assert S.evaluate(p)["confirmed_state"] == "above_floor"
    first = S.ladder(p)[0]
    assert first["location"] == "below" and first["confirmation"] == "pending"
    assert p["verified_event"]["date"] == "2026-11-04" and p["review_status"] == "analyst_proposed"


@pytest.mark.parametrize("v", ACC["synthetic_downside_vectors"], ids=lambda v: v["id"])
def test_synthetic_downside_vectors(v):
    p = ACC["packets"][v["symbol"]]
    before = p.fingerprint
    assert S.downside_state(v["price"], p.downside) == v["expected"]
    assert S.evaluate(p, quote=v["price"])["quote_state"] == v["expected"]
    assert p.fingerprint == before == L.fingerprint(p.data)


@pytest.mark.parametrize("v", ACC["synthetic_upside_vectors"], ids=lambda v: v["id"])
def test_synthetic_upside_vectors(v):
    r = S.ceiling_state(v["zone"], v["bars"])
    assert r["state"] == v["expected"] and r["retest_confirmed"] == v["expected_retest_confirmed"]


def test_isrg_small_quote_change_never_moves_levels():
    p = ACC["packets"]["ISRG"]
    a, b = S.evaluate(p, quote=454.65), S.evaluate(p, quote=454.67)
    assert a["quote_state"] == b["quote_state"] == "above_floor"
    assert S.ladder(p, 454.65)[0]["low"] == S.ladder(p, 454.67)[0]["low"] == 462
    assert p.downside["failure"] == 424 and p.fingerprint == L.fingerprint(L.thaw(p.data))


def test_packets_are_immutable_and_revisions_are_explicit():
    p = ACC["packets"]["PODD"]
    with pytest.raises(AttributeError):
        p.data = {}
    with pytest.raises(TypeError):
        p.downside["failure"] = 120
    raised = L.new_version(p, {"downside": {**L.thaw(p.downside), "failure": 135}}, "higher low confirmed",
                           "PODD-2026-10-23-v2")
    assert raised.downside["failure"] == 135 and p.downside["failure"] == 133 and raised.id != p.id
    with pytest.raises(L.PacketError, match="can't be lowered"):
        L.new_version(p, {"downside": {**L.thaw(p.downside), "failure": 130}}, "price fell", "PODD-v3")
    with pytest.raises(L.PacketError, match="needs a reason"):
        L.new_version(p, {}, " ", "PODD-v4")


def test_packet_cross_field_rules():
    base = L.thaw(ACC["packets"]["PODD"].data)

    def bad(**edit):
        d = json.loads(json.dumps(base))
        for path, value in edit.items():
            node = d
            *keys, last = path.split("__")
            for k in keys:
                node = node[k]
            node[last] = value
        return L.problems(d)

    assert L.problems(base) == []
    assert any("ordered" in x for x in bad(downside__failure=141))
    assert any("sum to 100" in x for x in bad(scenarios__weights_pct={"up": 40, "sideways": 35, "down": 30}))
    assert any("5-point" in x for x in bad(scenarios__weights_pct={"up": 33, "sideways": 33, "down": 34}))
    assert any("ascending" in x for x in bad(upside__ceilings=[base["upside"]["ceilings"][1], base["upside"]["ceilings"][0]]))
    assert any("explain_only" in x for x in bad(action_mode="trade"))
    assert any("code_candidate" in x for x in bad(level_selection="code_candidate_unreviewed"))
    assert any("subjective" in x for x in bad(scenarios__method="calibrated"))


def test_undetermined_without_a_constructive_floor():
    assert S.downside_state(150.0, None) == "undetermined"
    assert S.downside_state(None, ACC["packets"]["PODD"].downside) == "undetermined"


def test_ceiling_gap_clears_without_inventing_a_visit_and_partial_bars_never_confirm():
    zone = {"low": 150, "high": 152}
    gap = S.ceiling_state(zone, [{"session": "d1", "high": 160, "low": 155, "close": 158, "completed": True}])
    assert gap["state"] == "close_above" and not gap["retest_confirmed"]
    forming = S.ceiling_state(zone, [{"session": "d1", "high": 154, "low": 151, "close": 153, "completed": True},
                                     {"session": "d2", "high": 153, "low": 150.5, "close": 152.5, "completed": False}])
    assert forming["state"] == "close_above" and forming["partial_attempt"] and not forming["retest_confirmed"]


# ---- history

@pytest.mark.parametrize("symbol", sorted(STOCK_CSV))
def test_history_reproduces_the_reference_analogues(symbol):
    ev = evidence(symbol)
    got = H.analogues(bars(symbol), H.POLICIES[symbol])
    assert [a["date"] for a in got["analogues"]] == [a["date"] for a in ev["analogues"]]
    for mine, want in zip(got["analogues"], ev["analogues"]):
        for k, v in want.items():
            if k == "path":
                assert mine[k] == pytest.approx(v, abs=1e-3)
            elif k == "returns":
                assert {h: mine[k][h] for h in v} == pytest.approx(v, rel=1e-9)
            elif isinstance(v, float):
                assert close(mine[k], v), (symbol, want["date"], k)
            else:
                assert mine[k] == v, (symbol, want["date"], k)
    if "history_summary" in ev:
        want, mine = ev["history_summary"], got["summary"]
        assert (mine["n"], mine["counts"]) == (want["n"], want["counts"])
        for h, stats in want["returns"].items():
            assert mine["returns"][h] == pytest.approx(stats, rel=1e-9)
        assert close(mine["median_mfe"], want["median_mfe"]) and close(mine["median_mae"], want["median_mae"])


def test_history_selection_is_causal_and_unobserved_outcomes_are_null():
    df = bars("PODD")
    pol = H.POLICIES["PODD"]
    base = H.select(F.indicators(df), pol)
    future = df.copy()
    future.loc[future.index[-5:], ["Open", "High", "Low", "Close"]] *= 3      # rewrite the most recent rows
    f2 = F.indicators(future)
    early = [i for i in base if i + 20 < len(df) - 25]
    assert [i for i in H.select(f2, pol) if i in early] == early
    i = len(df) - 8                                                          # a signal 7 sessions ago
    out = H.outcome(df, F.indicators(df), i, pol)
    assert out["returns"]["5"] is not None and out["returns"]["10"] is None and out["returns"]["20"] is None
    assert out["category"] is None and len(out["path"]) == 8


def test_history_counts_reconcile_and_rates_are_not_probabilities():
    for symbol in STOCK_CSV:
        got = H.analogues(bars(symbol), H.POLICIES[symbol])
        s = got["summary"]
        assert sum(s["counts"].values()) == s["n"] == len(got["analogues"])
        assert all(not math.isnan(a["distance"]) for a in got["analogues"])
        assert "probab" not in got["rule"].lower()
