"""Synthetic data only; successful source paths do not assert real MSFT values."""
import ast
import copy
from datetime import date
import json
from pathlib import Path

from stockwatch import msft_dossier as md, sec_quality as sq, valuation_evidence as ve
from test_valuation_evidence import fixture, instance

DAY = date(2026, 3, 1)


def sources(*, missing=False, changed=False):
    c = fixture()
    if changed:
        c['facts']['us-gaap']['Revenues']['units']['USD'][-1]['val'] = 120
        c['facts']['us-gaap']['PaymentsToAcquirePropertyPlantAndEquipment']['units']['USD'][-1]['val'] = 20
    def get(url):
        return c if url == ve.FACTS_URL else {'cik': ve.CIK, 'sic': '7372'}
    def read(url):
        if missing:
            raise OSError('synthetic archive outage')
        if url.endswith('/index.json'):
            return b'{"directory":{"item":[{"name":"synthetic.xml"}]}}'
        # A synthetic instance per original accession. Values are intentionally not MSFT facts.
        year = 2000 + int(url.split('/')[-2][10:12]) - 1
        cc = copy.deepcopy(c)
        for f in cc['facts']['us-gaap'].values():
            f['units']['USD'] = [x for x in f['units']['USD'] if x['end'].startswith(str(year))]
        cc['facts']['us-gaap'] = {k: v for k, v in cc['facts']['us-gaap'].items() if v['units']['USD']}
        raw = instance(cc)
        return raw.replace(b'2025-01-01', f'{year}-01-01'.encode()).replace(b'2025-12-31', f'{year}-12-31'.encode())
    return ve.Sources(get=get, get_bytes=read)


def test_multiyear_findings_are_sourced_and_price_still_refused():
    r = md.build(sources(changed=True), DAY)
    assert r['business_economics']['status'] == 'OBSERVED MULTI-YEAR ECONOMICS'
    years = r['business_economics']['years']
    assert len(years) == 3 and years[0]['values']['revenue'] == 120
    assert years[0]['operating_margin'] == 20/120
    assert years[0]['ocf_less_cash_capex'] == 10
    assert r['decision']['positive_findings'] and r['decision']['opposing_findings']
    assert all(y['sources']['revenue'].startswith('https://www.sec.gov/') for y in years)
    assert r['decision']['valuation_disposition'] == 'INSUFFICIENT EVIDENCE'
    assert not r['valuation_cases'] and r['reverse_implied_growth'] is None
    assert all(g['status'] == 'missing' for g in r['readiness_gates'][1:])
    text = md.markdown(r)
    assert text.index('valuation:') < text.index('<details>')
    assert 'not a 3/6/12-month' in text and 'not FCFF' in text
    assert {i['field'] for i in r['matching_investigations']} == set(md.WATCH)


def test_archive_outage_never_becomes_a_business_conclusion():
    r = md.build(sources(missing=True), DAY)
    assert r['business_economics']['status'] == 'INSUFFICIENT VERIFIED HISTORY'
    assert not r['decision']['positive_findings'] and not r['business_economics']['years']
    assert r['coverage_counts']['verified'] == 0
    assert r['coverage_counts']['provisional'] > 0


def test_replay_and_earlier_asof_have_no_lookahead():
    src = sources()
    original = md.build(src, DAY)
    replay = md.build(ve.Sources(copy.deepcopy(src.snapshot)), DAY)
    assert original == replay
    early = md.build(ve.Sources(copy.deepcopy(src.snapshot)), date(2025, 3, 1))
    assert all(not r['source'] or r['source']['filed'] <= '2025-03-01' for r in early['annual_evidence'])
    assert all(y['end'] <= '2024-12-31' for y in early['business_economics']['years'])
    assert all(not r['parts'] or all(p['source']['filed'] <= '2025-03-01' for p in r['parts']) for r in early['ttm_evidence'])


def test_unprefixed_share_units_dei_and_eps_are_resolved_without_inventing_units():
    raw = b'''<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:g="http://fasb.org/us-gaap/2025"
       xmlns:dei="http://xbrl.sec.gov/dei/2025" xmlns:i="http://www.xbrl.org/2003/iso4217">
       <context id="x"><period><instant>2025-12-31</instant></period></context>
       <unit id="s"><measure>shares</measure></unit>
       <unit id="p"><divide><unitNumerator><measure>i:USD</measure></unitNumerator>
       <unitDenominator><measure>shares</measure></unitDenominator></divide></unit>
       <dei:EntityCommonStockSharesOutstanding contextRef="x" unitRef="s">10</dei:EntityCommonStockSharesOutstanding>
       <g:EarningsPerShareDiluted contextRef="x" unitRef="p">2.15</g:EarningsPerShareDiluted></xbrl>'''
    out = sq.parse_instance(raw)
    assert out[('EntityCommonStockSharesOutstanding', None, '2025-12-31')] == [(10, sq.XBRLI+'shares')]
    assert out[('EarningsPerShareDiluted', None, '2025-12-31')] == [(2.15, '{'+sq.ISO4217+'}USD/'+sq.XBRLI+'shares')]
    bad = raw.replace(b'<measure>shares</measure>', b'<measure>notDeclared:shares</measure>')
    assert sq.parse_instance(bad)[('EntityCommonStockSharesOutstanding', None, '2025-12-31')][0][1] is None
    dimensioned = raw.replace(b'<context id="x">', b'<context id="x"><scenario/>')
    assert not sq.parse_instance(dimensioned)


