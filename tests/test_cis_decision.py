"""CIS replacement decision adapter (shadow): state names, state vs action, mandates, false-buy prevention."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from stockwatch.cis import decision as D
from stockwatch.cis import explain as X
from stockwatch.cis import level_packet as L
from stockwatch.cis import presentation as V
from stockwatch.cis import refdata
from stockwatch.cis import shadow

PACKETS = D.reviewed_packets()


def ref(symbol, held, tier=2, **changes):
    p = PACKETS[symbol]
    # the dated defense check is the only use of bars here; without the private data it has none (and the
    # reference outcomes don't depend on it: no reference passes the reward/risk filter)
    inp = D.inputs_from_packet(p, V.recent(X.report(symbol)) if refdata.available() else [])
    for k, v in changes.items():
        setattr(inp, k, v)
    return D.decide(p, inp, held, tier)


def roomy_packet(**edit):
    """PODD's packet with a distant first ceiling and no event, so only the entry checks decide."""
    d = L.thaw(PACKETS["PODD"].data)
    d.pop("verified_event")
    d["packet_id"] = "SYNTH-roomy-v1"
    d["upside"]["ceilings"] = [{"id": "c1", "zone": {"low": 170, "high": 175}, "current_quote_location": "below",
                                "confirmation": "pending", "anchor_evidence": []}]
    d.update(edit)
    return L.Packet(d)


PODD_CLOSE = PACKETS["PODD"]["completed_close"]
# defended after the levels were set (22 Oct): into the zone and back above 142, then held above it
DEFENDED = [{"session": "2026-10-23", "high": 146, "low": 141.5, "close": 143, "completed": True},
            {"session": "2026-10-26", "high": 149, "low": 143, "close": 148, "completed": True}]
NOT_DEFENDED = [{"session": "2026-10-23", "high": 150, "low": 145, "close": 148, "completed": True},
                {"session": "2026-10-26", "high": 150, "low": 146, "close": 148, "completed": True}]


def inputs(close, quote=None, recent=DEFENDED, **kw):
    kw.setdefault("as_of_close_now", PODD_CLOSE)
    return D.Inputs(close, "2026-10-26", quote, None, kw.pop("low", None), kw.pop("high", None),
                    kw.pop("later", []), recent, **kw)


# ---- names and the four references

def test_owner_state_names_are_used_and_internal_ids_unchanged():
    assert D.DOWN_LABEL == {"above_floor": "SUPPORT HOLD", "testing_floor": "SUPPORT HOLD · TESTING",
                            "warning": "SUPPORT BREAK", "failure": "TRADE INVALIDATED",
                            "major_damage": "TREND BREAKDOWN", "undetermined": "NO REVIEWED FLOOR"}
    assert {D.UP_LABEL[k] for k in ("testing", "close_above", "retest_defended", "failed_breakout")} == {
        "RESISTANCE TEST", "BREAKOUT CONFIRMED", "BREAKOUT RETEST HELD", "FAILED BREAKOUT"}
    assert X.STATE_LABEL is D.DOWN_LABEL and X.CEILING_LABEL is D.UP_LABEL


@pytest.mark.parametrize("symbol,held,tier,action", [
    ("ISRG", True, 1, "HOLD"), ("ISRG", False, 2, "WAIT"),
    ("FICO", True, 1, "HOLD"), ("FICO", False, 2, "WAIT"),
    ("PODD", True, 2, "HOLD"), ("PODD", False, 2, "WAIT"),
    ("CRDO", True, 1, "TRIM / REDUCE REVIEW"), ("CRDO", True, 2, "TRIM / REDUCE REVIEW"), ("CRDO", False, 2, "NO TRADE"),
])
def test_reference_outcomes_match_the_approved_mapping(symbol, held, tier, action):
    d = ref(symbol, held, tier)
    assert d["supported"] and d["action"] == action and d["no_order_placed"] and d["mode"] == "shadow"


