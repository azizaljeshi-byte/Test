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
    monkeypatch.setattr(ts.simplecall,'of',lambda s:{'word':'Sell','group':'sell','cls':'act','why':'w','sure':(4,6),'fund':50.0,'fund_word':'Fair','line':316.6})
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


def test_escaped_navigation_and_notes_and_only_one_call_is_shown():
    s=snap();s['ticker']='FICT<"&';s['payload']['name']='<script>name</script>'
    s['payload']['technical']['one_call']['call']='ADD'
    h=ts.detail_header(s)
    assert '<script>' not in h and '&lt;script&gt;' in h
    assert 'ADD' in h and 'disagree' not in h and 'ACT' not in h and 'New call' not in h
    assert 't=FICT%3C%22%26' in ts.chips([s['ticker']],s['ticker'])


def test_radar_shows_the_one_call_in_plain_words_and_unknown_stays_unknown():
    for call,label in [('EXIT','Sell'),('AVOID','Avoid'),('ON THE LINE','On the line'),('WAIT FOR TURN','Watch'),('BUY','Buy'),('ADD','Add'),('HOLD','Hold'),('WAIT','Wait')]:
        s=snap();s['payload']['technical']['one_call']['call']=call
        assert f'>{label}</span>' in ts.radar_rows([s])
    s=snap();s['payload']['technical']['one_call']={'known':False,'call':'UNKNOWN','why':'not enough history'}
    h=ts.radar_rows([s])
    assert '>No call</span>' in h and 'not enough history' in h


def test_the_fundamentals_number_is_guidance_and_never_changes_the_call():
    lo=snap();lo['fundamental_score']=10.0
    hi=snap();hi['fundamental_score']=95.0
    a,b=ts.simplecall.of(lo),ts.simplecall.of(hi)
    assert a['word']==b['word'] and a['why']==b['why']
    assert '10/100' in ts.radar_rows([lo]) and '95/100' in ts.radar_rows([hi]) and 'guidance only' in ts.radar_rows([hi])
    un=snap();un['fundamental_score']=None
    assert 'Fundamentals: unknown' in ts.radar_rows([un]) and '0/100' not in ts.radar_rows([un])


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
    brief={'headline':'X needs attention now','why':['Risk: saved warning','Opportunity: <script>x</script>'],
           'changed':['First scan'],'watch':['A daily close below the exit line']}
    h=details.tape_brief_html(brief)
    assert all(text in h for text in [*brief['why'][:1],*brief['changed'],*brief['watch']])
    assert '<script>' not in h and '&lt;script&gt;' in h
    assert 'needs attention now' not in h                      # one call on the page: the old headline is not repeated
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
    monkeypatch.setattr(ts.ui,'price_parts',lambda s:{'price':32.5,'day':0.071,'live':'','ext':('AH',32.55,0.008),'note':''})
    h=ts.radar_rows([snap()])
    assert '$32.50' in h and '+7.1%' in h and 'AH $32.55' in h and '+0.8%' in h
    monkeypatch.setattr(ts.ui,'price_parts',lambda s:{'price':None,'day':None,'live':'','ext':None,'note':'AH no trades yet'})
    h=ts.radar_rows([snap()])
    assert 'unknown' in h and 'n/a' in h and 'AH no trades yet' in h and '$0.00' not in h
