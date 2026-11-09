"""Tape screen composition from hand-made readings; no scoring/trading changes."""
import copy

from stockwatch import tape_screens as ts, tradelevels, stockhead, portfolio_view, portfolio
from test_stockhead import snap as stock_snap


def snap():
    s=stock_snap();s['ticker']='FICTA';s['payload']['name']='Invented company'
    return s


def test_ladder_is_proportional_staggered_and_does_not_mutate_source():
    rows=[{'label':'Now','level':100.,'tone':'now','note':''},
          {'label':'Exit line','level':99.,'tone':'exit','note':'Daily close'},
          {'label':'Plan stop','level':90.,'tone':'exit','note':'Hard stop'}]
    before=copy.deepcopy(rows)
    layout=tradelevels.scaled_layout(rows,340)
    assert [x['level'] for x in layout]==[100,99,90]
    assert layout[1]['y']-layout[0]['y']==30
    assert layout[2]['y']-layout[0]['y']==300
    assert layout[1]['label_y']-layout[0]['label_y']>30
    assert rows==before
    h=tradelevels.scaled_html(rows,100)
    assert 'Chart exit (Exit line)' in h and 'Plan stop' in h and 'drawn to scale' in h


def test_coincident_and_missing_levels_do_not_get_invented_or_drawn_at_zero():
    rows=[{'label':'Price','level':100.,'tone':'now'},{'label':'Support','level':100.,'tone':'mid'}]
    layout=tradelevels.scaled_layout(rows)
    assert layout[0]['y']==layout[1]['y'] and layout[0]['label_y']!=layout[1]['label_y']
    for value in (None,False,0,float('inf'),float('nan')):
        assert tradelevels.scaled_layout([{'label':'Unknown','level':value}])==[]
    assert 'Levels unknown' in tradelevels.scaled_html([])


def test_detail_uses_existing_levels_and_keeps_variable_agreement_denominator(monkeypatch):
    s=snap();before=copy.deepcopy(s)
    monkeypatch.setattr(ts.dayboard,'assess',lambda s:{'word':'ACT','sell_side':True,'sure':(4,6),'why':None,'held_buy':False})
    h=ts.detail_header(s)
    assert '4 of 6 checks agree' in h and h.count('<i')==6
    ladder=ts.detail_ladder(s)
    for row in stockhead.ladder(s):
        assert f'{row["level"]:,.2f}' in ladder
    assert s==before


def test_unknown_fundamentals_never_become_zero_or_crash():
    s=snap();s['fundamental_score']=None;s['payload']['fundamental']={'available':False}
    h=ts.detail_tables(s)
    assert 'Fundamentals score' in h and 'unknown' in h and '0 / 100' not in h
    assert 'Plan stop' in h and 'Your plan' in h and 'Chart' in h and 'Company' in h and 'News' in h


def test_escaped_navigation_and_notes_and_reconciled_clash_warning(monkeypatch):
    s=snap();s['ticker']='FICT<"&';s['payload']['name']='<script>name</script>'
    monkeypatch.setattr(ts.dayboard,'assess',lambda s:{'word':'ACT','sell_side':True,'sure':None,'why':'unknown','held_buy':False})
    s['payload']['technical']['one_call']['call']='BUY'
    h=ts.detail_header(s)
    assert 'The two calls disagree' in h and 'Do not buy' in h
    assert '<script>' not in h and '&lt;script&gt;' in h
    assert 't=FICT%3C%22%26' in ts.chips([s['ticker']],s['ticker'])


def test_radar_preserves_unknown_and_watch_instead_of_labelling_everything_hold(monkeypatch):
    for word,label in [('ACT','Act'),('BUY','Buy zone'),('CALM','Hold'),('WATCH','Watch'),('UNCLEAR','Unclear')]:
        s=snap()
        monkeypatch.setattr(ts.dayboard,'assess',lambda s,w=word:{'word':w,'sell_side':False,'sure':None,'why':'unknown','held_buy':False,'checks':[]})
        monkeypatch.setattr(ts.dayboard,'_why',lambda *a:'Saved explanation')
        assert f'>{label}</span>' in ts.radar_rows([s])