def test_none_of_the_references_passes_the_entry_filter():
    for symbol, gross in (("ISRG", 1.375), ("FICO", 1.05), ("PODD", 0.889)):
        check = ref(symbol, False)["entry_check"]
        assert check["rr_gross"] == pytest.approx(gross, abs=0.001) and not check["passes_filter"]
        assert check["rr_net"] < check["rr_gross"] and check["rr_validated"] is False
    assert any("earnings" in b for b in ref("PODD", False)["entry_check"]["blocks"])


def test_crdo_exit_is_only_provisional_and_the_wick_is_intraday():
    d = ref("CRDO", True, 1)
    assert d["downside"]["confirmed"] == "SUPPORT BREAK" and d["downside"]["provisional"] == "TRADE INVALIDATED"
    assert any(r.startswith("Provisional") and "confirmed only if a session closes" in r for r in d["reasons"])
    assert any("below 149; the quote has recovered" in r for r in d["reasons"])
    assert d["action"] not in ("EXIT TACTICAL", "RISK — REVIEW REDUCTION/EXIT")


# ---- state vs action, mandates

def test_broken_levels_never_liquidate_without_a_known_mandate():
    p = PACKETS["PODD"]
    below_failure = inputs(132.0)
    assert D.decide(p, below_failure, True, 1)["action"] == "RISK — REVIEW REDUCTION/EXIT"     # core holding
    tier2 = D.decide(p, below_failure, True, 2)
    assert tier2["action"] == "REVIEW REQUIRED" and any("no trade contract" in r for r in tier2["reasons"])
    assert D.decide(p, below_failure, True, 2, tactical_contract=True)["action"] == "EXIT TACTICAL"
    assert D.decide(p, below_failure, False)["action"] == "NO TRADE"
    assert D.decide(p, inputs(120.0), True, 1)["downside"]["confirmed"] == "TREND BREAKDOWN"


@pytest.mark.parametrize("close,label,held_action,watch_action", [
    (142.0, "SUPPORT HOLD", "HOLD", "WAIT"),                                 # equal to the floor top: above
    (140.0, "SUPPORT HOLD · TESTING", "HOLD", "WAIT FOR SUPPORT CONFIRMATION"),  # equal to the floor low: testing
    (139.99, "SUPPORT BREAK", "TRIM / REDUCE REVIEW", "NO TRADE"),
    (133.0, "SUPPORT BREAK", "TRIM / REDUCE REVIEW", "NO TRADE"),            # equal to failure: not below it
    (132.99, "TRADE INVALIDATED", "REVIEW REQUIRED", "NO TRADE"),
    (126.0, "TRADE INVALIDATED", "REVIEW REQUIRED", "NO TRADE"),             # equal to major damage
    (125.99, "TREND BREAKDOWN", "REVIEW REQUIRED", "NO TRADE"),
])
def test_threshold_equality_and_actions(close, label, held_action, watch_action):
    p = PACKETS["PODD"]
    held, watch = D.decide(p, inputs(close), True, 2), D.decide(p, inputs(close), False)
    assert held["downside"]["confirmed"] == label
    assert (held["action"], watch["action"]) == (held_action, watch_action)


def test_entering_the_floor_zone_is_testing_not_a_proven_hold():
    d = D.decide(PACKETS["PODD"], inputs(141.0), False)
    assert d["downside"]["confirmed"] == "SUPPORT HOLD · TESTING" and d["category"] == "WAIT"
    assert any("without a proven defense" in r for r in d["reasons"])


def test_a_wick_or_quote_never_changes_the_confirmed_action():
    p = PACKETS["PODD"]
    wick = D.decide(p, inputs(148.0, quote=147.0, low=125.0), True, 1)
    assert wick["action"] == "HOLD" and wick["downside"]["confirmed"] == "SUPPORT HOLD"
    assert any(r.startswith("Intraday:") and "below 126" in r for r in wick["reasons"])
    crash = D.decide(p, inputs(148.0, quote=120.0), True, 1)
    assert crash["action"] == "HOLD" and crash["downside"]["provisional"] == "TREND BREAKDOWN"


