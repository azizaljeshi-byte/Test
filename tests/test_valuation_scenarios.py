"""Pure synthetic examples only. Numbers here are not forecasts for real public companies."""
from datetime import date
from pathlib import Path

import pytest
import yaml

from stockwatch import sec_quality as sq, valuation_lab as lab, valuation_scenarios as vs

DAY = date(2026, 3, 1)


def cfg():
    return yaml.safe_load(vs.CONFIG_PATH.read_text())


def record(value, unit='USD', kind='observation', end='2025-12-31', **extra):
    return {'value': value, 'unit': unit, 'status': sq.USABLE, 'kind': kind, 'source': 'synthetic hand-calculation fixture',
            'rationale': 'test only, not a company observation or forecast', 'available_on': '2026-02-15',
            'period_end': end, **extra}


def assumption(value, unit='ratio'):
    return record(value, unit, 'analyst_assumption')


def case(growth=0, margin=.2, dilution=0):
    vals = {'growth': growth, 'margin_pre_sbc': margin, 'tax': 0., 'dna_pct': .02,
            'maintenance_pct': .02, 'growth_capex_pct': 0., 'wc_pct': .1, 'sbc_pct': 0.,
            'non_sbc_dilution': dilution}
    c = {k: assumption([v]*5) for k, v in vals.items()}
    c['terminal'] = {k: assumption(v) for k, v in vals.items()}
    c['terminal']['roic'] = assumption(.2)
    return c


def packet():
    obs = {k: record(v) for k, v in {'price': 10., 'cash': 20., 'investments': 5., 'debt': 25.,
                                    'debt_noncurrent': 20., 'debt_current': 5., 'finance_lease_liabilities': 0.,
                                    'preferred': 0., 'noncontrolling': 0., 'revenue': 100.,
                                    'operating_working_capital': 10., 'independent_normalized_fcff': 20.}.items()}
    obs['shares'] = record(10., 'shares')
    obs['revenue']['period_start'] = '2025-01-01'
    for k in ('price', 'shares'):
        obs[k].update(class_id='SYNTH-common', split_basis_date='2025-12-31')
    obs['price'].update(period_end='2026-02-27', available_on='2026-02-27')
    obs['treasury_10y'] = record(.04, 'ratio', end='2026-02-27', available_on='2026-02-27')
    obs['beta'] = record(1., 'ratio', method='synthetic 5-year weekly market regression, no adjustment')
    obs['borrowing_cost'] = record(.05, 'ratio')
    obs['peer_ev_fcff'] = record(10., 'multiple', method='separate synthetic peer median')
    obs['independent_normalized_fcff']['method'] = 'separate synthetic normalized NOPAT + D&A − investment − delta WC'
    contracts = {k: assumption(v, 'contract') for k, v in {
        'business_scope': 'operating_business_consolidated_drivers_reconciled',
        'share_basis': 'fully_diluted_common_same_class', 'corporate_actions': 'verified_price_share_basis',
        'lease_scope': 'finance_leases_in_debt_and_investment_operating_leases_in_costs',
        'cross_check_basis': 'ev_fcff_after_sbc_same_lease_scope'}.items()}
    contracts['capital_tax'] = assumption(0.)
    return {'observations': obs, 'contracts': contracts,
            'scenarios': {'bear': case(margin=.15), 'base': case(), 'bull': case(margin=.25)}}


def company():
    facts = {}
    for name, value in [('Revenues', 100.), ('OperatingIncomeLoss', 20.),
                        ('NetCashProvidedByUsedInOperatingActivities', 30.),
                        ('PaymentsToAcquirePropertyPlantAndEquipment', 2.), ('ShareBasedCompensation', 0.),
                        ('DepreciationDepletionAndAmortization', 2.)]:
        facts[name] = {'units': {'USD': [{'val': value, 'start': f'{y}-01-01', 'end': f'{y}-12-31',
                   'form': '10-K', 'filed': f'{y+1}-02-15', 'accn': f'synthetic-{y}'} for y in range(2020, 2026)]}}
    for name, value in [('CashAndCashEquivalentsAtCarryingValue', 20.), ('StockholdersEquity', 100.)]:
        facts[name] = {'units': {'USD': [{'val': value, 'end': '2025-12-31', 'form': '10-K',
                                        'filed': '2026-02-15', 'accn': 'synthetic-2025'}]}}
    return {'entityName': 'SYNTHETIC ONLY', 'facts': {'us-gaap': facts}}


