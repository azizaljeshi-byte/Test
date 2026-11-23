"""Read-only valuation readings from saved snapshots. Not wired to any account.

Gaps are fractions of the supplied price, not percentage points. A negative gap
means the estimate is below that price. Analysts also contribute to fair value:
these are agreement checks, not independent evidence or probabilities.
"""
from __future__ import annotations

import math

FAIR_GAP, ANALYST_GAP, MIN_METHODS, FUND_SCORE = .15, .10, 2, 75.0
PILLARS = ('valuation', 'growth', 'quality', 'balance')


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _dict(value):
    return value if isinstance(value, dict) else {}


def reading(snap: dict, price: float, *, fair_gap: float = FAIR_GAP, analyst_gap: float = ANALYST_GAP) -> dict:
    """Classify agreement at today's supplied price; never reuse an old upside as today's.

    The overvalued test mirrors the negative gap thresholds on the same price
    denominator. Two finite positive method mids are required. Method names alone
    are not evidence. No timestamp freshness is inferred from this stored data.
    """
    if not (0 < fair_gap < 1 and 0 < analyst_gap < 1):
        raise ValueError('gap thresholds must be between zero and one')
    payload = _dict(snap.get('payload'))
    fund = _dict(payload.get('fundamental'))
    fv = _dict(_dict(_dict(payload.get('research')).get('valuation')).get('fair_value'))
    methods = {k: v for k, v in _dict(fv.get('methods')).items()
               if _num(_dict(v).get('mid')) is not None and v['mid'] > 0}
    out = {'label': 'unknown', 'fair_gap': None, 'analyst_gap': None, 'methods': len(methods), 'why': ''}
    reasons = []
    if _num(price) is None or price <= 0:
        return {**out, 'why': 'Current price is unknown or not positive.'}
    mid = _num(fv.get('mid'))
    if mid is not None and mid > 0:
        out['fair_gap'] = _num(mid / price - 1)
        if out['fair_gap'] is None:
            reasons.append('Fair-value gap is not finite.')
    else:
        reasons.append('Fair value is unknown.')
    if len(methods) < MIN_METHODS:
        reasons.append(f'Only {len(methods)} valid fair-value methods; needs {MIN_METHODS}.')
    # Prefer the actual saved analyst estimate used in this fair value. The engine
    # otherwise saves the ratio and reference price, so reconstruct the target.
    target = _num(_dict(methods.get('analysts')).get('mid'))
    if target is None:
        up, reference = _num(fund.get('analyst_upside')), _num(snap.get('price'))
        if up is not None and reference is not None and reference > 0:
            target = reference * (1 + up)
    if target is not None and target > 0 and math.isfinite(target):
        out['analyst_gap'] = _num(target / price - 1)
        if out['analyst_gap'] is None:
            reasons.append('Analyst gap is not finite.')
    else:
        reasons.append('Analyst target is unknown.')
    if reasons:
        return {**out, 'why': ' '.join(reasons)}
    fair, analyst = out['fair_gap'], out['analyst_gap']
    # Allow only roundoff at the boundary (e.g. 110/100-1 < .10).
    above = lambda value, threshold: value > threshold or math.isclose(value, threshold, rel_tol=1e-12, abs_tol=1e-12)
    label = ('undervalued' if above(fair, fair_gap) and above(analyst, analyst_gap) else
             'overvalued' if above(-fair, fair_gap) and above(-analyst, analyst_gap) else 'fair')
    why = f'Fair value {fair:+.1%}, analyst target {analyst:+.1%} from price; {len(methods)} methods.'
    if label == 'fair':
        why += ' Estimates do not both meet the cheap or expensive threshold; fair does not mean proven fair value.'
    return {**out, 'label': label, 'why': why}


def very_strong(snap: dict, *, pillar_floor: float | None = None) -> tuple[bool, str]:
    """Default is score >=75, with explicit unavailable/missing scores rejected.

    Optional pillar floor is for offline sensitivity checks only. With a floor,
    all four pillars must be known. No floor is applied to any account here.
    """
    f = _dict(_dict(snap.get('payload')).get('fundamental'))
    score = _num(snap.get('fundamental_score'))
    if f.get('available') is False or score is None or not 0 <= score <= 100:
        return False, 'Fundamentals are unknown or unavailable.'
    if score < FUND_SCORE:
        return False, f'Fundamentals {score:g}; needs {FUND_SCORE:g}.'
    if pillar_floor is not None:
        if _num(pillar_floor) is None or not 0 <= pillar_floor <= 100:
            raise ValueError('pillar floor must be between zero and 100')
        for pillar in PILLARS:
            value = _num(f.get('pillar_' + pillar))
            if value is None or not 0 <= value <= 100:
                return False, f'{pillar.capitalize()} pillar is unknown.'
            if value < pillar_floor:
                return False, f'{pillar.capitalize()} pillar {value:g}; needs {pillar_floor:g}.'
    return True, f'Fundamentals {score:g}; meets {FUND_SCORE:g}.'


def audit(snaps: list[dict]) -> dict:
    """Aggregate only: safe to share without ticker names, prices or holdings.

    Counts are descriptive sensitivity checks, not evidence to optimize thresholds.
    Analyst headcounts are not saved by the current engine; do not substitute
    recommendation/earnings coverage, which measures a different population.
    """
    readings = [reading(s, s.get('price')) for s in snaps]
    strong = [very_strong(s)[0] for s in snaps]
    with_floor = [very_strong(s, pillar_floor=50)[0] for s in snaps]
    spreads = []
    for s in snaps:
        fv = _dict(_dict(_dict(_dict(s.get('payload')).get('research')).get('valuation')).get('fair_value'))
        mids = [_num(_dict(m).get('mid')) for m in _dict(fv.get('methods')).values()]
        mids = [m for m in mids if m is not None and m > 0]
        spreads.append(len(mids) >= 2 and max(mids) / min(mids) > 2)
    return {'stocks': len(snaps), 'method_mid_spread_over2x': sum(spreads), **{label: sum(r['label'] == label for r in readings)
                                   for label in ('undervalued', 'fair', 'overvalued', 'unknown')},
            'very_strong': sum(strong), 'very_strong_floor50': sum(with_floor),
            'floor50_removed': sum(a and not b for a, b in zip(strong, with_floor)),
            'cheap_and_strong': sum(r['label'] == 'undervalued' and ok for r, ok in zip(readings, strong)),
            'cheap_20_15': sum(reading(s, s.get('price'), fair_gap=.20, analyst_gap=.15)['label'] == 'undervalued' for s in snaps),
            'analyst_headcount': 'not saved in snapshot fundamentals; cannot test a headcount floor'}
