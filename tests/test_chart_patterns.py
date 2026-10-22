from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stockwatch import chart_patterns as cp


def prices(n=1800, seed=42):
    rng = np.random.default_rng(seed)
    close = 100*np.exp(np.cumsum(rng.normal(.0003, .012, n)))
    opening = close*np.exp(rng.normal(0, .002, n))
    return pd.DataFrame({'Open': opening, 'High': np.maximum(opening, close)*1.01,
                         'Low': np.minimum(opening, close)*.99, 'Close': close,
                         'Volume': rng.integers(10000, 50000, n)}, index=pd.bdate_range('2000-01-03', periods=n))


def settings(**kwargs):
    return cp.Settings(windows=(20,), horizons=(5, 20), min_matches=1, max_distance=10, **kwargs)


def test_exact_shape_and_scale_invariance():
    f = prices(200)
    bad = np.zeros(len(f), dtype=bool)
    a = cp.features(f, 150, 20, 100, bad)
    scaled = f.copy()
    scaled.iloc[:, :4] *= 3
    scaled.Volume *= 2
    b = cp.features(scaled, 150, 20, 100, bad)
    assert cp.distance(a, b)['distance'] == pytest.approx(0, abs=1e-12)
    assert cp.distance(a, a)['distance'] == 0
    b['volume'] = b['volume']*2
    assert cp.distance(a, b)['volume'] > 0


def test_asof_and_feature_no_lookahead():
    f = prices(900)
    cfg = settings()
    day = f.index[700]
    past = cp.research(f.iloc[:701], adjusted=True, cfg=cfg)
    changed = f.copy()
    changed.iloc[701:, :4] *= 5
    changed.iloc[701:, 4] = 0
    assert cp.research(changed, adjusted=True, as_of=str(day.date()), cfg=cfg) == past
    bad = np.zeros(len(f), dtype=bool)
    assert cp.distance(cp.features(f, 500, 20, 100, bad),
                       cp.features(changed, 500, 20, 100, bad))['distance'] == 0


def test_disjoint_episodes_include_context_and_forward_horizon():
    candidates = [{'left': 0, 'end': 99}, {'left': 110, 'end': 209}, {'left': 150, 'end': 249}]
    selected = cp.independent(candidates, 20, 10)
    assert selected == [candidates[0], candidates[2]]


def test_outcomes_both_hit_stop_first_and_hand_calculated_returns():
    f = prices(10)
    f.iloc[:, :4] = 100
    f.loc[f.index[1], ['High', 'Low']] = [120, 90]
    cfg = settings()
    o = cp.outcome(f, 0, 5, cfg)
    assert o['same_bar_ambiguous'] and o['result'] == 'stop' and o['days'] == 1
    assert o['return'] == pytest.approx(-cfg.cost)
    assert o['mfe'] == pytest.approx(.2) and o['mae'] == pytest.approx(-.1)
    f.loc[f.index[1], 'Low'] = 99
    assert cp.outcome(f, 0, 5, cfg)['result'] == 'target'
    f.loc[f.index[1], 'High'] = 101
    assert cp.outcome(f, 0, 5, cfg)['result'] == 'no hit'
    with pytest.raises(ValueError, match='incomplete'):
        cp.outcome(f, 7, 5, cfg)


def test_missing_sessions_weekends_splits_and_invalid_data():
    f = prices(200)
    # Ordinary weekend is allowed, a missing ordinary Wednesday is not.
    assert not cp.boundaries(f).any()
    missing = f.drop(f.index[52])
    assert cp.boundaries(missing)[52]
    split = f.copy()
    split.iloc[120:, :4] /= 2
    assert cp.boundaries(split)[120]
    assert cp.features(split, 160, 20, 100, cp.boundaries(split)) is None
    with pytest.raises(ValueError, match='adjusted'):
        cp.clean(f, adjusted=False)
    with pytest.raises(ValueError, match='unique'):
        cp.clean(pd.concat([f.iloc[:1], f]), adjusted=True)
    f.iloc[0, 0] = np.nan
    with pytest.raises(ValueError, match='invalid'):
        cp.clean(f, adjusted=True)


def test_report_holdout_and_sample_refusal(tmp_path):
    f = prices(1800)
    report = cp.research(f, adjusted=True, cfg=settings(), benchmark=f)
    assert report['status'] == 'INSUFFICIENT EVIDENCE'
    w = report['windows'][0]
    split = int(len(f)*.7)
    assert all(m['end']+20 < split for m in w['matches'])
    for a in w['matches']:
        for b in w['matches']:
            if a is not b:
                assert a['left'] > b['end']+20 or b['left'] > a['end']+20
    for e in w['walk_forward']['evaluations']:
        assert pd.Timestamp(e['date']) > f.index[split]
        assert e['library_last_outcome_index'] < split
    assert w['walk_forward']['n'] > 0
    assert set(w['baselines']) == {'regime', 'dip'}
    assert 'Historical chart comparison' in cp.comparison_html(report)
    assert '<polyline' in cp.comparison_html(report)
    assert 'Distance' in cp.markdown(report)
    assert cp.research(f.iloc[:10], adjusted=True)['reason'] == 'not enough adjusted history'
    file = tmp_path/'prices.csv'
    f.to_csv(file, index_label='Date')
    assert cp.main(['EXAMPLE', '--csv', str(file)]) == 2  # no adjustment attestation


def test_unknown_benchmark_days_and_bad_current_window():
    f = prices(400)
    benchmark = f.iloc[:200]
    r = cp.research(f, adjusted=True, cfg=settings(), benchmark=benchmark)
    assert 'current context' in r['windows'][0]['reason']
    f.iloc[-1, 4] = 0
    f.iloc[-50:, 4] = 0
    r = cp.research(f, adjusted=True, cfg=settings())
    assert 'current context' in r['windows'][0]['reason']


def test_no_production_imports_and_wilson():
    root = Path(__file__).resolve().parents[1]
    for p in [root/'dashboard.py', *(root/'stockwatch').glob('*.py')]:
        if p.name != 'chart_patterns.py':
            assert 'chart_patterns' not in p.read_text()
    lo, hi = cp.wilson(5, 10)
    assert lo < .5 < hi
    assert cp.wilson(0, 0) is None