def test_pennies_on_the_quote_never_move_levels_or_the_action():
    p = PACKETS["ISRG"]
    before = p.fingerprint
    a = D.decide(p, D.inputs_from_packet(p), False)
    b_inp = D.inputs_from_packet(p)
    b_inp.quote = 454.65
    b = D.decide(p, b_inp, False)
    assert a["levels"] == b["levels"] and a["action"] == b["action"] and p.fingerprint == before


# ---- upside states feed the decision

def test_upside_states_change_the_call():
    p = roomy_packet()
    zone_bar = lambda s, h, lo, c: {"session": s, "high": h, "low": lo, "close": c, "completed": True}  # noqa: E731
    breakout = [zone_bar("d1", 177, 171, 176)]
    assert D.decide(p, inputs(176.0, later=breakout), False)["action"] == "SETUP CANDIDATE"
    retest = breakout + [zone_bar("d2", 178, 174, 177)]
    d = D.decide(p, inputs(177.0, later=retest), False)
    assert d["action"] == "WAIT — REVIEW NEW FLOOR" and d["upside"][0]["label"] == "BREAKOUT RETEST HELD"
    failed = breakout + [zone_bar("d2", 172, 165, 168)]
    assert D.decide(p, inputs(168.0, later=failed), True, 1)["action"] == "REDUCE/EXIT REVIEW"
    assert D.decide(p, inputs(168.0, later=failed), False)["action"] == "NO TRADE"
    inside = breakout + [zone_bar("d2", 176, 170, 172)]
    unresolved = D.decide(p, inputs(172.0, later=inside), False)
    assert unresolved["upside"][0]["label"] == "RESISTANCE TEST" and unresolved["action"] == "WAIT"
    test = D.decide(p, inputs(165.0, quote=171.0, high=171.5), False)            # quote inside the band
    assert test["upside"][0]["label"] == "RESISTANCE TEST" and test["action"] == "WAIT"


# ---- false-buy prevention

def test_a_buy_proposal_needs_every_check_and_never_places_an_order():
    p = roomy_packet()
    ok = D.decide(p, inputs(148.0), False)
    assert ok["action"] == "BUY ON DIP (CONDITIONAL PROPOSAL)" and ok["stance"] == "BUY ON PULLBACK"
    assert ok["entry_check"]["worst_entry"] == 142 and ok["entry_check"]["passes_filter"]
    assert any("No order is placed" in r for r in ok["reasons"]) and ok["no_order_placed"]
    assert D.decide(p, inputs(148.0, recent=NOT_DEFENDED), False)["action"] == "SETUP CANDIDATE"
    evented = D.decide(p, inputs(148.0, event={"type": "earnings", "date": "2026-11-04"}), False)
    assert evented["action"] == "SETUP CANDIDATE"
    bad_data = D.decide(p, inputs(148.0, data_ok=False, data_note="stale bars"), False)
    assert bad_data["action"] == "DATA REVIEW" and not bad_data["supported"]
    assert D.decide(p, inputs(148.0), True, 1)["action"] == "HOLD"                # held: no buy from the adapter
    near = roomy_packet(upside={"ceilings": [{"id": "c1", "zone": {"low": 150, "high": 152},
                                              "current_quote_location": "below", "confirmation": "pending"}]})
    assert D.decide(near, inputs(148.0), False)["action"] == "WAIT"


