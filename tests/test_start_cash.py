"""PR #84 task A: capital lifts keep every saved trade and position, exactly once."""
import copy
import json

import pytest

from stockwatch import paper, paper_newcall, quick
from stockwatch.store import Store


@pytest.mark.parametrize('account', ['quick', 'newcall'])
@pytest.mark.parametrize('start,deposit', [(50_000, 50_000), (100_000, 0), (120_000, 0)])
def test_saved_books_lift_once_without_changing_history(tmp_path, account, start, deposit):
    module = quick if account == 'quick' else paper_newcall
    path = tmp_path / 'books.db'
    store = Store(path)
    saved = {
        'cash': 32_123.45, 'start': start,
        'positions': {'SYNTH': {'shares': 30, 'entry': 100, 'stop': 95, 'trade': 7}},
        'trades': [{'id': 7, 'status': 'OPEN'}, {'id': 6, 'status': 'CLOSED', 'result': -12.5}],
        'log': [{'event': str(i)} for i in range(250)],
        'blocked': [{'event': str(i)} for i in range(550)],
        'skipped': [{'event': str(i)} for i in range(350)],
        'next_id': 8, 'entry_times': ['2026-11-10T11:00:00-05:00'], 'extra_history': ['keep this'],
    }
    original = copy.deepcopy(saved)
    raw = json.dumps(saved)
    store.set_setting(module.BOOK_KEY, raw)
    for _ in range(2):
        # Reopen the DB to verify the top-up survives a restart without repeating.
        store = Store(path)
        book = module.load_book(store)
        cash = book['cash'] if account == 'quick' else book.cash
        baseline = book['start'] if account == 'quick' else book.start
        assert cash == original['cash'] + deposit
        assert baseline == max(start, 100_000)
        persisted = json.loads(store.get_setting(module.BOOK_KEY))
        for key, value in original.items():
            if key not in ('cash', 'start'):
                assert persisted[key] == value
        if not deposit:
            assert store.get_setting(module.BOOK_KEY) == raw


def test_new_books_and_position_caps():
    assert quick.new_book()['cash'] == quick.new_book()['start'] == 100_000
    assert paper.Book().cash == paper.Book().start == 100_000
    assert quick.MAX_OPEN == paper_newcall.MAX_POSITIONS == 15
    # The owner kept the percentages; only the dollars implied by them increase.
    assert quick.SIZE_PCT == {'A': 5.0, 'B': 3.0}
    assert quick.START_CASH * quick.SIZE_PCT['A'] / 100 == 5_000
    assert quick.START_CASH * quick.SIZE_PCT['B'] / 100 == 3_000
    assert quick.DAY_LOSS_PCT == 1.0
    assert quick.START_CASH * quick.DAY_LOSS_PCT / 100 == 1_000
    assert paper_newcall.SIZE_CAP_PCT == 15.0


@pytest.mark.parametrize('module', [quick, paper_newcall])
def test_migration_does_not_overwrite_a_newer_trade(tmp_path, monkeypatch, module):
    store = Store(tmp_path / 'race.db')
    saved = {'cash': 40_000, 'start': 50_000, 'trades': [], 'positions': {}}
    store.set_setting(module.BOOK_KEY, json.dumps(saved))
    newer = {**saved, 'cash': 85_000, 'start': 100_000,
             'trades': [{'id': 1, 'status': 'OPEN'}], 'positions': {'SYNTH': {'shares': 50}}}
    replace = store.replace_setting

    def concurrent_trade(key, expected, value):
        # Tracker saved a trade after the page read the old book, before its migration write.
        Store(tmp_path / 'race.db').set_setting(key, json.dumps(newer))
        return replace(key, expected, value)

    monkeypatch.setattr(store, 'replace_setting', concurrent_trade)
    book = module.load_book(store)
    assert (book['cash'] if module is quick else book.cash) == 85_000
    assert json.loads(store.get_setting(module.BOOK_KEY)) == newer
