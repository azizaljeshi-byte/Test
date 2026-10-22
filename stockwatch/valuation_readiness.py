"""MSFT-only readiness evidence. No DCF, market fetch, policy defaults or approved forecasts.

SEC concept matches are accounting observations, not automatic economic-scope approvals.
The only added live source is the official Treasury daily nominal par-yield XML feed.
"""
from __future__ import annotations

import base64
from datetime import date, timedelta
import hashlib
import json
import math
import time
import urllib.request
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from . import sec_access, sec_quality as sq, valuation_evidence as ve

USABLE, RECONCILE, UNAVAILABLE = 'usable', 'reconcile', 'unavailable'
TREASURY_ROOT = 'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml'
ATOM = '{http://www.w3.org/2005/Atom}'
DATA = '{http://schemas.microsoft.com/ado/2007/08/dataservices}'
# Explicit concepts: overlapping totals/components are kept separately, never blindly added.
CAPITAL = {
    'cash': 'CashAndCashEquivalentsAtCarryingValue', 'investments_current': 'ShortTermInvestments',
    'debt_total_reported': 'LongTermDebt', 'debt_noncurrent': 'LongTermDebtNoncurrent',
    'current_maturities': 'LongTermDebtCurrent', 'short_borrowings': 'ShortTermBorrowings',
    'commercial_paper': 'CommercialPaper', 'finance_leases_total': 'FinanceLeaseLiability',
    'finance_leases_current': 'FinanceLeaseLiabilityCurrent', 'finance_leases_noncurrent': 'FinanceLeaseLiabilityNoncurrent',
    'operating_leases_total': 'OperatingLeaseLiability', 'operating_leases_current': 'OperatingLeaseLiabilityCurrent',
    'operating_leases_noncurrent': 'OperatingLeaseLiabilityNoncurrent',
    'preferred_claims': 'PreferredStockValue', 'noncontrolling_claims': 'MinorityInterest',
    'common_shares': 'CommonStockSharesOutstanding',
}


def missing(field, reason, unit=None):
    return {'field': field, 'status': UNAVAILABLE, 'value': None, 'unit': unit, 'reason': reason,
            'source': None, 'kind': 'missing_evidence'}


def treasury_url(year):
    return TREASURY_ROOT + f'?data=daily_treasury_yield_curve&field_tdr_date_value={year}'


class TreasurySources:
    """Fixed official host/year feeds, <=1 request/sec, 5MB read cap, no redirects or credentials.

    Snapshot is separate from SEC and is private/local only; replay never fetches absent URLs.
    """
    def __init__(self, snapshot=None, *, read=None):
        self.replay = snapshot is not None
        self.snapshot = snapshot if self.replay else {'version': 'treasury.1', 'sources': {}}
        if self.snapshot.get('version') != 'treasury.1':
            raise ValueError('unsupported Treasury snapshot')
        self.reader, self.last = read, None

    def read(self, year):
        url = treasury_url(year)
        item = self.snapshot['sources'].get(url)
        if item:
            if 'error' in item:
                raise OSError('official Treasury source unavailable')
            raw = base64.b64decode(item['body'], validate=True)
            if hashlib.sha256(raw).hexdigest() != item['sha256']:
                raise ValueError('Treasury snapshot hash mismatch')
            return raw
        if self.replay:
            raise OSError('Treasury source absent from replay; no fetch')
        if self.last is not None:
            time.sleep(max(0, 1-(time.monotonic()-self.last)))
        self.last = time.monotonic()
        try:
            if self.reader:
                raw = self.reader(url)
            else:
                request = urllib.request.Request(url, headers={'User-Agent': 'StockWatch official Treasury research'})
                with urllib.request.build_opener(sec_access.NoRedirect()).open(request, timeout=20) as r:
                    raw = r.read(5_000_001)
            if len(raw) > 5_000_000:
                raise ValueError('Treasury response exceeds 5MB')
        except Exception:
            self.snapshot['sources'][url] = {'error': 'official Treasury request failed; no rate inferred'}
            raise OSError('official Treasury request failed; no rate inferred') from None
        self.snapshot['sources'][url] = {'body': base64.b64encode(raw).decode(),
                                          'sha256': hashlib.sha256(raw).hexdigest()}
        return raw


