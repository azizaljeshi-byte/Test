"""Synthetic readiness sources only. No issuer prices, yields, beta or debt figures."""
import ast
import copy
from datetime import date
import json
from pathlib import Path

import pytest

from stockwatch import valuation_readiness as vr, msft_dossier as md, valuation_evidence as ve
from test_cash_conversion import sources, DAY


def xml_rates(*entries):
    return ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">' +
            ''.join(f'<entry><d:NEW_DATE>{day}T00:00:00</d:NEW_DATE><d:BC_10YEAR>{rate}</d:BC_10YEAR></entry>'
                    for day,rate in entries) + '</feed>').encode()


def test_treasury_official_capture_ratio_chronology_and_replay():
    raw = xml_rates(('2026-10-20','4.0'),('2026-10-21','4.1'),('2026-10-22','9.9'))
    src = vr.TreasurySources(read=lambda u: raw)
    r = vr.treasury_10y(src,date(2026,10,22))
    assert r['status'] == vr.USABLE and r['value'] == pytest.approx(.041)
    assert r['period_end'] == '2026-10-21' and r['available_on'] == '2026-10-22'
    assert r['source'].startswith(vr.TREASURY_ROOT) and 'par yield' in r['basis']
    replay = vr.TreasurySources(copy.deepcopy(src.snapshot),read=lambda u: pytest.fail('network'))
    assert vr.treasury_10y(replay,date(2026,10,22)) == r
    src.snapshot['sources'][r['source']]['sha256'] = 'tampered'
    assert vr.treasury_10y(vr.TreasurySources(src.snapshot),date(2026,10,22))['status'] == vr.UNAVAILABLE


@pytest.mark.parametrize('raw,state', [
    (xml_rates(('2026-10-01','4.0')),vr.UNAVAILABLE),
    (xml_rates(('2026-10-21','')),vr.UNAVAILABLE),
    (xml_rates(('2026-10-21','4.0'),('2026-10-21','4.5')),vr.RECONCILE),
    (b'changed source schema',vr.UNAVAILABLE),
])
def test_missing_stale_conflicting_and_changed_treasury_refuse(raw,state):
    assert vr.treasury_10y(vr.TreasurySources(read=lambda u:raw),date(2026,10,22))['status'] == state


def test_treasury_outage_no_substitute_or_secret_message():
    def failed(url):
        raise OSError('secret identity in upstream exception')
    r = vr.treasury_10y(vr.TreasurySources(read=failed),date(2026,10,22))
    assert r['status'] == vr.UNAVAILABLE and r['value'] is None
    assert 'secret' not in json.dumps(r)


def price(**changes):
    return {'ticker':'MSFT','value':100.,'unit':'USD/share','date':'2026-10-21','available_on':'2026-10-22',
            'source':'https://example.test/public-close','provider':'synthetic source','license_reference':'synthetic permission only',
            'captured_at':'2026-10-21','basis':'raw_unadjusted','class_id':'MSFT-common','split_basis_date':'2026-10-21',
            'corporate_actions_reviewed_through':'2026-10-22',**changes}


def test_valid_close_is_candidate_not_validated_market_cap_and_drops_unrelated_secrets():
    r=vr.market_close_candidate(price(api_key='synthetic-secret'),date(2026,10,22))
    assert r['status'] == vr.RECONCILE and r['value']==100
    assert 'api_key' not in r and 'synthetic-secret' not in json.dumps(r)
    assert vr.market_close_candidate(None,date(2026,10,22))['value'] is None


@pytest.mark.parametrize('changes', [
    {'date':'2026-09-01'},{'available_on':'2026-10-23'},{'basis':'dividend_adjusted'},
    {'class_id':'another-class'},{'split_basis_date':'2020-01-01'},{'corporate_actions_reviewed_through':'2026-10-20'},
    {'unit':'EUR/share'},{'corporate_actions_reviewed_through':'2026-10-23'},{'source':'https://example.test/quote?apikey=secret'},{'captured_at':'2026-10-23'},
])
def test_price_stale_forward_adjustment_class_and_action_mismatch_refuse(changes):
    r=vr.market_close_candidate(price(**changes),date(2026,10,22))
    assert r['status']==vr.UNAVAILABLE and r['value'] is None