def quality(c=None, bank=False):
    return sq.quality_company('SYNTH', c or company(), {'sic': '6021' if bank else '7372'}, DAY)


def test_hand_calculated_perpetuity_fade_and_terminal_reinvestment():
    c = vs.driver_case(case(), 'flat', DAY)
    model = vs.fcff_projection(100., 10., c, .1)
    # Revenue=100; EBIT=20; depreciation=2 and maintenance=2 cancel; no WC change.
    assert model['enterprise_value'] == pytest.approx(200.)
    assert model['terminal_fcff'] == 20. and model['terminal_reinvestment'] == 0.
    c = vs.driver_case(case(growth=.1), 'growing', DAY)
    c['terminal_growth'] = .025
    m = vs.fcff_projection(100., 10., c, .1)
    assert m['years'][4]['drivers']['growth'] == .1
    assert m['years'][5]['drivers']['growth'] == pytest.approx(.085)
    assert m['years'][9]['drivers']['growth'] == pytest.approx(.025)
    assert m['terminal_reinvestment'] == pytest.approx(m['years'][-1]['nopat']*1.025*.025/.2)
    assert m['enterprise_value'] == pytest.approx(m['explicit_pv']+m['terminal_pv'])


def test_sbc_charged_once_and_dilution_time_weighting():
    c = vs.driver_case(case(), 'flat', DAY)
    c['sbc_pct'] = [.05]*5; c['terminal']['sbc_pct'] = .05
    m = vs.fcff_projection(100., 10., c, .1)
    assert m['enterprise_value'] == pytest.approx(150.)  # pre-SBC EBIT20 − SBC5; no second subtraction
    c = vs.driver_case(case(dilution=.1), 'diluted', DAY)
    diluted = vs.fcff_projection(100., 10., c, .1)
    assert diluted['owner_enterprise_pv'] < diluted['enterprise_value']
    expected = sum(20./1.1**t/1.1**t for t in range(1, 11))+200./1.1**10/1.1**10
    assert diluted['owner_enterprise_pv'] == pytest.approx(expected)


def test_rate_growth_negative_cashflow_and_invalid_inputs():
    c = vs.driver_case(case(), 'base', DAY)
    c['terminal_growth'] = .09
    with pytest.raises(vs.EvidenceGap, match='r−g'):
        vs.fcff_projection(100., 10., c, .1)
    c = vs.driver_case(case(margin=-.1), 'loss', DAY)
    c['terminal']['margin_pre_sbc'] = .2
    m = vs.fcff_projection(100., 10., c, .1)
    assert m['years'][0]['fcff'] == -10. and m['years'][0]['nopat'] == -10.
    c['terminal']['margin_pre_sbc'] = -.1
    with pytest.raises(vs.EvidenceGap, match='terminal NOPAT'):
        vs.fcff_projection(100., 10., c, .1)
    with pytest.raises(vs.EvidenceGap):
        vs.finite(float('nan'), 'input')


def test_market_cost_capital_and_capital_bridge_hand_calculated():
    p = packet(); b = vs.capital_bridge(p['observations'], p['contracts'], DAY, cfg()['freshness_days'])
    assert b['equity_market_value'] == 100. and b['equity_adjustment'] == 0.
    r = vs.cost_of_capital(p['observations'], p['contracts'], b, DAY, cfg())
    assert r['rate'] == pytest.approx(.09*.8+.05*.2)
    assert vs.equity_value(200., b)['equity_per_share'] == 20.
    p['observations']['preferred']['value'] = 10.
    b = vs.capital_bridge(p['observations'], p['contracts'], DAY, cfg()['freshness_days'])
    assert vs.equity_value(200., b)['equity_per_share'] == 19.
    with pytest.raises(vs.EvidenceGap, match='negative common residual'):
        vs.equity_value(-1., b)