def treasury_10y(sources, as_of):
    """Daily dates do not certify intraday publication; conservatively usable from following day."""
    rows = []
    try:
        for year in sorted({as_of.year, (as_of-timedelta(days=7)).year}):
            raw = sources.read(year)
            for entry in ET.fromstring(raw).findall(ATOM+'entry'):
                day_text = entry.findtext('.//'+DATA+'NEW_DATE')
                if not day_text:
                    continue
                day = date.fromisoformat(day_text[:10])
                if day + timedelta(days=1) > as_of:
                    continue
                text = entry.findtext('.//'+DATA+'BC_10YEAR')
                val = float(text)/100 if text and text.strip() else None
                if val is not None and (not math.isfinite(val) or not -.1 <= val <= 1):
                    raise ValueError('invalid Treasury yield')
                rows.append((day, val, treasury_url(year), hashlib.sha256(raw).hexdigest()))
    except Exception:
        return missing('treasury_10y', 'Official Treasury XML unavailable/invalid or incomplete replay; no substitute rate.', 'ratio')
    if not rows:
        return missing('treasury_10y', 'No date-eligible official 10Y observation; no same-day publication precision assumed.', 'ratio')
    day = max(x[0] for x in rows)
    latest = [r for r in rows if r[0] == day]
    vals = {r[1] for r in latest}
    row = {'field': 'treasury_10y', 'unit': 'ratio', 'currency': 'USD', 'kind': 'official_market_observation',
           'source': latest[0][2], 'source_sha256': latest[0][3], 'period_end': str(day),
           'available_on': str(day+timedelta(days=1)), 'as_of': str(as_of),
           'availability_basis': 'Daily feed date plus one calendar day; not certified point-in-time archival publication.',
           'freshness_days': (as_of-day).days, 'basis': 'nominal 10Y Treasury par yield, not company WACC or a zero-coupon spot rate'}
    if len(vals) != 1:
        return row | {'status': RECONCILE, 'value': None, 'reason': 'Conflicting same-date Treasury yields.'}
    value = next(iter(vals))
    if value is None or (as_of-day).days > 7:
        return row | {'status': UNAVAILABLE, 'value': None, 'reason': 'Latest eligible 10Y yield missing or stale under seven-day research freshness rule.'}
    return row | {'status': USABLE, 'value': value, 'reason': 'Official dated observation only; ERP/tax and company financing inputs remain unresolved.'}



def safe_reference(text):
    try:
        parsed = urlsplit(text)
        return parsed.scheme == 'https' and bool(parsed.hostname) and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
    except (TypeError, ValueError):
        return False

def market_close_candidate(record, as_of):
    """Validate a proposed capture; provenance/class/splits still require independent review.

    No public-market data provider is enabled by this function or by default CLI execution.
    """
    bad = lambda reason: missing('price', reason, 'USD/share')
    if not isinstance(record, dict):
        return bad('No permissible independently reviewed market-close capture configured; no price guessed.')
    try:
        day, available = date.fromisoformat(record['date']), date.fromisoformat(record['available_on'])
        value = record['value']
        if not day <= available <= as_of or (as_of-day).days > 7:
            return bad('Close capture is stale or not available as of the report.')
        if record.get('ticker') != 'MSFT' or record.get('unit') != 'USD/share' or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            return bad('MSFT finite positive USD/share close required.')
        if record.get('basis') != 'raw_unadjusted' or record.get('class_id') != 'MSFT-common':
            return bad('Adjusted price or unresolved common-share class; no valuation price accepted.')
        if record.get('split_basis_date') != record['date'] or date.fromisoformat(record['corporate_actions_reviewed_through']) != as_of:
            return bad('Corporate-action/price-share basis unresolved.')
        if (not all(record.get(k) for k in ('source', 'provider', 'license_reference', 'captured_at'))
                or not safe_reference(record.get('source'))):
            return bad('Provider, permission reference, capture date and source required.')
        captured = date.fromisoformat(record['captured_at'][:10])
        if not day <= captured <= available:
            return bad('Historical price cannot be represented as a contemporaneous capture.')
    except (ValueError, TypeError, KeyError):
        return bad('Malformed dated market capture; no price accepted.')
    safe = {k: record[k] for k in ('ticker','unit','value','date','available_on','source','provider','license_reference',
                                   'captured_at','basis','class_id','split_basis_date','corporate_actions_reviewed_through')}
    return safe | {'field': 'price', 'status': RECONCILE, 'kind': 'market_capture_candidate',
                           'reason': 'Schema passed; independent source rights and corporate-action/share reconciliation not certified by metadata.'}


