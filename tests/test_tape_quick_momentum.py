"""Pure Tape rendering; invented ticks, hand-made saved paths, no live account."""
import copy
from datetime import datetime

import pytest

from stockwatch import quick, quick_view as q, rising_view as r
from stockwatch.data import NY

NOW=datetime(2026,11,9,12,tzinfo=NY)


def trade(**kwargs):
    return dict({'ticker':'FICTA','opened':'2026-11-09 10:00','closed':'2026-11-09 11:00',
                 'status':'CLOSED','entry':100.,'exit':102.,'stop0':98.,'shares':10.,'result':20.,'pct':2.,
                 'exit_reason':'stop hit','signal':101.,'pullback_low':99.,'rank':1,'of':4},**kwargs)


def book():
    b=quick.new_book()
    b['trades']=[trade(),trade(ticker='FICTB',result=-10,pct=-1),trade(ticker='FICTC',result=0,pct=0),
                 trade(closed='2026-11-08 11:00',result=200)]
    b['positions']={'FICTD':{'entry':50.,'shares':2}}
    return b


def test_day_total_matches_existing_definition_on_known_values_and_win_denominator():
    b=book();original=copy.deepcopy(b)
    summary=q.day_summary(b,{'FICTD':52},NOW)
    assert summary['total']==quick.day_result(b,{'FICTD':52},NOW)==14
    assert summary['closed']==summary['known']==3
    assert summary['win_share']==pytest.approx(1/3)
    assert b==original


@pytest.mark.parametrize('bad',[None,True,float('nan'),float('inf'),0])
def test_missing_live_price_does_not_assume_entry_or_zero(bad):
    summary=q.day_summary(book(),{'FICTD':bad},NOW)
    assert summary['total'] is None and summary['unknown']==1
    assert 'day total unavailable' in q.parts({'book':book()}, {'FICTD':bad},NOW)[0]


def test_unknown_closed_result_or_date_and_no_measured_wins_remain_unknown():
    b=quick.new_book();b['trades']=[trade(result=None)]
    summary=q.day_summary(b,{},NOW)
    assert summary['total'] is None and summary['known']==0 and summary['win_share'] is None
    b['trades']=[trade(closed=None)]
    assert q.day_summary(b,{},NOW)['total'] is None
    assert q.day_summary({}, {},NOW)['total'] is None
    assert q.day_summary(quick.new_book(),{},NOW)['total']==0  # genuinely empty known account


def test_saved_pullback_low_distinguishes_waiting_for_dip_from_waiting_for_turn():
    b=quick.new_book()
    b['watch']={'FICTA':{'p0':100.,'pull_lo':98.},'FICTB':{'p0':20.,'pull_lo':None}}
    h=q.html({'book':b},now=NOW)
    assert h.index('day total')<h.index('Waiting for a pullback')<h.index('Open now')<h.index('Closed</h3>')
    assert 'Dipped, waiting for the turn' in h and 'Waiting for a dip' in h and 'Pullback low unknown' in h
    assert h.index('FICTA')<h.index('Dipped, waiting for the turn')<h.index('FICTB')<h.index('Waiting for a dip')
    assert 'Turning up' not in h and 'Not yet' not in h
    assert '<svg' not in h


def test_trade_row_uses_no_picture_without_a_path_and_escapes_all_text():
    h=q.trade_row(trade(ticker='FICT<"&',exit_reason='<script>x</script>'))
    assert '<svg' not in h and '<script>' not in h
    assert 'FICT&lt;&quot;&amp;' in h and '&lt;script&gt;' in h
    assert 't=FICT%3C%22%26' in h
    h=q.trade_row({'ticker':'FICTA','status':'CLOSED'})
    assert 'unknown' in h and '$0.00' not in h and '+0.0%' not in h


def test_saved_path_dots_and_dashed_stop_are_on_one_price_scale_without_input_mutation():
    t=trade(path=[['2026-11-09T10:00:00-05:00',100.],['2026-11-09T10:30:00-05:00',101.],['2026-11-09T11:00:00-05:00',102.]])
    original=copy.deepcopy(t)
    h=q.price_path(t)
    assert '<svg' in h and h.count('<circle')==2 and 'stroke-dasharray="3 3"' in h
    assert 'points="4.00,20.00 60.00,12.50 116.00,5.00"' in h
    assert 'cy="20.00"' in h and 'cy="5.00"' in h and 'y1="35.00"' in h
    assert t==original
    # Out-of-window/missing event times do not become dots at an invented index.
    assert q.price_path({**t,'opened':'2026-11-08 10:00','closed':None}).count('<circle')==0


@pytest.mark.parametrize('path',[None,[],[[1,100]],[[2,100],[1,101]],[[1,100],[2,None]],[[1,100],[2,float('nan')]],'<script>'])
def test_missing_or_invalid_path_never_creates_a_sparkline(path):
    assert q.price_path(trade(path=path))==''


def test_open_trade_uses_current_position_entry_and_keeps_manual_sale_tags():
    t=trade(status='OPEN',entry=90.,result=0,pct=None)
    h=q.trade_row(t,{'entry':100.,'shares':2},105.)
    assert '+$10.00' in h and '+5.0%' in h
    assert 'SOLD BY HAND' in q.trade_row(trade(exit_reason='owner override: sold by hand'))


def momentum(**changes):
    return dict({'t':'FICTA','chg':3.4,'vol_x':2.1,'rsi_d':1.,'hist_d':.2,'tracked':True,'tag':'NEW'},**changes)


def test_momentum_compact_move_volume_and_reason_do_not_invent_chart_events():
    h=r.table([momentum()])
    assert '+3.4%' in h and '2.1× normal' in h and 'RSI rising; MACD improving.' in h
    assert 'New high' not in h and '<details>' in h and 'yours' in h
    assert 'Waiting: volume unknown' in r.table([momentum(miss='volume unknown')])
    assert 'Price and momentum fell since the previous run.' in r.table([momentum(tag='FADING')])
    assert 'unknown' in r.table([{'t':'FICTA'}]) and 'unknown stocks' in r.headline({})
    assert '3 stocks building momentum' in r.headline({'pass':3,'at':NOW.isoformat()})


def test_momentum_escapes_names_notes_and_encodes_query_values_without_mutation():
    row=momentum(t='FICT<&"',miss='<script>x</script>');before=copy.deepcopy(row)
    h=r.table([row])
    assert '<script>' not in h and 'FICT&lt;&amp;&quot;' in h and 't=FICT%3C%26%22' in h
    assert row==before and r.stamp({})=='unknown time'



def test_current_owned_trade_watch_failure_is_visible_and_all_skip_reasons_remain_available():
    b=book()
    top,_,rest=q.parts({'book':b,'state':{'skipped':{'FICTD':'price unknown: open trade is NOT being watched',
                                                  'FICTE':'<script>no price</script>'}}}, {},NOW)
    assert 'open trade is NOT being watched' in top
    assert 'FICTE' in rest and '&lt;script&gt;' in rest and '<script>' not in rest
