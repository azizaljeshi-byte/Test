from datetime import datetime

from stockwatch import candidates
from stockwatch.data import NY


class FakeStore:
    def __init__(self):
        self.s = {}

    def get_setting(self, k):
        return self.s.get(k)

    def set_setting(self, k, v):
        self.s[k] = v

    def latest_snapshots(self):
        return []


def _run(monkeypatch, times):
    store, calls = FakeStore(), []
    monkeypatch.setattr(candidates, "record", lambda s, n: False)
    monkeypatch.setattr(candidates, "export", lambda s: "")
    monkeypatch.setattr(candidates, "us_session", lambda n: "REGULAR")
    for h, m in times:
        out = candidates.tick(store, datetime(2026, 11, 2, h, m, tzinfo=NY))
        if out["scanned"]:
            calls.append((h, m))
    return calls


def test_scans_every_5_minutes_from_9_45_until_15_55(monkeypatch):
    times = [(h, m) for h in range(9, 17) for m in range(0, 60, 5) if (h, m) >= (9, 30)]
    got = _run(monkeypatch, times)
    assert got[0] == (9, 45) and got[1] == (9, 50) and got[-1] == (15, 55)
    assert len(got) == (15 * 60 + 55 - (9 * 60 + 45)) // 5 + 1
    assert (9, 40) not in got and (16, 0) not in got and (10, 0) in got and (10, 5) in got


def test_no_scan_before_9_45_or_after_15_55(monkeypatch):
    assert _run(monkeypatch, [(9, 35), (9, 40), (16, 0), (16, 5)]) == []
