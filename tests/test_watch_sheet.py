"""Watch-tab integration: fake Sheet and cached prices, never a Google or Yahoo request."""
import copy
import json
import threading
from datetime import datetime, timezone

import pytest

from stockwatch import live, smallcap_sheet, tape_screens, ui, watch_sheet as ws
from stockwatch.config import Holding, Portfolio, TierRules
from stockwatch.store import Store

NOW = datetime(2026, 11, 13, 13, 15, tzinfo=timezone.utc)


class Sheet:
    def __init__(self, rows):
        self.rows = copy.deepcopy(rows)
        self.batches = []
        self.fail_read = self.fail_write = False

    def worksheet(self, name):
        assert name == 'Watch'
        return self

    def get(self, range_name):
        assert range_name == 'A2:B'
        if self.fail_read:
            raise RuntimeError('private-link-or-key-do-not-print')
        return copy.deepcopy(self.rows)

    def batch_update(self, data, value_input_option):
        assert value_input_option == 'RAW'
        if self.fail_write:
            raise RuntimeError('private-link-or-key-do-not-print')
        self.batches.append(data)


def snapshot(ticker='SYNTH', price=12.5):
    return {'ticker': ticker, 'tier': 2, 'price': price, 'verdict': 'WATCH',
            'fundamental_score': None, 'technical_score': None, 'composite': None,
            'payload': {'watchlist': True, 'signals': [], 'position': {}, 'fundamental': {'available': False},
                        'name': 'Invented Company', 'technical': {'day_change': 0.02,
                        'one_call': {'known': True, 'call': 'BUY', 'why': 'test'}}, 'quote': {}}}


def save_list(store, items):
    store.set_setting(ws.KEY, json.dumps({'at': NOW.isoformat(), 'items': items, 'error': None}))


def test_read_trims_uppercases_validates_and_keeps_physical_rows():
    sheet = Sheet([[' synth ', ' first '], [], ['SYNTH', 'duplicate'], ['bad <script>', 'bad'],
                   ['BRK.B', 'dot'], ['ABC-D', 'dash'], ['123', 'invalid'], ['', 'no ticker'], ['A'], ['LONGTICKERX']])
    rows = []
    assert ws.read(sheet, rows) == [{'ticker': 'SYNTH', 'comment': 'first'}, {'ticker': 'BRK.B', 'comment': 'dot'},
                                     {'ticker': 'ABC-D', 'comment': 'dash'}, {'ticker': 'A', 'comment': ''}]
    assert [r['row'] for r in rows] == [2, 4, 5, 6, 7, 8, 10, 11]
    assert [r['ticker'] for r in rows if r['status'] == 'Not a ticker'] == ['BAD <SCRIPT>', '123', 'LONGTICKERX']
    assert sheet.batches == []


def test_technical_ceiling_marks_extra_rows_and_deduplicates():
    sheet = Sheet([[f'S{i}', 'test'] for i in range(62)] + [['S0', 'duplicate']])
    rows = []
    assert len(ws.read(sheet, rows)) == 60
    assert [r['row'] for r in rows if r['status'] == 'Over the 60 limit'] == [62, 63]
    assert rows[-1]['status'] == ''  # duplicate of an active ticker does not add a stock


def test_sync_writes_one_batch_only_to_c_through_h_with_unknown_prices(tmp_path, monkeypatch):
    store = Store(tmp_path / 'job.db')
    sheet = Sheet([['SYNTH', '=not a formula'], [], ['KNOWN'], ['BAD!'], ['MISSING']])
    before = copy.deepcopy(sheet.rows)
    monkeypatch.setattr(store, 'snapshot', lambda t: snapshot(t) if t != 'MISSING' else None)
    result = ws.sync(store, known={'KNOWN'}, sheet=sheet, now=NOW)
    assert result['error'] is None
    assert result['items'][0] == {'ticker': 'SYNTH', 'comment': '=not a formula'}
    assert len(sheet.batches) == 1
    batch = sheet.batches[0]
    assert [b['range'] for b in batch] == ['C2:H2', 'C4:H4', 'C5:H5', 'C6:H6']
    assert [b['values'][0][0] for b in batch] == ['Watching', 'Already in your list', 'Not a ticker', 'No prices found']
    assert batch[0]['values'][0][1:] == ['Invented Company', 12.5, '+2.0%', 'BUY', '13 Nov 16:15']
    assert batch[-1]['values'][0][2:5] == ['unknown', 'unknown', 'unknown']
    assert sheet.rows == before  # owner's A:B never changes


