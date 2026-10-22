"""Synthetic pattern fixtures only: none of these values represent Microsoft's financials."""
import copy
from datetime import date
import json
from pathlib import Path

import pytest

from stockwatch import msft_dossier as md, valuation_evidence as ve

DAY = date(2027, 3, 1)
PATTERN = [(100., 20., 60., 15., 3.), (125., 30., 70., 28., 4.), (160., 44.8, 90., 52., 5.)]
TAGS = ('Revenues', 'OperatingIncomeLoss', 'NetCashProvidedByUsedInOperatingActivities',
        'PaymentsToAcquirePropertyPlantAndEquipment', 'ShareBasedCompensation')


def sources(values=PATTERN, mode='ok'):
    facts = {tag: {'units': {'USD': []}} for tag in TAGS}
    for year, vals in zip(range(2024, 2027), values):
        if mode == 'gap' and year == 2025 or mode == 'one' and year != 2026:
            continue
        for tag, value in zip(TAGS, vals):
            facts[tag]['units']['USD'].append({'val': value, 'start': f'{year}-01-01', 'end': f'{year}-12-31',
                 'filed': f'{year+1}-02-15', 'form': '10-K', 'accn': f'0000789019-{str(year+1)[2:]}-000001'})
    if mode == 'revised':
        rev = facts['Revenues']['units']['USD']
        rev.append(rev[-1] | {'val': 170., 'filed': '2027-02-20', 'accn': '0000789019-27-000002'})
    c = {'cik': ve.CIK, 'entityName': 'SYNTHETIC pattern fixture only', 'facts': {'us-gaap': facts}}
    def get(url):
        return c if url == ve.FACTS_URL else {'cik': ve.CIK, 'sic': '7372'}
    def read(url):
        if mode == 'outage':
            raise OSError('synthetic archive outage')
        if url.endswith('/index.json'):
            return b'{"directory":{"item":[{"name":"synthetic.xml"}]}}'
        contexts, rows = [], []
        for tag, item in facts.items():
            for f in item['units']['USD']:
                if f['accn'].replace('-', '') not in url:
                    continue
                if mode == 'missing' and tag == 'Revenues' and f['end'] == '2026-12-31':
                    continue
                i = len(contexts)
                contexts.append(f'<context id="c{i}"><period><startDate>{f["start"]}</startDate><endDate>{f["end"]}</endDate></period></context>')
                rows.append(f'<g:{tag} contextRef="c{i}" unitRef="u">{f["val"]}</g:{tag}>')
        return ('<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:g="http://fasb.org/us-gaap/2025" '
                'xmlns:i="http://www.xbrl.org/2003/iso4217"><unit id="u"><measure>i:USD</measure></unit>'
                + ''.join(contexts + rows) + '</xbrl>').encode()
    return ve.Sources(get=get, get_bytes=read)


def test_deteriorating_residual_despite_growth_is_ranked_first_with_math_and_sources():
    r = md.build(sources(), DAY)
    cc = r['cash_conversion']
    assert cc['status'] == 'OBSERVED ACCOUNTING CHANGES' and cc['consecutive_years'] == 3
    assert [y['ocf_minus_cash_ppe_usd'] for y in cc['annual']] == [45, 42, 38]
    assert [y['ocf_revenue'] for y in cc['annual']] == pytest.approx([.6, .56, .5625])
    assert [y['residual_revenue'] for y in cc['annual']] == pytest.approx([.45, .336, .2375])
    assert cc['yoy'][0]['ocf_minus_cash_ppe_usd_change'] == -3
    assert cc['yoy'][1]['ocf_minus_cash_ppe_usd_pct_change'] == pytest.approx(38/42-1)
    assert cc['yoy'][1]['residual_revenue_change_pp'] == pytest.approx(-9.85)
    assert cc['yoy'][1]['cash_ppe_revenue_change_pp'] == pytest.approx(10.1)
    codes = [f['code'] for f in r['decision']['priority_findings']]
    assert codes == ['persistent_residual_deterioration', 'growth_cash_divergence', 'rising_cash_capital_intensity']
    assert cc['direction']['ocf_minus_cash_ppe_usd_change'] == 'down'
    assert cc['direction']['revenue_usd_change'] == 'up'
    text = md.markdown(r)
    assert text.index('Two consecutive fiscal-year declines') < text.index('OCF exceeded cash PP&E spending')
    assert 'USD -4.000' in text and '-9.85 pp' in text
    assert '2025-12-31' in text and 'not proof of causation' in text
    assert all(y['sources']['capex'].startswith('https://www.sec.gov/') for y in cc['annual'])
    assert all(f['kind'] == 'derived_accounting_observation' for f in cc['findings'])
    assert 'not measured outcomes' in text and 'incremental cash returns' in text
    assert r['decision']['valuation_disposition'] == 'INSUFFICIENT EVIDENCE' and not r['valuation_cases']
    assert r['reverse_implied_growth'] is None and r['version'] == 'msft-dossier.2'


