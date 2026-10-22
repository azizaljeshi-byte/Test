"""Phase 2A-3 MSFT-only SEC evidence pilot. Standalone; never imported by the app.

Run: python -m stockwatch.valuation_evidence --output /tmp/msft-evidence
Replay: add --snapshot /tmp/msft-evidence.sources.json --as-of YYYY-MM-DD
No market connector or forecast approval is inferred. A partial packet is a useful diagnostic,
not a fair value. Current companyfacts filtered by filing date are not a certified PIT archive.
"""
from __future__ import annotations

import argparse
import base64
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from . import sec, sec_quality as sq, valuation_lab as lab, valuation_scenarios as vs

VERSION = '2a-3.msft.1'
CIK = 789019
FACTS_URL = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK:010d}.json'
SUBMISSIONS_URL = f'https://data.sec.gov/submissions/CIK{CIK:010d}.json'
INSUFFICIENT = 'INSUFFICIENT EVIDENCE'
# These are *requests*, never default numbers. Presence in companyfacts does not prove economic scope.
REQUESTS = {
    'price': 'Dated market close and corporate-action/class basis; no retrospectively adjusted PIT claim.',
    'shares': 'Reconcile spot fully diluted common shares, options/RSUs, class and split basis; EPS averages are not spot shares.',
    'investments': 'Verify surplus rather than operating/restricted investments and same-date bridge scope.',
    'debt': 'Reconcile all non-lease current/noncurrent debt plus finance leases; commercial paper alone is not total current debt.',
    'debt_noncurrent': 'Verify non-lease scope and all borrowing components against the debt note.',
    'debt_current': 'Verify current maturities plus short-term borrowings; do not choose one overlapping tag as the total.',
    'finance_lease_liabilities': 'Reconcile current plus noncurrent finance leases and investment treatment.',
    'preferred': 'Explicitly verify preferred claims or evidenced absence; a missing tag is not zero.',
    'noncontrolling': 'Verify minority claims or evidenced absence; a missing tag is not zero.',
    'operating_working_capital': 'Reconcile operating receivables/inventory/payables/deferred revenue, excluding financing and cash.',
    'treasury_10y': 'Dated official US Treasury 10Y observation within the configured freshness window.',
    'beta': 'Dated reproducible regression/adjustment window and market benchmark, not an unexplained vendor number.',
    'borrowing_cost': 'Contemporaneous evidenced marginal borrowing cost, not interest expense divided by debt.',
    'peer_ev_fcff': 'Independent dated peer set, EV/FCFF fiscal/SBC/lease/dilution scope and non-comparability review.',
    'independent_normalized_fcff': 'Independent normalized after-SBC FCFF calculation, not a multiple of the DCF output.',
}
CONTRACTS = {
    'business_scope': 'Review segment economics and consolidated driver suitability.',
    'share_basis': 'Review fully diluted same-class denominator, treasury-stock/options/RSU treatment.',
    'corporate_actions': 'Verify price/share split basis and no intervening corporate-action mismatch.',
    'lease_scope': 'Review lease debt, costs and future lease-funded investment together.',
    'capital_tax': 'Owner-approved cost-of-capital tax assumption, independently attributed.',
    'cross_check_basis': 'Independent after-SBC FCFF comparable on consistent lease/capital/share scope.',
}
ASSUMPTIONS = {
    'years_1_to_5': 'Source or request approval for growth, pre-SBC margin, tax, D&A, maintenance/growth capex, working capital, SBC and non-SBC dilution in each case.',
    'terminal': 'Approve sustainable growth, ROIC/reinvestment, margins and zero terminal extra dilution, with years 6–10 fade.',
    'policy': 'Approve ERP/freshness/spread policy separately; illustrative 5% ERP is not observed market data or adopted policy.',
    'competitive_thesis': 'Source demand, segment growth, competition and moat evidence; no generic technology-company narrative.',
}


class SourceFailure(RuntimeError):
    """A captured source failure whose message survives replay without changing its type prefix."""


