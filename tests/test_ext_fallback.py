"""Pre-market / after-hours price from Yahoo's quote fields when the minute chart has no trade from this session (owner, 9 Nov: FICO)."""
from datetime import datetime, timezone

from stockwatch import data
from stockwatch.data import NY

NOW = datetime(2026, 11, 9, 7, 25, tzinfo=NY)                                  # Monday 07:25 New York, pre-market


def q(**kw):
    base = {"market_state": "PRE", "ext_session": "post", "ext_price": 691.81, "ext_change": -0.0188, "ext_stale": True,
            "regular_price": 705.08, "source": "1m bars", "error": None}
    return {**base, **kw}


def ts(h, m, day=9):
    return int(datetime(2026, 11, day, h, m, tzinfo=NY).timestamp())


def test_a_stale_stock_takes_todays_pre_market_trade_and_the_change_is_against_the_last_regular_price():
    out = data._apply_ext_info(q(), {"preMarketPrice": 705.0, "preMarketTime": ts(7, 15)}, NOW)
    assert out["ext_session"] == "pre" and out["ext_price"] == 705.0 and not out["ext_stale"]
    assert abs(out["ext_change"] - (705.0 / 705.08 - 1)) < 1e-9 and out["source"] == "quote fields"


def test_an_old_or_missing_or_future_trade_changes_nothing():
    base = q()
    assert data._apply_ext_info(base, {"preMarketPrice": 705.0, "preMarketTime": ts(18, 0, day=6)}, NOW) == base      # Friday's
    assert data._apply_ext_info(base, {"preMarketPrice": None, "preMarketTime": ts(7, 15)}, NOW) == base
    assert data._apply_ext_info(base, {"preMarketPrice": 705.0, "preMarketTime": ts(9, 0)}, NOW) == base               # in the future
    assert data._apply_ext_info(base, {"preMarketPrice": float("nan"), "preMarketTime": ts(7, 15)}, NOW) == base
    assert data._apply_ext_info(q(regular_price=None), {"preMarketPrice": 705.0, "preMarketTime": ts(7, 15)}, NOW)["ext_price"] == 691.81


def test_only_stocks_without_a_trade_from_this_session_are_asked():
    assert data._needs_ext_patch(q())
    assert data._needs_ext_patch(q(ext_price=None, ext_stale=False))
    assert not data._needs_ext_patch(q(ext_session="pre", ext_stale=False))
    assert not data._needs_ext_patch(q(market_state="REGULAR"))
    assert not data._needs_ext_patch(q(market_state="CLOSED"))


def test_the_provider_asks_once_per_window_and_never_raises(monkeypatch):
    data._ext_info_cache.clear()
    calls = []
    prov = data.YahooProvider.__new__(data.YahooProvider)
    monkeypatch.setattr(prov, "_raw_ext", lambda t: calls.append(t) or {"preMarketPrice": 705.0, "preMarketTime": int(datetime.now(timezone.utc).timestamp())}, raising=False)
    monkeypatch.setattr(data, "_apply_ext_info", lambda qq, raw, now=None: {**qq, "ext_price": raw["preMarketPrice"], "ext_stale": False} if raw else qq)
    a = prov._patch_stale_ext("FICO", q())
    b = prov._patch_stale_ext("FICO", q())
    assert a["ext_price"] == 705.0 and b["ext_price"] == 705.0 and calls == ["FICO"]
    data._ext_info_cache.clear()
    monkeypatch.setattr(prov, "_raw_ext", lambda t: (_ for _ in ()).throw(RuntimeError("rate limited")), raising=False)
    assert prov._patch_stale_ext("FICO", q())["ext_price"] == 691.81
    data._ext_info_cache.clear()


def test_bulk_quotes_limits_how_many_stocks_are_asked(monkeypatch):
    data._ext_info_cache.clear()
    prov = data.YahooProvider.__new__(data.YahooProvider)
    names = [f"T{i}" for i in range(30)]
    monkeypatch.setattr(prov, "_bar_bulk_quotes", lambda ts_: {t: q() for t in ts_}, raising=False)
    asked = []
    monkeypatch.setattr(prov, "_patch_stale_ext", lambda t, qq: asked.append(t) or qq, raising=False)
    prov.bulk_quotes(names)
    assert len(asked) == data.EXT_INFO_MAX