def test_single_year_nonconsecutive_or_stale_history_does_not_establish_quality():
    r = md.build(sources(), DAY)
    annual = r['annual_evidence']
    one = [x for x in annual if x['source'] and x['source']['end'] == '2025-12-31']
    assert md.economics(one, DAY)['status'] == 'INSUFFICIENT VERIFIED HISTORY'
    gaps = [x for x in annual if x['source'] and x['source']['end'] != '2024-12-31']
    assert md.economics(gaps, DAY)['status'] == 'INSUFFICIENT VERIFIED HISTORY'
    assert md.economics(annual, date(2030, 1, 1))['status'] == 'INSUFFICIENT VERIFIED HISTORY'


def test_conflicts_and_wrong_periods_cannot_support_trends():
    r = md.build(sources(), DAY)
    rows = r['annual_evidence']
    for x in rows:
        if x['field'] == 'operating_cash_flow':
            x['status'] = sq.RECONCILE
    assert not md.economics(rows, DAY)['positive_findings']
    assert not md.economics(rows, DAY)['years']


def test_ttm_unmatched_component_is_not_usable():
    r = md.build(sources(missing=True), DAY)
    assert all(t['value'] is None and t['status'] != sq.USABLE for t in r['ttm_evidence'])
    r = md.build(sources(), DAY)
    assert any(t['status'] == sq.USABLE for t in r['ttm_evidence'])
    for t in r['ttm_evidence']:
        if t['status'] == sq.USABLE:
            assert all(p['filing_check']['status'] == 'matches' for p in t['parts'])