class Sources:
    """Capture official inputs for deterministic offline replay; hashes detect drift, not authenticity."""
    def __init__(self, snapshot=None, *, get=None, get_bytes=None):
        self.replay = snapshot is not None
        if self.replay and snapshot.get('version') != VERSION:
            raise ValueError('unsupported source snapshot version')
        self.snapshot = snapshot if self.replay else {
            'version': VERSION, 'ticker': 'MSFT', 'collected_at': datetime.now(timezone.utc).isoformat(), 'sources': {}}
        if self.snapshot.get('ticker') != 'MSFT':
            raise ValueError('this pilot accepts MSFT only')
        self.get, self.get_bytes = get or sec._get, get_bytes or sq._get_bytes

    def read(self, url, binary=False):
        allowed = url in (FACTS_URL, SUBMISSIONS_URL) or url.startswith(f'https://www.sec.gov/Archives/edgar/data/{CIK}/')
        if not allowed:
            raise ValueError('source outside MSFT official SEC scope')
        saved = self.snapshot['sources'].get(url)
        if saved is not None:
            if saved.get('error'):
                raise SourceFailure(saved['error'])
            raw = base64.b64decode(saved['body'], validate=True)
            if hashlib.sha256(raw).hexdigest() != saved['sha256']:
                raise ValueError('source hash mismatch')
        elif self.replay:
            raise OSError('source absent from snapshot; replay never fetches')
        else:
            try:
                data = self.get_bytes(url) if binary else self.get(url)
                raw = data if binary else json.dumps(data, sort_keys=True, allow_nan=False).encode()
                if len(raw) > 20_000_000:
                    raise ValueError('source exceeds 20 MB pilot limit')
            except Exception as exc:
                self.snapshot['sources'][url] = {'error': f'{type(exc).__name__}: {exc}'}
                raise SourceFailure(self.snapshot['sources'][url]['error']) from exc
            self.snapshot['sources'][url] = {'sha256': hashlib.sha256(raw).hexdigest(),
                                             'body': base64.b64encode(raw).decode(),
                                             'encoding': 'raw bytes' if binary else 'canonical JSON (not wire bytes)'}
        return raw if binary else json.loads(raw)


def filing_check(selected, unit, sources, cache):
    """Match a unique company-wide fact in the original instance, including period, unit and accession."""
    if not selected or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', selected.get('accn') or ''):
        return {'status': 'unverified', 'reason': 'missing/invalid filing accession'}
    accn = selected['accn']
    root = sq._archive(CIK, accn)
    try:
        if accn not in cache:
            index = sources.read(root + '/index.json', True)
            names = [x['name'] for x in json.loads(index).get('directory', {}).get('item', [])]
            instance = sq.pick_instance(names)
            if not instance:
                raise ValueError('filing has no readable XBRL instance')
            if '/' in instance or '\\' in instance or '..' in instance:
                raise ValueError('invalid instance filename')
            url = root + '/' + instance
            cache[accn] = (url, sq.parse_instance(sources.read(url, True)))
        url, facts = cache[accn]
        measures = {'USD': f'{{{sq.ISO4217}}}USD', 'shares': sq.XBRLI + 'shares',
                    'USD/shares': f'{{{sq.ISO4217}}}USD/{sq.XBRLI}shares'}
        matches = facts.get((selected['concept'], selected.get('start'), selected['end']), [])
        values = {v for v, u in matches if u == measures[unit]}
        if len(values) != 1 or not math.isclose(next(iter(values)), selected['value'], rel_tol=1e-9, abs_tol=1e-8):
            return {'status': 'unverified', 'url': url, 'reason': 'filing value, unit or undimensioned period missing/conflicting'}
        return {'status': 'matches', 'url': url, 'value': next(iter(values)),
                'proof': 'same concept, company-wide period and unit; no economic-scope approval implied'}
    except Exception as exc:
        return {'status': 'unverified', 'reason': f'{type(exc).__name__}: {exc}'}


