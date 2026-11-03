import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("co", Path(__file__).resolve().parent.parent / "scripts" / "candidates_outcomes.py")
co = importlib.util.module_from_spec(spec)
spec.loader.exec_module(co)


def test_kind_and_found_minutes():
    assert co.kind_of("Quick: up 1.0% = 0.8 daily ranges (breakout candidate) + New call: BUY") == "breakout"
    assert co.kind_of("New call: ADD") == "newcall"
    assert co.found_minutes("refresh 10:05") == 605
    assert co.found_minutes("pre-open 09:20") == 570
    assert co.found_minutes("not on the list") is None


def test_forward_returns():
    bars = [(600 + 5 * i, 100 + i * 0.5) for i in range(30)]          # 10:00 .. 12:25, rising 0.5 per bar
    f = co.forward(bars, 600)
    assert f["p30"] == 3.0 and f["p60"] == 6.0 and f["worst"] == 0.0
    assert co.forward(bars, 800) is None                               # found after the data ends
    short = co.forward(bars[:4], 600)
    assert short["p30"] is None and short["p60"] is None              # not enough bars: unknown, not 0
