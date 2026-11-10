"""No Google or market requests: Sheet API and provider are faked."""
import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from stockwatch import smallcap as sc, smallcap_sheet as sheets
from stockwatch.store import Store


class Tab:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.row_count = 2
        self.fail_after_write = False

    def clear(self):
        self.rows = []

    def get_all_values(self):
        return copy.deepcopy(self.rows)

    def resize(self, rows):
        self.row_count = rows

    def update(self, *, range_name, values, value_input_option):
        assert value_input_option == 'RAW'
        start = int(range_name.split(':')[0][1:]) - 1
        while len(self.rows) < start + len(values):
            self.rows.append([])
        self.rows[start:start + len(values)] = copy.deepcopy(values)
        if self.fail_after_write:
            self.fail_after_write = False
            raise TimeoutError('private URL must not appear in CLI output')


class Sheet:
    def __init__(self):
        self.tabs = {}

    def worksheet(self, name):
        import gspread
        if name not in self.tabs:
            raise gspread.WorksheetNotFound(name)
        return self.tabs[name]

    def add_worksheet(self, title, rows, cols):
        assert title in ('Shortlist', 'Log')
        self.tabs[title] = Tab()
        return self.tabs[title]


def batch(events=True):
    return {'shortlist': [['Ticker', 'Resistance'], ['AAA', 'unknown']],
            'log': [['Time (Riyadh)', 'Ticker', 'What happened']] +
                   ([['10 Nov 18:00', 'AAA', 'Entered the shortlist']] if events else []),
            'tickers': ['AAA']}


def test_creates_tabs_replaces_shortlist_appends_events_and_keeps_one_header():
    sheet = Sheet()
    sheets.deliver(sheet, batch(), lambda p: None)
    sheet.tabs['Shortlist'].rows.append(['STALE'])
    second = batch()
    second['shortlist'] = [['Ticker', 'Resistance']]
    sheets.deliver(sheet, second, lambda p: None)
    assert sheet.tabs['Shortlist'].rows == second['shortlist']
    assert len(sheet.tabs['Log'].rows) == 3
    assert sheet.tabs['Log'].rows[0][0] == 'Time (Riyadh)'
    sheets.deliver(sheet, batch(False), lambda p: None)
    assert len(sheet.tabs['Log'].rows) == 3
    assert sheet.tabs['Log'].row_count == 3


def test_empty_first_run_writes_log_header_and_unknown_stays_unknown():
    sheet = Sheet()
    sheets.deliver(sheet, batch(False), lambda p: None)
    assert len(sheet.tabs['Log'].rows) == 1
    assert sheet.tabs['Shortlist'].rows[1][1] == 'unknown'


def test_timeout_after_server_write_retries_reserved_rows_from_disk(tmp_path):
    sheet, db = Sheet(), tmp_path / 'job.db'
    sheet.tabs['Log'] = Tab([['header'], ['old event']])
    sheet.tabs['Log'].fail_after_write = True
    store = Store(db)
    save = lambda p: store.set_setting('pending', json.dumps(p))
    with pytest.raises(TimeoutError):
        sheets.deliver(sheet, batch(), save)
    pending = json.loads(Store(db).get_setting('pending'))
    assert pending['log_start'] == 3
    sheets.deliver(sheet, pending, save)
    assert len(sheet.tabs['Log'].rows) == 3  # accepted timeout didn't duplicate the event


@pytest.fixture
def session(monkeypatch):
    import stockwatch.data as data
    monkeypatch.setattr(data, 'us_session', lambda now: 'REGULAR')


@pytest.mark.parametrize('missing', ['url', 'key', 'bad_key', 'bad_url'])
def test_missing_or_invalid_config_exits_before_db_or_scan(monkeypatch, capsys, tmp_path, session, missing):
    monkeypatch.delenv('GOOGLE_SERVICE_ACCOUNT_JSON', raising=False)
    monkeypatch.delenv('GOOGLE_APPLICATION_CREDENTIALS', raising=False)
    monkeypatch.delenv('STOCKWATCH_SMALLCAP_SHEET_URL', raising=False)
    if missing != 'url':
        # Fictional ID only; never the owner's link.
        monkeypatch.setenv('STOCKWATCH_SMALLCAP_SHEET_URL',
                           'https://docs.google.com/spreadsheets/d/fake-test-id' if missing != 'bad_url' else 'private-bad-url')
    if missing in ('bad_key', 'bad_url'):
        monkeypatch.setenv('GOOGLE_SERVICE_ACCOUNT_JSON', 'private-invalid-json')
    db = tmp_path / 'unused.db'
    assert sc.main(['--db', str(db)]) == 0
    output = capsys.readouterr().out
    assert 'Missing' in output or 'Cannot read' in output or 'must be' in output
    assert 'private-' not in output
    assert not db.exists()


