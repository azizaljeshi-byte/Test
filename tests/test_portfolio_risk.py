"""Invented positions and deterministic bars only. Never read private config."""
import ast
import copy
from datetime import timedelta
import json
from pathlib import Path

import pytest
import yaml

from stockwatch import portfolio_risk as pr


def report():
    p,c,now=pr.demo()
    return pr.build(p,c,now)


def test_values_weights_cash_tiers_watchlist_and_scenarios():
    r=report();s=r['summary'];a,b,w=r['positions']
    assert s['usable_positions']==2 and s['watchlist_positions']==1
    assert s['equity_value']==pytest.approx(a['market_value']+b['market_value'])
    assert s['nav']==pytest.approx(s['equity_value']+500)
    assert sum(x['weight'] for x in (a,b))+s['cash_weight']==pytest.approx(1)
    assert s['unrealized_pl']==pytest.approx(s['equity_value']-1350)
    assert w['market_value'] is None and w['weight'] is None and not w['held']
    assert a['tier']==1 and b['tier']==2
    assert r['scenarios'][0]['dollar_change']==pytest.approx(-.1*s['equity_value'])
    assert r['scenarios'][0]['nav_change_fraction']==pytest.approx(-.1*s['equity_value']/s['nav'])
    assert s['portfolio_drawdown'] is None
    assert a['technical']['drawdown_from_window_peak']<=0
    assert all(x['analogue_probability'] is None and x['financial_evidence']['status']=='unavailable' for x in r['positions'])


@pytest.mark.parametrize('mode',['duplicate','negative','missing_shares','missing_basis','nan','bool','tier','currency','overflow','empty','watch_only'])
def test_invalid_private_positions_fail_closed_without_leak(mode):
    p,_,_=pr.demo()
    if mode=='duplicate':p['holdings'].append({**p['holdings'][0],'ticker':'syntha'})
    if mode=='negative':p['holdings'][0]['shares']=-1
    if mode=='missing_shares':del p['holdings'][0]['shares']
    if mode=='missing_basis':del p['holdings'][0]['cost_basis']
    if mode=='nan':p['holdings'][0]['shares']=float('nan')
    if mode=='bool':p['holdings'][0]['shares']=True
    if mode=='tier':p['holdings'][0]['tier']=3
    if mode=='currency':p['currency']='EUR'
    if mode=='overflow':p['holdings'][0].update(shares=1e308,cost_basis=1e308)
    if mode=='empty':p['holdings']=[]
    if mode=='watch_only':p['holdings']=[p['holdings'][-1]]
    with pytest.raises(pr.PrivateInputError) as e:
        pr.parse_portfolio(yaml.safe_dump(p))
    assert 'SYNTHA' not in str(e.value)


@pytest.mark.parametrize('mode',['missing','stale','future_capture','future_bar','negative','nan','wrong_currency','adjustment','duplicate','unsorted','gap','bad_ohlc'])
def test_invalid_or_partial_quotes_block_totals_not_zero(mode):
    p,c,now=pr.demo();r=c['SYNTHA']
    if mode=='missing':c.pop('SYNTHA')
    if mode=='stale':now+=timedelta(days=8)
    if mode=='future_capture':r['captured_at']=(now+timedelta(days=1)).isoformat()
    if mode=='future_bar':r['bars'][-1]['date']='2026-10-23'
    if mode=='negative':r['bars'][-1]['raw_close']=-1
    if mode=='nan':r['bars'][-1]['close']=float('nan')
    if mode=='wrong_currency':r['currency']='EUR'
    if mode=='adjustment':r['basis']='adjusted_close'
    if mode=='duplicate':r['bars'].append(r['bars'][-1])
    if mode=='unsorted':r['bars'].reverse()
    if mode=='gap':r['bars'][100:115]=[]
    if mode=='bad_ohlc':r['bars'][-1]['high']=1
    result=pr.build(p,c,now);s=result['summary']
    assert s['status']=='INSUFFICIENT EVIDENCE'
    assert s['equity_value'] is None and s['nav'] is None and s['unrealized_pl'] is None
    assert not result['scenarios'] and not result['sector_exposure']
    assert all(x['weight'] is None for x in result['positions'])
    assert result['positions'][0]['flag']=='review'


