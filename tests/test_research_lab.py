"""Research Lab view helpers: offline, synthetic or pinned data only."""
import ast
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stockwatch import research_lab as rl

ROOT = Path(__file__).resolve().parents[1]


def wait(jobs, kind, ticker):
    for _ in range(200):
        job = jobs.get(kind, ticker)
        if job and job['state'] != 'running':
            return job
        time.sleep(.01)
    raise AssertionError('job did not finish')


def test_empty_packets_show_assumptions_required_and_never_a_value():
    rows = {r['ticker']: r for r in rl.completeness(rl.load_scenario_config())}
    for t in ('MSFT', 'AVGO', 'MU', 'JPM'):
        assert rows[t]['status'] == 'ASSUMPTIONS REQUIRED' and rows[t]['note'] == '0/6 groups'
    # each company is measured against its own family's requirements
    assert rows['MSFT']['missing'] == [g[0] for g in rl.INDUSTRIAL_GROUPS]
    assert rows['JPM']['family'] == 'bank' and rows['JPM']['missing'] == [g[0] for g in rl.BANK_GROUPS]
    assert 'Balance sheet' not in rows['JPM']['missing']
    # families with no valuation model aren't asked for evidence at all
    assert rows['RIVN']['status'] == rows['BRK-B']['status'] == 'UNAVAILABLE' and not rows['RIVN']['groups']
    assert rows['RIVN']['reason'].startswith('cash-burning')


def packet_for(groups, drop=None):
    packet = {}
    for name, section, keys in groups:
        for k in keys:
            if (name, k) != drop:
                packet.setdefault(section, {})[k] = {'value': 1}
    return packet


def test_bank_and_industrial_readiness_use_their_own_requirements():
    bank = {'X': ('bank', 'test')}
    full_bank = packet_for(rl.BANK_GROUPS)
    row = rl.completeness({'companies': {'X': full_bank}}, bank)[0]
    assert row['status'] == 'READY TO CHECK' and row['missing'] == [] and row['note'] == '6/6 groups'
    # a complete industrial packet doesn't make a bank ready: its tangible-equity inputs are still missing
    row = rl.completeness({'companies': {'X': packet_for(rl.INDUSTRIAL_GROUPS)}}, bank)[0]
    assert row['status'] == 'INCOMPLETE' and 'Tangible common equity' in row['missing']
    row = rl.completeness({'companies': {'X': packet_for(rl.BANK_GROUPS, ('Reconciliations', 'bank_tce'))}}, bank)[0]
    assert row['status'] == 'INCOMPLETE' and row['missing'] == ['Reconciliations'] and row['note'] == '5/6 groups'
    # and a complete bank packet doesn't make an industrial company ready
    ind = {'X': ('cash compounder', 'test')}
    assert rl.completeness({'companies': {'X': full_bank}}, ind)[0]['status'] == 'INCOMPLETE'
    assert rl.completeness({'companies': {'X': packet_for(rl.INDUSTRIAL_GROUPS)}}, ind)[0]['status'] == 'READY TO CHECK'
    assert rl.completeness({'companies': {'X': {}}}, ind)[0]['status'] == 'ASSUMPTIONS REQUIRED'
    # an unclassified company is never called ready, however full its packet
    row = rl.completeness({'companies': {'NEW': packet_for(rl.INDUSTRIAL_GROUPS)}})[0]
    assert row['family'] == 'not classified yet' and row['status'] == 'INCOMPLETE'


def test_a_fresh_sec_check_replaces_the_stored_family():
    jobs = rl.Jobs(ttl=60)
    jobs.submit('valuation', 'MSFT', lambda: {'family': {'family': 'bank'}})
    wait(jobs, 'valuation', 'MSFT')
    fam = rl.checked_families(jobs, ['MSFT', 'JPM'])
    assert fam['MSFT'][0] == 'bank' and fam['MSFT'][1].startswith('Check SEC data') and 'JPM' not in fam
    assert rl.completeness({'companies': {'MSFT': {}}}, fam)[0]['missing'] == [g[0] for g in rl.BANK_GROUPS]


