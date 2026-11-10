"""Fake bulk Yahoo frames; no live requests or trading/account modifications."""
import threading
from datetime import datetime, timedelta

import pandas as pd
import pytest

from stockwatch import universe_feed as u, paper_live, quick

NOW=datetime(2026,11,6,10,20,tzinfo=u.NY)


def daily():
    return pd.DataFrame({'Open':10.,'High':12.,'Low':9.,'Close':11.,'Volume':1_000_000.},
                        index=pd.bdate_range(end='2026-11-05',periods=30))


def minute():
    return pd.DataFrame({'Open':11.,'High':12.,'Low':10.,'Close':11.5,'Volume':1000.},
                        index=pd.date_range('2026-11-06 09:30',periods=50,freq='min',tz=u.NY))


class Fake:
    def __init__(self): self.calls=[]; self.bad={}; self.fail=False
    def __call__(self,group,interval):
        self.calls.append((list(group),interval))
        if self.fail: raise OSError('private exception contents')
        return {t:self.bad.get((t,interval),daily() if interval=='1d' else minute()).copy() for t in group}


def run(feed, tracked=(), now=NOW):
    done=threading.Event()
    work=feed._work
    def wrapped(at):
        try: work(at)
        finally: done.set()
    feed._work=wrapped
    assert feed.refresh(tracked,now)
    assert done.wait(5), 'fake refresh did not finish'
    feed._work=work


def test_bulk_batches_exclude_tracked_daily_cache_and_compatible_read_only_records():
    fake=Fake();clock=[NOW]
    names=[f'FICT{i}' for i in range(271)]
    f=u.Feed(universe=names,download=fake,clock=lambda:clock[0])
    run(f,tracked={'FICT0'})
    rows=f.snapshots(NOW)
    assert len(rows)==270 and f.stats['calls']==12
    assert all(len(group)<=50 for group,_ in fake.calls)
    assert all('FICT0' not in group for group,_ in fake.calls)
    row=rows[0]
    assert row['volume']==50_000 and row['vol_avg20']==1_000_000
    assert row['change']==pytest.approx(11.5/11-1) and row['atr']==3
    assert row['days_to_earnings'] is None and row['earnings_note']
    assert paper_live.fresh_price(row,NOW)==(11.5,'')
    assert quick.read_chart(row['chart'],row['price'],11,row['atr'])['span']==49
    assert len(row['bars'])==50
    rows[0]['payload']['quote']['live_price']=0
    rows[0]['bars'].iloc[0,0]=0
    assert f.snapshots(NOW)[0]['price']==11.5 and f.snapshots(NOW)[0]['bars'].iloc[0,0]==11
    clock[0]+=timedelta(seconds=60)
    run(f,tracked={'FICT0'},now=clock[0])
    assert f.stats['calls']==6 and [interval for _,interval in fake.calls[-6:]]==['1m']*6
    assert not f.refresh(set(),clock[0])   # refresh interval, not another download


@pytest.mark.parametrize('fault', ['missing_price','missing_volume','bad_average','no_daily','naive','old','future','negative_volume'])
def test_missing_or_stale_values_excluded_with_reason(fault):
    fake=Fake();d,m=daily(),minute()
    if fault=='missing_price': m.iloc[-1,m.columns.get_loc('Close')]=float('nan')
    if fault=='missing_volume': m.iloc[-1,m.columns.get_loc('Volume')]=float('nan')
    if fault=='bad_average': d.iloc[-1,d.columns.get_loc('Volume')]=float('nan')
    if fault=='no_daily': d=d.iloc[:0]
    if fault=='naive': m.index=m.index.tz_localize(None)
    if fault=='old': m.index-=timedelta(days=1)
    if fault=='future': m.index+=timedelta(days=1)
    if fault=='negative_volume': m.iloc[-1,m.columns.get_loc('Volume')]=-1
    fake.bad[('FICTA','1d')]=d;fake.bad[('FICTA','1m')]=m
    f=u.Feed(universe=['FICTA'],download=fake,clock=lambda:NOW)
    run(f)
    assert not f.snapshots(NOW) and f.records(NOW)[0]['why']


def test_configurable_price_and_average_volume_filters_keep_diagnostic_reason():
    fake=Fake()
    f=u.Feed(universe=['FICTA'],download=fake,clock=lambda:NOW,min_price=12,min_volume=2_000_000)
    run(f)
    r=f.records(NOW)[0]
    assert not r['eligible'] and any('feed minimum' in reason for reason in r['why'])
    assert not f.snapshots(NOW)


def test_freshness_session_expiry_and_failed_cycles_never_return_tradeable_old_data():
    fake=Fake();clock=[NOW]
    f=u.Feed(universe=['FICTA'],download=fake,clock=lambda:clock[0])
    assert not f.refresh([],NOW.replace(hour=8)) and not fake.calls
    run(f)
    assert not f.snapshots(NOW+timedelta(minutes=3))
    assert not f.snapshots(NOW.replace(hour=17))
    assert f.records(NOW+timedelta(minutes=3))[0]['why']
    fake.fail=True;clock[0]+=timedelta(seconds=60)
    run(f,now=clock[0])
    assert not f.snapshots(clock[0])
    assert f.stats['error']=='OSError' and 'private' not in str(f.stats)
    assert 'failed' in ' '.join(f.records(clock[0])[0]['why'])


def test_slow_download_is_nonblocking_no_overlap_and_cycle_is_discarded(monkeypatch):
    entered,release,finished=threading.Event(),threading.Event(),threading.Event()
    ticks=[0.]
    monkeypatch.setattr(u.time,'monotonic',lambda:ticks[0])
    def slow(group,interval):
        entered.set()
        assert release.wait(5)
        ticks[0]=30.
        return {t:daily() for t in group}
    f=u.Feed(universe=['FICTA'],download=slow,clock=lambda:NOW,max_seconds=20)
    work=f._work
    def wrap(at):
        try: work(at)
        finally: finished.set()
    f._work=wrap
    assert f.refresh([],NOW)
    assert entered.wait(2)
    assert f.snapshots(NOW)==[] and not f.refresh([],NOW+timedelta(minutes=2))
    release.set();assert finished.wait(2)
    assert not f.snapshots(NOW) and f.stats['error']=='TimeoutError'
    assert f.stats['calls']==1


def test_next_earnings_date_uses_future_cached_dates_without_treating_missing_as_zero():
    r=u._record('FICTA',daily(),minute(),NOW,{'FICTA':['2026-10-10','2026-11-09']},5,500_000)
    assert r['days_to_earnings']==3
    r=u._record('FICTA',daily(),minute(),NOW,{'FICTA':['2026-10-10']},5,500_000)
    assert r['days_to_earnings'] is None and r['eligible']
    r=u._record('FICTA',daily(),minute(),NOW,{'FICTA':['2026-11-06']},5,500_000)
    assert r['days_to_earnings']==0  # known today is a real zero


def test_default_yahoo_bulk_wrapper_disables_internal_threads_and_handles_single_and_multi(monkeypatch):
    import yfinance
    calls=[]
    def download(names,**kwargs):
        calls.append(kwargs)
        return pd.concat({t:minute() for t in names},axis=1)
    monkeypatch.setattr(yfinance,'download',download)
    assert len(u._download(['FICTA','FICTB'],'1m'))==2
    assert len(u._download(['FICTA'],'1m')['FICTA'])==50
    assert all(c['threads'] is False and c['timeout']==5 and c['prepost'] is False for c in calls)