def test_different_quote_dates_do_not_create_false_precise_portfolio():
    p,c,now=pr.demo();c['SYNTHB']['bars'].pop()
    s=pr.build(p,c,now)['summary']
    assert s['usable_positions']==2 and len(s['quote_dates'])==2
    assert s['equity_value'] is None


def test_cash_unknown_not_zero_and_watchlist_outage_does_not_block_held():
    p,c,now=pr.demo();p['cash']=None;c.pop('SYNTHW')
    r=pr.build(p,c,now);s=r['summary']
    assert s['equity_value']>0 and s['cash'] is None and s['nav'] is None and s['cash_weight'] is None
    assert sum(x['weight'] or 0 for x in r['positions'])==pytest.approx(1)
    assert 'cash unknown' in r['positions'][0]['weight_basis']
    assert r['positions'][-1]['flag']=='review'


def test_benchmark_outage_blocks_market_lens_not_position_arithmetic():
    p,c,now=pr.demo();c.pop('SPY')
    r=pr.build(p,c,now)
    assert r['market_stress']['status']=='unavailable'
    assert r['summary']['equity_value']>0
    assert 'correlation_spy' not in r['positions'][0]


def test_reproducible_flags_correlation_and_countertrend():
    p,c,now=pr.demo()
    first=pr.build(p,c,now)
    assert first==pr.build(copy.deepcopy(p),copy.deepcopy(c),now)
    assert first['positions'][0]['flag']=='reduce-review'
    assert first['positions'][0]['counter_trend_strength']
    assert first['positions'][1]['technical']['trend']=='down'
    assert first['pair_correlations'][0]['observations']==60
    assert first['sector_exposure'][0]['sector']=='Synthetic sector'


def test_unknown_sector_and_constant_correlation():
    p,c,now=pr.demo();p['holdings'][0]['sector']=None
    for r in c['SYNTHA']['bars']:
        r.update(raw_close=100,open=100,high=101,low=99,close=100)
    result=pr.build(p,c,now)
    assert any(r['sector']=='Unknown' for r in result['sector_exposure'])
    assert result['pair_correlations'][0]['value'] is None


def test_html_escapes_private_labels_and_has_no_external_assets():
    r=report();r['positions'][0]['sector']='<script>attack()</script>'
    r['positions'][0]['reasons'].append('<script>attack()</script>')
    text=pr.render(r)
    assert '<script>' not in text and '&lt;script&gt;' in text
    assert 'Content-Security-Policy' in text and 'SYNTHETIC DEMO' in text
    assert '<script src' not in text and '<link ' not in text


def test_private_output_permissions_checkout_guard_and_no_overwrite(tmp_path):
    r=report();p,c,now=pr.demo();out=tmp_path/'private'
    pr.write_private(out,r,c)
    assert out.stat().st_mode&0o777==0o700
    assert all(f.stat().st_mode&0o777==0o600 for f in out.iterdir())
    snap=json.loads((out/'capture.json').read_text())
    assert snap['as_of']==now.isoformat() and pr.build(p,snap['captures'],pr.instant(snap['as_of']))==r
    with pytest.raises(FileExistsError):pr.write_private(out,r,c)
    checkout=tmp_path/'checkout';checkout.mkdir();(checkout/'.git').touch()
    with pytest.raises(pr.PrivateInputError):pr.write_private(checkout/'output',r,c)
    link=tmp_path/'link';link.symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(pr.PrivateInputError):pr.write_private(link/'escape',r,c)