@pytest.mark.parametrize('bad_price', [None, float('nan'), 0, -2])
def test_missing_prices_are_unknown_not_zero(tmp_path, monkeypatch, bad_price):
    store, sheet = Store(tmp_path / 'job.db'), Sheet([['SYNTH']])
    monkeypatch.setattr(store, 'snapshot', lambda t: snapshot(t, bad_price))
    ws.sync(store, sheet=sheet, now=NOW)
    cells = sheet.batches[0][0]['values'][0]
    assert cells[0] == 'No prices found' and cells[2] == 'unknown'


def test_read_failure_keeps_last_successful_list_and_time_and_sanitizes_errors(tmp_path, capsys, caplog):
    store = Store(tmp_path / 'job.db')
    old = [{'ticker': 'SYNTH', 'comment': 'keep'}]
    save_list(store, old)
    sheet = Sheet([])
    sheet.fail_read = True
    result = ws.sync(store, sheet=sheet)
    assert result['items'] == old and result['at'] == NOW.isoformat()
    assert 'could not be read' in result['error']
    assert 'private-link' not in json.dumps(result) + capsys.readouterr().out + caplog.text
    assert sheet.batches == []


def test_successful_empty_read_removes_stocks_but_failed_write_keeps_new_read(tmp_path):
    store = Store(tmp_path / 'job.db')
    save_list(store, [{'ticker': 'OLD', 'comment': ''}])
    sheet = Sheet([['SYNTH', 'new note']])
    sheet.fail_write = True
    result = ws.sync(store, sheet=sheet, now=NOW)
    assert result['items'] == [{'ticker': 'SYNTH', 'comment': 'new note'}]
    assert 'status cells' in result['error'] and 'private-link' not in result['error']
    assert ws.sync(store, sheet=Sheet([]), now=NOW)['items'] == []
    assert ws.items(store) == []


def test_watch_url_override_fallback_and_no_global_env_mutation(monkeypatch, tmp_path):
    env = {'STOCKWATCH_SMALLCAP_SHEET_URL': 'fallback', 'STOCKWATCH_WATCH_SHEET_URL': 'override',
           'GOOGLE_APPLICATION_CREDENTIALS': 'external-key-path'}
    selected = ws.sheet_env(env)
    assert selected['STOCKWATCH_SMALLCAP_SHEET_URL'] == 'override' and env['STOCKWATCH_SMALLCAP_SHEET_URL'] == 'fallback'
    assert selected['GOOGLE_APPLICATION_CREDENTIALS'] == 'external-key-path'
    assert ws.sheet_env({'STOCKWATCH_SMALLCAP_SHEET_URL': 'fallback'})['STOCKWATCH_SMALLCAP_SHEET_URL'] == 'fallback'
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    seen = []
    monkeypatch.setattr(smallcap_sheet, 'connect', lambda e: seen.append(e) or Sheet([]))
    ws.sync(Store(tmp_path / 'job.db'))
    assert seen[0]['STOCKWATCH_SMALLCAP_SHEET_URL'] == 'override'


@pytest.mark.parametrize('wide', [False, True])
def test_portfolio_adds_real_watchlist_deduplicates_and_removes_without_deleting_open_trades(tmp_path, monkeypatch, wide):
    store = Store(tmp_path / 'job.db')
    rules = TierRules(0.4, 0.6, 12, 2.5, 7)
    base = Portfolio([Holding('HELD', 1, 5, 20), Holding('EXIST', 2, 0)], {1: rules, 2: rules})
    monkeypatch.setattr(live, 'load_portfolio', lambda: base)
    save_list(store, [{'ticker': 'SYNTH', 'comment': 'test'}, {'ticker': 'HELD', 'comment': 'owned'}])
    result = live.current_portfolio(store, wide=wide)
    assert [h.ticker for h in result.holdings] == ['HELD', 'EXIST', 'SYNTH']
    added = result.holdings[-1]
    assert added.tier == 2 and added.shares == 0 and added.is_watchlist
    assert 'SYNTH' not in result.extras
    assert result.holdings[0].cost_basis == 20 and result.holdings[0].shares == 5
    store.set_setting('quick_book', json.dumps({'positions': {'SYNTH': {'shares': 2}}}))
    save_list(store, [])
    removed = live.current_portfolio(store, wide=wide)
    assert ('SYNTH' in {h.ticker for h in removed.holdings}) == wide
    if wide:
        assert 'SYNTH' in removed.extras  # stop still watched; no Radar card after removal
    assert json.loads(store.get_setting('quick_book'))['positions']['SYNTH']['shares'] == 2


