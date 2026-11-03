"""The one-call shadow layer (stockwatch/onecall.py). Synthetic bars only."""
import numpy as np

from stockwatch import onecall, status
from test_status import bars, ramp, with_floor, no_floor, NOW

REAL_LOG = onecall.log_call        # conftest turns the module's own log off for every test


def test_grade_and_timeframe():
    assert onecall.risk_grade(0.01, None, 80, -0.05)["grade"] == "Safe"
    assert onecall.risk_grade(0.07, 3, 30, -0.4)["grade"] == "Extreme"
    assert "unknown" in onecall.risk_grade(0.01, None, None)["why"]
    assert onecall.timeframe(1)["word"] == "SHORT"
    assert onecall.timeframe(3)["word"] == "MEDIUM"
    assert onecall.timeframe(6)["word"] == "SWING"
    assert onecall.timeframe(None) is None


def test_unknown_without_floor(monkeypatch):
    no_floor(monkeypatch)
    out = onecall.assess(bars(ramp()), now=NOW)
    assert out["call"] == "UNKNOWN" and not out["known"] and out["why"]


def test_unknown_short_history():
    assert onecall.assess(bars(ramp(50)), now=NOW)["call"] == "UNKNOWN"


def test_exit_and_avoid(monkeypatch):
    c = ramp()
    with_floor(monkeypatch, c[-1] * 1.02, c[-1] * 1.05)
    assert onecall.assess(bars(c), now=NOW, owned=True)["call"] == "EXIT"
    assert onecall.assess(bars(c), now=NOW, owned=False)["call"] == "AVOID"


def test_band_is_on_the_line(monkeypatch):
    c = ramp()
    bar = bars(c)
    with_floor(monkeypatch, c[-1] * 1.003, c[-1] * 1.02)       # a hair above the close: inside half a swing
    out = onecall.assess(bar, now=NOW, owned=True)
    assert out["call"] == "ON THE LINE" and out["band_line"] < out["exit_line"]


def test_log_writes_once_per_session(tmp_path):
    oc = {"known": True, "as_of": "2026-10-26", "call": "BUY", "close": 10, "exit_line": 9, "band_line": 8.8,
          "distance_swings": 1.0}
    assert REAL_LOG("ZZZ", oc, False, folder=tmp_path) is True
    assert REAL_LOG("ZZZ", oc, False, folder=tmp_path) is False
    assert len((tmp_path / "New call log.csv").read_text(encoding="utf-8-sig").splitlines()) == 2
    assert REAL_LOG("ZZY", {"known": False}, False, folder=tmp_path) is False


def test_far_above_line_is_hold_or_wait(monkeypatch):
    c = ramp()
    with_floor(monkeypatch, c[-1] * 0.5, c[-1] * 0.55)
    assert onecall.assess(bars(c), now=NOW, owned=True)["call"] == "HOLD"
    assert onecall.assess(bars(c), now=NOW, owned=False)["call"] == "WAIT"


def test_buy_when_turning_near_line(monkeypatch):
    c = list(ramp(400)[:-6] * 1.0)
    base = c[-1]
    c += [base * 0.97, base * 0.95, base * 0.94, base * 0.935, base * 0.93, base * 0.94]   # dips then ticks up
    arr = np.array(c)
    line = arr[-1] * 0.985
    with_floor(monkeypatch, line, line * 1.03)
    out = onecall.assess(bars(arr), now=NOW, owned=False, account=50_000)
    assert out["call"] in ("BUY", "WAIT FOR TURN")
    if out["call"] == "BUY":
        assert out["size"]["shares"] > 0 and out["timeframe"]
    held = onecall.assess(bars(arr), now=NOW, owned=True)
    assert held["call"] in ("ADD", "WAIT FOR TURN")


def test_earnings_blocks_buy_and_over_limit_is_note(monkeypatch):
    c = list(ramp(400)[:-3]) + [100.0, 99.0, 100.5]
    arr = np.array(c)
    with_floor(monkeypatch, 98.0, 99.0)
    out = onecall.assess(bars(arr), now=NOW, owned=True, earnings_days=1, position_pct=0.25, position_limit=0.15)
    assert out["call"] != "ADD" and out["over_limit"] is True
    assert any("earnings" in f for f in out["flags"])


def test_reuses_a_status_it_is_given(monkeypatch):
    c = ramp()
    with_floor(monkeypatch, c[-1] * 0.5, c[-1] * 0.55)
    st = status.assess(bars(c), now=NOW)
    monkeypatch.setattr(onecall.status, "assess", lambda *a, **k: (_ for _ in ()).throw(AssertionError("built twice")))
    assert onecall.assess(bars(c), now=NOW, st=st)["call"] == "WAIT"
