"""Support and resistance numbers on the rows, and Finnhub's technical read as a second opinion. Offline, fakes only."""
import pytest

from stockwatch import data, finnhub, status, ui
from stockwatch.config import Holding
from stockwatch.data import DemoProvider
from stockwatch.engine import evaluate

from test_ci_scan import ev
from test_status import NOW, bars, ramp
from test_status_wiring import LEVELS, ps, snap_of
from test_stockwatch import make_portfolio


def with_ceilings(monkeypatch, low, high, ceilings):
    dn = {"zone": {"low": low, "high": high}, "warning": low, "failure": low * 0.97, "major_damage": low * 0.90}
    up = {"ceilings": [{"zone": {"low": a, "high": b}} for a, b in ceilings]}
    monkeypatch.setattr(status.candidates, "extract", lambda df, sym, src, *a, **k: ({"downside": dn, "upside": up}, {}))


# ---- resistance in the status levels

def test_the_nearest_ceiling_above_the_close_is_the_resistance(monkeypatch):
    c = ramp()
    price = c[-1]
    with_ceilings(monkeypatch, price * 0.8, price * 0.82, [(price * 0.9, price * 0.95), (price * 1.1, price * 1.12), (price * 1.3, price * 1.32)])
    lv = status.assess(bars(c), NOW)["levels"]
    assert lv["resist_low"] == pytest.approx(price * 1.1) and lv["resist_high"] == pytest.approx(price * 1.12)


def test_no_ceiling_above_means_no_resistance_number(monkeypatch):
    c = ramp()
    with_ceilings(monkeypatch, c[-1] * 0.8, c[-1] * 0.82, [])
    assert "resist_low" not in status.assess(bars(c), NOW)["levels"]


# ---- the row and Details numbers

def lv_snap(code="breakdown", **extra):
    e = ev("HOOD", "HOLD")
    e.technical = {"price_status": ps(code, levels={**LEVELS, **extra})}
    return snap_of(e)


def test_the_row_shows_support_deeper_and_resistance():
    html = ui.row(lv_snap(resist_low=104.5, resist_high=106.0))
    assert "S 98.00 · deeper 90.00 · R 104.50" in html


def test_the_row_leaves_out_resistance_when_there_is_none_and_the_line_when_there_is_no_floor():
    assert ui.levels_line(lv_snap()) == "S 98.00 · deeper 90.00"
    e = ev("HOOD", "HOLD")
    e.technical = {"price_status": ps("weakening", floor=False)}
    assert ui.levels_line(snap_of(e)) == "" and "LEVELS" not in ui.row(snap_of(e))
    old = ev("HOOD", "HOLD")                         # a snapshot saved before statuses existed
    assert ui.levels_line(snap_of(old)) == ""


def test_details_names_the_resistance_zone():
    assert "resistance 104.50 to 106.00" in ui.status_note(lv_snap(resist_low=104.5, resist_high=106.0))


# ---- comparing another source with our status

RAW = {"source": "Finnhub", "signal": "sell", "buy": 3, "neutral": 4, "sell": 12, "trending": True,
       "levels": [88.0, 93.5, 101.2, 110.0]}


def test_a_matching_read_confirms_a_clashing_one_disagrees_a_neutral_one_is_mixed():
    out = status.second_opinion("breakdown", RAW, 96.0)
    assert out["verdict"] == "confirms" and out["agrees"] is True and out["support"] == 93.5 and out["resistance"] == 101.2
    assert status.second_opinion("breakdown", {**RAW, "signal": "buy"}, 96.0)["verdict"] == "disagrees"
    assert status.second_opinion("breakdown", {**RAW, "signal": "neutral"}, 96.0)["verdict"] == "mixed"
    assert status.second_opinion("record_high", {**RAW, "signal": "buy"}, 96.0)["verdict"] == "confirms"
    assert status.second_opinion("record_high", RAW, 96.0)["verdict"] == "disagrees"


