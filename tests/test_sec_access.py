"""Official diagnostic transport tests; no real SEC or credential values used."""
from datetime import date
import io
import json
from pathlib import Path
import urllib.error

import pytest

from stockwatch import sec_access as sa, valuation_evidence as ve


class Clock:
    def __init__(self):
        self.t = 0.

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class Response(io.BytesIO):
    status = 200


def transport(monkeypatch, opener):
    monkeypatch.setenv('SEC_USER_AGENT', 'Synthetic Test test@example.invalid')
    clock = Clock()
    return sa.OfficialTransport(opener=opener, clock=clock.now, sleep=clock.sleep, wall=clock.now), clock


def test_identity_gate_and_official_scope(monkeypatch):
    monkeypatch.delenv('SEC_USER_AGENT', raising=False)
    t = sa.OfficialTransport(opener=lambda *a, **k: pytest.fail('network'))
    with pytest.raises(sa.AccessFailure, match='no request sent'):
        t.read(ve.FACTS_URL)
    assert not t.events
    for url in ['https://example.com/', ve.FACTS_URL + '?token=secret',
                'https://www.sec.gov/Archives/edgar/data/1/test.xml']:
        with pytest.raises(sa.AccessFailure, match='scope'):
            t.read(url)


def test_spacing_cache_and_no_contact_logging(monkeypatch):
    calls = []
    def open_(req, **kwargs):
        calls.append(req.full_url)
        assert req.headers['User-agent'].startswith('Synthetic Test')
        return Response(b'{}')
    t, clock = transport(monkeypatch, open_)
    assert t.json(ve.FACTS_URL) == {}
    t.read(ve.FACTS_URL)
    t.json(ve.SUBMISSIONS_URL)
    assert len(calls) == 2 and clock.t >= .5
    assert 'example.invalid' not in json.dumps(t.events)


@pytest.mark.parametrize('status', [429, 503])
def test_transient_retry_honors_retry_after(monkeypatch, status):
    calls = []
    def open_(req, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, status, 'synthetic', {'Retry-After': '3'}, None)
        return Response(b'{}')
    t, clock = transport(monkeypatch, open_)
    assert t.read(ve.FACTS_URL) == b'{}'
    assert len(calls) == 2 and clock.t >= 3


def test_proxy_denial_and_origin_http_are_distinct_and_not_retried(monkeypatch):
    for exc, layer in [(urllib.error.URLError('Tunnel connection failed: 403 Forbidden secret'), 'proxy_connect'),
                       (urllib.error.HTTPError(ve.FACTS_URL, 403, 'secret', {}, None), 'http_response_origin_unconfirmed')]:
        def open_(req, **kwargs):
            raise exc
        t, _ = transport(monkeypatch, open_)
        for _ in range(2):
            with pytest.raises(sa.AccessFailure) as got:
                t.read(ve.FACTS_URL)
            assert 'secret' not in str(got.value)
        assert len(t.events) == 1 and t.events[0]['layer'] == layer


def test_long_retry_after_stops_instead_of_retrying_early(monkeypatch):
    def open_(req, **kwargs):
        raise urllib.error.HTTPError(req.full_url, 429, 'synthetic', {'Retry-After': '120'}, None)
    t, clock = transport(monkeypatch, open_)
    with pytest.raises(sa.AccessFailure):
        t.read(ve.FACTS_URL)
    assert len(t.events) == 1 and clock.t == 0
    assert sa.retry_delay('Thu, 01 Jan 1970 00:00:10 GMT', 0) == 10
    assert sa.retry_delay('invalid', 0) is None


def test_partial_outage_and_zero_coverage_are_honest(monkeypatch):
    def open_(req, **kwargs):
        if req.full_url == ve.FACTS_URL:
            return Response(json.dumps({'cik': ve.CIK, 'facts': {}}).encode())
        raise urllib.error.URLError('Tunnel connection failed: 403 Forbidden')
    t, _ = transport(monkeypatch, open_)
    report, d = sa.run(t, date(2026, 10, 22))
    assert d['probes'][0]['status'] == 'retrieved' and d['probes'][1]['status'] == 'unavailable'
    assert len(t.events) == 2   # evidence run reuses failures, no retry loop
    assert report['research_disposition'] == ve.INSUFFICIENT and d['coverage']['verified'] == 0
    assert not report['scenarios'] and not report['drivers']


def test_success_and_archive_outage_keep_provenance(monkeypatch):
    # Reuse the clearly synthetic SEC-shaped fixture from the evidence pilot, not issuer observations.
    from test_valuation_evidence import fixture, instance
    c = fixture()
    def opener(block_archive=False):
        def open_(req, **kwargs):
            url = req.full_url
            if url == ve.FACTS_URL:
                return Response(json.dumps(c).encode())
            if url == ve.SUBMISSIONS_URL:
                return Response(json.dumps({'cik': ve.CIK, 'sic': '7372'}).encode())
            if block_archive:
                raise urllib.error.HTTPError(url, 403, 'synthetic', {}, None)
            if url.endswith('/index.json'):
                return Response(b'{"directory":{"item":[{"name":"synthetic.xml"}]}}')
            return Response(instance(c))
        return open_
    for blocked in [False, True]:
        t, _ = transport(monkeypatch, opener(blocked))
        r, d = sa.run(t, date(2026, 3, 1))
        assert d['coverage']['verified' if not blocked else 'provisional'] > 0
        assert d['coverage']['verified'] == r['measured_coverage']['verified_fields']
        assert not r['scenarios'] and d['archive'].startswith('attempted')
        assert all(v['origin'] == 'SEC' for v in r['packet']['companies']['MSFT']['observations'].values())


def test_cli_missing_identity_is_safe_and_writes_diagnostics(monkeypatch, tmp_path):
    monkeypatch.delenv('SEC_USER_AGENT', raising=False)
    assert sa.main(['--output', str(tmp_path / 'report')]) == 2
    d = json.loads((tmp_path / 'report.diagnostic.json').read_text())
    assert d['identity_status'] == 'missing' and d['requests'] == []
    assert (tmp_path / 'report.md').exists()
    assert not list(tmp_path.glob('*.sources.json'))


def test_manual_workflow_has_no_schedule_and_no_source_bodies():
    import yaml
    root = Path(__file__).resolve().parents[1]
    w = yaml.safe_load((root / '.github/workflows/sec-msft-diagnostic.yml').read_text())
    assert set(w.get('on', w.get(True))) == {'workflow_dispatch'}
    assert w['permissions'] == {'contents': 'read'}
    artifact = w['jobs']['diagnostic']['steps'][-1]['with']['path']
    assert 'sources' not in artifact and 'diagnostic.json' in artifact