def test_synthetic_example_matches_the_hand_check_and_dilution_weight():
    _, r = rl.synthetic_valuation()
    assert [round(s['equity_per_share'], 4) for s in r['scenarios'].values()] == [18.2927, 24.3902, 30.4878]
    _, d = rl.synthetic_valuation(.02)
    base = d['scenarios']['base']
    assert base['equity_per_share'] == pytest.approx(24.3902439 * base['dilution_claim_weight'])
    assert base['years'][-1]['drivers']['non_sbc_dilution'] == 0   # fades to zero by year 10
    head, grid = rl.sensitivity_grid(r)
    assert head[1:] == ['1.5%', '2.5%', '3.5%'] and len(grid) == 3 and all(len(row) == 4 for row in grid)
    assert rl.scenario_rows(r)[1][:2] == ['Base', '24.39']
    assert len(rl.driver_rows(r['scenarios']['base'])) == 10


def test_pinned_chart_example_reads_as_insufficient_evidence():
    rep = rl.chart_example()
    assert rep['status'] == 'INSUFFICIENT EVIDENCE' and rep['as_of'] == '2018-02-07'
    for size in (20, 40, 60):
        w = rl.window(rep, size)
        assert len(w['matches']) == 4 and w['walk_forward']['n'] == 0
        assert 'Out-of-sample checks: 0' in rl.holdout_note(w, rep['settings'])
        groups = {row[1] for row in rl.summary_rows(w)}
        assert groups == {'Matches', 'Same regime', 'Any dip'}
    assert rl.outcome_rows(rl.window(rep, 20)['matches'][0])[0][0] == '5d'
    assert 'error' in rl.chart_example(ROOT / 'missing.json')


def bars(n=900):
    rng = np.random.default_rng(1)
    close = 100 * np.exp(np.cumsum(rng.normal(0, .01, n)))
    return pd.DataFrame({'Open': close, 'High': close * 1.01, 'Low': close * .99, 'Close': close,
                         'Volume': rng.integers(1000, 2000, n)}, index=pd.bdate_range('2020-01-01', periods=n))


def test_chart_run_uses_completed_sessions_and_labels_the_source():
    frame = bars()

    class YahooProvider:   # stands in for the real class: the label follows the provider's type
        calls = []

        def history(self, ticker, period='5y'):
            self.calls.append((ticker, period))
            return frame

    today = frame.index[-1].date()
    rep = rl.chart_run(YahooProvider(), 'TEST', today=today)
    assert rep['as_of'] == str(frame.index[-2].date())   # the forming bar for `today` is left out
    assert rep['market_data'] is True and rep['source'].startswith('Yahoo daily history')
    assert rep['status'] == 'INSUFFICIENT EVIDENCE'
    assert YahooProvider.calls == [('TEST', 'max'), ('SPY', 'max')]

    class DemoProvider(YahooProvider):
        pass
    rep = rl.chart_run(DemoProvider(), 'TEST', today=today)
    assert rep['market_data'] is False and rep['source'].startswith('DEMO prices')

    class BadDemo(DemoProvider):
        def history(self, ticker, period='5y'):
            f = frame.copy()
            f.iloc[5, 1] = f.iloc[5, 3] * .5   # High below Close
            return f
    BadDemo.__name__ = 'DemoProvider'
    with pytest.raises(ValueError, match='DEMO prices'):
        rl.chart_run(BadDemo(), 'TEST', today=today)


def test_price_source_follows_the_selected_provider_not_a_flag(monkeypatch):
    from stockwatch import data
    # the app's own selection: demo by environment, demo by settings.data_provider, or Yahoo
    for env, setting, expect in (('1', 'yahoo', 'demo'), (None, 'demo', 'demo'), (None, 'yahoo', 'yahoo')):
        if env:
            monkeypatch.setenv('STOCKWATCH_DEMO', env)
        else:
            monkeypatch.delenv('STOCKWATCH_DEMO', raising=False)
        name = data.selected_provider(setting)
        src = rl.price_source(data.get_provider(name))
        assert name == expect and src['market_data'] is (expect == 'yahoo')
        if expect == 'demo':
            assert 'not market observations' in src['text']
        else:
            assert 'auto_adjust' in src['text'] and 'fetched now' not in src['text']
            assert f"{data.CachedProvider.TTL['history']} seconds old" in src['text']
    assert rl.price_source(object())['market_data'] is False
    # the page passes its own provider and never decides the label itself
    page = (ROOT / 'dashboard.py').read_text()
    research = page[page.index('def _research_submit'):page.index('@st.fragment(run_every="5s")')]
    assert 'research_lab.chart_run(data, ticker)' in research and 'STOCKWATCH_DEMO' not in research