def beta_candidate(stock, benchmark, as_of):
    """Reproducible monthly simple-return beta candidate; never silently adopted in WACC.

    Inputs require permission/source metadata and the same split/dividend-adjusted monthly dates.
    """
    bad = lambda why: missing('beta', why, 'ratio')
    try:
        for series in (stock, benchmark):
            if (not isinstance(series, dict) or not all(series.get(k) for k in ('source', 'provider', 'license_reference'))
                    or not safe_reference(series.get('source')) or series.get('basis') != 'split_and_dividend_adjusted'):
                return bad('Beta requires sourced permitted adjusted return series; raw/dividend-misaligned prices rejected.')
        if stock.get('ticker') != 'MSFT' or benchmark.get('ticker') != 'SPY':
            return bad('Beta window requires MSFT and explicitly identified SPY benchmark.')
        a, b = stock['observations'], benchmark['observations']
        days = [date.fromisoformat(x['date']) for x in a]
        if len(a) != len(b) or len(a) < 37 or [x['date'] for x in a] != [x['date'] for x in b]:
            return bad('At least 37 exactly aligned monthly closes required; no fills.')
        months = [d.year*12+d.month for d in days]
        if (any(y-x != 1 for x,y in zip(months, months[1:])) or days[-1] > as_of or (as_of-days[-1]).days > 45
                or any(not date.fromisoformat(s['date']) <= date.fromisoformat(s['available_on']) <= as_of for series in (a,b) for s in series)):
            return bad('Beta requires consecutive monthly observations available by as-of with a recent endpoint.')
        if any(isinstance(x['close'],bool) for series in (a,b) for x in series):
            return bad('Boolean is not a closing price.')
        prices = [[float(x['close']) for x in series] for series in (a,b)]
        if any(not math.isfinite(v) or v <= 0 for series in prices for v in series):
            return bad('Invalid adjusted close in beta window.')
        returns = [[new/old-1 for old,new in zip(series, series[1:])] for series in prices]
        x,y = returns
        mx,my = sum(x)/len(x),sum(y)/len(y)
        variance = sum((v-my)**2 for v in y)
        if variance <= 0:
            return bad('Benchmark return variance is zero.')
        beta = sum((sx-mx)*(sy-my) for sx,sy in zip(x,y))/variance
        if not math.isfinite(beta) or not math.isfinite(variance) or any(not math.isfinite(v) for series in returns for v in series):
            return bad('Nonfinite beta/return variance; no estimate accepted.')
    except (KeyError, ValueError, TypeError, AttributeError, ZeroDivisionError, OverflowError):
        return bad('Missing or malformed reproducible beta series; no vendor beta substituted.')
    return {'field': 'beta', 'status': RECONCILE, 'unit': 'ratio', 'kind': 'derived_market_candidate', 'value': beta,
            'source': [stock['source'], benchmark['source']], 'window': [str(days[0]),str(days[-1])],
            'frequency': 'monthly simple returns', 'return_count': len(x), 'benchmark': 'SPY',
            'adjustment_basis': 'split_and_dividend_adjusted', 'as_of': str(as_of),
            'sampling_rule': 'One supplied close per consecutive month on exactly matching dates; no resampling or filling.',
            'input_sha256': hashlib.sha256(json.dumps([stock,benchmark],sort_keys=True,allow_nan=False).encode()).hexdigest(),
            'reason': 'Reproducible covariance/variance candidate, not adopted WACC beta; source rights, sampling convention and corporate-action review remain.'}


