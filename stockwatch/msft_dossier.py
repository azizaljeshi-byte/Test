"""Standalone MSFT decision-first SEC dossier. No price forecast or trading integration.

Runs with the paced official transport on an authorized host; --snapshot replays privately
retained SEC inputs without network. No issuer metrics or investment thresholds are hardcoded.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import math
from pathlib import Path

from . import sec_access as access, sec_quality as sq, valuation_evidence as ve, valuation_lab as lab
from .sec_audit import FIELDS

KEYS = ('revenue', 'operating_income', 'operating_cash_flow', 'capex', 'sbc', 'dna',
        'basic_shares', 'diluted_shares', 'eps_diluted')
WATCH = ('basic_shares', 'diluted_shares', 'eps_diluted', 'shares_outstanding', 'dna')
GATES = {
    'price_and_shares': 'Contemporaneous spot price and fully diluted same-class/corporate-action basis, not EPS weighted averages.',
    'capital_bridge': 'Same-date non-lease debt, surplus investments, all finance leases, preferred/minority reconciliation.',
    'cost_of_capital': 'Dated Treasury, evidenced beta and borrowing cost, capital weights and separately approved tax/ERP policy.',
    'approved_forward_cases': 'Explicitly approved sourced bear/base/bull drivers, maintenance/growth investment, working capital, terminal ROIC and growth.',
    'competitive_evidence': 'Sourced demand, competition and segment economics; historical ratios alone do not prove a moat.',
}


def check_row(key, source, status, issues, sources, cache, as_of):
    unit = FIELDS[key][2]
    selected = dict(source) if source else None
    match = ve.filing_check(selected, unit, sources, cache) if selected else {'status': 'unverified', 'reason': 'no selected fact'}
    state = status
    if state == sq.USABLE and match['status'] != 'matches':
        state = 'unverified'
    if selected:
        try:
            end, filed = date.fromisoformat(selected['end']), date.fromisoformat(selected['filed'])
            start = date.fromisoformat(selected['start']) if selected.get('start') else end
            value = selected['value']
            if (not start <= end <= filed <= as_of or not selected.get('form') or isinstance(value, bool)
                    or not isinstance(value, (int, float)) or not math.isfinite(value)):
                state = sq.UNKNOWN
        except (KeyError, TypeError, ValueError):
            state = sq.UNKNOWN
    return {'field': key, 'unit': unit, 'value': selected.get('value') if selected else None,
            'status': state, 'source': selected, 'filing_check': match, 'issues': issues,
            'kind': 'issuer_fact', 'adjustment': 'as reported; no split/restatement normalization inferred'}


def annual_rows(company, sources, as_of, cache):
    rows = []
    for key in KEYS:
        for h in lab.annual_history(company, key, as_of)[:5]:
            # Inherited annual_history checks revisions/conflicts. Also preserve explicit fallback scope warnings.
            concepts = FIELDS[key][3]
            concept = next((c for c in concepts if c.split(':')[-1] == h['concept']), h['concept'])
            scope = sq._scope_flag(concept, concepts)
            state = sq.RECONCILE if scope and h['status'] == sq.USABLE else h['status']
            row = check_row(key, h, state, h['issues'] + ([scope[1]] if scope else []), sources, cache, as_of)
            rows.append(row | {'basis': 'annual'})
    return rows


def ttm_rows(q, sources, as_of, cache):
    rows = []
    for key in ('revenue', 'operating_income', 'operating_cash_flow', 'capex', 'sbc'):
        t = q['fields'][key].get('ttm') or {}
        parts = [(name, check_row(key, source, sq.USABLE, [], sources, cache, as_of))
                 for name, source in t.get('parts', [])]
        ok = bool(parts) and t.get('status') == sq.USABLE and all(r['status'] == sq.USABLE for _, r in parts)
        rows.append({'field': key, 'basis': 'TTM', 'kind': 'derived_metric', 'unit': 'USD',
                     'value': t.get('value') if ok else None, 'status': sq.USABLE if ok else 'unavailable',
                     'formula': 'annual or annual + current YTD - prior YTD, per Phase 1B',
                     'parts': [{'role': name, **r} for name, r in parts],
                     'reason': t.get('reason') or ('all components filing-matched' if ok else 'one or more components not usable/matched')})
    return rows


def economics(annual, as_of):
    """Observed direction only; exact annual intervals/filings, no forecast, moat claim or score."""
    grouped = {}
    for r in annual:
        if r['source'] and r['status'] == sq.USABLE:
            s = r['source']
            grouped.setdefault((s.get('start'), s['end'], s['accn']), {})[r['field']] = r
    years = []
    for (start, end, accn), fs in sorted(grouped.items(), reverse=True):
        needed = {'revenue', 'operating_income', 'operating_cash_flow', 'capex', 'sbc'}
        if not needed <= fs.keys() or fs['revenue']['value'] <= 0 or fs['capex']['value'] < 0 or fs['sbc']['value'] < 0:
            continue
        values = {k: fs[k]['value'] for k in needed}
        years.append({'start': start, 'end': end, 'accn': accn, 'values': values,
                      'operating_margin': values['operating_income']/values['revenue'],
                      'capex_revenue': values['capex']/values['revenue'], 'sbc_revenue': values['sbc']/values['revenue'],
                      'ocf_less_cash_capex': values['operating_cash_flow']-values['capex'],
                      'sources': {k: fs[k]['filing_check']['url'] for k in needed}})
    years.sort(key=lambda y: y['end'], reverse=True)
    # Collapse only identical same-year copies; differing values/periods are ambiguous.
    clusters = []
    for y in years:
        if not clusters or sq._gap(clusters[-1][0]['end'], y['end']) > 300:
            clusters.append([y])
        else:
            clusters[-1].append(y)
    years, ambiguities = [], []
    for copies in clusters:
        first = copies[0]
        conflict = any((other['start'], other['end']) != (first['start'], first['end'])
                       or any(not math.isclose(other['values'][k], first['values'][k], rel_tol=1e-9, abs_tol=1e-8)
                              for k in first['values']) for other in copies[1:])
        if conflict:
            ambiguities.append({'end': first['end'], 'accessions': [y['accn'] for y in copies],
                                'reason': 'Conflicting same-year values or fiscal periods; not used.'})
            break  # do not skip a disputed recent year to manufacture an older trend
        if years and not 350 <= sq._gap(years[-1]['end'], first['end']) <= 380:
            break  # retain the recent consecutive run, never bridge an older gap
        years.append(first | {'corroborating_accessions': [y['accn'] for y in copies]})
        if len(years) == 3:
            break
    positives, negatives, neutral = [], [], []
    paired = len(years) >= 2 and all(350 <= sq._gap(a['end'], b['end']) <= 380 for a, b in zip(years, years[1:]))
    fresh = bool(years) and (as_of-date.fromisoformat(years[0]['end'])).days <= 550
    if paired and fresh:
        newest, oldest = years[0], years[-1]
        growth = newest['values']['revenue']/oldest['values']['revenue']-1
        margin = newest['operating_margin']-oldest['operating_margin']
        for value, text in [(growth, f"Revenue changed {growth:+.1%} from FY {oldest['end']} to {newest['end']}."),
                            (margin, f"Operating margin changed {margin*100:+.1f} percentage points over those fiscal years.")]:
            (positives if value > 0 else negatives if value < 0 else neutral).append(text)
        if all(y['ocf_less_cash_capex'] > 0 for y in years):
            positives.append('OCF exceeded cash PP&E spending in every matched fiscal year; the residual is not FCFF and does not separately expense SBC.')
        elif any(y['ocf_less_cash_capex'] <= 0 for y in years):
            negatives.append('Cash PP&E spending met or exceeded OCF in at least one matched fiscal year.')
        if newest['capex_revenue'] > oldest['capex_revenue']:
            negatives.append('Cash PP&E spending consumed a larger share of revenue; maintenance versus expansion and lease-funded capacity remain unresolved.')
        if newest['sbc_revenue'] > oldest['sbc_revenue']:
            negatives.append('SBC consumed a larger share of revenue; this is an expense/claims consideration, not a measured spot dilution rate.')
    return {'status': 'OBSERVED MULTI-YEAR ECONOMICS' if paired and fresh else 'INSUFFICIENT VERIFIED HISTORY',
            'years': years, 'ambiguous_years': ambiguities, 'positive_findings': positives[:3], 'opposing_findings': negatives[:3], 'neutral_findings': neutral,
            'limits': ['No observation is promoted to moat, durable demand or growth forecast.',
                       'Annual trends require exact same-period/accession accounting inputs and consecutive fiscal years.',
                       'No generic leverage ratio is computed from unreconciled debt/lease scope.',
                       'Weighted-average basic/diluted share counts are not a spot fully diluted denominator.']}


def build(sources, as_of):
    base = ve.evaluate(sources, as_of)
    annual, ttm, failure = [], [], None
    try:
        company = sources.read(ve.FACTS_URL)
        submissions = sources.read(ve.SUBMISSIONS_URL)
        if int(company.get('cik', 0)) != ve.CIK or int(submissions.get('cik', 0)) != ve.CIK:
            raise ValueError('MSFT issuer mismatch')
        q = sq.quality_company('MSFT', company, submissions, as_of)
        cache = {}
        annual = annual_rows(company, sources, as_of, cache)
        ttm = ttm_rows(q, sources, as_of, cache)
    except Exception:
        failure = 'Official MSFT source history unavailable/invalid; no business-quality conclusion inferred.'
    quality = economics(annual, as_of)
    history_ok = quality['status'] == 'OBSERVED MULTI-YEAR ECONOMICS'
    investigations = []
    for key in WATCH:
        row = next((r for r in base['coverage'] if r['field'] == key), None)
        investigations.append({'field': key, 'status': row['status'] if row else 'unavailable',
                               'source': row['source'] if row else None,
                               'filing_check': row['filing_check'] if row else {'status': 'unverified'},
                               'interpretation': ('Depreciation and total depreciation/amortization are different scopes; no automatic substitution or addition.' if key == 'dna' else
                                                  'Filing matching, if successful, verifies this reported unit/period only; no spot share/class/split reconciliation is inferred.')})
    gates = [{'gate': 'multi_period_evidence', 'status': 'observed' if history_ok else 'missing',
              'reason': 'At least two consecutive aligned fiscal years of five core metrics, latest within 550 days; this is a research freshness rule, not investment policy.'}]
    gates += [{'gate': key, 'status': 'missing', 'reason': text} for key, text in GATES.items()]
    rows = base['coverage']
    counts = {'verified': sum(r['status'] == sq.USABLE for r in rows),
              'provisional': sum(r['status'] == 'unverified' and r['value'] is not None for r in rows)}
    counts['unavailable'] = len(rows)-sum(counts.values())
    return {'version': 'msft-dossier.1', 'ticker': 'MSFT', 'as_of': str(as_of),
            'decision': {'valuation_disposition': ve.INSUFFICIENT, 'business_economics': quality['status'],
                         'positive_findings': quality['positive_findings'], 'opposing_findings': quality['opposing_findings'],
                         'uncertainty': 'Price attractiveness cannot be assessed without market/share/capital/discount/forecast and competitive evidence.',
                         'top_missing_inputs': [g['gate'] for g in gates if g['status'] == 'missing'][:3],
                         'horizon': 'Observed fiscal-year business economics; not a 3/6/12-month market forecast.',
                         'would_change_assessment': ['A new independently matched year reverses or confirms revenue/margin/cash-investment trends.',
                                                    'Reconcile lease investment, share claims and depreciation scope before extending cash-return conclusions.',
                                                    'Complete independently sourced market/capital inputs and explicit owner approval of forward cases.']},
            'readiness_gates': gates, 'valuation_cases': {}, 'reverse_implied_growth': None,
            'business_economics': quality, 'annual_evidence': annual, 'ttm_evidence': ttm,
            'selected_coverage': rows, 'coverage_counts': counts, 'matching_investigations': investigations,
            'source_failure': failure, 'source_manifest': {u: {k: v for k, v in item.items() if k != 'body'}
                                                          for u, item in sources.snapshot['sources'].items()},
            'caveats': base['caveats'] + ['Raw SEC reports are not split-adjusted market prices or independently approved forward assumptions.',
                                        'Missing opposing/positive findings means none established by these rules, not absence of business risk/opportunity.',
                                        'Replay requires trusted retained sources; hashes detect drift, not authenticity.']}


def markdown(r):
    d = r['decision']
    lines = ['# MSFT research decision', '', f"As of {r['as_of']} · valuation: **{d['valuation_disposition']}**", '',
             f"Business economics: **{d['business_economics']}**", '', d['horizon'], '', d['uncertainty'], '', '## Evidence for and against', '']
    if r['source_failure']:
        lines[4:4] = ['**Source warning:** ' + r['source_failure'], '']
    if r['business_economics'].get('ambiguous_years'):
        lines += ['Conflicting duplicate fiscal years were excluded; see the annual evidence ledger.', '']
    for label, key in [('Positive observations', 'positive_findings'), ('Opposing observations', 'opposing_findings')]:
        lines += ['', f'**{label}**', ''] + ['- '+x for x in d[key]]
        if not d[key]:
            lines += ['- None established from sufficiently verified multi-year inputs; do not infer absence of risk or merit.']
    lines += ['', '**What would change the assessment**'] + ['- '+x for x in d['would_change_assessment']]
    lines += ['', '**Top missing inputs:** ' + ', '.join(d['top_missing_inputs']), '', 'Research only: no BUY/SELL, trade instruction or calibrated probability.', '',
              '<details><summary>Observed fiscal years and filing sources</summary>', '',
              '| Fiscal year | Revenue USD | Operating margin | OCF less cash PP&E USD | Cash PP&E / revenue | SBC / revenue | Filing |', '|---|---|---|---|---|---|---|']
    for y in r['business_economics']['years']:
        lines.append(f"| {y['start']} to {y['end']} | {y['values']['revenue']:,.0f} | {y['operating_margin']:.1%} | {y['ocf_less_cash_capex']:,.0f} | {y['capex_revenue']:.1%} | {y['sbc_revenue']:.1%} | [{y['accn']}]({y['sources']['revenue']}) |")
    lines += ['', '</details>', '', '<details><summary>Readiness, annual versus TTM evidence, and matching gaps</summary>', '']
    # Structured ledger is secondary and contains source links/units/status; no raw XML/source bodies.
    for key in ('readiness_gates', 'coverage_counts', 'matching_investigations', 'annual_evidence', 'ttm_evidence'):
        lines += [f'### {key.replace("_", " ")}', '', '```json', json.dumps(r[key], indent=2, allow_nan=False), '```', '']
    lines += ['</details>', '', '## Limits', ''] + ['- '+x for x in r['caveats']]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--as-of', type=date.fromisoformat, default=datetime.now(access.NY).date())
    p.add_argument('--snapshot', type=Path)
    p.add_argument('--save-private-sources', type=Path, help='optional local replay snapshot; do not upload publicly')
    args = p.parse_args(argv)
    transport = access.OfficialTransport()
    sources = ve.Sources(json.loads(args.snapshot.read_text()) if args.snapshot else None,
                         get=transport.json, get_bytes=transport.read)
    r = build(sources, args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix('.json').write_text(json.dumps(r, indent=2, allow_nan=False) + '\n')
    args.output.with_suffix('.md').write_text(markdown(r))
    if args.save_private_sources:
        args.save_private_sources.parent.mkdir(parents=True, exist_ok=True)
        args.save_private_sources.write_text(json.dumps(sources.snapshot, allow_nan=False))
    print(json.dumps({'valuation': r['decision']['valuation_disposition'], 'business': r['decision']['business_economics'],
                      'coverage': r['coverage_counts']}))
    return 0 if r['business_economics']['status'] == 'OBSERVED MULTI-YEAR ECONOMICS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