def test_the_threshold_is_a_configurable_unvalidated_filter(monkeypatch):
    p = roomy_packet()
    assert D.rr_min() == (1.5, "default 1.5 (unvalidated)")
    monkeypatch.setenv(D.RR_ENV, "5")
    d = D.decide(p, inputs(148.0), False)
    assert d["action"] == "WAIT" and d["entry_check"]["rr_min"] == 5.0
    assert d["entry_check"]["rr_min_source"] == "STOCKWATCH_CIS_RR_MIN=5 (unvalidated)"
    for bad in ("abc", "0.5", "9"):
        monkeypatch.setenv(D.RR_ENV, bad)
        assert D.rr_min()[0] == 1.5 and "ignored invalid" in D.rr_min()[1]


# ---- unsupported, legacy, flag

def test_no_reviewed_packet_is_unsupported_and_never_relabelled():
    d = D.decide(None, None, True, 1)
    assert not d["supported"] and d["action"] == "CIS UNSUPPORTED" and d["category"] is None
    assert "legacy" in d["reasons"][0]
    cand = L.thaw(PACKETS["PODD"].data)
    cand.update(level_selection="code_candidate_unreviewed", review_status="code_candidate_unreviewed")
    assert D.decide(L.Packet(cand), inputs(148.0), False)["action"] == "CIS UNSUPPORTED"
    assert set(D.reviewed_packets()) == {"ISRG", "FICO", "CRDO", "PODD"}
    assert D.decide(PACKETS["PODD"], inputs(None), False)["action"] == "DATA REVIEW"


@pytest.mark.parametrize("value,expected", [(None, "off"), ("", "off"), ("on", "off"), ("active", "off"),
                                            ("shadow", "shadow"), (" SHADOW ", "shadow")])
def test_switch_is_off_by_default_and_has_no_active_mode(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv(D.FLAG, raising=False)
    else:
        monkeypatch.setenv(D.FLAG, value)
    assert D.mode() == expected


def test_the_adapter_feeds_nothing_in_production():
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "stockwatch"
    for name in ("engine.py", "tradeplan.py", "transitions.py", "ci_scan.py", "notify.py", "scanner.py", "live.py"):
        tree = ast.parse((root / name).read_text())
        mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not any("cis" in m for m in mods), name


# ---- live inputs

def test_live_inputs_use_completed_bars_and_a_validated_quote():
    p = PACKETS["PODD"]
    idx = pd.date_range("2026-10-01", "2026-10-30", freq="B", tz="America/New_York")
    hist = pd.DataFrame({"Open": 145.0, "High": 149.0, "Low": 144.0, "Close": 148.0, "Volume": 1e6}, index=idx)
    hist.loc[idx[idx.strftime("%Y-%m-%d") == "2026-10-22"], "Close"] = PODD_CLOSE
    now = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)                   # Friday 11:00 New York
    fresh = {"market_state": "REGULAR", "live_price": 147.5, "live_time": "2026-10-30T14:55:00+00:00"}
    inp = D.live_inputs(p, hist, fresh, now)
    assert inp.completed_session == "2026-10-29" and inp.quote == 147.5             # today's forming bar excluded
    assert [b["session"] for b in inp.later_bars][0] == "2026-10-23"
    stale = {"market_state": "REGULAR", "live_price": 100.0, "live_time": "2026-10-23T14:55:00+00:00"}
    assert D.live_inputs(p, hist, stale, now).quote is None                        # a week-old quote is refused
    assert D.live_inputs(p, None, fresh, now).data_ok is False
    assert D.decide(p, D.live_inputs(p, None, fresh, now), True, 1)["action"] == "DATA REVIEW"


# ---- shadow comparison

@pytest.mark.skipif(not refdata.available(), reason="private CIS reference data not installed")
def test_shadow_comparison_runs_old_and_new_on_the_same_frozen_bars():
    rows = shadow.compare()
    assert {r["symbol"] for r in rows} == {"ISRG", "FICO", "CRDO", "PODD"} and len(rows) == 13
    observed = next(r for r in rows if r["case"].endswith("(live app capture)"))
    assert observed["legacy"]["stance"] == "BUY NOW" and observed["cis"]["action"] == "WAIT"
    assert observed["legacy"]["target"][1] == "2R measured move"                  # the invented target CIS drops
    assert all(r["cis"]["no_order_placed"] for r in rows)
    md = shadow.markdown(rows)
    assert md.count("\n") == len(rows) + 1 and "BUY ON DIP" not in md


