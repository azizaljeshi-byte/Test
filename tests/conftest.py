"""No test reaches the network: the unofficial second-opinion sources fail fast unless a test fakes them."""
import pytest


@pytest.fixture(autouse=True)
def _no_second_source_network(monkeypatch):
    from stockwatch import massive, newsfeed, stooq, tradingview

    def blocked(*a, **k):
        raise OSError("network disabled in tests")
    monkeypatch.setattr(tradingview, "_post", blocked)
    monkeypatch.setattr(stooq, "_get", blocked)
    monkeypatch.setattr(massive, "_get", blocked)
    from stockwatch import onecall
    monkeypatch.setattr(onecall, "log_call", lambda *a, **k: False)   # tests never write the owner's new-call log
    from stockwatch import ui
    monkeypatch.setattr(ui, "HIDE_OLD_CALLS", False)                   # the old-call tests run with the old words; the new ones set True
    from stockwatch import dayboard
    monkeypatch.setattr(dayboard, "SHOW_MAP", True)                    # the map is off on the Radar; its tests run with it on
    monkeypatch.delenv("STOCKWATCH_MASSIVE_KEY", raising=False)
    massive._days.clear()
    massive._blocked.clear()
    monkeypatch.setattr(newsfeed, "_get", blocked)
    newsfeed._cache.clear()
    from stockwatch import data
    data._SECOND.clear()
    data._PRICECHECK.clear()


def pytest_configure(config):
    config.addinivalue_line("markers", "new_rules: runs a Quick test under the 7 Nov rules instead of the legacy ones")