def test_cli_never_reads_private_config_in_demo_and_never_logs_holdings(tmp_path,monkeypatch,capsys):
    monkeypatch.delenv('CI',raising=False);monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
    monkeypatch.setenv('STOCKWATCH_PORTFOLIO','PRIVATE-SECRET-SENTINEL')
    monkeypatch.setattr(pr,'live_capture',lambda ticker:pytest.fail('network'))
    assert pr.main(['--demo','--output',str(tmp_path/'demo')])==0
    assert 'PRIVATE-SECRET' not in capsys.readouterr().out
    assert pr.main(['--output',str(tmp_path/'invalid')])==1
    captured=capsys.readouterr()
    assert 'PRIVATE-SECRET' not in captured.err and 'SYNTH' not in captured.err


def test_cli_ci_and_missing_config_no_example_fallback(tmp_path,monkeypatch,capsys):
    monkeypatch.setenv('CI','true')
    assert pr.main(['--demo','--output',str(tmp_path/'ci')])==1
    assert not (tmp_path/'ci').exists()
    monkeypatch.delenv('CI');monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
    monkeypatch.delenv('STOCKWATCH_PORTFOLIO',raising=False)
    assert pr.main(['--output',str(tmp_path/'missing')])==1
    assert not (tmp_path/'missing').exists()


def test_cli_replay_network_free(tmp_path,monkeypatch):
    monkeypatch.delenv('CI',raising=False);monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
    p,c,now=pr.demo();source=tmp_path/'source';pr.write_private(source,pr.build(p,c,now),c)
    config=tmp_path/'positions.yaml';config.write_text(yaml.safe_dump(p))
    monkeypatch.setattr(pr,'live_capture',lambda t:pytest.fail('network'))
    assert pr.main(['--portfolio',str(config),'--replay',str(source/'capture.json'),'--output',str(tmp_path/'replayed')])==0
    assert json.loads((source/'report.json').read_text())==json.loads((tmp_path/'replayed'/'report.json').read_text())


def test_runner_isolation():
    root=Path(__file__).resolve().parents[1]
    forbidden={'scanner','engine','notify','live','store','tradeplan','signals','config','ui','research_lab'}
    tree=ast.parse((root/'stockwatch/portfolio_risk.py').read_text())
    imports={n.module.split('.')[-1] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.module}
    assert not imports&forbidden
    for path in [root/'dashboard.py',*(root/'stockwatch').glob('*.py')]:
        if path.name=='portfolio_risk.py':continue
        assert 'portfolio_risk' not in path.read_text()


def test_live_collection_end_asof_privacy_and_partial_failure(tmp_path,monkeypatch,capsys):
    import logging
    from datetime import datetime
    p,c,now=pr.demo()
    # Use a historical local clock for freshness, with captures produced after collection begins.
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return now+timedelta(seconds=2)
    monkeypatch.setattr(pr,'datetime',Clock)
    monkeypatch.delenv('CI',raising=False);monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
    monkeypatch.setenv('STOCKWATCH_PORTFOLIO',yaml.safe_dump(p))
    def fetch(ticker):
        print('PRIVATE SENTINEL position')
        logging.error('PRIVATE SENTINEL provider failure')
        if ticker=='SYNTHB':raise ValueError('PRIVATE SENTINEL shares')
        record=copy.deepcopy(c[ticker]);record['captured_at']=(now+timedelta(seconds=1)).isoformat()
        return record
    monkeypatch.setattr(pr,'live_capture',fetch)
    assert pr.main(['--output',str(tmp_path/'live-fake')])==0
    streams=capsys.readouterr()
    assert 'SENTINEL' not in streams.out+streams.err
    result=json.loads((tmp_path/'live-fake/report.json').read_text())
    assert result['summary']['usable_positions']==1 and result['summary']['equity_value'] is None
    assert result['positions'][0]['quote']['status']=='usable'


def test_correlation_refuses_different_return_intervals():
    _,c,now=pr.demo()
    a=pr.series_frame(c['SYNTHA'],now);b=pr.series_frame(c['SYNTHB'],now)
    b=b.drop(b.index[-5])
    assert pr.correlation(a,b)['value'] is None
