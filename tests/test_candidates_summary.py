"""Read-only candidate outcome summaries: real zeros count, missing readings do not."""
import copy

import pytest

from stockwatch import candidates


def test_empty_and_entirely_unknown_rows_never_invent_zero_performance():
    for rows in ([], [{}, {'p60':None,'close_pct':None}]):
        s=candidates.summary(rows)
        assert s['rows']==len(rows) and s['p60_count']==s['close_count']==0
        assert s['p60_up_share'] is None and s['p60_average'] is None and s['close_average'] is None


def test_each_metric_uses_only_its_own_known_outcomes_and_does_not_mutate_rows():
    rows=[{'p60':4.,'close_pct':None},{'p60':-2.,'close_pct':3.},
          {'p60':None,'close_pct':-1.},{'p60':0.0},{}]
    original=copy.deepcopy(rows)
    s=candidates.summary(rows)
    assert rows==original
    assert s['rows']==5 and s['p60_count']==3 and s['close_count']==2
    assert s['p60_up_share']==pytest.approx(1/3)
    assert s['p60_average']==pytest.approx(2/3) and s['close_average']==1.


def test_a_measured_flat_or_negative_return_is_not_unknown_or_up():
    s=candidates.summary([{'p60':0.,'close_pct':0.},{'p60':-2.,'close_pct':-4.}])
    assert s['p60_count']==s['close_count']==2
    assert s['p60_up_share']==0. and s['p60_average']==-1. and s['close_average']==-2.
    assert candidates.summary([{'p60':2.}])['p60_up_share']==1.


def test_invalid_nonfinite_and_boolean_readings_do_not_inflate_denominators():
    rows=[{'p60':v,'close_pct':v} for v in (None,float('nan'),float('inf'),-float('inf'),True,False,'2')]
    s=candidates.summary(rows+[{'p60':2.,'close_pct':-3.}])
    assert s['rows']==8 and s['p60_count']==s['close_count']==1
    assert s['p60_up_share']==1. and s['p60_average']==2. and s['close_average']==-3.