def coverage(q, sources):
    rows, cache = [], {}
    for key, f in q['fields'].items():
        s = f.get('selected')
        check = filing_check(s, f['unit'], sources, cache) if s else {'status': 'unverified', 'reason': 'no selected fact'}
        status = f['status']
        if status == sq.USABLE and check['status'] != 'matches':
            status = 'unverified'
        # Metadata omitted by malformed source rows must never become a validated observation.
        if s and (not s.get('filed') or not s.get('form')):
            status = sq.UNKNOWN
        if s:
            try:
                end, filed = date.fromisoformat(s['end']), date.fromisoformat(s['filed'])
                start = date.fromisoformat(s['start']) if s.get('start') else end
                if not start <= end <= filed <= date.fromisoformat(q['as_of']):
                    status = sq.UNKNOWN
            except (ValueError, TypeError, KeyError):
                status = sq.UNKNOWN
        if s and (isinstance(s.get('value'), bool) or not isinstance(s.get('value'), (int, float))
                  or not math.isfinite(s['value'])):
            status = sq.UNKNOWN
        rows.append({'field': key, 'unit': f['unit'], 'value': s.get('value') if s else None,
                     'kind': 'issuer_fact', 'status': status, 'source': s, 'filing_check': check,
                     'issues': f['issues'], 'as_of': q['as_of']})
    return rows


def record(row):
    s = row['source']
    return {'value': row['value'], 'unit': row['unit'], 'kind': 'observation', 'status': sq.USABLE,
            'origin': 'SEC', 'source': row['filing_check']['url'], 'concept': s['concept'],
            'accn': s['accn'], 'form': s['form'], 'filed': s['filed'], 'available_on': s['filed'],
            'period_start': s.get('start'), 'period_end': s['end'],
            'rationale': 'Phase 1B usable selection matched to original filing; scope limitations remain explicit'}


def build_packet(rows):
    # Only annual revenue and unambiguous cash map directly into 2A-2. No EPS/share or debt shortcut.
    obs = {}
    for key in ('revenue', 'cash'):
        row = next(r for r in rows if r['field'] == key)
        if row['status'] == sq.USABLE:
            obs[key] = record(row)
    return {'observations': obs, 'contracts': {}, 'scenarios': {}}


def findings(rows):
    """Explain actual aligned accounting observations; never infer demand, moat or a forecast."""
    by = {r['field']: r for r in rows}
    out = []
    def aligned(*keys):
        rs = [by[k] for k in keys]
        return (all(r['status'] == sq.USABLE and r['value'] is not None for r in rs)
                and len({(r['source'].get('start'), r['source']['end'], r['source']['accn']) for r in rs}) == 1)
    if aligned('revenue', 'capex') and by['revenue']['value'] > 0:
        ratio = by['capex']['value'] / by['revenue']['value']
        out.append({'driver': 'Capital intensity', 'kind': 'issuer_fact_calculation',
                    'text': f'Cash PP&E spending was {ratio:.1%} of reported revenue; maintenance/growth and lease-funded investment are unresolved.',
                    'fields': ['capex', 'revenue'], 'value': ratio})
    if aligned('operating_cash_flow', 'capex'):
        residual = by['operating_cash_flow']['value'] - by['capex']['value']
        out.append({'driver': 'Cash conversion', 'kind': 'issuer_fact_calculation',
                    'text': f'Reported operating cash flow less cash PP&E spending was USD {residual:,.0f}; this is not FCFF and does not separately charge SBC.',
                    'fields': ['operating_cash_flow', 'capex'], 'value': residual})
    if aligned('sbc', 'revenue') and by['revenue']['value'] > 0:
        ratio = by['sbc']['value'] / by['revenue']['value']
        out.append({'driver': 'Compensation claims', 'kind': 'issuer_fact_calculation',
                    'text': f'Reported SBC was {ratio:.1%} of revenue; award/share reconciliation and future dilution remain unresolved.',
                    'fields': ['sbc', 'revenue'], 'value': ratio})
    return out[:3]