def sec_capital(sources, as_of):
    """Collect exact same-date concept evidence; economic scope never follows from the tag name alone."""
    out = {}
    try:
        company = sources.read(ve.FACTS_URL)
        submissions = sources.read(ve.SUBMISSIONS_URL)
        if int(company.get('cik',0)) != ve.CIK or int(submissions.get('cik',0)) != ve.CIK:
            raise ValueError('MSFT issuer mismatch')
        q = sq.quality_company('MSFT', company, submissions, as_of)
        target = q['balance_sheet']['date']
        if not target:
            raise ValueError('no balance-sheet anchor')
        cache = {}
        for key, concept in CAPITAL.items():
            unit = 'shares' if key == 'common_shares' else 'USD'
            facts = sq._candidates(company, [concept], unit, as_of)[0].get(concept, [])
            same = [f for f in facts if f['end'] == target and not f.get('start') and f.get('filed')]
            if not same:
                out[key] = missing(key, f'{concept} missing at balance date {target}; absence is not zero.',unit)
                continue
            chosen = max(same,key=lambda f:f['filed'])
            source = sq._source(chosen,concept)
            contested = sq._contest(facts,chosen,unit)
            check = ve.filing_check(source,unit,sources,cache)
            status = RECONCILE if contested else USABLE
            if check['status'] != 'matches' or (as_of-date.fromisoformat(target)).days > 200:
                status = UNAVAILABLE
            value = chosen['val']
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0 or not date.fromisoformat(target) <= date.fromisoformat(chosen['filed']) <= as_of:
                status = UNAVAILABLE
            out[key] = {'field':key,'value':value,'unit':unit,'currency':'USD' if unit=='USD' else None,
                        'kind':'issuer_accounting_observation','status':status,'source':source,'filing_check':check,
                        'available_on':chosen['filed'],'as_of':str(as_of), 'freshness_days':(as_of-date.fromisoformat(target)).days,
                        'reason':contested[1] if contested else 'Exact reported concept; economic debt/lease/surplus/share scope still needs review.'}
    except Exception:
        for key in CAPITAL:
            out.setdefault(key,missing(key,'MSFT same-date original-filing evidence unavailable; no zero inferred.'))
    return out


def lease_check(rows, family):
    keys = [family+'_total', family+'_current', family+'_noncurrent']
    rs = [rows[k] for k in keys]
    if any(r['status'] != USABLE for r in rs):
        return {'status':UNAVAILABLE,'reason':'Full lease total/current/noncurrent evidence not verified; no partial sum used.'}
    if len({r['source']['end'] for r in rs}) != 1:
        return {'status':RECONCILE,'reason':'Lease totals/components have different dates.'}
    matches = math.isclose(rs[0]['value'],rs[1]['value']+rs[2]['value'],rel_tol=1e-9,abs_tol=.01)
    return {'status':USABLE if matches else RECONCILE,
            'reason':'Total matches current plus noncurrent; count the total ONCE, not total plus components.' if matches else 'Lease total does not match current plus noncurrent.',
            'source_concepts':[r['source']['concept'] for r in rs]}



def dated_treasury(record, as_of):
    """Recheck a supplied rate record so a stale cached result cannot survive a new as-of."""
    if not isinstance(record, dict):
        return missing('treasury_10y','Official Treasury source not supplied/replayed; no rate default.','ratio')
    if record.get('status') != USABLE:
        return record
    try:
        end, available = date.fromisoformat(record['period_end']), date.fromisoformat(record['available_on'])
        value = record['value']
        digest = record.get('source_sha256','')
        valid = (end+timedelta(days=1) <= available <= as_of and 0 <= (as_of-end).days <= 7
                 and record.get('source') == treasury_url(end.year) and record.get('unit') == 'ratio'
                 and record.get('kind') == 'official_market_observation' and record.get('currency') == 'USD'
                 and len(digest) == 64 and all(c in '0123456789abcdef' for c in digest)
                 and not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value)
                 and -.1 <= value <= 1)
        if valid:
            return record
    except (KeyError, ValueError, TypeError):
        pass
    return missing('treasury_10y','Supplied Treasury record is stale, future, malformed or lacks official source/unit/hash evidence.','ratio')