@pytest.mark.parametrize('mode', ['one', 'gap', 'revised', 'missing', 'outage'])
def test_unusable_recent_history_cannot_generate_cash_claims(mode):
    r = md.build(sources(mode=mode), DAY)
    assert r['cash_conversion']['status'] == 'INSUFFICIENT VERIFIED HISTORY'
    assert not r['cash_conversion']['findings'] and not r['decision']['priority_findings']
    assert 'Cash conversion: **INSUFFICIENT VERIFIED HISTORY**' in md.markdown(r)
    assert not r['valuation_cases']


@pytest.mark.parametrize('values,expected', [
    ([(100,20,60,15,3), (125,30,80,18,4), (160,44.8,110,22,5)], 'up'),
    ([(100,20,60,15,3)]*3, 'flat'),
])
def test_improving_and_flat_cash_conversion_have_no_deterioration_flags(values, expected):
    r = md.build(sources(values), DAY)
    assert r['cash_conversion']['direction']['ocf_minus_cash_ppe_usd_change'] == expected
    assert not r['cash_conversion']['findings']


def test_mixed_direction_is_not_labeled_two_consecutive_declines():
    vals = [(100,20,60,15,3), (125,30,85,20,4), (160,44.8,70,15,5)]
    cc = md.build(sources(vals), DAY)['cash_conversion']
    assert cc['direction']['ocf_minus_cash_ppe_usd_change'] == 'mixed'
    assert 'persistent_residual_deterioration' not in [f['code'] for f in cc['findings']]
    assert 'growth_cash_divergence' in [f['code'] for f in cc['findings']]


def test_two_year_window_has_yoy_but_no_three_year_persistence_claim():
    src = sources()
    r = md.build(src, date(2026,3,1))
    cc = r['cash_conversion']
    assert cc['consecutive_years'] == 2 and len(cc['yoy']) == 1
    assert all(y['end'] <= '2025-12-31' for y in cc['annual'])
    assert not any(f['code'] == 'persistent_residual_deterioration' for f in cc['findings'])
    replay = md.build(ve.Sources(copy.deepcopy(src.snapshot)), date(2026,3,1))
    assert replay == r


def test_ambiguous_and_unmatched_rows_never_support_new_diagnostic():
    r = md.build(sources(), DAY)
    rows = copy.deepcopy(r['annual_evidence'])
    for row in rows:
        if row['field'] == 'revenue' and row['source']['end'] == '2026-12-31':
            row['filing_check']['status'] = 'unverified'
    cc = md.cash_conversion(md.economics(rows, DAY), rows)
    assert cc['status'] == 'INSUFFICIENT VERIFIED HISTORY' and not cc['findings']
    rows = copy.deepcopy(r['annual_evidence'])
    dup = copy.deepcopy([x for x in rows if x['source']['end'] == '2026-12-31'])
    for x in dup:
        x['source']['accn'] = '0000789019-27-000099'
        if x['field'] == 'revenue':
            x['value'] = 170
    cc = md.cash_conversion(md.economics(rows+dup, DAY), rows+dup)
    assert not cc['findings'] and cc['status'] == 'INSUFFICIENT VERIFIED HISTORY'


def test_zero_or_negative_ocf_and_residual_do_not_create_invalid_ratios():
    vals = [(100,20,10,10,3), (125,30,0,20,4), (160,44.8,-10,25,5)]
    cc = md.build(sources(vals), DAY)['cash_conversion']
    assert cc['annual'][1]['cash_ppe_ocf'] is None and cc['annual'][2]['cash_ppe_ocf'] is None
    assert cc['yoy'][0]['ocf_minus_cash_ppe_usd_pct_change'] is None  # baseline residual zero
    assert cc['direction']['cash_ppe_ocf_change_pp'] == 'unavailable'
    json.dumps(cc, allow_nan=False)
    root = Path(__file__).resolve().parents[1]
    assert 'risk_score' not in (root/'stockwatch/msft_dossier.py').read_text()