@pytest.mark.parametrize('source', ['json', 'file'])
def test_connect_uses_service_account_and_sheets_scope_only(monkeypatch, source):
    import gspread
    from google.oauth2.service_account import Credentials
    calls = []
    monkeypatch.setenv('STOCKWATCH_SMALLCAP_SHEET_URL', 'https://docs.google.com/spreadsheets/d/fake-test-id')
    monkeypatch.delenv('GOOGLE_SERVICE_ACCOUNT_JSON', raising=False)
    monkeypatch.setenv('GOOGLE_APPLICATION_CREDENTIALS', 'fake-key-file')
    if source == 'json':
        monkeypatch.setenv('GOOGLE_SERVICE_ACCOUNT_JSON', '{"type":"service_account"}')
    def credentials(value, scopes):
        calls.append((value, scopes))
        return 'fake-credentials'
    monkeypatch.setattr(Credentials, 'from_service_account_info', credentials)
    monkeypatch.setattr(Credentials, 'from_service_account_file', credentials)
    monkeypatch.setattr(gspread, 'authorize', lambda c: SimpleNamespace(open_by_url=lambda url: (c, url), set_timeout=lambda seconds: None))
    assert sheets.connect()[0] == 'fake-credentials'
    assert calls[0][1] == ['https://www.googleapis.com/auth/spreadsheets']
    assert isinstance(calls[0][0], dict) == (source == 'json')


@pytest.mark.parametrize('stamp,active', [
    ('2026-11-10T08:59:00', False), ('2026-11-10T09:00:00', True),
    ('2026-11-11T00:59:00', True), ('2026-11-11T01:00:00', False),
    ('2026-07-06T07:59:00', False), ('2026-07-06T08:00:00', True),
    ('2026-07-07T00:00:00', False), ('2026-11-14T15:00:00', False),
    ('2026-11-15T15:00:00', False),
])
def test_session_gate_boundaries_dst_weekends(stamp, active):
    from stockwatch.data import us_session
    assert (us_session(datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)) != 'CLOSED') == active


def test_closed_cli_does_not_connect_or_create_db(monkeypatch, tmp_path, capsys):
    import stockwatch.data as data
    monkeypatch.setattr(data, 'us_session', lambda now: 'CLOSED')
    monkeypatch.setattr(sheets, 'connect', lambda: pytest.fail('must not connect'))
    db = tmp_path / 'unused.db'
    assert sc.main(['--db', str(db)]) == 0
    assert 'skipped' in capsys.readouterr().out and not db.exists()


def test_cli_pending_delivery_survives_failure_and_retries_before_scan(monkeypatch, tmp_path, session, capsys):
    import stockwatch.data as data
    sheet, db = Sheet(), tmp_path / 'smallcap.db'
    monkeypatch.setattr(sheets, 'connect', lambda: sheet)
    monkeypatch.setattr(data, 'get_provider', lambda kind: object())
    monkeypatch.setattr(sc, 'universe', lambda store, now: (['AAA'], 'test list'))
    scans = []
    def run(provider, tickers, store, now, on_result):
        scans.append(1)
        result = {'rows': [], 'log': [], 'qualified': 0, 'tradable': 1, 'universe': 1, 'fundamentals_missing': 1}
        on_result(result)
        return result
    monkeypatch.setattr(sc, 'run', run)
    sheet.tabs['Log'] = Tab()
    sheet.tabs['Log'].fail_after_write = True
    assert sc.main(['--db', str(db)]) == 1
    assert Store(db).get_setting('smallcap_sheet_pending') != 'null'
    assert 'private URL' not in capsys.readouterr().out
    assert sc.main(['--db', str(db)]) == 0
    assert scans == [1]
    assert Store(db).get_setting('smallcap_sheet_pending') == 'null'
    assert len(sheet.tabs['Log'].rows) == 1


def test_demo_never_connects_to_google(monkeypatch, tmp_path, session):
    import stockwatch.data as data
    monkeypatch.setattr(sheets, 'connect', lambda: pytest.fail('demo must not connect'))
    monkeypatch.setattr(data, 'get_provider', lambda kind: object())
    monkeypatch.setattr(sc, 'universe', lambda store, now: ([], 'test'))
    monkeypatch.setattr(sc, 'run', lambda *args, **kw: {
        'rows': [], 'log': [], 'qualified': 0, 'tradable': 0, 'universe': 0, 'fundamentals_missing': 0})
    assert sc.main(['--demo', '--out', str(tmp_path / 'csv'), '--db', str(tmp_path / 'live.db')]) == 0
    assert not (tmp_path / 'live.db').exists()