def series(ticker, multiplier=1):
    rows=[];value=100.
    for i in range(37):
        day=date(2023+i//12,1+i%12,28)
        value *= 1+multiplier*(.01 if i%2 else -.005)
        rows.append({'date':str(day),'available_on':str(day),'close':value})
    return {'ticker':ticker,'source':f'https://example.test/{ticker}','provider':'synthetic only',
            'currency':'USD','license_reference':'synthetic permission only','basis':'split_and_dividend_adjusted','observations':rows}


def test_reproducible_beta_uses_adjusted_aligned_monthly_returns_but_is_not_adopted_wacc():
    stock,market=series('MSFT',2),series('SPY')
    r=vr.beta_candidate(stock,market,date(2026,2,1))
    assert r['status']==vr.RECONCILE and r['value']==pytest.approx(2.)
    assert r['return_count']==36 and r['frequency']=='monthly simple returns'
    assert vr.beta_candidate(None,market,date(2026,2,1))['status']==vr.UNAVAILABLE


@pytest.mark.parametrize('mode',['adjusted_mismatch','gap','date_mismatch','future','stale','variance_zero'])
def test_beta_missing_misaligned_forward_or_no_variance_refuses(mode):
    a,b=series('MSFT'),series('SPY')
    day=date(2026,2,1)
    if mode=='adjusted_mismatch':a['basis']='raw_unadjusted'
    if mode=='gap':a['observations'].pop(5);b['observations'].pop(5)
    if mode=='date_mismatch':b['observations'][-1]['date']='2026-01-27'
    if mode=='future':a['observations'][-1]['available_on']='2027-01-01'
    if mode=='stale':day=date(2027,1,1)
    if mode=='variance_zero':
        for r in b['observations']:r['close']=100.
    assert vr.beta_candidate(a,b,day)['status']==vr.UNAVAILABLE


def capital_sources():
    c=sources().read(ve.FACTS_URL)
    values={'CashAndCashEquivalentsAtCarryingValue':10.,'FinanceLeaseLiability':8.,
            'FinanceLeaseLiabilityCurrent':3.,'FinanceLeaseLiabilityNoncurrent':5.,
            'LongTermDebt':50.,'LongTermDebtNoncurrent':40.,'LongTermDebtCurrent':10.,'CommercialPaper':4.}
    for tag,value in values.items():
        c['facts']['us-gaap'][tag]={'units':{'USD':[{'val':value,'end':'2026-12-31','filed':'2027-02-15',
                                                   'form':'10-K','accn':'0000789019-27-000001'}]}}
    def get(url):return c if url==ve.FACTS_URL else {'cik':ve.CIK,'sic':'7372'}
    def read(url):
        if url.endswith('/index.json'):return b'{"directory":{"item":[{"name":"synthetic.xml"}]}}'
        nodes=[]
        for tag,value in values.items():nodes.append(f'<g:{tag} contextRef="c" unitRef="u">{value}</g:{tag}>')
        return ('<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:g="http://fasb.org/us-gaap/2025" xmlns:i="http://www.xbrl.org/2003/iso4217">'
                '<context id="c"><period><instant>2026-12-31</instant></period></context><unit id="u"><measure>i:USD</measure></unit>'
                +''.join(nodes)+'</xbrl>').encode()
    return ve.Sources(get=get,get_bytes=read)


def test_same_date_original_filing_capital_observations_and_lease_sum_do_not_clear_bridge():
    src=capital_sources();r=vr.evaluate(src,DAY)
    fields={f['field']:f for f in r['fields']}
    assert fields['cash']['status']==vr.USABLE and fields['cash']['value']==10
    lease=r['lease_reconciliations']['finance_leases']
    assert lease['status']==vr.USABLE and 'ONCE' in lease['reason']
    assert fields['preferred_claims']['status']==vr.UNAVAILABLE and fields['preferred_claims']['value'] is None
    assert fields['noncontrolling_claims']['value'] is None
    assert r['blockers']==['price_share_basis','capital_bridge','discount_inputs','approved_forward_assumptions']
    assert 'overlap' in next(g['reason'] for g in r['gates'] if g['gate']=='capital_bridge')
    assert not r['valuation_cases'] and r['reverse_implied_growth'] is None


def test_missing_mismatched_date_or_conflicting_lease_sum_is_not_accepted():
    rows=vr.sec_capital(capital_sources(),DAY)
    rows['finance_leases_current']['value']=4
    assert vr.lease_check(rows,'finance_leases')['status']==vr.RECONCILE
    rows['finance_leases_current']['value']=3
    rows['finance_leases_current']['source']['end']='2026-09-30'
    assert vr.lease_check(rows,'finance_leases')['status']==vr.RECONCILE
    rows['finance_leases_current']['status']=vr.UNAVAILABLE
    assert vr.lease_check(rows,'finance_leases')['status']==vr.UNAVAILABLE


def test_readiness_preserves_unapproved_policies_and_no_valuation_even_with_treasury():
    rate=vr.treasury_10y(vr.TreasurySources(read=lambda u:xml_rates(('2027-02-28','4.0'))),DAY)
    r=md.build(sources(),DAY,treasury=rate)
    ready=r['valuation_readiness'];fields={x['field']:x for x in ready['fields']}
    assert fields['treasury_10y']['status']==vr.USABLE
    assert fields['beta']['value'] is None and fields['marginal_borrowing_cost']['value'] is None
    assert fields['erp_policy']['value'] is None and fields['tax_policy']['value'] is None
    assert r['version']=='msft-dossier.3' and r['decision']['valuation_disposition']=='INSUFFICIENT EVIDENCE'
    assert not r['valuation_cases'] and r['reverse_implied_growth'] is None
    assert 'Valuation readiness blockers:' in md.markdown(r)
    assert 'secret' not in json.dumps(r)


def test_presentation_scales_only_text_names_both_and_preserves_ocf_counterevidence():
    assert md.movement(-4.624e9)=='USD -4.62B' and md.movement(2.5e6)=='USD +2.50M'
    assert md.fiscal_pair('2025-06-30','2026-06-30')=='FY2025 → FY2026 (ended 30 Jun)'
    r=md.build(sources(),DAY)
    text=md.markdown(r)
    assert 'declines in both OCF minus cash PP&E spending and residual/revenue' in text
    assert 'OCF/revenue nevertheless improved' in text
    assert r['cash_conversion']['yoy'][-1]['residual_revenue_change_pp']==pytest.approx(-9.85)


def test_readiness_isolation_and_snapshot_replay_remain_network_free():
    src=capital_sources();first=vr.evaluate(src,DAY)
    assert vr.evaluate(ve.Sources(copy.deepcopy(src.snapshot)),DAY)==first
    root=Path(__file__).resolve().parents[1]
    for p in [root/'dashboard.py',*(root/'stockwatch').glob('*.py')]:
        nodes=list(ast.walk(ast.parse(p.read_text())))
        imports={a.name.split('.')[-1] for n in nodes if isinstance(n,(ast.Import,ast.ImportFrom)) for a in n.names}
        imports|={n.module.split('.')[-1] for n in nodes if isinstance(n,ast.ImportFrom) and n.module}
        if p.name not in ('valuation_readiness.py','msft_dossier.py'):assert 'valuation_readiness' not in imports
        if p.name=='valuation_readiness.py':assert not {'engine','tradeplan','store','notify','live','signals','config'} & imports


@pytest.mark.parametrize('values,subject', [
    ([(100,20,60,15,3),(80,19.2,55,15,4),(60,16.8,50,15,5)], 'OCF minus cash PP&E spending'),
    ([(100,20,60,15,3),(150,36,70,20,4),(220,61.6,90,35,5)], 'residual/revenue'),
])
def test_persistence_names_only_the_quantity_that_actually_declined(values,subject):
    cc=md.build(sources(values),DAY)['cash_conversion']
    text=next(x['text'] for x in cc['findings'] if x['code']=='persistent_residual_deterioration')
    assert text.startswith('Two consecutive fiscal-year declines in '+subject+'.')
    assert 'declines in both' not in text


@pytest.mark.parametrize('changes',[{'period_end':'2020-01-01'},{'available_on':'2027-03-02'},{'source':'https://example.test/rate'}])
def test_supplied_treasury_cannot_bypass_freshness_chronology_or_source_checks(changes):
    rate=vr.treasury_10y(vr.TreasurySources(read=lambda u:xml_rates(('2027-02-28','4.0'))),DAY)
    rate.update(changes)
    assert vr.dated_treasury(rate,DAY)['status']==vr.UNAVAILABLE


@pytest.mark.parametrize('mode', ['revision', 'filing_mismatch', 'stale'])
def test_rejected_capital_never_exposes_computable_value(monkeypatch, mode):
    if mode == 'revision':
        src = capital_sources()
        quality = vr.sq.quality_company('MSFT', src.read(ve.FACTS_URL), src.read(ve.SUBMISSIONS_URL), DAY)
        monkeypatch.setattr(vr.sq, 'quality_company', lambda *args: quality)
        monkeypatch.setattr(vr.sq, '_contest', lambda *args: (True, 'Reported amount revised'))
        monkeypatch.setattr(vr.ve, 'filing_check', lambda *args: {'status':'unverified'})
    elif mode == 'filing_mismatch':
        monkeypatch.setattr(vr.ve, 'filing_check', lambda *args: {'status':'mismatch'})
    day = date(2027, 10, 1) if mode == 'stale' else DAY
    rows = vr.sec_capital(capital_sources(), day)
    assert rows['cash']['status'] == vr.UNAVAILABLE
    assert rows['cash']['value'] is None
    assert rows['cash']['source'] and rows['cash']['reason']
    assert 'value' not in rows['cash']['source']
    assert 'value' not in rows['cash']['filing_check']
    assert vr.lease_check(rows, 'finance_leases')['status'] == vr.UNAVAILABLE


def test_components_never_imply_bridge_exists():
    result = vr.evaluate(capital_sources(), DAY)
    gate = next(g for g in result['gates'] if g['gate'] == 'capital_bridge')
    assert gate['status'] == vr.UNAVAILABLE
    assert 'No enterprise-to-equity bridge exists' in gate['reason']
    assert any('No enterprise-to-equity bridge exists' in s for s in result['summary'])


@pytest.mark.parametrize('payload', [None, {}, {'status':'usable','value':1},
                                     {'stock':None,'benchmark':{}}, {'stock':{},'benchmark':{},'value':1}])
def test_beta_evaluate_refuses_forged_and_malformed_payload(payload):
    result = vr.evaluate(capital_sources(), DAY, beta=payload)
    beta = next(f for f in result['fields'] if f['field']=='beta')
    assert beta['status'] == vr.UNAVAILABLE and beta['value'] is None
    assert not result['valuation_cases']


@pytest.mark.parametrize('mode', ['valid','future','stale','currency','secret_url'])
def test_beta_evaluate_recomputes_raw_evidence_and_replays(mode):
    a,b = series('MSFT',2), series('SPY')
    day = date(2026,2,1)
    if mode == 'future': a['observations'][-1]['available_on']='2027-01-01'
    if mode == 'stale': day=date(2027,1,1)
    if mode == 'currency': b['currency']='EUR'
    if mode == 'secret_url': a['source']='https://example.test/data?key=secret'
    src=capital_sources()
    result=vr.evaluate(src,day,beta={'stock':a,'benchmark':b})
    beta=next(f for f in result['fields'] if f['field']=='beta')
    assert beta['status'] == (vr.RECONCILE if mode=='valid' else vr.UNAVAILABLE)
    if mode=='valid':
        assert beta['value']==pytest.approx(2)
        assert vr.evaluate(ve.Sources(copy.deepcopy(src.snapshot)),day,beta={'stock':a,'benchmark':b})==result
    assert not result['valuation_cases'] and result['reverse_implied_growth'] is None
    assert 'secret' not in json.dumps(result)


@pytest.mark.parametrize('latest,state', [('',vr.UNAVAILABLE),('4.10',vr.USABLE)])
def test_treasury_latest_blank_never_falls_back_and_decimal_ratio_replays(latest,state):
    src=vr.TreasurySources(read=lambda u:xml_rates(('2026-10-20','4.0'),('2026-10-21',latest)))
    result=vr.treasury_10y(src,date(2026,10,22))
    assert result['status']==state and result['period_end']=='2026-10-21'
    assert result['value']==(None if not latest else .041)
    assert vr.treasury_10y(vr.TreasurySources(copy.deepcopy(src.snapshot)),date(2026,10,22))==result


def test_conflicting_latest_treasury_never_falls_back_on_replay():
    src=vr.TreasurySources(read=lambda u:xml_rates(('2026-10-20','4'),('2026-10-21','4.1'),('2026-10-21','4.2')))
    result=vr.treasury_10y(src,date(2026,10,22))
    assert result['status']==vr.RECONCILE and result['value'] is None
    assert vr.treasury_10y(vr.TreasurySources(copy.deepcopy(src.snapshot)),date(2026,10,22))==result
