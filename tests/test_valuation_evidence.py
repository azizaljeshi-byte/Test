"""Synthetic SEC-shaped fixtures only: these numbers do not describe Microsoft."""
import ast
import copy
from datetime import date
import json
from pathlib import Path

import pytest

from stockwatch import research_lab, sec_quality as sq, valuation_evidence as ve

DAY = date(2026, 3, 1)
ACCN = '0000789019-26-000001'


def fixture():
    facts = {}
    for tag, value in [('Revenues', 100.), ('OperatingIncomeLoss', 20.), ('NetIncomeLoss', 15.),
                       ('NetCashProvidedByUsedInOperatingActivities', 30.),
                       ('PaymentsToAcquirePropertyPlantAndEquipment', 10.), ('ShareBasedCompensation', 5.)]:
        facts[tag] = {'units': {'USD': [{'val': value, 'start': f'{y}-01-01', 'end': f'{y}-12-31',
                                      'form': '10-K', 'filed': f'{y+1}-02-15',
                                      'accn': ACCN if y == 2025 else f'0000789019-{str(y+1)[2:]}-000001'}
                                     for y in range(2020, 2026)]}}
    facts['CashAndCashEquivalentsAtCarryingValue'] = {'units': {'USD': [
        {'val': 20., 'end': '2025-12-31', 'form': '10-K', 'filed': '2026-02-15', 'accn': ACCN}]}}
    return {'cik': ve.CIK, 'entityName': 'SYNTHETIC pipeline fixture, NOT Microsoft observations', 'facts': {'us-gaap': facts}}


def instance(company, *, unit='USD', adjust=0, duplicate=False):
    facts = company['facts']['us-gaap']
    rows = []
    for tag, f in facts.items():
        candidates = f['units']['USD']
        end = max(x['end'] for x in candidates)
        fact = min((x for x in candidates if x['end'] == end), key=lambda x: x['filed'])
        val = fact['val'] + (adjust if tag == 'Revenues' else 0)
        context = 'flow' if 'start' in fact else 'instant'
        rows.append(f'<g:{tag} contextRef="{context}" unitRef="money">{val}</g:{tag}>')
        if duplicate and tag == 'Revenues':
            rows.append('<g:Revenues contextRef="flow" unitRef="money">999</g:Revenues>')
    return (f'<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:i="http://www.xbrl.org/2003/iso4217" '
            f'xmlns:g="http://fasb.org/us-gaap/2025">'
            '<context id="flow"><entity><identifier scheme="CIK">789019</identifier></entity>'
            '<period><startDate>2025-01-01</startDate><endDate>2025-12-31</endDate></period></context>'
            '<context id="instant"><entity><identifier scheme="CIK">789019</identifier></entity>'
            '<period><instant>2025-12-31</instant></period></context>'
            f'<unit id="money"><measure>i:{unit}</measure></unit>' + ''.join(rows) + '</xbrl>').encode()


def sources(company=None, **xml_args):
    company = company or fixture()
    def get(url):
        return company if url == ve.FACTS_URL else {'cik': str(ve.CIK), 'sic': '7372'}
    def get_bytes(url):
        if url.endswith('/index.json'):
            return json.dumps({'directory': {'item': [{'name': 'synthetic.xml'}]}}).encode()
        return instance(company, **xml_args)
    return ve.Sources(get=get, get_bytes=get_bytes)


def row(report, key):
    return next(r for r in report['coverage'] if r['field'] == key)


def test_end_to_end_verified_partial_packet_and_decision_first():
    r = ve.evaluate(sources(), DAY)
    assert r['research_disposition'] == 'INSUFFICIENT EVIDENCE'
    assert r['status'] == 'ASSUMPTIONS REQUIRED' and r['evidence_classification'] == 'PARTIAL'
    obs = r['packet']['companies']['MSFT']['observations']
    assert set(obs) == {'revenue', 'cash'} and obs['revenue']['value'] == 100
    assert obs['revenue']['origin'] == 'SEC' and obs['revenue']['accn'] == ACCN
    assert obs['revenue']['available_on'] == '2026-02-15' and obs['revenue']['period_start'] == '2025-01-01'
    assert row(r, 'revenue')['filing_check']['status'] == 'matches'
    assert [d['value'] for d in r['drivers']] == [.1, 20, .05]
    assert not r['scenarios'] and r['reverse_implied_growth'] is None
    assert r['model_disagreement']['status'] == 'UNAVAILABLE'
    text = ve.markdown(r)
    assert text.startswith('# MSFT — INSUFFICIENT EVIDENCE')
    assert text.index('Decision and dominant evidence') < text.index('SEC coverage')
    assert '2025-12-31' in text and ACCN in text
    assert 'unverified hypothesis' == r['bear_thesis']['kind']
    assert '3/6/12' in text