@pytest.mark.parametrize('key,change', [('debt', {'status': sq.UNKNOWN}), ('price', {'period_end': '2025-12-31'}),
    ('shares', {'class_id': 'OTHER'}), ('shares', {'split_basis_date': '2020-01-01'}),
    ('cash', {'period_end': '2025-09-30'}), ('preferred', {'value': None})])
def test_missing_stale_split_and_mixed_date_bridge_refused(key, change):
    p = packet(); p['observations'][key].update(change)
    with pytest.raises(vs.EvidenceGap):
        vs.capital_bridge(p['observations'], p['contracts'], DAY, cfg()['freshness_days'])


def test_evidence_never_uses_future_filings_or_assumptions_as_observations():
    r = record(10., origin='SEC', accn='a', form='10-K', filed='2026-03-02')
    with pytest.raises(vs.EvidenceGap):
        vs.evidence(r, 'future filing', DAY, 'USD')
    with pytest.raises(vs.EvidenceGap):
        vs.evidence(assumption(10., 'USD'), 'rate', DAY, 'USD')
    with pytest.raises(vs.EvidenceGap):
        vs.evidence(record(10., unit='EUR'), 'USD baseline', DAY, 'USD')
    p = packet(); p['observations']['treasury_10y']['available_on'] = '2026-03-02'
    b = vs.capital_bridge(p['observations'], p['contracts'], DAY, cfg()['freshness_days'])
    with pytest.raises(vs.EvidenceGap):
        vs.cost_of_capital(p['observations'], p['contracts'], b, DAY, cfg())


def test_end_to_end_scenarios_cross_check_sensitivity_and_default_refusal():
    r = vs.evaluate(quality(), company(), packet(), DAY, cfg())
    assert r['status'] == vs.COMPUTED
    assert len(r['sensitivity_only']) == 9 and len(r['scenarios']['base']['years']) == 10
    vals = [r['scenarios'][k]['equity_per_share'] for k in ('bear', 'base', 'bull')]
    assert vals == sorted(vals)
    assert r['cross_check']['equity_per_share'] == 20.
    assert r['cross_check']['difference_from_base_per_share'] != 0
    # No packet means explicit gaps, not default fair values or a generic rate labeled WACC.
    empty = vs.evaluate(quality(), company(), {}, DAY, cfg())
    assert empty['status'] == vs.UNAVAILABLE and not empty['scenarios'] and not empty['sensitivity_only']
    assert empty['required_evidence']
    p = packet(); p['observations']['peer_ev_fcff']['unit'] = 'levered_PE'
    r = vs.evaluate(quality(), company(), p, DAY, cfg())
    assert r['status'] == vs.COMPUTED and r['cross_check']['status'] == vs.UNAVAILABLE
    p = packet(); del p['observations']['beta']
    r = vs.evaluate(quality(), company(), p, DAY, cfg())
    assert r['status'] == vs.UNAVAILABLE and not r['scenarios'] and len(r['sensitivity_only']) == 9
    assert 'cost_of_capital' not in r
    assert all('not measured WACC' in cell['basis'] for cell in r['sensitivity_only'])


def test_disputed_sec_input_cannot_be_overridden_and_no_future_changes():
    c = company(); c['facts']['us-gaap']['Revenues']['units']['USD'].append({
        'val': 150., 'start': '2025-01-01', 'end': '2025-12-31', 'filed': '2026-02-15', 'form': '10-K', 'accn': 'synthetic-2025'})
    r = vs.evaluate(quality(c), c, packet(), DAY, cfg())
    assert not r['scenarios'] and r['status'] == vs.UNAVAILABLE
    future = company()
    future['facts']['us-gaap']['Revenues']['units']['USD'].append({'val': 900., 'start': '2025-01-01',
        'end': '2025-12-31', 'filed': '2026-04-15', 'form': '10-K/A', 'accn': 'future'})
    assert vs.evaluate(quality(future), future, packet(), DAY, cfg()) == vs.evaluate(quality(), company(), packet(), DAY, cfg())