# ---- second-source comparison (offline helper)

def test_source_check_separates_adjustment_coverage_and_missing_sessions():
    from stockwatch.cis import source_check as C
    from cis_helpers import synthetic
    yahoo = synthetic(300)
    last = str(yahoo.index[-1].date())
    same = C.compare(yahoo, yahoo.copy(), ("yahoo", "copy"), last)
    assert same["status"] == "MATCH" and same["last_session"] == last
    iex = yahoo.copy()
    iex["Volume"] = iex["Volume"] * 0.03                                  # a single venue's share of volume
    iex = iex.drop(iex.index[-5])                                         # a missing session
    r = C.compare(yahoo, iex, ("yahoo", "iex"), last)
    assert r["volume_coverage_gap"] and r["only_in"]["yahoo"] and not r["adjustment_suspected"]
    raw = yahoo.copy()
    drift = pd.Series(range(len(raw)), index=raw.index) * 0.0001 + 1     # dividend adjustment grows back in time
    for k in ("Open", "High", "Low", "Close"):
        raw[k] = raw[k] * drift[::-1].values
    assert C.compare(yahoo, raw, ("adj", "raw"), last)["adjustment_suspected"]
    broken = yahoo.copy()
    broken.iloc[3, broken.columns.get_loc("Close")] = -1
    assert C.compare(yahoo, broken, ("a", "b"))["status"] == "NOT COMPARABLE"


# ---- second-round review fixes (ChatGPT, PR #30)

def test_proposed_levels_are_shadow_only_and_never_activation_eligible():
    podd, isrg = ref("PODD", True, 1), ref("ISRG", True, 1)
    assert PACKETS["PODD"].reviewed and not PACKETS["PODD"].approved and PACKETS["ISRG"].approved
    assert podd["approval"] == "proposed (not owner-accepted)" and podd["activation_eligible"] is False
    assert any("not accepted by the owner" in r for r in podd["reasons"])
    assert isrg["approval"] == "owner-accepted" and isrg["evaluation"] == "historical snapshot"
    assert isrg["activation_eligible"] is False                      # a frozen snapshot is never a current call
    assert any("Historical snapshot" in r for r in isrg["reasons"])


def test_stale_levels_stop_being_a_basis_for_a_call():
    p = PACKETS["PODD"]
    later = [{"session": f"2026-11-{d:02d}", "high": 150, "low": 146, "close": 148, "completed": True}
             for d in range(1, D.MAX_PACKET_SESSIONS + 2)]
    old = D.decide(p, inputs(148.0, later=later, evaluated_on="2026-11-24"), True, 1)
    assert old["action"] == "STALE LEVELS — REVIEW REQUIRED" and old["category"] == "REVIEW"
    assert old["downside"]["confirmed"] == "SUPPORT HOLD" and "would have been: HOLD" in old["reasons"][0]
    assert old["activation_eligible"] is False
    split = D.decide(p, inputs(148.0, as_of_close_now=PODD_CLOSE / 2), True, 1)      # a 2-for-1 split re-based history
    assert split["action"] == "STALE LEVELS — REVIEW REQUIRED" and "corporate action" in split["reasons"][0]
    missing = D.decide(p, inputs(148.0, as_of_close_now=None), False)
    assert missing["action"] == "STALE LEVELS — REVIEW REQUIRED"
    assert D.decide(p, inputs(148.0), True, 1)["action"] == "HOLD"                  # fresh and matching