def evaluate(sources, as_of):
    """No forecast/market approvals are accepted in this pilot; no company-specific valuation emitted."""
    result = {'version': VERSION, 'ticker': 'MSFT', 'as_of': str(as_of),
              'research_disposition': INSUFFICIENT, 'status': 'UNAVAILABLE', 'drivers': [],
              'horizon': {'intrinsic': 'long-term business economics, not a price forecast',
                          '3/6/12_month': 'UNAVAILABLE: no short-term movement model'},
              'bear_thesis': {'kind': 'unverified hypothesis',
                              'text': 'Investment and lease-funded capacity may outpace sustainable incremental cash returns; this is a diligence question, not an issuer finding.'},
              'would_change_assessment': ['Verify aligned original-filing facts and reconcile debt, leases and fully diluted share/class/split basis.',
                                          'Source market inputs, competitive evidence and obtain explicit approval for scenario/terminal assumptions.'],
              'coverage': [], 'requests': [], 'scenarios': {}, 'reverse_implied_growth': None,
              'model_disagreement': {'status': 'UNAVAILABLE', 'reason': 'No approved, compatible valuation inputs; methods are never averaged.'},
              'caveats': ['Research only; no trading action, probability or production signal.',
                          'Filing matches verify extraction, not accounting correctness, economic scope or investment merit.',
                          'Historical as-of filters publication/period dates; current SEC downloads are not certified point-in-time archives.',
                          'Snapshots preserve source inputs and hashes for replay; hashes do not independently authenticate source truth.']}
    try:
        company, submissions = sources.read(FACTS_URL), sources.read(SUBMISSIONS_URL)
        if int(company.get('cik', 0)) != CIK or int(submissions.get('cik', 0)) != CIK:
            raise ValueError('SEC issuer identity mismatch; MSFT CIK required')
        q = sq.quality_company('MSFT', company, submissions, as_of)
        rows = coverage(q, sources)
        result['coverage'] = rows
        result['family'] = lab.classify(q, company, as_of, lab.load_assumptions())
        result['drivers'] = findings(rows)
        result['packet'] = {'companies': {'MSFT': build_packet(rows)}}
        result['status'] = 'ASSUMPTIONS REQUIRED' if any(r['status'] == sq.USABLE for r in rows) else 'UNAVAILABLE'
        usable = sum(r['status'] == sq.USABLE for r in rows)
        result['measured_coverage'] = {'verified_fields': usable, 'selected_fields': len(rows),
                                       'meaning': 'Phase 1B selected fields matched to filing, not percent valuation readiness'}
        result['evidence_classification'] = 'PARTIAL' if usable else 'UNAVAILABLE'
        result['contradictions'] = [{'field': r['field'], 'status': r['status'], 'issues': r['issues'],
                                     'filing_check': r['filing_check']} for r in rows
                                    if r['status'] not in (sq.USABLE, sq.UNKNOWN)]
        missing = [r['field'] for r in rows if r['status'] != sq.USABLE]
        result['dominant_uncertainty'] = ('Financial evidence not verified: ' + ', '.join(missing[:5]) if missing else
                                         'Sustainable returns on investment, approved forecasts, and market/share/lease reconciliation are unresolved.')
    except Exception as exc:
        result['source_error'] = str(exc) if isinstance(exc, SourceFailure) else f'{type(exc).__name__}: {exc}'
        result['packet'] = {'companies': {'MSFT': {'observations': {}, 'contracts': {}, 'scenarios': {}}}}
        result['evidence_classification'] = 'UNAVAILABLE'
        result['dominant_uncertainty'] = 'SEC evidence unavailable or invalid; no company assessment can be supported.'
        result['measured_coverage'] = {'verified_fields': 0, 'selected_fields': 0, 'meaning': 'source unavailable; no coverage claim'}
    obs = result['packet']['companies']['MSFT']['observations']
    for key in ('revenue', 'cash'):
        if key not in obs:
            result['requests'].append({'field': key, 'kind': 'issuer_evidence', 'reason': 'Usable original-filing match required.'})
    result['requests'] += [{'field': k, 'kind': 'independent_evidence', 'reason': why} for k, why in REQUESTS.items()]
    result['requests'] += [{'field': k, 'kind': 'reviewed_contract_or_assumption', 'reason': why} for k, why in CONTRACTS.items()]
    result['requests'] += [{'field': k, 'kind': 'owner_assumption_request', 'reason': why} for k, why in ASSUMPTIONS.items()]
    result['scenario_engine'] = {'status': vs.REQUIRED, 'reason': 'Partial packet only; evidence and explicit assumption approvals required before calling the scenario model.'}
    result['source_manifest'] = {url: {k: v for k, v in item.items() if k != 'body'}
                                 for url, item in sources.snapshot['sources'].items()}
    return result


