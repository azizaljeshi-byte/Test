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


def test_scans_every_30_minutes_from_10_until_15_30(monkeypatch):
    times = [(h, m) for h in range(9, 16) for m in range(0, 60, 5) if (h, m) >= (9, 30)]
    assert _run(monkeypatch, times) == [(10, 0), (10, 30), (11, 0), (11, 30), (12, 0), (12, 30), (13, 0), (13, 30),
                                        (14, 0), (14, 30), (15, 0), (15, 30)]


def test_no_scan_before_10_or_after_15_30(monkeypatch):
    assert _run(monkeypatch, [(9, 45), (15, 45), (15, 55)]) == []