@pytest.mark.parametrize('args', [{'unit': 'EUR'}, {'adjust': 1}, {'duplicate': True}])
def test_filing_units_conflict_and_drift_block_observation(args):
    r = ve.evaluate(sources(**args), DAY)
    assert 'revenue' not in r['packet']['companies']['MSFT']['observations']
    assert row(r, 'revenue')['status'] == 'unverified'
    assert not r['scenarios']


def test_missing_leases_debt_and_diluted_average_never_become_zero_or_spot_shares():
    c = fixture()
    c['facts']['us-gaap']['WeightedAverageNumberOfDilutedSharesOutstanding'] = {
        'units': {'shares': [{'val': 10, 'start': '2025-01-01', 'end': '2025-12-31',
                             'form': '10-K', 'filed': '2026-02-15', 'accn': ACCN}]}}
    r = ve.evaluate(sources(c), DAY)
    obs = r['packet']['companies']['MSFT']['observations']
    assert not {'shares', 'debt', 'finance_lease_liabilities', 'preferred'} & obs.keys()
    requests = {x['field']: x for x in r['requests']}
    assert all(k in requests for k in ('shares', 'finance_lease_liabilities', 'preferred', 'corporate_actions'))
    assert 'EPS averages are not spot' in requests['shares']['reason']


def test_asof_excludes_future_filings_and_flags_restatements():
    c = fixture()
    fact = c['facts']['us-gaap']['Revenues']['units']['USD'][-1]
    c['facts']['us-gaap']['Revenues']['units']['USD'].append(fact | {'val': 200, 'filed': '2026-04-15',
                                                                    'accn': '0000789019-26-000002'})
    early = ve.evaluate(sources(c), DAY)
    assert row(early, 'revenue')['value'] == 100 and row(early, 'revenue')['status'] == sq.USABLE
    later = ve.evaluate(sources(c), date(2026, 4, 20))
    assert row(later, 'revenue')['status'] == sq.RECONCILE
    assert 'revenue' not in later['packet']['companies']['MSFT']['observations']
    before = ve.evaluate(sources(), date(2026, 2, 14))
    assert row(before, 'revenue')['source']['end'] != '2025-12-31'
    assert all(not r['source'] or r['source']['filed'] <= '2026-02-14' for r in before['coverage'])


def test_missing_publication_metadata_and_staleness_refuse():
    c = fixture()
    c['facts']['us-gaap']['Revenues']['units']['USD'][-1]['filed'] = ''
    r = ve.evaluate(sources(c), DAY)
    assert 'revenue' not in r['packet']['companies']['MSFT']['observations']
    stale = ve.evaluate(sources(), date(2027, 3, 1))
    assert row(stale, 'revenue')['status'] == sq.STALE


def test_calendar_period_mismatch_prevents_calculated_drivers():
    c = fixture()
    c['facts']['us-gaap']['PaymentsToAcquirePropertyPlantAndEquipment']['units']['USD'][-1]['end'] = '2025-12-30'
    r = ve.evaluate(sources(c), DAY)
    assert not any(d['driver'] in ('Cash conversion', 'Capital intensity') for d in r['drivers'])


def test_snapshot_replay_hashes_no_network_and_earlier_asof():
    src = sources()
    first = ve.evaluate(src, DAY)
    snap = copy.deepcopy(src.snapshot)
    def forbidden(*args):
        raise AssertionError('replay attempted a fetch')
    replay = ve.evaluate(ve.Sources(snap, get=forbidden, get_bytes=forbidden), DAY)
    assert replay == first
    early = ve.evaluate(ve.Sources(snap, get=forbidden, get_bytes=forbidden), date(2025, 3, 1))
    assert all(not r['source'] or r['source']['end'] < '2026' for r in early['coverage'])
    snap['sources'][ve.FACTS_URL]['sha256'] = 'wrong'
    bad = ve.evaluate(ve.Sources(snap), DAY)
    assert 'hash mismatch' in bad['source_error'] and not bad['scenarios']