def test_cycle_normalization_uses_multiple_phases_and_usable_periods():
    c = company()
    for f, revenue, op in zip(c['facts']['us-gaap']['Revenues']['units']['USD'], [100., 150., 80., 160., 100., 140.],
                             [20., 50., -5., 45., 5., 35.]):
        f['val'] = revenue
        c['facts']['us-gaap']['OperatingIncomeLoss']['units']['USD'][int(f['end'][:4])-2020]['val'] = op
    ev = vs.cycle_evidence(c, DAY)
    assert ev['normalized_revenue'] == 120. and ev['min_operating_margin'] < 0
    # Latest margins are not the normalized base; the exact yearly evidence remains inspectable.
    assert len(ev['rows']) == 6 and ev['median_capex_pct'] > 0
    p = packet()
    p['observations']['revenue']['value'] = 140.
    p['observations']['operating_working_capital']['value'] = 14.
    r = vs.evaluate(quality(c), c, p, DAY, cfg())
    assert r['family']['family'] == lab.CYCLICAL and r['status'] == vs.COMPUTED
    assert r['scenarios']['base']['years'][0]['revenue'] == 120.
    c['facts']['us-gaap']['Revenues']['units']['USD'].pop(2)
    with pytest.raises(vs.EvidenceGap):
        vs.cycle_evidence(c, DAY)


def test_bank_formula_and_required_bank_economics():
    value = vs.bank_value(100., 10., .12, .02, .10)
    assert value['justified_p_tbv'] == pytest.approx(1.25)
    assert value['equity_per_share'] == pytest.approx(12.5)
    with pytest.raises(vs.EvidenceGap):
        vs.bank_value(100., 10., .01, .02, .10)
    p = packet()
    p['observations'].update({k: record(v, u) for k, v, u in [
        ('tangible_common_equity', 100., 'USD'), ('cet1_ratio', .13, 'ratio'),
        ('common_equity', 120., 'USD'), ('goodwill', 15., 'USD'), ('other_intangibles', 5., 'USD'),
        ('intangibles_tax_adjustment', 0., 'USD'),
        ('credit_loss_ratio', .01, 'ratio'), ('funding_cost', .03, 'ratio'), ('historical_rotce', .12, 'ratio')]})
    p['contracts']['bank_tce'] = assumption('common_equity_less_goodwill_and_intangibles_net_of_tax', 'contract')
    p['scenarios'] = {n: {'rotce': assumption(roe), 'growth': assumption(.02), 'capital_reserve': assumption(0., 'USD')}
                      for n, roe in [('bear', .08), ('base', .12), ('bull', .15)]}
    r = vs.evaluate(quality(bank=True), company(), p, DAY, cfg())
    assert r['status'] == vs.COMPUTED and r['cost_of_capital']['basis'].startswith('bank cost of equity')
    assert 'enterprise_value' not in r['scenarios']['base']
    p['observations']['tangible_common_equity']['value'] = 110.
    bad = vs.evaluate(quality(bank=True), company(), p, DAY, cfg())
    assert bad['status'] == vs.UNAVAILABLE and not bad['scenarios']
    p['observations']['tangible_common_equity']['value'] = 100.
    p['observations']['cet1_ratio']['status'] = sq.UNKNOWN
    r = vs.evaluate(quality(bank=True), company(), p, DAY, cfg())
    assert not r['scenarios'] and r['status'] == vs.UNAVAILABLE