def markdown(r):
    lines = [f"# MSFT — {r['research_disposition']}", '', f"As of {r['as_of']} · {r['status']} · {r['evidence_classification']}", '',
             'Research only. No BUY/SELL, return probability or short-term forecast.', '',
             '## Decision and dominant evidence', '', r['dominant_uncertainty'], '']
    lines += [f"- **{d['driver']}:** {d['text']}" for d in r['drivers']]
    if not r['drivers']:
        lines += ['- No verified, aligned accounting drivers available; do not infer business quality from missing data.']
    lines += ['', '**Conditional bear thesis (hypothesis):** ' + r['bear_thesis']['text'], '', '**What would change the assessment:**']
    lines += ['- ' + x for x in r['would_change_assessment']]
    lines += ['', 'Long-term intrinsic economics are separate from 3/6/12-month movement: the latter is unavailable.', '',
              'Valuation cases, reverse hurdle and sensitivities: unavailable until evidence and assumptions clear.', '',
              f"Measured coverage: {r['measured_coverage']['verified_fields']} / {r['measured_coverage']['selected_fields']} selected fields verified (not valuation readiness)."]
    if r.get('source_error'):
        lines += ['', 'Source failure: ' + r['source_error']]
    lines += ['', '<details><summary>SEC coverage and filing proof</summary>', '',
              '| Field | Selected value / unit | Status | Fiscal period | Filed / accession | Filing evidence |', '|---|---|---|---|---|---|']
    def cell(x):
        return str(x).replace('|', '\\|').replace('\n', ' ')
    for row in r['coverage']:
        s = row['source'] or {}
        lines += ['| ' + ' | '.join(cell(x) for x in (row['field'], f"{row['value']} {row['unit']}", row['status'],
                   f"{s.get('start')} to {s.get('end')}", f"{s.get('filed')} / {s.get('accn')}",
                   row['filing_check'].get('url') or row['filing_check'].get('reason'))) + ' |']
    lines += ['', '</details>', '', '<details><summary>Evidence and approval requests</summary>', '']
    lines += [f"- **{x['field']}** ({x['kind']}): {x['reason']}" for x in r['requests']]
    lines += ['', '</details>', '', '## Limits', ''] + ['- ' + x for x in r['caveats']]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--as-of', type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    p.add_argument('--snapshot', type=Path, help='replay a saved source snapshot without network')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    sources = Sources(json.loads(a.snapshot.read_text()) if a.snapshot else None)
    r = evaluate(sources, a.as_of)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    for suffix, payload in (('.json', r), ('.sources.json', sources.snapshot)):
        a.output.with_suffix(suffix).write_text(json.dumps(payload, indent=2, allow_nan=False) + '\n')
    a.output.with_suffix('.md').write_text(markdown(r))
    print(json.dumps({'disposition': r['research_disposition'], 'status': r['status'], 'coverage': r['measured_coverage']}))
    return 0  # an honest unavailable/partial diagnostic is a successful research report


if __name__ == '__main__':
    raise SystemExit(main())
