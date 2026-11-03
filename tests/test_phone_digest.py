"""Approved phone layout; all symbols and destinations are synthetic."""
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from stockwatch import events, notify
from stockwatch.config import Holding
from test_events import FakeStore, snap


def capture(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, 'ntfy_send', lambda *args: sent.append(args) or 'sent')
    return sent


def test_mixed_sweep_orders_exits_stops_buys_and_one_summary(monkeypatch):
    sent = capture(monkeypatch)
    store = FakeStore()
    hold = [Holding(t, 1, 10) for t in ('FICTA', 'FICTB', 'FICTE')]
    initial = [snap(t, 'HOLD') for t in ('FICTC', 'FICTD', 'FICTE', 'FICTB', 'FICTA')]
    events.call_flips(store, initial, hold)
    assert not sent
    calls = ['BUY', 'WAIT', 'HOLD', 'ON THE LINE', 'EXIT']
    changed = [snap(s['ticker'], call) for s, call in zip(initial, calls)]
    # Make the ordinary owned change eligible too.
    changed[2]['payload']['technical']['one_call']['call'] = 'WAIT'
    out = events.call_flips(store, changed, hold)
    assert out['owned_changes'] == 3 and out['watch_changes'] == 1 and out['buys'] == 1
    assert len(sent) == 1 and sent[0][2] == 5
    body = sent[0][1]
    assert body.index('FICTA:') < body.index('FICTB:') < body.index('FICTC:') < body.index('FICTE:') < body.index('Watchlist:')
    assert body.count('Watchlist:') == 1 and 'Tap for the full list.' in body
    assert 'ON THE LINE' not in body and 'swings' not in body
    full = json.loads(store.get_setting(events.CALL_DIGEST_KEY))['lines']
    assert any('FICTD:' in line for line in full)
    events.call_flips(store, changed, hold)
    assert len(sent) == 1
    # Back-and-forth flips remain eligible; same chart date does not suppress them.
    events.call_flips(store, [snap('FICTA', 'HOLD')], hold)
    events.call_flips(store, [snap('FICTA', 'EXIT')], hold)
    assert len(sent) == 3 and sent[-1][2] == 5


def test_no_eligible_changes_unknown_calls_and_chart_date_only_send_nothing(monkeypatch):
    sent = capture(monkeypatch)
    store = FakeStore()
    for snaps in ([], [snap('FICTA', 'HOLD')], [snap('FICTA', 'HOLD', 'next-date')], [snap('FICTA', None)]):
        events.call_flips(store, snaps, [])
    assert not sent


