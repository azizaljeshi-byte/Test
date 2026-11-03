from stockwatch import ask_ai


class FakeStore:
    def __init__(self):
        self.d = {}

    def get_setting(self, k):
        return self.d.get(k)

    def set_setting(self, k, v):
        self.d[k] = v


def test_sample_is_valid():
    assert ask_ai.check(ask_ai.sample_verdict()) == []


def test_check_flags_bad_verdict():
    v = ask_ai.sample_verdict()
    v["verdict"] = "MAYBE"
    assert "verdict" in ask_ai.check(v)


def test_save_latest_history():
    s = FakeStore()
    assert ask_ai.latest(s, "ISRG") is None
    a = ask_ai.sample_verdict("ISRG")
    b = ask_ai.sample_verdict("NOW")
    b["asked_at"] = "2026-11-03T08:10:00-05:00"
    ask_ai.save(s, a)
    ask_ai.save(s, b)
    assert ask_ai.latest(s, "isrg")["ticker"] == "ISRG"
    assert [r["ticker"] for r in ask_ai.history(s)] == ["NOW", "ISRG"]


def test_keeps_only_recent_per_ticker():
    s = FakeStore()
    for i in range(ask_ai.KEEP_PER_TICKER + 5):
        v = ask_ai.sample_verdict("ISRG")
        v["asked_at"] = f"2026-11-03T08:{i:02d}:00-05:00"
        ask_ai.save(s, v)
    assert len(ask_ai._load(s)["ISRG"]) == ask_ai.KEEP_PER_TICKER


# ---- the AI side
import json
from datetime import datetime

from stockwatch import agent
from stockwatch.data import NY


class SnapStore(FakeStore):
    def __init__(self, snaps):
        super().__init__()
        self.snaps = snaps

    def snapshot(self, t):
        return self.snaps.get(t)

    def latest_snapshots(self):
        return list(self.snaps.values())


def _snap():
    return {"ticker": "ISRG", "payload": {"profile": {"name": "Intuitive Surgical", "sector": "Healthcare"},
            "quote": {"regular_price": 436.87, "fetched_at": "2026-11-03T12:00:00+00:00"},
            "technical": {"atr": 9.0, "rsi": 57, "trend": "mixed", "sma200": 432.5,
                          "one_call": {"known": True, "call": "AVOID", "exit_line": 443.48, "distance_swings": -0.7},
                          "zones": {"known": True, "support": [{"low": 427, "high": 428.5, "grade": "HIGH", "touches": 5}],
                                    "resistance": [{"low": 439, "high": 441, "grade": "WEAK", "touches": 1}]}},
            "events": {"days_to_earnings": 80}}}


ANSWER = json.dumps({"verdict": "hold", "confidence": 2, "headline": "Wait.", "change_buy": "b", "change_hold": "h", "change_sell": "s"})
SAT = datetime(2026, 11, 7, 10, 0, tzinfo=NY)           # market closed


def test_ask_saves_ready_verdict(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    s = SnapStore({"ISRG": _snap()})
    v = ask_ai.ask(s, "isrg", SAT, caller=lambda *a: (ANSWER, {}))
    assert v["status"] == "ready" and v["verdict"] == "HOLD" and v["confidence"] == 2
    assert v["price"] == 436.87 and v["price_label"] == "last close"
    assert ask_ai.check(v) == []
    kinds = {lv["kind"] for lv in v["levels"]}
    assert {"exit_line", "support", "resistance", "price"} <= kinds
    assert [f for f in v["facts"] if f["label"] == "Volume vs normal"][0]["value"] is None     # unknown, not 0
    assert ask_ai.latest(s, "ISRG")["verdict"] == "HOLD"


def test_ask_failures_are_saved_not_raised(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    s = SnapStore({"ISRG": _snap()})
    assert ask_ai.ask(s, "ZZZZ", SAT)["status"] == "failed"                                      # not tracked
    bad = ask_ai.ask(s, "ISRG", SAT, caller=lambda *a: ('{"verdict": "MAYBE"}', {}))
    assert bad["status"] == "failed" and "MAYBE" in bad["error"]
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(agent, "has_key", lambda: False)
    assert "key" in ask_ai.ask(s, "ISRG", SAT)["error"]


def test_daily_limit(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("STOCKWATCH_ASK_MAX", "1")
    s = SnapStore({"ISRG": _snap()})
    assert ask_ai.ask(s, "ISRG", SAT, caller=lambda *a: (ANSWER, {}))["status"] == "ready"
    assert "limit" in ask_ai.ask(s, "ISRG", SAT, caller=lambda *a: (ANSWER, {}))["error"]


def test_request_queues_once():
    s = SnapStore({"ISRG": _snap()})
    ask_ai.request(s, "isrg", SAT)
    ask_ai.request(s, "ISRG", SAT)
    ask_ai.request(s, "bad ticker!", SAT)
    assert ask_ai._queue(s) == ["ISRG"]
    assert ask_ai.latest(s, "ISRG")["status"] == "asking"


def test_score_close():
    s = SnapStore({"ISRG": _snap()})
    v = ask_ai.sample_verdict("ISRG")
    v["asked_at"] = "2026-11-03T10:00:00-05:00"
    v["price"] = 430.0
    ask_ai.save(s, v)
    after_close = datetime(2026, 11, 3, 17, 0, tzinfo=NY)
    snap = _snap()
    snap["payload"]["quote"]["fetched_at"] = "2026-11-03T21:30:00+00:00"       # 16:30 New York
    s.snaps["ISRG"] = snap
    assert ask_ai.score(s, after_close) == 1
    assert ask_ai.latest(s, "ISRG")["scored"]["close"] == round((436.87 / 430 - 1) * 100, 2)
