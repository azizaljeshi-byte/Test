import json
from datetime import date

import pandas as pd

from stockwatch import data, massive, stooq


def grouped(day_prices: dict, status="OK") -> str:
    return json.dumps({"status": status, "results": [{"T": t, "c": c, "v": 1} for t, c in day_prices.items()]})


def series(dates, base=100.0, last_shift=0.0):
    idx = pd.to_datetime(dates)
    return pd.Series([base + i + (last_shift * (base + i) if i == len(dates) - 1 else 0) for i in range(len(dates))], index=idx)


DATES = [f"2026-10-{d:02d}" for d in (13, 14, 15, 16, 19, 20, 21, 22, 23)]


def load(ours, ticker="CRDO", extra=None):
    """Fill the cache as the background thread would, from our own closes (so they match) plus any extra days."""
    for d, c in ours.items():
        massive._days[d.date().isoformat()] = {ticker: float(c)}
    for d, m in (extra or {}).items():
        massive._days[d] = m


def test_parse_grouped_reads_closes_and_rejects_junk():
    assert massive.parse_grouped(grouped({"AAPL": 190.5, "BAD": -1})) == {"AAPL": 190.5}
    assert massive.parse_grouped(grouped({})) == {}
    assert massive.parse_grouped("<html>") is None and massive.parse_grouped(json.dumps({"status": "ERROR"})) is None


def test_no_key_means_no_check():
    assert "no Massive key" in massive.check("CRDO", series(DATES))["unavailable"]


def test_wanted_days_never_includes_today_and_covers_a_gap():
    ours = series(DATES)
    days = massive.wanted_days(ours, today=date(2026, 10, 27))
    assert "2026-10-26" in days and "2026-10-27" not in days and "2026-10-24" not in days
    assert days == sorted(days)


def test_loading_is_reported_not_guessed(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_MASSIVE_KEY", "k")
    monkeypatch.setattr(massive, "request", lambda days: None)
    out = massive.check("CRDO", series(DATES), today=date(2026, 10, 27))
    assert "loading" in out["unavailable"] and out["retry"] is True


def test_matching_closes_agree(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_MASSIVE_KEY", "k")
    monkeypatch.setattr(massive, "request", lambda days: None)
    ours = series(DATES)
    load(ours, extra={"2026-10-26": {"AAPL": 1.0}})
    out = massive.check("CRDO", ours, today=date(2026, 10, 24))
    assert out["source"] == "Massive" and out["agrees"] is True and out["verdict"] == "matches"


def test_a_bad_close_differs(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_MASSIVE_KEY", "k")
    monkeypatch.setattr(massive, "request", lambda days: None)
    ours = series(DATES)
    load(ours)
    massive._days["2026-10-23"] = {"CRDO": float(ours.iloc[-1]) * 0.95}
    out = massive.check("CRDO", ours, today=date(2026, 10, 24))
    assert out["verdict"] == "differs" and out["agrees"] is False


def test_history_that_stops_early_is_called_behind(monkeypatch):
    """Yahoo ended on Friday 23 Oct while Massive already had Monday 26 Oct: the price shown is a day old."""
    monkeypatch.setenv("STOCKWATCH_MASSIVE_KEY", "k")
    monkeypatch.setattr(massive, "request", lambda days: None)
    ours = series(DATES)
    load(ours, extra={"2026-10-26": {"CRDO": 151.15}})
    out = massive.check("CRDO", ours, today=date(2026, 10, 27))
    assert out["verdict"] == "behind" and out["agrees"] is False
    assert "2026-10-23" in out["note"] and "2026-10-26" in out["note"]


def test_a_holiday_is_not_mistaken_for_a_missing_bar(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_MASSIVE_KEY", "k")
    monkeypatch.setattr(massive, "request", lambda days: None)
    ours = series(DATES)
    load(ours, extra={"2026-10-26": {}})                # fetched, but no session that day
    out = massive.check("CRDO", ours, today=date(2026, 10, 27))
    assert out["verdict"] == "matches"


def test_worker_fetches_newest_first_and_remembers_refusals(monkeypatch):
    monkeypatch.setattr(massive, "GAP", 0)
    monkeypatch.setenv("STOCKWATCH_MASSIVE_KEY", "k")
    asked = []

    def fake(url):
        asked.append(url)
        if "2026-10-23" in url:
            raise OSError("403")
        return grouped({"CRDO": 150.0})
    monkeypatch.setattr(massive, "_get", fake)
    massive._run(["2026-10-22", "2026-10-26", "2026-10-23"])
    assert "2026-10-26" in asked[0] and "2026-10-23" in massive._blocked
    assert set(massive._days) == {"2026-10-26", "2026-10-22"}
    massive._run(["2026-10-23"])
    assert len(asked) == 3                                # the refused date is left alone for a while


def test_price_check_prefers_massive_and_falls_back_to_stooq(monkeypatch):
    ours = series(DATES)
    monkeypatch.setenv("STOCKWATCH_MASSIVE_KEY", "k")
    monkeypatch.setattr(massive, "request", lambda days: None)
    monkeypatch.setattr(stooq, "check", lambda t, c: {"source": "Stooq", "agrees": True, "verdict": "matches", "note": "ok"})
    first = data.price_check("CRDO", ours)                         # still loading: Stooq answers
    assert first["source"] == "Stooq"
    data._PRICECHECK.clear()
    load(ours)
    assert data.price_check("CRDO", ours)["source"] == "Massive"


def test_still_loading_is_asked_again_soon(monkeypatch):
    ours = series(DATES)
    monkeypatch.setenv("STOCKWATCH_MASSIVE_KEY", "k")
    monkeypatch.setattr(massive, "request", lambda days: None)
    monkeypatch.setattr(stooq, "check", lambda t, c: {"source": "Stooq", "unavailable": "Stooq could not be reached"})
    out = data.price_check("CRDO", ours)
    assert out.get("retry") and data.time.monotonic() - data._PRICECHECK["CRDO"][0] >= data.SECOND_TTL - 130


def test_partly_loaded_is_asked_again_soon(monkeypatch):
    """The first day arrives before the rest: that 'too few sessions' read must not be cached for hours."""
    monkeypatch.setenv("STOCKWATCH_MASSIVE_KEY", "k")
    monkeypatch.setattr(massive, "request", lambda days: None)
    ours = series(DATES)
    massive._days["2026-10-26"] = {"CRDO": 151.15}
    out = massive.check("CRDO", ours, today=date(2026, 10, 27))
    assert "overlap" in out["unavailable"] and out["retry"] is True