def test_nothing_usable_is_nothing_not_a_guess():
    assert status.second_opinion("breakdown", None, 96.0) is None
    assert status.second_opinion("breakdown", {}, 96.0) is None
    assert status.second_opinion("unknown", RAW, 96.0) is None
    only_levels = status.second_opinion("breakdown", {"levels": [93.5]}, 96.0)
    assert only_levels["verdict"] is None and only_levels["support"] == 93.5       # levels alone are still shown
    assert status.second_opinion("breakdown", {"signal": "hold?"}, 96.0) is None    # an unrecognised signal says nothing
    junk = status.second_opinion("breakdown", {**RAW, "levels": [float("nan"), -1, "x", None, 93.5]}, 96.0)
    assert junk["support"] == 93.5


def test_the_second_opinion_line():
    sec = status.second_opinion("breakdown", RAW, 96.0)
    line = ui.second_note({"second": sec})
    assert line.startswith("Finnhub: SELL (12 sell, 4 neutral, 3 buy) · confirms · its support 93.50, resistance 101.20.")
    assert "changes no call" in line
    assert ui.second_note({}) == "" and ui.second_note(None) == ""
    e = ev("HOOD", "HOLD")
    e.technical = {"price_status": ps("breakdown", second=sec)}
    assert "Finnhub: SELL" in ui.status_note(snap_of(e))


# ---- Finnhub parsing and failure handling

def fake_get(responses):
    def _get(path, **params):
        r = responses[path]
        if isinstance(r, Exception):
            raise r
        return r
    return _get


GOOD = {"/scan/technical-indicator": {"technicalAnalysis": {"count": {"buy": 3, "neutral": 4, "sell": 12}, "signal": "sell"},
                                      "trend": {"adx": 31.0, "trending": True}},
        "/scan/support-resistance": {"levels": [88.0, 93.5, 101.2]}}


def test_finnhub_maps_both_endpoints(monkeypatch):
    monkeypatch.setattr(finnhub, "_get", fake_get(GOOD))
    out = finnhub.second_opinion("HOOD")
    assert out == {"source": "Finnhub", "signal": "sell", "buy": 3, "neutral": 4, "sell": 12, "trending": True,
                   "levels": [88.0, 93.5, 101.2]}


def test_finnhub_survives_a_premium_only_endpoint_and_a_total_outage(monkeypatch):
    forbidden = OSError("HTTP Error 403: Forbidden")
    monkeypatch.setattr(finnhub, "_get", fake_get({**GOOD, "/scan/technical-indicator": forbidden}))
    out = finnhub.second_opinion("HOOD")
    assert out["signal"] is None and out["levels"] == [88.0, 93.5, 101.2]
    monkeypatch.setattr(finnhub, "_get", fake_get({k: forbidden for k in GOOD}))
    assert finnhub.second_opinion("HOOD") is None
    monkeypatch.setattr(finnhub, "_get", fake_get({k: {} for k in GOOD}))
    assert finnhub.second_opinion("HOOD") is None


