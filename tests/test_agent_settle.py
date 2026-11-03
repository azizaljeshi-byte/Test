from datetime import datetime, timedelta

from stockwatch import agent
from stockwatch.data import NY

NOW = datetime(2026, 11, 2, 11, 0, tzinfo=NY)


def _ans(*rows):
    return {"instructions": [{"ticker": t, "action": a, "state": st} for t, a, st in rows]}


def test_same_verdict_three_times_settles():
    seen = {}
    for i in range(3):
        agent.update_seen(seen, _ans(("GILD", "SELL", "falling")), {"GILD"}, {"GILD": 169.0}, NOW)
    assert seen["GILD"]["streak"] == 3
    assert agent.is_settled(seen, "GILD", True, 169.2, 2.0, NOW + timedelta(minutes=5))


def test_a_change_resets_and_a_move_or_time_unsettles():
    seen = {}
    for _ in range(3):
        agent.update_seen(seen, _ans(("GILD", "SELL", "falling")), {"GILD"}, {"GILD": 169.0}, NOW)
    assert not agent.is_settled(seen, "GILD", True, 171.0, 2.0, NOW)                           # moved a full range
    assert not agent.is_settled(seen, "GILD", True, 169.0, 2.0, NOW + timedelta(minutes=21))    # stale
    assert not agent.is_settled(seen, "GILD", False, 169.0, 2.0, NOW)                           # ownership changed
    agent.update_seen(seen, _ans(("GILD", "WAIT", "basing")), {"GILD"}, {"GILD": 169.0}, NOW)
    assert seen["GILD"]["streak"] == 1 and not agent.is_settled(seen, "GILD", True, 169.0, 2.0, NOW)


def test_unknown_price_is_never_settled():
    seen = {"X": {"act": "WAIT", "state": "basing", "own": False, "streak": 5, "price": None, "at": NOW.isoformat()}}
    assert not agent.is_settled(seen, "X", False, 10.0, 1.0, NOW)
    assert not agent.is_settled(seen, "X", False, None, 1.0, NOW)