def test_defense_must_come_after_the_levels_and_hold():
    p = roomy_packet()
    before = [{"session": "2026-10-20", "high": 146, "low": 141.5, "close": 143, "completed": True},
              {"session": "2026-10-21", "high": 149, "low": 143, "close": 148, "completed": True}]
    assert D.decide(p, inputs(148.0, recent=before), False)["action"] == "SETUP CANDIDATE"
    one_day = DEFENDED[:1]                                                              # no follow-through yet
    assert D.decide(p, inputs(143.0, recent=one_day), False)["action"] == "SETUP CANDIDATE"
    lost = DEFENDED + [{"session": "2026-10-27", "high": 143, "low": 139, "close": 141, "completed": True}]
    assert D.decide(p, inputs(148.0, recent=lost), False)["entry_check"]["defense"] is None
    assert D.decide(p, inputs(148.0), False)["entry_check"]["defense"] == "2026-10-23"


def test_missing_intraday_data_is_said_not_assumed():
    p = PACKETS["PODD"]
    d = D.decide(p, inputs(148.0, quote=147.0), True, 1)
    assert d["intraday_available"] is False
    assert all(b["crossed_below"] is None for b in d["downside"]["intraday"])
    assert any("not available" in r for r in d["reasons"])
    assert ref("CRDO", True, 1)["intraday_available"] is True
    no_quote = D.decide(p, inputs(148.0), True, 1)
    assert no_quote["downside"]["provisional"] == "NO CURRENT QUOTE" and no_quote["action"] == "HOLD"


# ---- Codex review of bac4f1f: reproductions

def daily(start, end, close=148.0, skip=()):
    idx = pd.date_range(start, end, freq="B", tz="America/New_York")
    idx = idx[[d.strftime("%Y-%m-%d") not in skip for d in idx]]
    h = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1e6}, index=idx)
    return h


def test_old_cached_history_is_data_review_not_a_current_hold():
    p = PACKETS["ISRG"]
    hist = daily("2026-06-01", "2026-10-22", close=p["completed_close"])            # ends on the packet day
    june = datetime(2027, 6, 1, 15, 0, tzinfo=timezone.utc)
    inp = D.live_inputs(p, hist, None, june)
    d = D.decide(p, inp, True, 1)
    assert inp.data_ok is False and "behind the expected 2027-05-31" in inp.data_note
    assert d["action"] == "DATA REVIEW" and not d.get("activation_eligible")
    # the next trading month with no new rows: still refused, the clock doesn't stop
    nov = datetime(2026, 11, 30, 15, 0, tzinfo=timezone.utc)
    assert D.decide(p, D.live_inputs(p, hist, None, nov), True, 1)["action"] == "DATA REVIEW"


def test_packet_age_runs_on_the_calendar_not_on_rows():
    p = PACKETS["ISRG"]
    hist = daily("2026-06-01", "2027-05-28", close=p["completed_close"])            # fresh data, old packet
    d = D.decide(p, D.live_inputs(p, hist, None, datetime(2027, 6, 1, 15, 0, tzinfo=timezone.utc)), True, 1)
    assert d["action"] == "STALE LEVELS — REVIEW REQUIRED" and d["activation_eligible"] is False
    fresh = daily("2026-06-01", "2026-10-28", close=p["completed_close"])
    ok = D.decide(p, D.live_inputs(p, fresh, None, datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)), True, 1)
    assert ok["action"] == "HOLD" and ok["evaluation"] == "live" and ok["activation_eligible"] is True
    assert D.weekdays_between("2026-10-22", "2026-10-23") == 0 and D.weekdays_between("2026-10-22", "2026-10-27") == 2