def test_portfolio_total_with_missing_quote_is_unknown_and_critical_warnings_remain():
    b=portfolio.new_book();b['seeded']='2026-11-08 10:00'
    b['positions']={'FICTA':{'shares':10.,'entry':100.,'base':10.,'source':'holding','opened':'2026-11-08 10:00','stop':95.}}
    before=copy.deepcopy(b)
    top,opens,rest=portfolio_view.parts({'book':b,'state':{}},{})
    assert 'total value' in top and 'total value and result are unknown' in top
    assert 'Broker stops set' in top and 'NO BROKER STOP' in opens[0][1]
    assert 'unknown' in opens[0][1] and 'pf-tape-result' in opens[0][1]
    assert 'Suggested adds' in rest and b==before


def test_compact_brief_preserves_all_saved_warnings_and_escapes_text():
    from stockwatch import details
    brief={'headline':'<script>headline</script>','why':['Risk: saved warning','Opportunity: saved upside'],
           'changed':['First scan'],'watch':['A daily close below the exit line']}
    h=details.tape_brief_html(brief)
    assert all(text in h for text in [*brief['why'],*brief['changed'],*brief['watch']])
    assert '<script>' not in h and '&lt;script&gt;' in h
    assert 'WHY' in h and 'CHANGED' in h and 'WATCH NEXT' in h


def test_radar_unknown_coverage_does_not_claim_clear_readings_or_known_earnings():
    rows=[{'verdict':'ERROR','payload':{'error':'feed blocked','events':{}}}]
    h=ts.radar_summary(rows,'NO SIGNAL',[],[],[],'<script>benchmark unavailable</script>')
    assert 'Readings incomplete' in h and 'Nothing urgent' not in h
    assert '<script>' not in h and 'benchmark unavailable' in h and 'unknown' in h


def test_suggested_add_card_uses_only_saved_suggestion_and_keeps_its_note():
    b=portfolio.new_book();b['seeded']='2026-11-08 10:00'
    suggestion={'ticker':'FICTB','price':100.,'fund':80.,'zone':[90.,95.],'stop':85.,'target':110.,'note':'Saved note <b>only</b>'}
    _,_,rest=portfolio_view.parts({'book':b,'state':{'suggested':[suggestion]}},{})
    assert 'Suggested adds' in rest and 'FICTB' in rest and '90.00 to 95.00' in rest
    assert '&lt;b&gt;only&lt;/b&gt;' in rest and '<b>only</b>' not in rest


def test_radar_retains_holdings_before_watchlist_even_when_watchlist_is_urgent(monkeypatch):
    held=snap();held['ticker']='FICTH';held['payload']['watchlist']=False
    watch=snap();watch['ticker']='FICTW';watch['payload']['watchlist']=True
    monkeypatch.setattr(ts.ui,'_ring_sort',lambda s:0 if s['ticker']=='FICTW' else 2)
    h=ts.radar_rows([watch,held])
    assert h.index('FICTH')<h.index('FICTW')


def test_radar_rows_show_the_price_the_day_change_and_after_hours_or_unknown(monkeypatch):
    monkeypatch.setattr(ts.dayboard,'assess',lambda s:{'word':'CALM','sell_side':False,'sure':None,'why':'unknown','held_buy':False,'checks':[]})
    monkeypatch.setattr(ts.dayboard,'_why',lambda *a:'Saved explanation')
    monkeypatch.setattr(ts.ui,'price_parts',lambda s:{'price':32.5,'day':0.071,'live':'','ext':('AH',32.55,0.008),'note':''})
    h=ts.radar_rows([snap()])
    assert '$32.50' in h and '+7.1%' in h and 'AH $32.55' in h and '+0.8%' in h
    monkeypatch.setattr(ts.ui,'price_parts',lambda s:{'price':None,'day':None,'live':'','ext':None,'note':'AH no trades yet'})
    h=ts.radar_rows([snap()])
    assert 'unknown' in h and 'n/a' in h and 'AH no trades yet' in h and '$0.00' not in h
