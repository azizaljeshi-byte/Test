"""Manual MSFT official-SEC diagnostic; isolated from app clients and trading.

Requires a descriptive SEC_USER_AGENT in private env. Never bypasses proxy/SEC denial.
python -m stockwatch.sec_access --output /tmp/msft-sec
"""
from __future__ import annotations

import argparse
from datetime import datetime
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from . import sec, sec_quality as sq, valuation_evidence as ve

NY = ZoneInfo('America/New_York')


class AccessFailure(OSError):
    """Sanitized classification: no response bodies, headers, identity or credentials in messages."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AccessFailure('redirect refused; inspect official endpoint configuration')


def retry_delay(value, now):
    """Honor Retry-After, but stop instead of retrying early if the wait exceeds our 30s budget."""
    if value is None:
        return 2.
    try:
        wait = float(value) if str(value).strip().isdigit() else parsedate_to_datetime(value).timestamp() - now
        return max(0., wait) if wait <= 30 else None
    except (ValueError, TypeError, OverflowError):
        return None


class OfficialTransport:
    """Serial <=2 requests/sec, per-run success/failure cache, max two attempts on 429/503 only.

    This limiter belongs only to the manual diagnostic. It doesn't claim to coordinate other app processes.
    """
    def __init__(self, *, opener=None, clock=time.monotonic, sleep=time.sleep, wall=time.time):
        self.opener = opener or urllib.request.build_opener(NoRedirect()).open
        self.clock, self.sleep, self.wall = clock, sleep, wall
        self.last = None
        self.cache, self.events = {}, []

    def read(self, url):
        p = urlsplit(url)
        if p.scheme != 'https' or p.netloc not in ('data.sec.gov', 'www.sec.gov') or p.query or p.fragment:
            raise AccessFailure('URL outside official MSFT scope')
        if url not in (ve.FACTS_URL, ve.SUBMISSIONS_URL) and not url.startswith(f'https://www.sec.gov/Archives/edgar/data/{ve.CIK}/'):
            raise AccessFailure('URL outside official MSFT scope')
        if url in self.cache:
            value = self.cache[url]
            if isinstance(value, AccessFailure):
                raise value
            return value
        if sec.user_agent_status() != 'configured':
            raise AccessFailure('SEC_USER_AGENT not configured with a descriptive name and contact; no request sent')
        error = AccessFailure('request unavailable')
        for attempt in range(2):
            if self.last is not None:
                self.sleep(max(0., .5 - (self.clock() - self.last)))
            self.last = self.clock()
            event = {'host': p.hostname, 'path': p.path, 'attempt': attempt + 1}
            self.events.append(event)
            try:
                req = urllib.request.Request(url, headers={'User-Agent': sec._user_agent(), 'Accept': '*/*'})
                with sec._SEC_SLOTS, self.opener(req, timeout=30) as response:
                    raw = response.read(20_000_001)
                    if len(raw) > 20_000_000:
                        raise AccessFailure('source exceeds 20 MB limit')
                    event.update(layer='http_response', status=response.status)
                self.cache[url] = raw
                return raw
            except urllib.error.HTTPError as exc:
                event.update(layer='http_response_origin_unconfirmed', status=exc.code)
                delay = retry_delay(exc.headers.get('Retry-After'), self.wall())
                exc.close()
                error = AccessFailure(f'HTTP {exc.code}; origin attribution unconfirmed')
                if attempt == 0 and exc.code in (429, 503) and delay is not None:
                    event['retry_after_seconds'] = delay
                    self.sleep(delay)
                    continue
            except urllib.error.URLError as exc:
                layer = 'proxy_connect' if 'Tunnel connection failed' in str(exc.reason) else 'transport'
                event['layer'] = layer
                error = AccessFailure('proxy CONNECT denied before origin response' if layer == 'proxy_connect' else 'transport failure before usable response')
            except Exception:
                event['layer'] = 'request_failure'
                error = AccessFailure('request/read/redirect failed; no usable source captured')
            break
        self.cache[url] = error
        raise error

    def json(self, url):
        return json.loads(self.read(url))


def run(transport, as_of):
    # Probe both endpoints independently; the evidence run reuses these cached responses/failures.
    probes = []
    for url in (ve.FACTS_URL, ve.SUBMISSIONS_URL):
        try:
            transport.json(url)
            probes.append({'host': 'data.sec.gov', 'path': urlsplit(url).path, 'status': 'retrieved'})
        except Exception as exc:
            # Do not serialize an arbitrary exception: some clients include request credentials in errors.
            probes.append({'host': 'data.sec.gov', 'path': urlsplit(url).path, 'status': 'unavailable',
                           'reason': str(exc) if isinstance(exc, AccessFailure) else 'response could not be decoded'})
    sources = ve.Sources(get=transport.json, get_bytes=transport.read)
    report = ve.evaluate(sources, as_of)
    rows = report['coverage']
    verified = sum(r['status'] == sq.USABLE for r in rows)
    provisional = sum(r['status'] == 'unverified' and r['value'] is not None for r in rows)
    counts = {'verified': verified, 'provisional': provisional, 'unavailable': len(rows) - verified - provisional,
              'total_fields': len(rows), 'meaning': 'selected financial facts, not valuation readiness'}
    report['access_coverage'] = counts
    diagnostic = {'ticker': 'MSFT', 'as_of': str(as_of), 'identity_status': sec.user_agent_status(),
                  'probes': probes, 'requests': transport.events, 'coverage': counts,
                  'archive': 'attempted by selected accession' if any(e['host'] == 'www.sec.gov' for e in transport.events)
                             else 'not reached; no verified accession/usable source path',
                  'limits': ['This process is paced <=2 requests/sec; other machines must share the SEC <=10/sec aggregate budget.',
                             'No alternate provider, proxy bypass or origin-denial workaround.',
                             'No source response or credential contents are included in diagnostic logs.']}
    return report, diagnostic


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    report, diagnostic = run(OfficialTransport(), datetime.now(NY).date())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix('.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    args.output.with_suffix('.md').write_text(ve.markdown(report) + '\nAccess coverage: ' + json.dumps(diagnostic['coverage']) + '\n')
    args.output.with_suffix('.diagnostic.json').write_text(json.dumps(diagnostic, indent=2) + '\n')
    print(json.dumps({'disposition': report['research_disposition'], 'identity_status': diagnostic['identity_status'],
                      'coverage': diagnostic['coverage'], 'archive': diagnostic['archive']}))
    return 0 if diagnostic['coverage']['verified'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