def test_missing_sessions_are_refused_but_one_holiday_is_allowed():
    p = PACKETS["ISRG"]
    now = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)
    holiday = daily("2026-06-01", "2026-10-28", close=p["completed_close"], skip=("2026-10-26",))
    assert D.live_inputs(p, holiday, None, now).data_ok is True
    gappy = daily("2026-06-01", "2026-10-28", close=p["completed_close"], skip=("2026-10-20", "2026-10-23", "2026-10-26"))
    inp = D.live_inputs(p, gappy, None, now)
    assert inp.data_ok is False and "missing" in inp.data_note
    assert D.decide(p, inp, True, 1)["action"] == "DATA REVIEW"


def _with_ledger(monkeypatch, tmp_path, *extra):
    """Simulate a reviewed ledger change that records more owner acceptances."""
    import json
    raw = json.loads(L.LEDGER.read_text())
    raw["acceptances"] += list(extra)
    path = tmp_path / "acceptances.json"
    path.write_text(json.dumps(raw))
    monkeypatch.setattr(L, "LEDGER", path)


def _live(packet, close=None):
    fresh = daily("2026-06-01", "2026-10-28", close=close or PACKETS["ISRG"]["completed_close"])
    return D.live_inputs(packet, fresh, None, datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc))


def test_a_revision_never_inherits_the_owner_acceptance(monkeypatch, tmp_path):
    isrg = PACKETS["ISRG"]
    v2 = L.new_version(isrg, {"downside": {**L.thaw(isrg.downside), "failure": 425}}, "tighter after a higher low",
                       "ISRG-2026-10-22-v2")
    assert isrg.approved and not v2.approved and v2["review_status"] == "analyst_proposed"
    assert v2["revision"]["supersedes"] == isrg.id
    assert not L.new_version(isrg, {}, "re-issued unchanged", "ISRG-2026-10-22-v2b").approved
    with pytest.raises(L.PacketError, match="can't be lowered"):
        L.new_version(isrg, {"downside": {**L.thaw(isrg.downside), "failure": 420}}, "price fell", "ISRG-v4")
    with pytest.raises(L.PacketError, match="new packet ID"):
        L.new_version(isrg, {}, "same id", isrg.id)
    # the owner accepts v2: a ledger entry is recorded (in a reviewed PR), and only then is it approved
    entry = L.acceptance_entry(v2, "owner accepted v2 in chat", "2026-10-24")
    v2_accepted = L.thaw(v2.data)
    v2_accepted["review_status"] = "user_accepted_in_chat"
    assert not L.Packet(v2_accepted).approved                          # status alone: still not approved
    _with_ledger(monkeypatch, tmp_path, entry)
    assert L.Packet(v2_accepted).approved
    assert D.decide(L.Packet(v2_accepted), _live(L.Packet(v2_accepted)), True, 1)["activation_eligible"] is True
    assert D.decide(v2, _live(v2), True, 1)["activation_eligible"] is False


def _edited(**edit):
    d = L.thaw(PACKETS["ISRG"].data)
    for path, value in edit.items():
        node = d
        *keys, last = path.split("__")
        for k in keys:
            node = node[int(k)] if isinstance(node, list) else node[k]
        node[last] = value
    return L.Packet(d)


@pytest.mark.parametrize("case,packet", [
    ("new ID, failure 424->425 (Codex)", lambda: _edited(packet_id="SYNTH-unaccepted-new-version", downside__failure=425)),
    ("new ID only", lambda: _edited(packet_id="ISRG-2026-10-22-copy")),
    ("same ID, changed failure", lambda: _edited(downside__failure=425)),
    ("same ID, changed ceiling", lambda: _edited(upside__ceilings__0__zone={"low": 465, "high": 466})),
    ("same ID, changed rationale", lambda: _edited(provenance__level_rationale="edited")),
    ("embedded acceptance copied from the original",
     lambda: _edited(downside__failure=425, acceptance={"packet_id": "ISRG-2026-10-22-v1",
                                                         "content_sha256": L.content_hash(PACKETS["ISRG"].data)})),
    ("revision metadata removed from a helper version", lambda: L.Packet({
        **{k: v for k, v in L.thaw(L.new_version(PACKETS["ISRG"], {"downside": {**L.thaw(PACKETS["ISRG"].downside),
                                                                                 "failure": 425}}, "r", "ISRG-v2").data).items()
           if k != "revision"}, "review_status": "user_accepted_in_chat"})),
])
def test_approval_fails_closed_for_any_unrecorded_content(case, packet):
    p = packet()
    assert p["review_status"] == "user_accepted_in_chat", case                  # every case claims acceptance
    assert not p.approved, case
    d = D.decide(p, _live(p), True, 1)
    assert d["approval"] == "proposed (not owner-accepted)" and d["activation_eligible"] is False, case