def evaluate(sources, as_of, treasury=None, market=None, beta=None):
    capital = sec_capital(sources,as_of)
    price = market_close_candidate(market,as_of)
    rate = dated_treasury(treasury,as_of)
    beta = beta or missing('beta','No independently reviewed adjusted stock/benchmark return series; no vendor beta default.','ratio')
    fields = [price,rate,beta] + list(capital.values())
    for key,reason in {
        'spot_fully_diluted_shares':'Reported outstanding/EPS-average shares do not reconcile treasury-stock method, options/RSUs, classes or future issuance.',
        'awards_and_options':'Award/option note and exercise-price/vesting/antidilutive treatment not reconciled; no shares estimated.',
        'surplus_investments':'Short-term investments are not automatically surplus/restricted-free cash.',
        'marginal_borrowing_cost':'No contemporaneous issuer debt yield/terms evidence; coupon or interest expense/debt is not a marginal rate.',
        'erp_policy':'Equity risk premium requires explicit owner-reviewed assumption; no illustrative 5% default.',
        'tax_policy':'Tax policy requires explicit owner-reviewed assumption; no default rate.',
        'depreciation_capex_scope':'Depreciation versus total D&A, maintenance/growth cash PP&E and lease-funded expansion remain unreconciled; see the dossier matching investigation.',
        'forecast_cases':'Bear/base/bull, maintenance/growth capex, lease expansion, terminal fade and ROIC require owner-reviewed assumptions.'}.items():
        fields.append(missing(key,reason))
    gates = [{'gate':'price_share_basis','status':RECONCILE if price['status']==RECONCILE else UNAVAILABLE,
              'reason':'Market close and spot fully diluted/share/corporate-action basis must reconcile together.'},
             {'gate':'capital_bridge','status':RECONCILE if any(r['status']==USABLE for r in capital.values()) else UNAVAILABLE,
              'reason':'No automatic debt sum: total debt, current maturities, short borrowings and commercial paper may overlap; lease inclusion and surplus claims need note review.'},
             {'gate':'discount_inputs','status':RECONCILE if rate['status']==USABLE else UNAVAILABLE,
              'reason':'Treasury alone cannot establish WACC; beta, marginal debt yield, capital weights and owner ERP/tax policy unresolved.'},
             {'gate':'approved_forward_assumptions','status':UNAVAILABLE,'reason':'No forward case/policy approvals ingested; never auto-execute DCF.'}]
    return {'version':'msft-readiness.1','as_of':str(as_of),'valuation_disposition':'INSUFFICIENT EVIDENCE',
            'fields':fields,'gates':gates,'blockers':[g['gate'] for g in gates if g['status']!=USABLE],
            'lease_reconciliations':{f:lease_check(capital,f) for f in ('finance_leases','operating_leases')},
            'summary': ['Dated market close plus spot fully diluted/corporate-action basis: unresolved.',
                        'Same-date debt/lease/surplus bridge: original concept matches do not establish economic scope.',
                        'Official 10Y Treasury: '+rate['status']+'; beta, marginal borrowing yield and owner ERP/tax remain unresolved.',
                        'No approved forward cases or depreciation/capex-scope reconciliation; valuation stays blocked.'],
            'supported_computations':['Original-filing concept matches; exact lease total/component arithmetic when all components pass.'],
            'unsupported_computations':['Enterprise/equity bridge, market capitalization, WACC, DCF and reverse-implied expectations.'],
            'valuation_cases':{},'reverse_implied_growth':None,
            'caveat':'Usable accounting concepts are not approved valuation inputs. No public market provider enabled; candidate metadata is not independent source verification.'}