def test_outage_and_issuer_mismatch_produce_honest_report(tmp_path):
    def blocked(url):
        raise OSError('source unavailable in test')
    src = ve.Sources(get=blocked)
    r = ve.evaluate(src, DAY)
    assert r['status'] == 'UNAVAILABLE' and r['measured_coverage']['verified_fields'] == 0
    assert not r['drivers'] and r['research_disposition'] == ve.INSUFFICIENT
    assert ve.evaluate(ve.Sources(copy.deepcopy(src.snapshot)), DAY) == r
    snapshot = tmp_path / 'snapshot.json'
    snapshot.write_text(json.dumps(src.snapshot))
    out = tmp_path / 'report'
    assert ve.main(['--snapshot', str(snapshot), '--as-of', str(DAY), '--output', str(out)]) == 0
    assert out.with_suffix('.md').exists() and out.with_suffix('.sources.json').exists()
    c = fixture(); c['cik'] = 123
    assert 'identity mismatch' in ve.evaluate(sources(c), DAY)['source_error']
    with pytest.raises(ValueError):
        ve.Sources({'version': ve.VERSION, 'ticker': 'AVGO', 'sources': {}})


def test_unavailable_filing_and_incomplete_snapshot_never_fetch_on_replay():
    src = sources()
    src.get_bytes = lambda url: (_ for _ in ()).throw(OSError('filing blocked'))
    r = ve.evaluate(src, DAY)
    assert not r['packet']['companies']['MSFT']['observations'] and not r['drivers']
    assert all(r['status'] != sq.USABLE for r in r['coverage'])
    r = ve.evaluate(ve.Sources({'version': ve.VERSION, 'ticker': 'MSFT', 'sources': {}}), DAY)
    assert 'replay never fetches' in r['source_error']


def test_comparable_difference_is_suppressed_for_diluted_base():
    _, base = research_lab.synthetic_valuation()
    assert base['cross_check']['difference_from_base_per_share'] == pytest.approx(20 - 24.3902439024)
    _, diluted = research_lab.synthetic_valuation(.02)
    x = diluted['cross_check']
    assert x['equity_per_share'] == 20
    assert x['difference_from_base_per_share'] is None
    assert 'different dilution bases' in x['comparison_status']


def test_adapter_is_not_imported_by_app_or_trading_modules():
    root = Path(__file__).resolve().parents[1]
    for path in [root / 'dashboard.py', *(root / 'stockwatch').glob('*.py')]:
        if path.name != 'valuation_evidence.py':
            tree = ast.parse(path.read_text())
            names = {a.name.split('.')[-1] for node in ast.walk(tree)
                     if isinstance(node, (ast.Import, ast.ImportFrom)) for a in node.names}
            names |= {node.module.split('.')[-1] for node in ast.walk(tree)
                      if isinstance(node, ast.ImportFrom) and node.module}
            assert 'valuation_evidence' not in names


def test_invalid_publication_chronology_cannot_enter_packet():
    c = fixture()
    c['facts']['us-gaap']['Revenues']['units']['USD'][-1]['filed'] = '2025-12-30'
    r = ve.evaluate(sources(c), DAY)
    assert row(r, 'revenue')['status'] == sq.UNKNOWN
    assert 'revenue' not in r['packet']['companies']['MSFT']['observations']


def test_partial_packet_is_compatible_but_cannot_run_the_scenario_model():
    src = sources()
    r = ve.evaluate(src, DAY)
    company = src.read(ve.FACTS_URL)
    q = sq.quality_company('MSFT', company, src.read(ve.SUBMISSIONS_URL), DAY)
    packet = r['packet']['companies']['MSFT']
    config = research_lab.load_scenario_config()
    out = research_lab.vs.evaluate(q, company, packet, DAY, config)
    assert out['status'] != research_lab.vs.COMPUTED and not out['scenarios']
    for name, observation in packet['observations'].items():
        assert research_lab.vs.evidence(observation, name, DAY, 'USD') == observation['value']