def test_missing_topic_and_dashboard_configuration(monkeypatch):
    for name in ('NTFY_TOPIC', 'NTFY_TOPIC_LOG', 'DASHBOARD_URL'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(notify.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('network without configuration'))
    store = FakeStore()
    events.call_flips(store, [snap('FICTA', 'WAIT')], [])
    events.call_flips(store, [snap('FICTA', 'BUY')], [])
    assert events._link('FICTA') is None and events._link() is None
    assert not store.get_setting(events.FAIL_KEY) and not store.get_setting(events.OUTBOX_KEY)


def test_private_runtime_links_single_stock_digest_and_retry(monkeypatch):
    sent = capture(monkeypatch)
    # Reserved synthetic host, constructed here; no deployed address or private link.
    base = 'https:' + '//example.invalid/app?old=value#fragment'
    monkeypatch.setenv('DASHBOARD_URL', base)
    store = FakeStore()
    events.call_flips(store, [snap('FICTA', 'WAIT'), snap('FICTB', 'WAIT')], [])
    events.call_flips(store, [snap('FICTA', 'BUY')], [])
    assert parse_qs(urlsplit(sent[0][4]).query) == {'view': ['target'], 't': ['FICTA']}
    events.call_flips(store, [snap('FICTA', 'WAIT'), snap('FICTB', 'BUY')], [])
    assert parse_qs(urlsplit(sent[1][4]).query) == {'view': ['log']}
    assert urlsplit(sent[1][4]).path == '/app' and not urlsplit(sent[1][4]).fragment
    assert parse_qs(urlsplit(events._link('FICT&?')).query)['t'] == ['FICT&?']
    store.set_setting(events.OUTBOX_KEY, json.dumps([{'title': 'Synthetic digest', 'text': 'FICTA update', 'priority': 5, 'tags': '', 'ticker': None}]))
    events.resend(store)
    assert parse_qs(urlsplit(sent[-1][4]).query) == {'view': ['log']} and sent[-1][2] == 5


@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), True])
def test_unknown_prices_and_exit_levels_are_not_zero(monkeypatch, value):
    sent = capture(monkeypatch)
    store = FakeStore()
    hold = [Holding('FICTA', 1, 2)]
    events.call_flips(store, [snap('FICTA', 'HOLD'), snap('FICTB', 'WAIT')], hold)
    a, b = snap('FICTA', 'EXIT'), snap('FICTB', 'BUY')
    a['payload']['technical']['one_call'].update(close=value, exit_line=value)
    b['price'] = value
    monkeypatch.setattr(events.ui, '_now', lambda s: (value, None, None))
    monkeypatch.setattr('stockwatch.rotation.build', lambda *a: [])
    events.call_flips(store, [a, b], hold)
    assert sent[0][2] == 5
    assert 'Closed unknown, below exit level unknown' in sent[0][1]
    assert 'Price unknown' in sent[0][1] and '0.00' not in sent[0][1]


def test_caps_keep_urgent_lines_before_buys_and_reserve_summary(monkeypatch):
    sent = capture(monkeypatch)
    store = FakeStore()
    names = [f'FICT{i}' for i in range(20)]
    hold = [Holding(t, 1, 1) for t in names]
    events.call_flips(store, [snap(t, 'HOLD') for t in names] + [snap('FICTBUY', 'WAIT')], hold)
    monkeypatch.setattr('stockwatch.rotation.build', lambda *a: [])
    events.call_flips(store, [snap('FICTBUY', 'BUY')] + [snap(t, 'EXIT') for t in names], hold)
    body = sent[0][1]
    assert len(sent) == 1 and sent[0][2] == 5 and len(body.encode()) <= 3800
    assert 'FICT0: Exit signal' in body and 'FICTBUY:' not in body
    assert body.endswith('Tap for the full list.')
    assert len(json.loads(store.get_setting(events.CALL_DIGEST_KEY))['lines']) == 21
    unicode_body = notify.phone_digest(['FICTA: Exit signal.', '字' * 4000, 'FICTB: New buy signal.'], 'Tap for the full list.')
    assert unicode_body.startswith('FICTA: Exit signal.') and 'FICTB' not in unicode_body
    assert len(unicode_body.encode()) <= 3800


def test_ntfy_click_header_uses_runtime_destination_and_body_is_valid_utf8(monkeypatch):
    requests = []
    class Response:
        def read(self):
            return b''
    monkeypatch.setenv('NTFY_TOPIC', 'synthetic-test-topic')
    monkeypatch.delenv('NTFY_TOKEN', raising=False)
    monkeypatch.delenv('DASHBOARD_URL', raising=False)
    monkeypatch.setattr(notify.urllib.request, 'urlopen', lambda req, **kw: requests.append(req) or Response())
    store = FakeStore()
    events.call_flips(store, [snap('FICTA', 'WAIT')], [])
    events.call_flips(store, [snap('FICTA', 'BUY')], [])
    assert not requests[0].get_header('Click')
    monkeypatch.setenv('DASHBOARD_URL', 'https:' + '//example.invalid/app')
    events.call_flips(store, [snap('FICTA', 'WAIT')], [])
    request = requests[-1]
    assert parse_qs(urlsplit(request.get_header('Click')).query) == {'view': ['target'], 't': ['FICTA']}
    assert request.get_header('Priority') == '2'
    assert 'Tap for the full list.' in request.data.decode('utf-8')
