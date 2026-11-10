"""Handmade snapshots only; no price feeds, holdings or account integration."""
import copy

import pytest

from stockwatch import valuation_screen as v


def snap(mid=120, analyst=115, score=80):
    return {'ticker':'FICTA', 'price':100., 'fundamental_score':score, 'payload':{
        'fundamental':{'available':True, 'analyst_upside':analyst / 100 - 1,
                       **{'pillar_'+p:60. for p in v.PILLARS}},
        'research':{'valuation':{'fair_value':{'mid':mid, 'methods':{
            'analysts':{'mid':analyst}, 'own history':{'mid':mid}}}}}}}


@pytest.mark.parametrize('mid,target,label', [(115,110,'undervalued'),(85,90,'overvalued'),
    (120,80,'fair'),(80,120,'fair'),(100,100,'fair'),(114,110,'fair'),(85,91,'fair')])
def test_thresholds_and_conflicting_estimates(mid,target,label):
    r=v.reading(snap(mid,target),100)
    assert r['label']==label and r['methods']==2
    assert r['fair_gap']==pytest.approx(mid/100-1)
    assert r['analyst_gap']==pytest.approx(target/100-1)


def test_reprice_both_estimates_and_reconstruct_target_from_saved_ratio():
    s=snap()
    del s['payload']['research']['valuation']['fair_value']['methods']['analysts']
    s['payload']['research']['valuation']['fair_value']['methods']['peer multiple']={'mid':125}
    r=v.reading(s,200)
    assert r['label']=='overvalued' and r['analyst_gap']==pytest.approx(115/200-1)
    del s['price']
    assert v.reading(s,200)['label']=='unknown'


@pytest.mark.parametrize('bad',[None,True,float('nan'),float('inf'),0,-2,'100'])
def test_unknown_invalid_price_and_fair_value(bad):
    s=snap()
    assert v.reading(s,bad)['label']=='unknown'
    s['payload']['research']['valuation']['fair_value']['mid']=bad
    assert v.reading(s,100)['label']=='unknown'


def test_method_names_without_valid_values_are_not_evidence_and_missing_target_not_zero():
    s=snap()
    fv=s['payload']['research']['valuation']['fair_value']
    fv['methods']={'empty':{},'analysts':{'mid':None},'own history':{'mid':120}}
    s['payload']['fundamental']['analyst_upside']=None
    r=v.reading(s,100)
    assert r['label']=='unknown' and r['methods']==1 and r['analyst_gap'] is None
    assert 'Analyst target is unknown' in r['why']
    assert v.reading({},100)['fair_gap'] is None


def test_fundamentals_unknown_score_availability_and_optional_pillar_floor():
    assert v.very_strong(snap(score=75))[0]
    assert not v.very_strong(snap(score=74.9))[0]
    for score in (None,True,float('nan'),float('inf'),101,-1):
        assert not v.very_strong(snap(score=score))[0]
    s=snap();s['payload']['fundamental']['available']=False
    assert not v.very_strong(s)[0]
    s=snap();s['payload']['fundamental']['pillar_balance']=0
    assert v.very_strong(s)[0] and not v.very_strong(s,pillar_floor=50)[0]
    s['payload']['fundamental']['pillar_balance']=None
    assert 'unknown' in v.very_strong(s,pillar_floor=50)[1]


def test_audit_is_pure_aggregate_and_reports_sensitivity_without_mutation():
    rows=[snap(),snap(80,85),snap(100,100),{}]
    original=copy.deepcopy(rows)
    a=v.audit(rows)
    assert a['stocks']==4 and a['undervalued']==a['overvalued']==a['fair']==a['unknown']==1
    assert a['cheap_and_strong']==1 and a['very_strong']==3
    assert 'FICTA' not in str(a) and rows==original


def test_read_only_database_audit_uses_latest_per_stock_and_never_prints_symbols(tmp_path):
    import json
    import sqlite3
    from scripts.valuation_screen_audit import report
    path=tmp_path/'private.sqlite'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE snapshots (id INTEGER PRIMARY KEY,ticker TEXT,price REAL,fundamental_score REAL,payload TEXT)')
        for i,s in enumerate([snap(80,85),snap()],1):
            c.execute('INSERT INTO snapshots VALUES (?,?,?,?,?)',(i,'FICTA',s['price'],s['fundamental_score'],json.dumps(s['payload'])))
    before=path.read_bytes()
    result=report(path)
    assert result['stocks']==result['undervalued']==1 and 'FICTA' not in str(result)
    assert path.read_bytes()==before
    with pytest.raises(sqlite3.OperationalError):
        report(tmp_path/'absent.sqlite')
    assert not (tmp_path/'absent.sqlite').exists()


def test_overflow_is_unknown_and_method_disagreement_is_audit_only():
    s=snap(mid=1e308,analyst=115)
    r=v.reading(s,1e-310)
    assert r['label']=='unknown' and r['fair_gap'] is None and r['analyst_gap'] is None
    s=snap()
    s['payload']['research']['valuation']['fair_value']['methods']['own history']['mid']=500
    assert v.audit([s])['method_mid_spread_over2x']==1
