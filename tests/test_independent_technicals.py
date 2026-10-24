"""TradingView's rating and Stooq's price re-check as independent second sources. Offline, fakes only."""
import pandas as pd
import pytest

from stockwatch import data, stooq, tradingview


def tv_row(name, rating, exchange="NASDAQ", adx=30.0):
    d = [name, 100.0, rating, rating, rating, 55.0, adx, 80.0, 85.0, 90.0, 95.0, 105.0, 110.0, 120.0]
    return {"s": f"{exchange}:{name}", "d": d}


def test_signal_thresholds():
    assert tradingview.signal(0.6) == ("buy", True)
    assert tradingview.signal(0.2) == ("buy", False)
    assert tradingview.signal(0.0) == ("neutral", False)
    assert tradingview.signal(-0.2) == ("sell", False)
    assert tradingview.signal(-0.7) == ("sell", True)
    assert tradingview.signal(None) == (None, False)


def test_read_prefers_a_real_us_listing_and_skips_unknown(monkeypatch):
    monkeypatch.setattr(tradingview, "_post", lambda p: {"data": [tv_row("INTC", 0.5, "OTC"), tv_row("INTC", -0.4, "NASDAQ")]})
    out = tradingview.read(["intc", "ZZZZ"])
    assert out["INTC"]["signal"] == "sell" and "ZZZZ" not in out
    assert out["INTC"]["levels"] == [80.0, 85.0, 90.0, 95.0, 105.0, 110.0, 120.0]


def test_a_failed_tradingview_call_is_no_read_not_an_error():
    assert tradingview.second_opinion("INTC") is None      # conftest blocks the network


def test_data_second_opinion_uses_tradingview_first(monkeypatch):
    monkeypatch.setattr(tradingview, "_post", lambda p: {"data": [tv_row("INTC", -0.4)]})
    assert data.second_opinion("INTC")["source"] == "TradingView"


CSV = "Date,Open,High,Low,Close,Volume\n" + "\n".join(
    f"2026-10-{d:02d},1,1,1,{100 + d},10" for d in range(1, 15)) + "\n"


def ours(shift=0.0, upto=14):
    idx = pd.to_datetime([f"2026-10-{d:02d}" for d in range(1, upto + 1)])
    return pd.Series([(100 + d) * (1 + (shift if d == upto else 0)) for d in range(1, upto + 1)], index=idx)


def test_parse_reads_closes_and_rejects_no_data():
    s = stooq.parse(CSV)
    assert len(s) == 14 and s.iloc[-1] == 114.0
    assert stooq.parse("No data") is None and stooq.parse("") is None


def test_matching_closes_agree():
    out = stooq.compare(ours(), stooq.parse(CSV))
    assert out["verdict"] == "matches" and out["agrees"] is True


def test_a_bad_close_is_called_out_with_the_day():
    out = stooq.compare(ours(shift=0.05), stooq.parse(CSV))
    assert out["verdict"] == "differs" and out["agrees"] is False
    assert out["worst_day"] == "2026-10-14" and "may be wrong" in out["note"]


def test_too_little_overlap_says_why_and_never_guesses():
    out = stooq.compare(ours(upto=3), stooq.parse(CSV))
    assert "agrees" not in out and "overlap" in out["unavailable"]
    assert "no daily prices" in stooq.compare(ours(), None)["unavailable"]


def test_stooq_failure_says_it_could_not_be_reached():
    assert "could not be reached" in stooq.check("INTC", ours())["unavailable"]


def test_price_check_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(stooq, "_get", lambda url: calls.append(url) or CSV)
    a = data.price_check("INTC", ours())
    b = data.price_check("INTC", ours())
    assert a == b and a["verdict"] == "matches" and len(calls) == 1


@pytest.mark.parametrize("sym,url", [("BRK.B", "brk-b.us")])
def test_dotted_tickers_use_stooq_dash_form(monkeypatch, sym, url):
    seen = []
    monkeypatch.setattr(stooq, "_get", lambda u: seen.append(u) or CSV)
    stooq.check(sym, ours())
    assert url in seen[0]


def test_details_line_for_the_price_check():
    from stockwatch import ui
    assert ui.pricecheck_note(None) == ""
    assert "matches" in ui.pricecheck_note({"pricecheck": stooq.compare(ours(), stooq.parse(CSV))})
    assert "no read" in ui.pricecheck_note({"pricecheck": {"source": "Stooq", "unavailable": "Stooq could not be reached"}})