def test_valuation_check_treats_an_sec_outage_as_retryable(monkeypatch):
    monkeypatch.setattr(rl.vs, 'research_ticker', lambda t, d, c: {'ticker': t, 'status': 'UNAVAILABLE',
                                                                       'gaps': ['URLError: blocked']})
    with pytest.raises(RuntimeError, match='blocked'):
        rl.valuation_check('MSFT', date(2026, 3, 1))
    monkeypatch.setattr(rl.vs, 'research_ticker', lambda t, d, c: {'ticker': t, 'family': {'family': 'x'}})
    assert rl.valuation_check('MSFT')['family'] == {'family': 'x'}


def test_jobs_run_one_at_a_time_keep_results_and_retry_failures():
    jobs = rl.Jobs(ttl=60)
    gate = __import__('threading').Event()
    assert 'Checking AAA' in jobs.submit('v', 'AAA', lambda: gate.wait(1) and {'ok': 1})
    assert jobs.busy() == ('v', 'AAA')
    assert 'Still working on AAA' in jobs.submit('v', 'BBB', lambda: {'ok': 2})
    gate.set()
    assert wait(jobs, 'v', 'AAA')['result'] == {'ok': 1}
    assert 'showing that result' in jobs.submit('v', 'AAA', lambda: {'ok': 3})   # kept, not re-run
    def boom():
        raise ValueError('no data')
    jobs.submit('v', 'CCC', boom)
    assert wait(jobs, 'v', 'CCC')['error'] == 'ValueError: no data'
    assert 'Checking CCC' in jobs.submit('v', 'CCC', lambda: {'ok': 4})        # a failure can be retried at once
    assert wait(jobs, 'v', 'CCC')['result'] == {'ok': 4}
    expired = rl.Jobs(ttl=60)
    expired.submit('v', 'DDD', lambda: {'ok': 5})
    wait(expired, 'v', 'DDD')
    expired.ttl = 0
    time.sleep(.01)
    assert expired.get('v', 'DDD') is None


def test_ticker_input_is_validated():
    assert rl.clean_ticker(' brk-b ') == 'BRK-B'
    assert rl.clean_ticker('') is None and rl.clean_ticker('MSFT; rm') is None and rl.clean_ticker('1ABC') is None


def _imports(path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            names |= {node.module or ''} | {f'{node.module or ""}.{a.name}'.strip('.') for a in node.names}
        elif isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
    return names


RESEARCH = {'chart_patterns', 'valuation_scenarios', 'valuation_lab', 'sec_quality', 'sec_audit'}
TRADING = {'engine', 'tradeplan', 'analogs', 'store', 'notify', 'scanner', 'live', 'market', 'turbo', 'signals',
           'briefing', 'fundamental', 'technical', 'relative', 'deepdive', 'street', 'catalysts', 'config'}


def test_research_bridge_boundaries():
    # the bridge reaches only the research engines, never scoring, plans, alerts, storage or the portfolio
    used = {n.split('.')[-1] for n in _imports(ROOT / 'stockwatch' / 'research_lab.py')}
    assert not used & TRADING, used & TRADING
    # the page reaches the research engines only through the bridge
    page = ROOT / 'dashboard.py'
    assert 'research_lab' in page.read_text()
    assert not {n.split('.')[-1] for n in _imports(page)} & RESEARCH
    # and nothing on the trading side imports the bridge or the engines
    for p in (ROOT / 'stockwatch').glob('*.py'):
        if p.stem in TRADING:
            assert not {n.split('.')[-1] for n in _imports(p)} & (RESEARCH | {'research_lab'}), p.name
