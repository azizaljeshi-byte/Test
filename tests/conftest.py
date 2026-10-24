"""No test reaches the network: the unofficial second-opinion sources fail fast unless a test fakes them."""
import pytest


@pytest.fixture(autouse=True)
def _no_second_source_network(monkeypatch):
    from stockwatch import stooq, tradingview

    def blocked(*a, **k):
        raise OSError("network disabled in tests")
    monkeypatch.setattr(tradingview, "_post", blocked)
    monkeypatch.setattr(stooq, "_get", blocked)
    from stockwatch import data
    data._SECOND.clear()
    data._PRICECHECK.clear()
