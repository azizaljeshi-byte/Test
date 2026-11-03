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
