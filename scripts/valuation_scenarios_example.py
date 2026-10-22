"""Export the hand-checkable SYNTHETIC worked example. Never fetches market/SEC data.

Fixture numbers and citations are deliberately fictitious. They cannot value MSFT/MU/JPM.
The same evidence packet schema is used for real observations with verified sources.
"""
from datetime import date
import json
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stockwatch import sec_quality as sq, valuation_scenarios as vs


def record(value, unit='USD', kind='observation', end='2025-12-31', **extra):
    return {'value': value, 'unit': unit, 'kind': kind, 'status': 'usable',
            'source': 'SYNTHETIC: hand-calculated teaching fixture, not real market/company evidence',
            'rationale': 'Demonstrates arithmetic and evidence schema only',
            'available_on': '2026-02-15', 'period_end': end, **extra}


def example():
    cfg = yaml.safe_load(vs.CONFIG_PATH.read_text())
    obs = {k: record(v) for k, v in {'price': 10., 'shares': 10., 'cash': 20., 'investments': 5.,
            'debt': 25., 'debt_noncurrent': 20., 'debt_current': 5., 'finance_lease_liabilities': 0.,
            'preferred': 0., 'noncontrolling': 0., 'revenue': 100., 'operating_working_capital': 10.,
            'independent_normalized_fcff': 20.}.items()}
    obs['shares']['unit'] = 'shares'
    for k in ('price', 'shares'):
        obs[k].update(class_id='SYNTH-common', split_basis_date='2025-12-31')
    obs['revenue']['period_start'] = '2025-01-01'
    obs['price'].update(period_end='2026-02-27', available_on='2026-02-27')
    obs['treasury_10y'] = record(.04, 'ratio', end='2026-02-27', available_on='2026-02-27')
    obs['beta'] = record(1., 'ratio', method='SYNTHETIC beta=1, no regression performed')
    obs['borrowing_cost'] = record(.05, 'ratio')
    obs['peer_ev_fcff'] = record(10., 'multiple')
    obs['independent_normalized_fcff']['method'] = 'Independent synthetic FCFF = EBIT20 + D&A2 − maintenance2 = 20'
    contracts = {k: record(v, 'contract', 'analyst_assumption') for k, v in {
        'business_scope': 'operating_business_consolidated_drivers_reconciled',
        'share_basis': 'fully_diluted_common_same_class', 'corporate_actions': 'verified_price_share_basis',
        'lease_scope': 'finance_leases_in_debt_and_investment_operating_leases_in_costs',
        'cross_check_basis': 'ev_fcff_after_sbc_same_lease_scope'}.items()}
    contracts['capital_tax'] = record(0., 'ratio', 'analyst_assumption')
    scenarios = {}
    for name, margin in [('bear', .15), ('base', .20), ('bull', .25)]:
        drivers = {'growth': 0., 'margin_pre_sbc': margin, 'tax': 0., 'dna_pct': .02,
                   'maintenance_pct': .02, 'growth_capex_pct': 0., 'wc_pct': .1, 'sbc_pct': 0., 'non_sbc_dilution': 0.}
        case = {k: record([v]*5, 'ratio', 'analyst_assumption') for k, v in drivers.items()}
        case['terminal'] = {k: record(v, 'ratio', 'analyst_assumption') for k, v in drivers.items()}
        case['terminal']['roic'] = record(.2, 'ratio', 'analyst_assumption')
        scenarios[name] = case
    packet = {'observations': obs, 'contracts': contracts, 'scenarios': scenarios}
    facts = {}
    for tag, value in [('Revenues', 100.), ('OperatingIncomeLoss', 20.),
        ('NetCashProvidedByUsedInOperatingActivities', 30.), ('PaymentsToAcquirePropertyPlantAndEquipment', 2.),
        ('ShareBasedCompensation', 0.), ('DepreciationDepletionAndAmortization', 2.)]:
        facts[tag] = {'units': {'USD': [{'val': value, 'start': f'{y}-01-01', 'end': f'{y}-12-31',
            'form': '10-K', 'filed': f'{y+1}-02-15', 'accn': f'SYNTHETIC-{y}'} for y in range(2020, 2026)]}}
    facts['CashAndCashEquivalentsAtCarryingValue'] = {'units': {'USD': [{'val': 20., 'end': '2025-12-31',
        'form': '10-K', 'filed': '2026-02-15', 'accn': 'SYNTHETIC-2025'}]}}
    company = {'entityName': 'SYNTHETIC teaching example', 'facts': {'us-gaap': facts}}
    day = date(2026, 3, 1)
    q = sq.quality_company('SYNTHETIC', company, {'sic': '7372'}, day)
    report = vs.evaluate(q, company, packet, day, cfg)
    return cfg | {'companies': {'SYNTHETIC': packet}}, report


if __name__ == '__main__':
    config, report = example()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/tmp/valuation-synthetic')
    out.with_suffix('.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
    out.with_suffix('.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    out.with_suffix('.md').write_text(vs.markdown([report]))
    print(json.dumps({'status': report['status'], 'values': {
        k: v['equity_per_share'] for k, v in report['scenarios'].items()}}))
