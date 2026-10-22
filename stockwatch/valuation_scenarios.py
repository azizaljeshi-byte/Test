"""Phase 2A-2: isolated, evidence-gated valuation research. No production imports.

Definitive research scenarios require dated observations plus separately attributed analyst
assumptions. Missing evidence produces gaps, never company-specific default fair values.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import math
from pathlib import Path
from statistics import median

import yaml

from . import sec, sec_quality as sq, valuation_lab as lab

CONFIG_PATH = Path(__file__).with_name('valuation_scenarios.yaml')
COMPUTED, UNAVAILABLE, REQUIRED = 'computed research scenarios', 'UNAVAILABLE', 'ASSUMPTIONS REQUIRED'
DRIVERS = ('growth', 'margin_pre_sbc', 'tax', 'dna_pct', 'maintenance_pct', 'growth_capex_pct', 'wc_pct',
           'sbc_pct', 'non_sbc_dilution')


class EvidenceGap(ValueError):
    def __init__(self, message, status=UNAVAILABLE):
        super().__init__(message)
        self.status = status


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EvidenceGap(f'{name}: finite number required')
    return float(value)


def evidence(record, name, as_of, unit, *, observation=True, age=None):
    """Validate availability dates, units, status and attribution; never infer a zero or source.

    This is an explicit analyst evidence contract, not a claim to independently audit a citation.
    Caller-supplied provenance must be independently checked during review.
    """
    if not isinstance(record, dict) or record.get('value') is None:
        raise EvidenceGap(f'{name}: missing evidence', UNAVAILABLE if observation else REQUIRED)
    if record.get('status') != sq.USABLE:
        raise EvidenceGap(f"{name}: {record.get('status', 'unknown')}")
    allowed = ('observation',) if observation else ('analyst_assumption', 'policy')
    if record.get('kind') not in allowed:
        raise EvidenceGap(f'{name}: expected {"observation" if observation else "attributed assumption"}')
    if record.get('unit') != unit or not record.get('source') or not record.get('rationale'):
        raise EvidenceGap(f'{name}: unit, source and rationale required')
    try:
        available, end = date.fromisoformat(record['available_on']), date.fromisoformat(record['period_end'])
    except (ValueError, KeyError, TypeError) as exc:
        raise EvidenceGap(f'{name}: valid availability and period dates required') from exc
    if available > as_of or end > as_of or end > available:
        raise EvidenceGap(f'{name}: evidence not available as of {as_of}')
    if age is not None and (as_of-end).days > age:
        raise EvidenceGap(f'{name}: stale under the versioned {age}-day freshness assumption')
    if record.get('origin') == 'SEC' and not all(record.get(k) for k in ('accn', 'form', 'filed')):
        raise EvidenceGap(f'{name}: SEC accession, form and filing date required')
    if record.get('origin') == 'SEC':
        try:
            if date.fromisoformat(record['filed']) > as_of or date.fromisoformat(record['filed']) > available:
                raise EvidenceGap(f'{name}: filing not available at evidence timestamp')
        except (ValueError, TypeError) as exc:
            raise EvidenceGap(f'{name}: invalid filing date') from exc
    return record['value']


def number(records, name, as_of, unit='USD', **kwargs):
    return finite(evidence(records.get(name), name, as_of, unit, **kwargs), name)


def attribution(record, name, as_of):
    try:
        return evidence(record, name, as_of, 'contract', observation=False)
    except EvidenceGap as exc:
        raise EvidenceGap(str(exc)) from exc


def capital_bridge(observations, contracts, as_of, freshness):
    """Common equity bridge, with explicit zero observations for absent senior claims/assets."""
    vals = {k: number(observations, k, as_of, 'shares' if k == 'shares' else 'USD',
                      age=freshness['price'] if k == 'price' else freshness['capital'])
            for k in ('price', 'shares', 'cash', 'investments', 'debt', 'debt_noncurrent', 'debt_current',
                      'finance_lease_liabilities', 'preferred', 'noncontrolling')}
    if vals['shares'] <= 0 or vals['price'] <= 0 or any(vals[k] < 0 for k in vals if k not in ('price', 'shares')):
        raise EvidenceGap('capital bridge: positive price/shares and nonnegative balances required')
    if attribution(contracts.get('share_basis'), 'share basis reconciliation', as_of) != 'fully_diluted_common_same_class':
        raise EvidenceGap('share basis must reconcile fully diluted common shares and the quoted class')
    if attribution(contracts.get('corporate_actions'), 'point-in-time corporate actions', as_of) != 'verified_price_share_basis':
        raise EvidenceGap('point-in-time price/share split basis unresolved')
    price, shares = observations['price'], observations['shares']
    if (not price.get('class_id') or price.get('class_id') != shares.get('class_id')
            or price.get('split_basis_date') != shares.get('split_basis_date')
            or not price.get('split_basis_date')):
        raise EvidenceGap('quoted price and fully diluted shares require identical class and split-basis metadata')
    try:
        if date.fromisoformat(price['split_basis_date']) > as_of:
            raise EvidenceGap('price/share basis uses a future corporate action')
    except (ValueError, TypeError) as exc:
        raise EvidenceGap('invalid split-basis date') from exc
    if attribution(contracts.get('lease_scope'), 'debt/lease/investment scope', as_of) != 'finance_leases_in_debt_and_investment_operating_leases_in_costs':
        raise EvidenceGap('finance lease funding and investment must both be included; operating leases stay in costs')
    days = {observations[k]['period_end'] for k in ('cash', 'investments', 'debt', 'debt_noncurrent', 'debt_current',
                                                 'finance_lease_liabilities', 'preferred', 'noncontrolling')}
    if len(days) != 1:
        raise EvidenceGap('capital bridge balances must share exactly one date')
    if not math.isclose(vals['debt'], vals['debt_noncurrent']+vals['debt_current']+vals['finance_lease_liabilities'],
                        rel_tol=1e-6, abs_tol=.01):
        raise EvidenceGap('debt total must reconcile to non-lease current + noncurrent debt + all finance lease liabilities')
    vals['equity_market_value'] = vals['price']*vals['shares']
    vals['equity_adjustment'] = vals['cash']+vals['investments']-vals['debt']-vals['preferred']-vals['noncontrolling']
    return vals


def cost_of_capital(observations, contracts, bridge, as_of, cfg, *, bank=False):
    rf = number(observations, 'treasury_10y', as_of, 'ratio', age=cfg['freshness_days']['treasury_10y'])
    beta = number(observations, 'beta', as_of, 'ratio', age=cfg['freshness_days']['beta'])
    if not observations['beta'].get('method'):
        raise EvidenceGap('beta: regression/adjustment method and window required')
    erp = finite(cfg['equity_risk_premium']['value'], 'illustrative ERP')
    if not 0 <= rf < 1 or not 0 <= beta <= 5 or not 0 <= erp < 1:
        raise EvidenceGap('cost of capital inputs outside supported bounds')
    ke = rf+beta*erp
    result = {'cost_of_equity': ke, 'risk_free': rf, 'beta': beta, 'illustrative_erp': erp,
              'erp_source': cfg['equity_risk_premium']['source'], 'kind': 'market-anchored with explicit ERP assumption'}
    if bank:
        return result | {'rate': ke, 'basis': 'bank cost of equity; never enterprise WACC'}
    if bridge['preferred'] > 0 or bridge['noncontrolling'] > 0:
        raise EvidenceGap('preferred/minority funding requires separately evidenced market weights and costs; current WACC adapter supports common equity and debt only')
    kd = number(observations, 'borrowing_cost', as_of, 'ratio', age=cfg['freshness_days']['borrowing_cost'])
    tax = finite(evidence(contracts.get('capital_tax'), 'cost of capital tax assumption', as_of, 'ratio', observation=False), 'tax')
    if not 0 <= kd < 1 or not 0 <= tax < 1:
        raise EvidenceGap('borrowing cost or tax assumption out of range')
    e, d = bridge['equity_market_value'], bridge['debt']
    wacc = ke*e/(e+d)+kd*(1-tax)*d/(e+d)
    return result | {'rate': wacc, 'basis': 'nominal USD WACC', 'cost_of_debt': kd, 'tax': tax,
                     'equity_weight': e/(e+d), 'debt_weight': d/(e+d)}


def driver_case(record, name, as_of):
    """All year 1–5 drivers must be separately attributed. No +/- default cases."""
    if not isinstance(record, dict):
        raise EvidenceGap(f'{name}: scenario assumptions required', REQUIRED)
    out = {}
    for k in DRIVERS:
        vals = evidence(record.get(k), f'{name}.{k}', as_of, 'ratio', observation=False)
        if not isinstance(vals, list) or len(vals) != 5:
            raise EvidenceGap(f'{name}.{k}: five explicit annual driver values required')
        out[k] = [finite(v, f'{name}.{k}') for v in vals]
    terminal = record.get('terminal', {})
    for k in DRIVERS:
        if k != 'growth':
            out.setdefault('terminal', {})[k] = finite(evidence(terminal.get(k), f'{name}.terminal.{k}', as_of,
                                                                 'ratio', observation=False), k)
    out['terminal_growth'] = finite(evidence(terminal.get('growth'), f'{name}.terminal.growth', as_of,
                                             'ratio', observation=False), 'terminal growth')
    out['terminal_roic'] = finite(evidence(terminal.get('roic'), f'{name}.terminal.roic', as_of,
                                           'ratio', observation=False), 'terminal ROIC')
    return out


def fcff_projection(revenue, working_capital, case, rate, *, min_spread=.02):
    """GAAP SBC charged exactly once: EBIT = revenue × (margin before SBC − SBC ratio).

    Years 6–10 linearly fade every driver. From year 11 terminal reinvestment = NOPAT×g/ROIC;
    do not grow a cash flow forever without funding the terminal growth.
    """
    revenue, wc = finite(revenue, 'baseline revenue'), finite(working_capital, 'operating working capital')
    rate, gt, roic = finite(rate, 'rate'), case['terminal_growth'], case['terminal_roic']
    if revenue <= 0 or rate-gt < min_spread or not 0 <= gt < roic <= 1:
        raise EvidenceGap('positive revenue, r−g ≥ minimum spread and 0 ≤ g < terminal ROIC ≤ 1 required')
    years, pv, owner_pv, shares_factor = [], 0., 0., 1.
    for t in range(1, 11):
        drivers = {k: case[k][t-1] if t <= 5 else case[k][-1]+(
            (gt if k == 'growth' else case['terminal'][k])-case[k][-1])*(t-5)/5 for k in DRIVERS}
        if (not -.99 < drivers['growth'] <= 2 or not 0 <= drivers['tax'] < 1
                or not -1 <= drivers['margin_pre_sbc'] <= 1
                or any(not 0 <= drivers[k] <= 1 for k in ('dna_pct', 'maintenance_pct', 'growth_capex_pct', 'sbc_pct'))
                or not -.5 <= drivers['wc_pct'] <= 1 or not 0 <= drivers['non_sbc_dilution'] <= 1):
            raise EvidenceGap('forecast driver outside supported research bounds')
        revenue *= 1+drivers['growth']
        ebit = revenue*(drivers['margin_pre_sbc']-drivers['sbc_pct'])
        # Loss years receive no tax-credit assumption.
        nopat = ebit-max(ebit, 0)*drivers['tax']
        next_wc = revenue*drivers['wc_pct']
        dna = revenue*drivers['dna_pct']
        maintenance, growth_capex = revenue*drivers['maintenance_pct'], revenue*drivers['growth_capex_pct']
        fcff = nopat+dna-maintenance-growth_capex-(next_wc-wc)
        wc = next_wc
        pv += fcff/(1+rate)**t
        shares_factor *= 1+drivers['non_sbc_dilution']
        owner_pv += fcff/(1+rate)**t/shares_factor
        years.append({'year': t, 'revenue': revenue, 'ebit': ebit, 'nopat': nopat, 'dna': dna,
                      'maintenance_capex': maintenance, 'growth_capex': growth_capex, 'working_capital': wc,
                      'fcff': fcff, 'dilution_factor': shares_factor, 'drivers': drivers})
    terminal_nopat = years[-1]['nopat']*(1+gt)
    if terminal_nopat <= 0:
        raise EvidenceGap('terminal NOPAT must be positive; no forced value for a loss-making terminal business')
    terminal_reinvestment = terminal_nopat*gt/roic
    terminal_fcff = terminal_nopat-terminal_reinvestment
    tv_pv = terminal_fcff/(rate-gt)/(1+rate)**10
    ev = pv+tv_pv
    return {'years': years, 'enterprise_value': ev, 'explicit_pv': pv, 'terminal_pv': tv_pv,
            'owner_enterprise_pv': owner_pv+tv_pv/shares_factor,
            'terminal_share': tv_pv/ev if ev > 0 else None, 'terminal_fcff': terminal_fcff,
            'terminal_reinvestment': terminal_reinvestment, 'terminal_roic': roic,
            'dilution_factor': shares_factor, 'rate': rate, 'terminal_growth': gt}


def equity_value(ev, bridge):
    """All values in nominal USD, per reconciled fully diluted common share outstanding at valuation.

    Non-SBC dilution assumes no offsetting financing proceeds: a conservative explicit scenario,
    not an issuance forecast. Future SBC is already a cost in EBIT and isn't diluted again.
    """
    equity = ev+bridge['equity_adjustment']
    if equity < 0:
        raise EvidenceGap('enterprise PV does not cover senior claims: negative common residual, no defensible per-share price in this model')
    return {'equity_value': equity, 'equity_per_share': equity/bridge['shares'],
            'share_count': bridge['shares'], 'equity_adjustment': bridge['equity_adjustment']}


def bank_value(tce, shares, rotce, growth, ke, reserve=0., min_spread=.02):
    """Steady-state residual-income justified P/TBV: (ROTCE−g)/(Ke−g), not industrial EV/FCF."""
    for name, val in locals().copy().items():
        finite(val, name)
    if (tce <= 0 or shares <= 0 or reserve < 0 or reserve >= tce or not 0 <= growth <= rotce <= 1
            or ke-growth < min_spread):
        raise EvidenceGap('bank requires positive TCE/shares, feasible retention and Ke−g ≥ minimum spread')
    multiple = (rotce-growth)/(ke-growth)
    value = (tce-reserve)*multiple
    return {'justified_p_tbv': multiple, 'equity_value': value, 'equity_per_share': value/shares,
            'rotce': rotce, 'growth': growth, 'cost_of_equity': ke, 'capital_reserve': reserve}


def cycle_evidence(company, as_of):
    rows = lab._evidence(company, as_of, 6, sq.reference(company, as_of).get('fy_end'))
    if len(rows) < 5 or any(any(r['status'][k] != sq.USABLE for k in lab.EVIDENCE_FIELDS) for r in rows):
        raise EvidenceGap('cycle normalization requires ≥5 complete quality-gated fiscal years')
    if any(not 300 <= sq._gap(a['end'], b['end']) <= 400 for a, b in zip(rows, rows[1:])):
        raise EvidenceGap('cycle normalization: fiscal years not consecutive/comparable')
    if any(r['revenue'] <= 0 for r in rows):
        raise EvidenceGap('cycle normalization: positive annual revenue required')
    margins = [r['operating_income']/r['revenue'] for r in rows]
    drops = [a['revenue']/b['revenue']-1 for a, b in zip(rows, rows[1:])]
    if not (min(margins) < 0 < max(margins) or min(drops) <= -.15):
        raise EvidenceGap('available history does not demonstrate multiple cycle phases')
    return {'rows': rows, 'normalized_revenue': median(r['revenue'] for r in rows),
            'median_operating_margin': median(margins),
            'median_capex_pct': median(r['capex']/r['revenue'] for r in rows),
            'median_ocf_conversion': median(r['operating_cash_flow']/r['revenue'] for r in rows),
            'min_operating_margin': min(margins), 'max_operating_margin': max(margins),
            'worst_revenue_change': min(drops),
            'caveat': 'Historical medians are normalization evidence, not forecasts of demand/pricing. Scenario margins, investment and conversion still need attributed assumptions.'}


def _observed_gates(q):
    gaps = []
    for k in ('revenue', 'operating_income', 'dna', 'capex', 'sbc', 'cash'):
        f = q['fields'][k]
        if f['status'] != sq.USABLE or not f['selected'] or f['selected']['value'] is None:
            gaps.append(f"SEC {k}: {f['status']}; " + '; '.join(f['issues']))
    return gaps


def evaluate(q, company, packet, as_of, cfg):
    """Return a ledger even when no model can run. Never upgrade disputed SEC facts via a packet."""
    family = lab.classify(q, company, as_of, lab.load_assumptions())
    out = {'ticker': q['ticker'], 'as_of': str(as_of), 'family': family, 'status': UNAVAILABLE,
           'assumptions_version': cfg['version'], 'policy_approved': cfg['approved'],
           'evidence_packet': packet, 'scenarios': {}, 'sensitivity_only': [], 'gaps': [],
           'required_evidence': ['as-of UST/beta/borrowing cost and market capital weights',
                                 'fully diluted common-class reconciliation and historical price/share split basis',
                                 'same-date cash/investments/debt including finance leases/preferred/minority bridge',
                                 'annual revenue, operating working capital and attributed five-year/terminal drivers',
                                 'independent normalized FCFF and comparable EV/FCFF basis',
                                 'banks: TCE reconciliation, regulatory capital, credit, funding and sustainable ROTCE'],
           'sec_inputs': {k: {'status': f['status'], 'source': f.get('selected'), 'issues': f['issues']}
                          for k, f in q['fields'].items()},
           'caveats': ['Research only: no investment/trading recommendation or calibrated probabilities.',
                       'Citation metadata is validated; a human must independently verify its economic meaning.',
                       'Current SEC companyfacts can contain restatements; historical as-of availability is filtered, not certified point-in-time archival data.',
                       'Future SBC is an expense once; extra dilution is non-SBC, assumes no financing proceeds and is a conservative scenario.']}
    kind = family['family']
    if q['ticker'] == 'VRT':
        out['gaps'] = ['VRT deferred until its SEC/asset-depreciation audit is independently verified']
        return out
    if kind == lab.CASH_BURN:
        out['runway'] = lab.runway(q, company, as_of)
        out['gaps'] = ['Cash-burning family: runway/funding/dilution only; no intrinsic value']
        return out
    if kind not in (lab.COMPOUNDER, lab.CYCLICAL, lab.BANK):
        out['gaps'] = [family['rule']]
        return out
    obs, contracts = packet.get('observations', {}), packet.get('contracts', {})
    try:
        cover = next((row for row in q['shares']['rows'] if row['key'] == 'cover'), {})
        if (cover.get('date') and obs.get('shares', {}).get('period_end')
                and obs['shares']['period_end'] < cover['date']):
            raise EvidenceGap('share evidence predates the latest SEC cover-page count; no carry-forward')
        if kind == lab.BANK:
            if (obs.get('tangible_common_equity', {}).get('period_end') is not None
                    and obs['tangible_common_equity']['period_end'] != q['reference'].get('end')):
                raise EvidenceGap('bank inputs must use the latest company-reported period; no older book carried forward')
            out.update(_evaluate_bank(obs, contracts, packet.get('scenarios', {}), as_of, cfg))
            return out
        out['gaps'] = _observed_gates(q)
        if out['gaps']:
            return out
        if attribution(contracts.get('business_scope'), 'business/segment scope review', as_of) != 'operating_business_consolidated_drivers_reconciled':
            raise EvidenceGap('conglomerate/sum-of-parts economics unsupported; a reviewed operating-business driver scope is required')
        bridge = capital_bridge(obs, contracts, as_of, cfg['freshness_days'])
        if (q['balance_sheet']['date'] is not None and
                obs['cash']['period_end'] != q['balance_sheet']['date']):
            raise EvidenceGap('capital bridge must use the latest company balance-sheet date; no carry-forward')
        out['capital_bridge'] = bridge
        # A baseline must be the exact annual revenue selected by the SEC quality layer.
        selected = q['fields']['revenue']['selected']
        revenue = number(obs, 'revenue', as_of)
        if (obs['revenue']['period_end'] != selected['end'] or obs['revenue'].get('period_start') != selected['start']
                or not math.isclose(revenue, selected['value'], rel_tol=1e-9)):
            raise EvidenceGap('baseline revenue must reconcile to the selected SEC annual fact')
        wc = number(obs, 'operating_working_capital', as_of)
        if obs['operating_working_capital']['period_end'] != selected['end']:
            raise EvidenceGap('operating working capital and revenue must share a fiscal-year end')
        if kind == lab.CYCLICAL:
            out['cycle_normalization'] = cycle_evidence(company, as_of)
            revenue = out['cycle_normalization']['normalized_revenue']
            # Preserve the observed operating-WC ratio when normalizing revenue.
            wc *= revenue/selected['value']
        cases = {name: driver_case(packet.get('scenarios', {}).get(name), name, as_of) for name in ('bear', 'base', 'bull')}
        rate = None
        try:
            rate = cost_of_capital(obs, contracts, bridge, as_of, cfg)
            out['cost_of_capital'] = rate
        except EvidenceGap as exc:
            out['gaps'].append(str(exc))
        if rate is not None:
            for name, case in cases.items():
                model = fcff_projection(revenue, wc, case, rate['rate'], min_spread=cfg['min_rate_growth_spread'])
                out['scenarios'][name] = model | equity_value(model['owner_enterprise_pv'], bridge)
            values = [out['scenarios'][n]['equity_per_share'] for n in ('bear', 'base', 'bull')]
            if values != sorted(values):
                raise EvidenceGap('bear/base/bull driver cases do not produce an ordered range; reconcile assumptions')
        for r in cfg['sensitivity_rates']:
            for gt in cfg['terminal_growth_sensitivity']:
                case = cases['base'] | {'terminal_growth': gt}
                try:
                    model = fcff_projection(revenue, wc, case, r, min_spread=cfg['min_rate_growth_spread'])
                    out['sensitivity_only'].append({'rate': r, 'growth': gt, 'basis': 'assumed discount rate, not measured WACC',
                                                    'terminal_share': model['terminal_share'],
                                                    **equity_value(model['owner_enterprise_pv'], bridge)})
                except EvidenceGap as exc:
                    out['sensitivity_only'].append({'rate': r, 'growth': gt, 'status': UNAVAILABLE, 'reason': str(exc)})
        if rate is None:
            out['status'] = UNAVAILABLE
            out['gaps'].append('Only a sensitivity grid is available; no company-specific measured-rate scenarios')
            return out
        out['cross_check'] = _cross_check(obs, contracts, bridge, as_of, cfg, out['scenarios']['base'])
        out['status'] = COMPUTED
    except EvidenceGap as exc:
        # A failed late gate must not leave partial fair-value numbers looking validated.
        out['scenarios'], out['sensitivity_only'] = {}, []
        out['status'] = exc.status
        out['gaps'].append(str(exc))
    return out


def _cross_check(obs, contracts, bridge, as_of, cfg, base):
    try:
        multiple = number(obs, 'peer_ev_fcff', as_of, 'multiple', age=cfg['freshness_days']['comparables'])
        normal = number(obs, 'independent_normalized_fcff', as_of, age=cfg['freshness_days']['normalization'])
        if multiple <= 0 or normal <= 0:
            raise EvidenceGap('cross-check needs positive independently normalized FCFF and EV/FCFF')
        if attribution(contracts.get('cross_check_basis'), 'independent comparable basis', as_of) != 'ev_fcff_after_sbc_same_lease_scope':
            raise EvidenceGap('cross-check basis must match after-SBC FCFF/lease scope; not P/FCF or levered OCF')
        if not obs['independent_normalized_fcff'].get('method'):
            raise EvidenceGap('independently normalized FCFF calculation required')
        v = equity_value(multiple*normal, bridge)
        return {'status': 'computed independent context', 'multiple': multiple, 'normalized_fcff': normal, **v,
                'difference_from_base_per_share': v['equity_per_share']-base['equity_per_share'],
                'note': 'A separate normalized cash-flow/multiple lens, never averaged into the intrinsic scenarios.'}
    except EvidenceGap as exc:
        return {'status': UNAVAILABLE, 'reason': str(exc)}


def _evaluate_bank(obs, contracts, scenarios, as_of, cfg):
    # These are gating observations, not industrial enterprise inputs or an inferred capital buffer.
    keys = {'tangible_common_equity': 'USD', 'common_equity': 'USD', 'goodwill': 'USD', 'other_intangibles': 'USD',
            'intangibles_tax_adjustment': 'USD', 'shares': 'shares', 'cet1_ratio': 'ratio', 'credit_loss_ratio': 'ratio',
            'funding_cost': 'ratio', 'historical_rotce': 'ratio'}
    vals = {k: number(obs, k, as_of, unit, age=cfg['freshness_days']['capital']) for k, unit in keys.items()}
    if len({obs[k]['period_end'] for k in keys if k != 'shares'}) != 1:
        raise EvidenceGap('bank tangible equity, capital, credit, funding and returns must share a reporting date')
    if vals['cet1_ratio'] <= 0 or vals['credit_loss_ratio'] < 0 or vals['funding_cost'] < 0:
        raise EvidenceGap('bank regulatory/credit/funding observations invalid')
    expected_tce = vals['common_equity']-vals['goodwill']-vals['other_intangibles']+vals['intangibles_tax_adjustment']
    if (any(vals[k] < 0 for k in ('goodwill', 'other_intangibles', 'intangibles_tax_adjustment'))
            or not math.isclose(vals['tangible_common_equity'], expected_tce, rel_tol=1e-6, abs_tol=.01)):
        raise EvidenceGap('tangible common equity does not reconcile to common equity minus goodwill/intangibles plus evidenced tax adjustment')
    if attribution(contracts.get('share_basis'), 'bank share basis', as_of) != 'fully_diluted_common_same_class':
        raise EvidenceGap('bank common share classes/dilution unresolved')
    if attribution(contracts.get('bank_tce'), 'bank tangible common equity reconciliation', as_of) != 'common_equity_less_goodwill_and_intangibles_net_of_tax':
        raise EvidenceGap('bank tangible COMMON equity reconciliation required, not total stockholders equity')
    rate = cost_of_capital(obs, contracts, None, as_of, cfg, bank=True)
    results = {}
    for name in ('bear', 'base', 'bull'):
        case = scenarios.get(name, {})
        v = {k: finite(evidence(case.get(k), f'{name}.{k}', as_of, 'USD' if k == 'capital_reserve' else 'ratio',
                                observation=False), k) for k in ('rotce', 'growth', 'capital_reserve')}
        results[name] = bank_value(vals['tangible_common_equity'], vals['shares'], v['rotce'], v['growth'],
                                   rate['rate'], v['capital_reserve'], cfg['min_rate_growth_spread'])
    if [results[k]['equity_per_share'] for k in ('bear', 'base', 'bull')] != sorted(v['equity_per_share'] for v in results.values()):
        raise EvidenceGap('bank scenario values not ordered; reconcile drivers')
    cross_check = {'status': UNAVAILABLE, 'reason': 'independently comparable observed bank P/TBV not supplied'}
    if obs.get('peer_p_tbv'):
        multiple = number(obs, 'peer_p_tbv', as_of, 'multiple', age=cfg['freshness_days']['comparables'])
        if multiple <= 0 or not obs['peer_p_tbv'].get('method'):
            raise EvidenceGap('bank comparable P/TBV requires a positive multiple and peer/basis method')
        cross_check = {'status': 'computed independent context', 'multiple': multiple,
                       'equity_per_share': vals['tangible_common_equity']*multiple/vals['shares'],
                       'note': 'Peer P/TBV context, not averaged into the residual-income scenarios.'}
    return {'status': COMPUTED, 'gaps': [], 'cost_of_capital': rate, 'bank_observations': vals, 'scenarios': results,
            'cross_check': cross_check,
            'bank_formula': '(TCE − explicit capital reserve) × (sustainable ROTCE − g) / (Ke − g) / reconciled shares',
            'caveat': 'Steady-state residual-income lens; sustainable ROTCE and reserve are explicit analyst assumptions, not forecasts or regulatory approval.'}


def research_ticker(ticker, as_of, cfg, *, get=None, lookup=None, price_fn=None):
    get, lookup, price_fn = get or sec._get, lookup or sec.cik_lookup, price_fn or lab.fetch_price
    try:
        cik, why = lookup(ticker)
        if cik is None:
            raise EvidenceGap(why or 'no SEC CIK')
        company = get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json')
        try:
            submissions = get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json')
        except Exception:
            submissions = None
        q = sq.quality_company(ticker, company, submissions, as_of)
        packet = cfg.get('companies', {}).get(ticker.upper(), {})
        out = evaluate(q, company, packet, as_of, cfg)
        try:
            out['phase2a1_risk_context'] = lab.value_company(
                ticker, company, submissions, price_fn(ticker, as_of), as_of)['risk']
        except Exception as exc:
            # Supplemental market context must never erase the independently evaluated ledger.
            out['phase2a1_risk_context'] = {'status': UNAVAILABLE,
                                           'reason': f'Optional risk context failed: {type(exc).__name__}: {exc}'}
        return out
    except Exception as exc:
        return {'ticker': ticker.upper(), 'as_of': str(as_of), 'status': UNAVAILABLE,
                'gaps': [f'{type(exc).__name__}: {exc}'], 'scenarios': {}}


def markdown(reports):
    lines = ['# Phase 2A-2 valuation research', '', 'Research only. Bear/base/bull are assumption cases, not probabilities or trade recommendations.', '',
             'Nonfinancial formula: EBIT = revenue × (pre-SBC margin − SBC ratio); NOPAT = EBIT minus taxes on positive EBIT; '
             'FCFF = NOPAT + depreciation − maintenance investment − growth investment − change in operating working capital. '
             'Future finance-lease-funded investment is included in the investment assumptions. Terminal FCFF = NOPAT₁₁ × (1 − g/ROIC).', '',
             'Equity bridge: enterprise present value + cash + surplus investments − debt (including finance leases) '
             '− preferred claims − noncontrolling interests. Divide by reconciled fully diluted common shares. '
             'Additional non-SBC dilution reduces each year’s ownership at that year, not every cash flow by the year-10 share count. '
             'The initial surplus cash/senior-claim adjustment is at time zero; future capital proceeds are not assumed.', '']
    for r in reports:
        lines += [f"## {r['ticker']} — {r['status']}", '', f"As of {r['as_of']}", '']
        if r.get('family'):
            lines += [f"Family: {r['family']['family']}. {r['family']['rule']}", '']
        lines += ['- '+g for g in r['gaps']]
        if r.get('scenarios'):
            lines += ['', '| Case | Equity/share (research USD) | Rate | Terminal share |', '|---|---|---|---|']
            for name, result in r['scenarios'].items():
                rate = result.get('rate', result.get('cost_of_equity'))
                terminal = result.get('terminal_share')
                lines.append(f"| {name} | {result['equity_per_share']:.2f} | {rate:.1%} | "
                             + (f'{terminal:.1%}' if terminal is not None else 'N/A: bank P/TBV') + ' |')
            for name, result in r['scenarios'].items():
                if not result.get('years'):
                    continue
                lines += ['', f'### {name.title()}: annual operating drivers and cash flow', '',
                          '| Year | Revenue | Pre-SBC margin | SBC/revenue | Tax | D&A | Maintenance | Growth investment | Operating WC | FCFF | Ownership dilution factor |',
                          '|---|---|---|---|---|---|---|---|---|---|---|']
                for y in result['years']:
                    d = y['drivers']
                    lines.append(f"| {y['year']} | {y['revenue']:.2f} | {d['margin_pre_sbc']:.1%} | {d['sbc_pct']:.1%} | "
                                 f"{d['tax']:.1%} | {y['dna']:.2f} | {y['maintenance_capex']:.2f} | {y['growth_capex']:.2f} | "
                                 f"{y['working_capital']:.2f} | {y['fcff']:.2f} | {y['dilution_factor']:.4f} |")
        # Include complete formulas/inputs and sources in a readable auditable ledger.
        for key in ('required_evidence', 'sec_inputs', 'capital_bridge', 'cost_of_capital', 'cycle_normalization', 'evidence_packet',
                    'scenarios', 'sensitivity_only', 'cross_check', 'bank_observations', 'runway', 'phase2a1_risk_context'):
            if r.get(key):
                lines += ['', f'### {key.replace("_", " ").title()}', '', '```json', json.dumps(r[key], indent=2, allow_nan=False), '```']
        lines += ['', *['- '+c for c in r.get('caveats', [])], '']
    return '\n'.join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('tickers', nargs='+')
    p.add_argument('--as-of', type=date.fromisoformat, default=date.today())
    p.add_argument('--config', type=Path, default=CONFIG_PATH)
    p.add_argument('--json', type=Path)
    p.add_argument('--markdown', type=Path)
    args = p.parse_args(argv)
    cfg = yaml.safe_load(args.config.read_text())
    results = [research_ticker(t, args.as_of, cfg) for t in args.tickers]
    if args.json:
        args.json.write_text(json.dumps(results, indent=2, allow_nan=False))
    report = markdown(results)
    if args.markdown:
        args.markdown.write_text(report)
    else:
        print(report)
    # Missing assumptions is a completed diagnostic, not successful valuation or missing SEC retrieval.
    return 2 if all('family' not in r for r in results) else (1 if any('family' not in r for r in results) else 0)


if __name__ == '__main__':
    raise SystemExit(main())
