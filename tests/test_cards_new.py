from stockwatch import quick, ui


def _snap(call="ADD / BUY", why="near the line"):
    return {"ticker": "AAA", "tier": 1, "verdict": "BUY", "price": 100.0, "composite": 70, "technical_score": 70,
            "fundamental_score": 70, "payload": {"watchlist": True, "signals": [], "position": {}, "plan": {"stance": "BUY"},
            "technical": {"one_call": {"known": True, "call": call, "why": why}}}}


def test_chips_show_both_calls_and_hide_old(monkeypatch):
    monkeypatch.setattr(ui, "HIDE_OLD_CALLS", True)
    ui.set_quick({}, {"AAA": "bounce"})
    h = ui.row(_snap())
    assert "Quick" in h and "bounce" in h and "New call" in h and "ADD / BUY" in h and "near the line" in h
    assert "PLAN" not in h and "BUY NOW" not in h
    assert ui.trade_plan({"stance": "BUY"}, None, 0, 0) == "" and ui.plan_line({"stance": "BUY"}) == ""
    ui.set_quick({}, {})


def test_quick_holding_and_no_call(monkeypatch):
    monkeypatch.setattr(ui, "HIDE_OLD_CALLS", True)
    ui.set_quick({"AAA": 1.5}, {})
    s = _snap()
    s["payload"]["technical"] = {}
    h = ui.call_chips(s)
    assert "holding +1.5%" in h and "no call yet" in h
    ui.set_quick({}, {})


def test_quick_top_up_keeps_trades():
    b = {**quick.new_book(), "cash": 9000.0, "start": 10000.0, "trades": [{"id": 1}]}
    assert quick.top_up(b) is True
    assert b["cash"] == 49000.0 and b["start"] == 50000.0 and b["trades"] == [{"id": 1}]
    assert quick.top_up(b) is False
    assert quick.POSITION_PCT == 5 and quick.MAX_OPEN == 15