def test_dossier_source_failure_cli_and_isolation(tmp_path, monkeypatch):
    snapshot = {'version': ve.VERSION, 'ticker': 'MSFT', 'sources': {}}
    path = tmp_path/'empty.json'; path.write_text(json.dumps(snapshot))
    assert md.main(['--snapshot', str(path), '--as-of', str(DAY), '--output', str(tmp_path/'out')]) == 2
    assert 'INSUFFICIENT EVIDENCE' in (tmp_path/'out.md').read_text()
    root = Path(__file__).resolve().parents[1]
    for p in [root/'dashboard.py', *(root/'stockwatch').glob('*.py')]:
        nodes = list(ast.walk(ast.parse(p.read_text())))
        imports = {a.name.split('.')[-1] for n in nodes if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        imports |= {n.module.split('.')[-1] for n in nodes if isinstance(n, ast.ImportFrom) and n.module}
        if p.name != 'msft_dossier.py':
            assert 'msft_dossier' not in imports
        else:
            assert not {'engine', 'tradeplan', 'store', 'notify', 'live', 'signals', 'config'} & imports


def test_unit_namespace_shadowing_is_resolved_locally_not_from_later_declarations():
    xml = b'''<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:m="urn:wrong">
    <unit id="wrong"><measure>m:USD</measure></unit>
    <unit id="right" xmlns:m="http://www.xbrl.org/2003/iso4217"><measure>m:USD</measure></unit>
    <unit id="undeclared"><measure xmlns="">shares</measure></unit>
    <unit id="shares"><measure>shares</measure></unit></xbrl>'''
    units = sq._units(xml, None)
    assert units['wrong'] == '{urn:wrong}USD'
    assert units['right'] == '{'+sq.ISO4217+'}USD'
    assert 'undeclared' not in units and units['shares'] == sq.XBRLI+'shares'


def test_recent_consecutive_pair_survives_older_gap_without_bridging_it():
    rows = md.build(sources(), DAY)['annual_evidence']
    gap = [r for r in rows if r['source']['end'] in ('2025-12-31', '2024-12-31', '2022-12-31')]
    result = md.economics(gap, DAY)
    assert result['status'] == 'OBSERVED MULTI-YEAR ECONOMICS'
    assert [y['end'] for y in result['years']] == ['2025-12-31', '2024-12-31']
    single = [r for r in gap if r['source']['end'] != '2024-12-31']
    result = md.economics(single, DAY)
    assert result['status'] == 'INSUFFICIENT VERIFIED HISTORY'
    assert [y['end'] for y in result['years']] == ['2025-12-31']
    assert not result['positive_findings']


def test_identical_duplicate_years_keep_provenance_but_conflicts_fail_closed():
    rows = md.build(sources(), DAY)['annual_evidence']
    duplicate = copy.deepcopy([r for r in rows if r['source']['end'] == '2025-12-31'])
    other_accn = '0000789019-26-000099'
    for r in duplicate:
        r['source']['accn'] = other_accn
        r['filing_check']['url'] = sq._archive(ve.CIK, other_accn) + '/synthetic.xml'
    same = md.economics(rows + duplicate, DAY)
    assert same['status'] == 'OBSERVED MULTI-YEAR ECONOMICS'
    assert len(same['years']) == 3 and not same['ambiguous_years']
    assert set(same['years'][0]['corroborating_accessions']) == {'0000789019-26-000001', other_accn}
    next(r for r in duplicate if r['field'] == 'revenue')['value'] = 150
    bad = md.economics(rows + duplicate, DAY)
    assert bad['status'] == 'INSUFFICIENT VERIFIED HISTORY' and not bad['years']
    assert bad['ambiguous_years'][0]['end'] == '2025-12-31'
    assert not bad['positive_findings'] and not bad['opposing_findings']


def quarterly_sources(mode='ok'):
    """True annual + current 10-Q YTD - prior 10-Q YTD, independently filed/matched."""
    c = fixture()
    rev = c['facts']['us-gaap']['Revenues']['units']['USD']
    prior = {'val': 40., 'start': '2025-01-01', 'end': '2025-06-30', 'form': '10-Q',
             'filed': '2025-08-01', 'accn': '0000789019-25-000002'}
    current = {'val': 60., 'start': '2026-01-01', 'end': '2026-06-30', 'form': '10-Q',
               'filed': '2026-08-01', 'accn': '0000789019-26-000002'}
    rev += [prior, current]
    if mode == 'revised':
        rev.append(current | {'val': 80., 'filed': '2026-08-10', 'accn': '0000789019-26-000003'})
    def get(url):
        return c if url == ve.FACTS_URL else {'cik': ve.CIK, 'sic': '7372'}
    def get_bytes(url):
        if mode == 'absent' and current['accn'].replace('-', '') in url:
            raise OSError('synthetic missing current 10-Q')
        if url.endswith('/index.json'):
            return b'{"directory":{"item":[{"name":"synthetic.xml"}]}}'
        contexts, facts = [], []
        for tag, byunit in c['facts']['us-gaap'].items():
            for fact in byunit['units']['USD']:
                if fact['accn'].replace('-', '') not in url:
                    continue
                i = len(contexts)
                end = '2026-06-29' if mode == 'mismatch' and fact is current else fact['end']
                period = f"<startDate>{fact['start']}</startDate><endDate>{end}</endDate>" if fact.get('start') else f'<instant>{end}</instant>'
                contexts.append(f'<context id="c{i}"><period>{period}</period></context>')
                facts.append(f'<g:{tag} contextRef="c{i}" unitRef="u">{fact["val"]}</g:{tag}>')
        return ('<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:g="http://fasb.org/us-gaap/2025" '
                'xmlns:i="http://www.xbrl.org/2003/iso4217"><unit id="u"><measure>i:USD</measure></unit>'
                + ''.join(contexts + facts) + '</xbrl>').encode()
    return ve.Sources(get=get, get_bytes=get_bytes)


def test_true_quarterly_ttm_matches_each_filing_and_rejects_bad_components():
    day = date(2026, 8, 15)
    def revenue(src):
        c = src.read(ve.FACTS_URL)
        q = sq.quality_company('MSFT', c, src.read(ve.SUBMISSIONS_URL), day)
        return next(r for r in md.ttm_rows(q, src, day, {}) if r['field'] == 'revenue')
    result = revenue(quarterly_sources())
    assert result['status'] == sq.USABLE and result['value'] == 120  # FY100 + YTD60 - prior40
    parts = result['parts']
    assert len(parts) == 3
    assert {p['source']['form'] for p in parts} == {'10-K', '10-Q'}
    assert len({p['source']['accn'] for p in parts}) == 3
    assert all(p['unit'] == 'USD' and p['filing_check']['status'] == 'matches' for p in parts)
    assert {p['source']['end'] for p in parts} == {'2025-12-31', '2025-06-30', '2026-06-30'}
    for mode in ('absent', 'revised', 'mismatch'):
        refused = revenue(quarterly_sources(mode))
        assert refused['status'] != sq.USABLE and refused['value'] is None, mode


def test_markdown_headings_are_separate_blocks_and_failure_is_near_conclusion():
    report = md.build(sources(changed=True), DAY)
    text = md.markdown(report)
    assert '\n\n**Opposing observations**\n\n' in text
    assert '\n\n**Positive observations**\n\n' in text
    failed = md.build(ve.Sources({'version': ve.VERSION, 'ticker': 'MSFT', 'sources': {}}), DAY)
    text = md.markdown(failed)
    assert text.index('INSUFFICIENT EVIDENCE') < text.index('**Source warning:**') < text.index('Business economics:')
    assert text.count(failed['source_failure']) == 1
