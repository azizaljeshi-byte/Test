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


# ---- re-check at the open, previous verdict, placeholder clean-up
def _at(h, m, day=3):
    return datetime(2026, 11, day, h, m, tzinfo=NY)


def test_ask_records_previous_and_drops_the_placeholder(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    s = SnapStore({"ISRG": _snap()})
    ask_ai.request(s, "ISRG", _at(4, 0))
    assert ask_ai.latest(s, "ISRG")["status"] == "asking"
    first = ask_ai.ask(s, "ISRG", _at(4, 1), caller=lambda *a: (ANSWER, {}))
    assert first["previous"] is None
    second = ask_ai.ask(s, "ISRG", _at(5, 0), caller=lambda *a: (ANSWER.replace("hold", "buy"), {}))
    assert second["previous"]["verdict"] == "HOLD" and second["verdict"] == "BUY" and second["recheck"] is False
    assert [r["status"] for r in ask_ai._load(s)["ISRG"]] == ["ready", "ready"]          # no 'asking' row left behind


def _regular(monkeypatch):
    monkeypatch.setattr(ask_ai, "us_session", lambda n: "REGULAR")


def test_open_recheck_queues_stocks_asked_before_the_open_once(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    _regular(monkeypatch)
    s = SnapStore({"ISRG": _snap(), "NOW": {**_snap(), "ticker": "NOW"}})
    ask_ai.ask(s, "ISRG", _at(4, 8), caller=lambda *a: (ANSWER, {}))
    ask_ai.ask(s, "NOW", _at(9, 50), caller=lambda *a: (ANSWER, {}))            # asked after 09:45: not re-checked
    assert ask_ai.open_recheck(s, _at(9, 30)) == []                              # too early
    assert ask_ai.open_recheck(s, _at(9, 46)) == ["ISRG"]
    assert ask_ai.open_recheck(s, _at(9, 47)) == []                              # only once a day
    assert ask_ai._queue(s) == ["ISRG"]


def test_open_recheck_marks_the_answer(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    _regular(monkeypatch)
    s = SnapStore({"ISRG": _snap()})
    ask_ai.ask(s, "ISRG", _at(4, 8), caller=lambda *a: (ANSWER, {}))
    ask_ai.open_recheck(s, _at(9, 46))
    v = ask_ai.ask(s, "ISRG", _at(9, 47), caller=lambda *a: (ANSWER.replace("hold", "avoid"), {}))
    assert v["recheck"] is True and v["previous"]["verdict"] == "HOLD" and v["verdict"] == "AVOID"


def test_open_recheck_skips_a_day_with_nothing_asked_and_late_hours(monkeypatch):
    _regular(monkeypatch)
    s = SnapStore({"ISRG": _snap()})
    assert ask_ai.open_recheck(s, _at(9, 46)) == []
    ask_ai.save(s, {**ask_ai.sample_verdict("ISRG"), "asked_at": "2026-11-03T04:08:00-05:00"})
    assert ask_ai.open_recheck(s, _at(13, 0)) == []                              # not hours after the open


# ---- trade plan (entry / stop / targets)
def _plan(**kw):
    p = {"entry": 100, "stop": 95, "target1": 110, "target2": 120, "stop_why": "under support 95", "target_why": "resistance 110"}
    p.update(kw)
    return p


def test_plan_is_kept_and_reward_risk_is_computed_by_code():
    from stockwatch import ask_ai
    p = ask_ai.check_plan(_plan(reward_risk=99), "BUY", 100)
    assert p["reward_risk"] == 2.0 and p["target2"] == 120.0 and p["stop"] == 95.0


def test_plan_dropped_when_not_sane():
    from stockwatch import ask_ai
    assert ask_ai.check_plan(_plan(), "SELL", 100) is None and ask_ai.check_plan(_plan(), "AVOID", 100) is None
    assert ask_ai.check_plan(_plan(stop=101), "BUY", 100) is None            # stop above entry
    assert ask_ai.check_plan(_plan(target1=99), "BUY", 100) is None          # target below entry
    assert ask_ai.check_plan(_plan(entry=130, target1=140), "BUY", 100) is None   # entry far from price
    assert ask_ai.check_plan(_plan(stop=60), "BUY", 100) is None             # stop too wide
    assert ask_ai.check_plan(_plan(entry=None), "BUY", 100) is None
    assert ask_ai.check_plan(None, "BUY", 100) is None
    assert ask_ai.check_plan(_plan(target1=102, target2=105), "BUY", 100)["target2"] == 105.0
    assert ask_ai.check_plan(_plan(target2=105, target1=110), "BUY", 100)["target2"] is None   # second target must be higher


def test_parse_answer_carries_plan():
    import json
    from stockwatch import ask_ai
    a = ask_ai.parse_answer(json.dumps({"verdict": "BUY", "confidence": 3, "headline": "h", "plan": _plan()}), 100)
    assert a["plan"]["entry"] == 100.0
    a = ask_ai.parse_answer(json.dumps({"verdict": "AVOID", "confidence": 3, "headline": "h", "plan": _plan()}), 100)
    assert a["plan"] is None


def test_plan_box_renders_and_escapes():
    from stockwatch import ask_ai_view
    out = ask_ai_view.plan_html({"entry": 100, "stop": 95, "target1": 110, "target2": None, "reward_risk": 2.0, "stop_why": "<b>x</b>", "target_why": ""})
    assert "Stop loss" in out and "&lt;b&gt;" in out and "<b>x</b>" not in out and "$2.0" in out
    assert "No plan" in ask_ai_view.plan_html(None)