def test_the_pinned_originals_stay_approved_and_the_ledger_matches_the_handoff():
    for symbol in ("ISRG", "FICO", "CRDO"):
        p = PACKETS[symbol]
        assert p.approved and L.ledger()[p.id] == L.content_hash(p.data)
        assert D.decide(p, _live(p, p["completed_close"]), True, 1)["activation_eligible"] is True
    assert "PODD-2026-10-22-v1" not in L.ledger() and not PACKETS["PODD"].approved
    assert set(L.ledger()) == {"ISRG-2026-10-22-v1", "FICO-2026-10-22-v1", "CRDO-2026-10-22-v1"}
    with pytest.raises(L.PacketError, match="code candidate"):
        cand = L.thaw(PACKETS["PODD"].data)
        cand.update(level_selection="code_candidate_unreviewed", review_status="code_candidate_unreviewed")
        L.acceptance_entry(L.Packet(cand), "x", "2026-10-24")


def test_failed_breakout_stands_until_a_completed_close_back_above():
    from stockwatch.cis import state as S
    zone = {"low": 170, "high": 175}
    bar = lambda s, h, lo, c, done=True: {"session": s, "high": h, "low": lo, "close": c, "completed": done}  # noqa: E731
    base = [bar("d1", 177, 171, 176), bar("d2", 172, 165, 168)]
    assert S.ceiling_state(zone, base)["state"] == "failed_breakout"
    wick = S.ceiling_state(zone, base + [bar("d3", 171, 166, 169)])                 # Codex's sequence
    assert wick["state"] == "failed_breakout" and wick["tested_after_failure"]
    lower = S.ceiling_state(zone, base + [bar("d3", 167, 160, 162)])
    assert lower["state"] == "failed_breakout" and not lower["tested_after_failure"]
    inside = S.ceiling_state(zone, base + [bar("d3", 174, 168, 172)])               # back inside: unresolved
    assert inside["state"] == "failed_breakout" and inside["tested_after_failure"]
    forming = S.ceiling_state(zone, base + [bar("d3", 176, 168, 174, done=False)])
    assert forming["state"] == "failed_breakout" and forming["partial_attempt"]
    again = S.ceiling_state(zone, base + [bar("d3", 174, 168, 172), bar("d4", 178, 173, 177)])
    assert again["state"] == "close_above" and [e for _, e in again["events"]] == ["close_above", "failed_breakout", "close_above"]
    retest = S.ceiling_state(zone, base + [bar("d3", 178, 173, 177), bar("d4", 178, 174, 176)])
    assert retest["state"] == "retest_defended"
    p = roomy_packet()
    held = D.decide(p, inputs(169.0, later=base + [bar("d3", 171, 166, 169)]), True, 1)
    assert held["action"] == "REDUCE/EXIT REVIEW" and held["upside"][0]["label"] == "FAILED BREAKOUT"
    assert D.decide(p, inputs(169.0, later=base + [bar("d3", 171, 166, 169)]), False)["action"] == "NO TRADE"
    back = D.decide(p, inputs(177.0, later=base + [bar("d3", 178, 173, 177)]), False)
    assert back["action"] == "SETUP CANDIDATE" and back["upside"][0]["label"] == "BREAKOUT CONFIRMED"