def test_the_cache_asks_finnhub_once_and_keeps_an_older_read_through_a_failed_refresh(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    data._SECOND.clear()
    calls = []

    def fake(ticker):
        calls.append(ticker)
        return RAW
    monkeypatch.setattr(finnhub, "second_opinion", fake)
    assert data.second_opinion("A") == RAW and data.second_opinion("A") == RAW and calls == ["A"]
    clock = [data.time.monotonic()]
    monkeypatch.setattr(data.time, "monotonic", lambda: clock[0] + data.SECOND_TTL + 1)
    monkeypatch.setattr(finnhub, "second_opinion", lambda t: None)
    assert data.second_opinion("A") == RAW                                         # the failed refresh doesn't blank it
    data._SECOND.clear()


def test_without_a_key_there_is_no_request(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    data._SECOND.clear()
    monkeypatch.setattr(finnhub, "_get", lambda *a, **k: pytest.fail("no key, so no request"))
    assert data.second_opinion("A") is None
    data._SECOND.clear()


# ---- the engine

def test_the_engine_asks_only_for_weak_or_broken_stocks(monkeypatch):
    asked = []
    monkeypatch.setattr(data, "second_opinion", lambda t: asked.append(t) or RAW)
    monkeypatch.setattr(status, "assess", lambda *a, **k: ps("breakdown"))
    e = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    sec = e.technical["price_status"]["second"]
    assert asked == ["AAA"] and sec["verdict"] == "confirms"
    monkeypatch.setattr(status, "assess", lambda *a, **k: ps("record_high"))
    e = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    assert asked == ["AAA"] and "second" not in e.technical["price_status"]       # a healthy stock costs no request
    monkeypatch.setattr(status, "assess", lambda *a, **k: ps("breakdown"))
    evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider(), light=True)
    assert asked == ["AAA"]                                                         # screening runs stay light


def test_a_failing_second_source_never_breaks_the_evaluation(monkeypatch):
    def boom(t):
        raise RuntimeError("Finnhub down")
    monkeypatch.setattr(data, "second_opinion", boom)
    monkeypatch.setattr(status, "assess", lambda *a, **k: ps("breakdown"))
    e = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    assert e.technical["price_status"]["code"] == "breakdown" and e.technical["price_status"]["second"]["unavailable"]


def test_the_second_opinion_changes_no_call(monkeypatch):
    monkeypatch.setattr(status, "assess", lambda *a, **k: ps("breakdown"))
    monkeypatch.setattr(data, "second_opinion", lambda t: None)
    a = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    monkeypatch.setattr(data, "second_opinion", lambda t: {**RAW, "signal": "buy"})
    b = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    assert (a.verdict, a.plan) == (b.verdict, b.plan)


# ---- never silent: the screen says why there is no second opinion

def test_the_reason_depends_on_whether_a_key_is_set():
    assert "no FINNHUB_API_KEY" in status.second_unavailable(False)["unavailable"]
    assert "paid plan" in status.second_unavailable(True)["unavailable"]


def test_the_engine_records_why_when_finnhub_gives_nothing(monkeypatch):
    monkeypatch.setattr(status, "assess", lambda *a, **k: ps("breakdown"))
    monkeypatch.setattr(data, "second_opinion", lambda t: None)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    e = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    assert "no FINNHUB_API_KEY" in e.technical["price_status"]["second"]["unavailable"]
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    e = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    assert "paid plan" in e.technical["price_status"]["second"]["unavailable"]
    monkeypatch.setattr(status, "assess", lambda *a, **k: ps("record_high"))
    e = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    assert "second" not in e.technical["price_status"]                              # healthy stocks aren't asked


def test_details_says_no_read_with_the_reason():
    line = ui.second_note({"second": status.second_unavailable(False)})
    assert line == ("TradingView / Finnhub: no read. TradingView answered nothing for this stock, "
                    "and no FINNHUB_API_KEY is set.")


def snap_second(sec):
    e = ev("SNAP", "HOLD")
    e.technical = {"price_status": ps("testing_support", second=sec)}
    return snap_of(e)


def test_the_row_carries_a_short_finnhub_tag():
    confirms = status.second_opinion("testing_support", RAW, 96.0)
    assert "<b>FINNHUB</b>confirms · SELL" in ui.row(snap_second(confirms))
    clash = status.second_opinion("testing_support", {**RAW, "signal": "buy"}, 96.0)
    assert ui.second_tag(snap_second(clash)) == "disagrees · BUY"
    mixed = status.second_opinion("testing_support", {**RAW, "signal": "neutral"}, 96.0)
    assert ui.second_tag(snap_second(mixed)) == "mixed · NEUTRAL"
    assert ui.second_tag(snap_second(status.second_opinion("testing_support", {"levels": [93.5]}, 96.0))) == "levels only"
    assert ui.second_tag(snap_second(status.second_unavailable(True))) == "no read"
    assert "<b>FINNHUB</b>no read" in ui.row(snap_second(status.second_unavailable(False)))


def test_a_healthy_row_shows_no_finnhub_line():
    e = ev("SNAP", "HOLD")
    e.technical = {"price_status": ps("record_high")}
    assert ui.second_tag(snap_of(e)) == "" and "FINNHUB" not in ui.row(snap_of(e))