def test_runway_only_and_unsupported_refuse_intrinsic_values():
    c = company()
    for f in c['facts']['us-gaap']['NetCashProvidedByUsedInOperatingActivities']['units']['USD']:
        f['val'] = -10.
    r = vs.evaluate(quality(c), c, packet(), DAY, cfg())
    assert r['family']['family'] == lab.CASH_BURN and not r['scenarios'] and 'runway' in r
    q = sq.quality_company('BRK-B', company(), {'sic': '6331'}, DAY)
    assert not vs.evaluate(q, company(), packet(), DAY, cfg())['scenarios']


def test_late_assumption_failure_suppresses_all_scenario_values():
    p = packet(); p['scenarios']['bull']['growth']['value'] = None
    r = vs.evaluate(quality(), company(), p, DAY, cfg())
    assert r['status'] == vs.REQUIRED and not r['scenarios']
    assert 'ASSUMPTIONS REQUIRED' in vs.markdown([r])
    assert not any('price implies' in g for g in r['gaps'])


def test_bank_tce_and_nonfinancial_debt_must_actually_reconcile():
    p = packet(); p['observations']['debt']['value'] = 30.
    with pytest.raises(vs.EvidenceGap, match='debt total must reconcile'):
        vs.capital_bridge(p['observations'], p['contracts'], DAY, cfg()['freshness_days'])


def test_investment_margin_and_terminal_sensitivities_have_expected_direction():
    base = vs.driver_case(case(), 'base', DAY)
    value = vs.fcff_projection(100., 10., base, .1)['enterprise_value']
    heavy = {**base, 'maintenance_pct': [.05]*5, 'terminal': {**base['terminal'], 'maintenance_pct': .05}}
    assert vs.fcff_projection(100., 10., heavy, .1)['enterprise_value'] < value
    assert vs.fcff_projection(100., 10., base, .12)['enterprise_value'] < value
    better = vs.driver_case(case(margin=.25), 'better', DAY)
    assert vs.fcff_projection(100., 10., better, .1)['enterprise_value'] > value


def test_no_live_app_imports():
    root = Path(__file__).resolve().parents[1]
    for p in [root/'dashboard.py', *(root/'stockwatch').glob('*.py')]:
        if p.name not in ('valuation_scenarios.py',):
            assert 'valuation_scenarios' not in p.read_text(), p.name


def test_known_newer_share_count_or_disputed_cash_cannot_be_bypassed():
    q = quality()
    next(row for row in q['shares']['rows'] if row['key'] == 'cover')['date'] = '2026-01-20'
    r = vs.evaluate(q, company(), packet(), DAY, cfg())
    assert r['status'] == vs.UNAVAILABLE and not r['scenarios']
    assert 'predates the latest SEC' in r['gaps'][0]
    q = quality(); q['fields']['cash']['status'] = sq.RECONCILE
    r = vs.evaluate(q, company(), packet(), DAY, cfg())
    assert r['status'] == vs.UNAVAILABLE and not r['scenarios']
    assert any('SEC cash' in g for g in r['gaps'])


def test_retrieval_and_cli_distinguish_gap_diagnostics_from_missing_sources(monkeypatch, tmp_path):
    def get(url):
        return company() if 'companyfacts' in url else {'sic': '7372'}
    r = vs.research_ticker('SYNTH', DAY, cfg(), get=get, lookup=lambda t: (1, None),
                          price_fn=lambda t, d: lab._input('price', None, sq.UNKNOWN))
    assert r['status'] == vs.UNAVAILABLE and 'family' in r and not r['scenarios']
    assert r['phase2a1_risk_context']
    monkeypatch.setattr(vs, 'research_ticker', lambda *args: r)
    output = tmp_path/'report.json'
    text = tmp_path/'report.md'
    assert vs.main(['SYNTH', '--as-of', str(DAY), '--json', str(output), '--markdown', str(text)]) == 0
    assert 'UNAVAILABLE' in text.read_text() and output.exists()
    monkeypatch.setattr(vs, 'research_ticker', lambda *args: {'ticker': 'SYNTH', 'as_of': str(DAY),
        'status': vs.UNAVAILABLE, 'gaps': ['source not retrieved'], 'scenarios': {}})
    assert vs.main(['SYNTH', '--markdown', str(text)]) == 2