def test_watch_stocks_get_full_evaluation_and_alerts_from_normal_sweep(tmp_path, monkeypatch):
    from stockwatch import data, engine, scanner
    from stockwatch.signals import OPPORTUNITY, Signal
    store = Store(tmp_path / 'job.db')
    base = Portfolio([], {2: TierRules(0.4, 0.6, 12, 2.5, 7)})
    save_list(store, [{'ticker': 'SYNTH', 'comment': ''}])
    portfolio = live.current_portfolio(store, base=base)
    seen = []
    def evaluate(holding, pf, provider, light=False):
        seen.append((holding.ticker, light))
        return engine.Evaluation(holding.ticker, 2, True, 12.5, None, None, None, 'WATCH',
                                 [Signal(OPPORTUNITY, 'technical', 'test', 'Invented test signal', 2)], {}, {})
    monkeypatch.setattr(engine, 'evaluate', evaluate)
    evaluations, alerts = scanner.analyse(portfolio, data.get_provider('demo'), store)
    assert [e.ticker for e in evaluations] == ['SYNTH']
    assert [a[0] for a in alerts] == ['SYNTH']
    assert store.snapshot('SYNTH') is not None
    assert seen == [('SYNTH', False)]
    assert portfolio.extras == frozenset()  # scanner suppresses alerts only for extras


def test_comments_are_escaped_under_radar_call_and_link_remains_tappable():
    snap = snapshot()
    ui.set_watch([{'ticker': 'SYNTH', 'comment': '<script>alert("x")</script> & wait'}])
    try:
        for html in (ui.row(snap), tape_screens.radar_rows([snap])):
            assert 'Your note: &lt;script&gt;' in html and '<script>' not in html
            assert '?view=target' in html and 't=SYNTH' in html
    finally:
        ui.set_watch([])
    assert 'Your note:' not in tape_screens.radar_rows([snap])


def test_tracker_schedules_one_worker_every_five_minutes_without_waiting(tmp_path, monkeypatch):
    monkeypatch.setenv('STOCKWATCH_WATCH_SHEET_URL', 'configured-only-no-request')
    monkeypatch.setattr(live, 'base_portfolio', lambda s: Portfolio([], {}))
    entered, release = threading.Event(), threading.Event()
    def slow(store, known):
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(ws, 'sync', slow)
    tracker = live.Tracker(None, store_path=tmp_path / 'job.db', start=False)
    try:
        assert tracker.maybe_watch_sync(now=1000)
        assert entered.wait(2)
        assert tracker.watch_running and not tracker.maybe_watch_sync(now=2000)
    finally:
        release.set()
    # Use the synchronous path to test the schedule deterministically after the worker ends.
    monkeypatch.setattr(ws, 'sync', lambda *args: None)
    # Join the named worker, rather than sleep/poll.
    for worker in threading.enumerate():
        if worker.name == 'stockwatch-watch-sheet':
            worker.join(3)
    assert not tracker.maybe_watch_sync(now=1299)
    assert tracker.maybe_watch_sync(now=1300, background=False)


def test_status_line_shows_count_read_time_or_safe_error(tmp_path):
    store = Store(tmp_path / 'job.db')
    save_list(store, [{'ticker': 'SYNTH', 'comment': ''}])
    assert ws.status_line(store) == 'Watch tab: 1 stocks, read 16:15 (Riyadh)'
    sheet = Sheet([])
    sheet.fail_read = True
    ws.sync(store, sheet=sheet)
    assert 'could not be read' in ws.status_line(store)
