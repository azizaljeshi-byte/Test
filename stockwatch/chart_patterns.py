"""Isolated historical OHLCV shape research. Never imported by the production app.

Distances are descriptive, not probabilities. All tunable settings are research assumptions.
Adjusted daily OHLCV is required; missing sessions and corporate actions are never filled.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import html
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Settings:
    windows: tuple[int, ...] = (20, 40, 60)
    horizons: tuple[int, ...] = (5, 20, 60)
    target: float = .15
    stop: float = .08
    cost: float = .002  # round trip, illustrative; no execution/slippage estimate
    max_distance: float = 1.0
    max_matches: int = 20
    min_matches: int = 8
    context: int = 100
    train_fraction: float = .7

    def __post_init__(self):
        if (not self.windows or min(self.windows) < 5 or not self.horizons or min(self.horizons) < 1
                or self.context < max(self.windows) or not 0 < self.stop < 1 or self.target <= 0
                or not 0 <= self.cost < 1 or not 0 < self.train_fraction < 1
                or self.max_distance <= 0 or self.max_matches < self.min_matches or self.min_matches < 1):
            raise ValueError('invalid research settings')


def clean(frame: pd.DataFrame, *, adjusted: bool) -> pd.DataFrame:
    if not adjusted:
        raise ValueError('adjusted OHLCV required; raw prices are not silently adjusted')
    columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    if not set(columns) <= set(frame.columns):
        raise ValueError('required columns: Open High Low Close Volume')
    f = frame[columns].copy()
    f.index = pd.DatetimeIndex(pd.to_datetime(f.index)).tz_localize(None).normalize()
    if f.index.has_duplicates or not f.index.is_monotonic_increasing:
        raise ValueError('dates must be unique and increasing')
    f = f.astype(float)
    if (not np.isfinite(f.to_numpy()).all() or (f.iloc[:, :4] <= 0).any().any()
            or (f.Volume < 0).any() or (f.High < f[['Open', 'Close', 'Low']].max(axis=1)).any()
            or (f.Low > f[['Open', 'Close', 'High']].min(axis=1)).any()):
        raise ValueError('invalid OHLCV; no missing values are filled')
    return f


def boundaries(f: pd.DataFrame) -> np.ndarray:
    """Reject windows crossing missing weekday sessions, >7-day gaps or >1.4x price ratios.

    US exchange holidays are allowed; other exchanges require an explicit calendar adapter.
    Jumps can be genuine events: rejecting them is conservative, not a split correction.
    """
    from pandas.tseries.holiday import USFederalHolidayCalendar
    # Federal holidays also include days exchanges trade. We still reject missing ordinary weekdays;
    # this is a conservative calendar approximation, disclosed in every report.
    holidays = USFederalHolidayCalendar().holidays(f.index.min(), f.index.max()).values.astype('datetime64[D]') if len(f) else []
    days = f.index.values.astype('datetime64[D]')
    bad = np.zeros(len(f), dtype=bool)
    if len(f) > 1:
        counts = np.busday_count(days[:-1], days[1:], holidays=holidays)
        bad[1:] = (counts > 1) | (np.diff(days).astype(int) > 7) | (np.abs(np.diff(np.log(f.Close))) > np.log(1.4))
    return bad


def features(f: pd.DataFrame, end: int, window: int, context: int, bad: np.ndarray) -> dict | None:
    start = end - window + 1
    left = end - context + 1
    if left < 0 or bad[left + 1:end + 1].any():
        return None
    c = f.Close.to_numpy()
    vol = float(np.std(np.diff(np.log(c[left:end + 1]))))
    if vol < 1e-8:
        return None
    w = f.iloc[start:end + 1]
    path = np.log(w.Close.to_numpy() / w.Close.iloc[0]) / (vol * np.sqrt(window))
    candles = np.column_stack([(np.log(w[x].to_numpy() / w.Close.to_numpy()) / vol) for x in ('Open', 'High', 'Low')])
    median_volume = float(w.Volume.median())
    if median_volume <= 0:
        return None
    volume = np.log1p(w.Volume.to_numpy() / median_volume)
    trend = 'up' if c[end] > c[left:end + 1].mean() else 'down'
    return {'end': end, 'start': start, 'left': left, 'path': path, 'candles': candles, 'volume': volume,
            'volatility': vol, 'trend': trend, 'dip': c[end] < c[end - 5]}


def distance(a: dict, b: dict) -> dict:
    terms = {k: float(np.sqrt(np.mean((a[k] - b[k]) ** 2))) for k in ('path', 'candles', 'volume')}
    terms['distance'] = .6 * terms['path'] + .25 * terms['candles'] + .15 * terms['volume']
    return terms


def outcome(f: pd.DataFrame, end: int, horizon: int, cfg: Settings) -> dict:
    if end + horizon >= len(f):
        raise ValueError('incomplete forward horizon')
    entry = float(f.Close.iloc[end])
    w = f.iloc[end + 1:end + horizon + 1]
    result, day, ambiguous = 'no hit', None, False
    for k, row in enumerate(w.itertuples(), 1):
        stop, target = row.Low <= entry * (1 - cfg.stop), row.High >= entry * (1 + cfg.target)
        if stop or target:
            result, day, ambiguous = ('stop' if stop else 'target'), k, bool(stop and target)
            break
    closes = np.r_[entry, w.Close.to_numpy()]
    return {'return': float(closes[-1] / entry - 1 - cfg.cost), 'result': result, 'days': day,
            'same_bar_ambiguous': ambiguous, 'mfe': float(w.High.max() / entry - 1),
            'mae': float(w.Low.min() / entry - 1),
            'drawdown': float(np.min(closes / np.maximum.accumulate(closes) - 1))}


def wilson(wins: int, n: int) -> list[float] | None:
    if not n:
        return None
    p, z = wins / n, 1.96
    den = 1 + z*z/n
    center = (p + z*z/(2*n))/den
    half = z*np.sqrt(p*(1-p)/n + z*z/(4*n*n))/den
    return [float(center-half), float(center+half)]


def summarize(rows: list[dict], horizon: int) -> dict:
    obs = [r['outcomes'][str(horizon)] for r in rows]
    n = len(obs)
    wins = [x for x in obs if x['result'] == 'target']
    return {'n': n, 'median_return': float(np.median([x['return'] for x in obs])) if n else None,
            'target_first_rate': len(wins)/n if n else None, 'wilson_95': wilson(len(wins), n),
            'stop_first_rate': sum(x['result'] == 'stop' for x in obs)/n if n else None,
            'no_hit_rate': sum(x['result'] == 'no hit' for x in obs)/n if n else None,
            'median_days_to_target': float(np.median([x['days'] for x in wins])) if wins else None,
            'median_mfe': float(np.median([x['mfe'] for x in obs])) if n else None,
            'median_mae': float(np.median([x['mae'] for x in obs])) if n else None,
            'worst_drawdown': min((x['drawdown'] for x in obs), default=None)}


def independent(candidates: list[dict], horizon: int, limit: int) -> list[dict]:
    selected = []
    for c in candidates:
        # Entire feature context + subsequent outcomes must be disjoint, not just endpoints.
        if all(c['left'] > x['end'] + horizon or x['left'] > c['end'] + horizon for x in selected):
            selected.append(c)
            if len(selected) == limit:
                break
    return selected


def matches(f: pd.DataFrame, cache: dict, query: dict, cfg: Settings, cutoff: int, mode='shape') -> list[dict]:
    horizon = max(cfg.horizons)
    candidates = []
    for end, feat in cache.items():
        if end + horizon >= min(query['left'], cutoff) or feat['trend'] != query['trend']:
            continue
        if feat.get('market_trend') != query.get('market_trend'):
            continue
        if query.get('market_volatility') and not .5 <= feat['market_volatility']/query['market_volatility'] <= 2:
            continue
        ratio = feat['volatility']/query['volatility']
        if not .5 <= ratio <= 2:
            continue
        if mode == 'dip' and not feat['dip']:
            continue
        terms = distance(query, feat)
        if mode == 'shape' and terms['distance'] > cfg.max_distance:
            continue
        candidates.append({'end': end, 'left': feat['left'], 'start': feat['start'],
                           'date': str(f.index[end].date()), 'formation_start': str(f.index[feat['start']].date()),
                           'context_start': str(f.index[feat['left']].date()), 'trend': feat['trend'],
                           'market_trend': feat.get('market_trend', 'unavailable'),
                           'volatility_ratio': float(ratio), **terms})
    # Baselines sample recent independent matched-regime episodes without using shape or outcomes.
    candidates.sort(key=(lambda c: c['distance']) if mode == 'shape' else (lambda c: -c['end']))
    selected = independent(candidates, horizon, cfg.max_matches)
    for c in selected:
        c['outcomes'] = {str(h): outcome(f, c['end'], h, cfg) for h in cfg.horizons}
    return selected


def research(frame: pd.DataFrame, *, adjusted: bool, ticker='CSV', as_of=None, cfg=Settings(), benchmark=None) -> dict:
    if as_of is not None:
        # Slice before validation/feature generation: future prices, volumes and gaps are invisible.
        frame = frame.loc[pd.to_datetime(frame.index).date <= pd.Timestamp(as_of).date()]
    f = clean(frame, adjusted=adjusted)
    market = None
    if benchmark is not None:
        if as_of is not None:
            benchmark = benchmark.loc[pd.to_datetime(benchmark.index).date <= pd.Timestamp(as_of).date()]
        market = clean(benchmark, adjusted=adjusted).Close.reindex(f.index)
    out = {'ticker': ticker, 'as_of': str(f.index[-1].date()) if len(f) else None,
           'status': 'INSUFFICIENT EVIDENCE', 'settings': asdict(cfg), 'windows': [],
           'limitations': ['Research only; no production BUY/SELL integration or probability of profit.',
                           'Adjusted OHLC outcomes approximate reinvested distributions; historical vendor data can be revised.',
                           'US federal holiday calendar is an approximation, not an exchange calendar; unknown gaps are excluded.',
                           'Broad-market trend is matched only when benchmark data is supplied; sector regimes are NOT controlled.',
                           'Target/stop touches use daily adjusted ranges, not executable fills; same-bar ties count as stops.',
                           'Illustrative round-trip cost; gaps, liquidity, spreads, event/dilution and going-concern risks are not modeled.',
                           'Wilson intervals describe this sample; episode separation does not prove statistical independence.',
                           'Settings are predeclared research assumptions, not optimized thresholds. No cross-stock pooling.']}
    if len(f) < cfg.context + max(cfg.horizons) + 1:
        out['reason'] = 'not enough adjusted history'
        return out
    bad = boundaries(f)
    split = int(len(f)*cfg.train_fraction)
    for window in cfg.windows:
        cache = {end: feat for end in range(cfg.context-1, len(f))
                 if (feat := features(f, end, window, cfg.context, bad)) is not None}
        cache = {end: feat for end, feat in cache.items()
                 if end + max(cfg.horizons) >= len(f)
                 or not bad[end+1:end+max(cfg.horizons)+1].any()}
        if market is not None:
            for end in list(cache):
                segment = market.iloc[cache[end]['left']:end+1]
                if segment.isna().any():
                    del cache[end]
                else:
                    cache[end]['market_trend'] = 'up' if segment.iloc[-1] > segment.mean() else 'down'
                    cache[end]['market_volatility'] = float(np.std(np.diff(np.log(segment))))
        query = cache.get(len(f)-1)
        if query is None:
            out['windows'].append({'window': window, 'reason': 'current context has a gap, jump or invalid volume/volatility'})
            continue
        # Freeze library at chronological training cutoff; no holdout outcomes used for matching/tuning.
        picked = matches(f, cache, query, cfg, split)
        bases = {mode: matches(f, cache, query, cfg, split, mode) for mode in ('regime', 'dip')}
        sensitivity = {str(multiplier): {str(h): summarize(matches(
            f, cache, query, replace(cfg, max_distance=cfg.max_distance*multiplier), split), h)
            for h in cfg.horizons} for multiplier in (.75, 1.0, 1.25)}
        evaluations = []
        stride = cfg.context + max(cfg.horizons)
        for end in range(split + cfg.context - 1, len(f)-max(cfg.horizons), stride):
            q = cache.get(end)
            if q is None or bad[end+1:end+max(cfg.horizons)+1].any():
                continue
            samples = {mode: matches(f, cache, q, cfg, split, mode) for mode in ('shape', 'regime', 'dip')}
            if any(len(v) < cfg.min_matches for v in samples.values()):
                continue
            h = max(cfg.horizons)
            actual = outcome(f, end, h, cfg)
            evaluations.append({'date': str(f.index[end].date()), 'actual': actual,
                                'predicted_median': {mode: summarize(rows, h)['median_return'] for mode, rows in samples.items()},
                                'library_last_outcome_index': split-1})
        # Exclude candidates with bad forward paths as well as bad formation/context.
        picked = [p for p in picked if not bad[p['end']+1:p['end']+max(cfg.horizons)+1].any()]
        bases = {k: [p for p in v if not bad[p['end']+1:p['end']+max(cfg.horizons)+1].any()] for k, v in bases.items()}
        for p in picked[:3]:
            start, end = p['start'], p['end'] + max(cfg.horizons)
            p['plot'] = [float(v/f.Close.iloc[p['start']]*100) for v in f.Close.iloc[start:end+1]]
            p['plot_dates'] = [str(d.date()) for d in f.index[start:end+1]]
        errors = {mode: float(np.mean([abs(e['actual']['return']-e['predicted_median'][mode]) for e in evaluations]))
                  if evaluations else None for mode in ('shape', 'regime', 'dip')}
        out['windows'].append({'window': window, 'trend': query['trend'], 'daily_volatility': query['volatility'],
                               'sample_sufficient': len(picked) >= cfg.min_matches,
                               'current_path': [float(v/f.Close.iloc[-window]*100) for v in f.Close.iloc[-window:]],
                               'matches': picked, 'summary': {str(h): summarize(picked, h) for h in cfg.horizons},
                               'distance_sensitivity': sensitivity,
                               'baselines': {mode: {str(h): summarize(rows, h) for h in cfg.horizons} for mode, rows in bases.items()},
                               'walk_forward': {'train_end': str(f.index[split-1].date()), 'evaluations': evaluations,
                                                'n': len(evaluations), 'mean_absolute_return_error': errors},
                               'reason': 'No calibrated tactical verdict: broad-market regime, execution risk and repeatable out-of-sample edge remain unverified.'})
    return out


def markdown(report: dict) -> str:
    lines = [f"# Chart Pattern Lab: {report['ticker']}", '', f"As of {report['as_of']} — **{report['status']}**", '',
             report.get('reason', ''), 'Distances measure shape similarity; hit-first rates are observed frequencies, not success probabilities.', '']
    if report.get('source'):
        lines += ['Source: ' + json.dumps(report['source']), '']
    for w in report['windows']:
        lines += [f"## {w['window']}-bar formation", '', w.get('reason', ''), '']
        if 'summary' not in w:
            continue
        lines += ['| Horizon | Independent episodes | Median net return | Target first | Stop first | No hit | 95% Wilson interval |',
                  '|---|---|---|---|---|---|---|']
        for h, s in w['summary'].items():
            lines.append(f"| {h} | {s['n']} | {s['median_return']} | {s['target_first_rate']} | {s['stop_first_rate']} | {s['no_hit_rate']} | {s['wilson_95']} |")
        lines += ['', f"Frozen training end: {w['walk_forward']['train_end']}. Disjoint holdout evaluations: {w['walk_forward']['n']}.",
                  f"Holdout return prediction MAE (shape/regime/dip): {w['walk_forward']['mean_absolute_return_error']}", '',
                  '| Formation start | Match end | Distance | Path / candles / volume | Volatility ratio |', '|---|---|---|---|---|']
        for m in w['matches']:
            lines.append(f"| {m['formation_start']} | {m['date']} | {m['distance']:.3f} | {m['path']:.3f} / {m['candles']:.3f} / {m['volume']:.3f} | {m['volatility_ratio']:.2f} |")
        lines += ['', 'Matched-regime and buy-the-dip baselines (same horizons and costs):',
                  '```json', json.dumps(w['baselines'], indent=2), '```', '',
                  'Sensitivity to distance cutoff (0.75× / 1× / 1.25×; never selected by outcomes):',
                  '```json', json.dumps(w['distance_sensitivity'], indent=2), '```']
    lines += ['', '## Limits', ''] + ['- ' + s for s in report['limitations']]
    return '\n'.join(lines) + '\n'


def comparison_html(report: dict) -> str:
    parts = ['<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>Chart Pattern Lab</title><style>body{font:16px system-ui;max-width:1000px;margin:20px auto;padding:12px;background:#101923;color:#eef3fa}section{margin:24px 0}svg{width:100%;height:auto;background:#182638}pre{white-space:pre-wrap;overflow-wrap:anywhere} .chart{overflow:auto}svg{min-width:600px}</style>',
             '<h1>Historical chart comparison</h1>',
             f"<p>{html.escape(report['ticker'])} · setup as of {html.escape(str(report['as_of']))} · <strong>{report['status']}</strong></p>",
             '<p>Research only. Solid: formation. Dashed: later historical path. Cyan: current formation. Orange: actual historical match. Scroll each chart horizontally on a phone.</p>']
    for w in report['windows']:
        for m in w.get('matches', [])[:3]:
            series = [w['current_path'], m['plot']]
            lo, hi = min(map(min, series)), max(map(max, series))
            span = max(hi-lo, 1)
            n = len(series[1])
            def points(vals, offset=0):
                return ' '.join(f'{40+(i+offset)*820/max(n-1,1):.1f},{215-(v-lo)/span*170:.1f}' for i, v in enumerate(vals))
            b = w['window']-1
            parts += [f"<section><h2>{w['window']} bars: {html.escape(m['formation_start'])} to {html.escape(m['date'])}</h2>",
                      f"<p>Distance {m['distance']:.3f}; {html.escape(m['trend'])} trend; volatility ratio {m['volatility_ratio']:.2f}. Indexed adjusted close (start=100).</p>",
                      '<div class="chart"><svg viewBox="0 0 900 260" role="img" aria-label="Current and historical normalized paths">',
                      f'<text x="5" y="30" fill="white">{hi:.1f}</text><text x="5" y="225" fill="white">{lo:.1f}</text>',
                      f'<polyline fill="none" stroke="#40dce0" stroke-width="3" points="{points(series[0])}"/>',
                      f'<polyline fill="none" stroke="#ffbd66" stroke-width="3" points="{points(series[1][:b+1])}"/>',
                      f'<polyline fill="none" stroke="#ffbd66" stroke-width="3" stroke-dasharray="6 4" points="{points(series[1][b:],b)}"/>',
                      f'<text x="40" y="250" fill="white">{m["formation_start"]}</text><text x="650" y="250" fill="white">{m["plot_dates"][-1]}</text></svg></div>',
                      '<table><tr><th>Days</th><th>Net return</th><th>First hit</th><th>Day hit</th></tr>']
            for horizon, obs in m['outcomes'].items():
                parts.append(f"<tr><td>{horizon}</td><td>{obs['return']:.1%}</td><td>{obs['result']}</td><td>{obs['days'] or '—'}</td></tr>")
            parts.append('</table></section>')
    parts += ['<h2>Full report</h2><pre>' + html.escape(markdown(report)) + '</pre>']
    return '\n'.join(parts)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('ticker')
    p.add_argument('--csv', type=Path, help='Date,Open,High,Low,Close,Volume; adjusted values required')
    p.add_argument('--adjusted', action='store_true', help='attest CSV OHLCV is adjusted consistently')
    p.add_argument('--as-of')
    p.add_argument('--benchmark-csv', type=Path, help='adjusted SPY OHLCV CSV, same format')
    p.add_argument('--output', type=Path, default=Path('chart-patterns'))
    p.add_argument('--target', type=float, default=.15)
    p.add_argument('--stop', type=float, default=.08)
    args = p.parse_args(argv)
    try:
        if args.csv:
            frame = pd.read_csv(args.csv, index_col='Date', parse_dates=True)
            adjusted = args.adjusted
            source = 'user-supplied adjusted CSV' if adjusted else 'unverified CSV'
            benchmark = pd.read_csv(args.benchmark_csv, index_col='Date', parse_dates=True) if args.benchmark_csv else None
        else:
            from .data import YahooProvider
            frame = YahooProvider().history(args.ticker, period='max')
            benchmark = YahooProvider().history('SPY', period='max')
            # A daily bar for today's New York date can still be forming. Always use prior sessions.
            frame = frame.loc[frame.index.date < datetime.now(ZoneInfo('America/New_York')).date()]
            adjusted, source = True, 'YahooProvider auto_adjust=True; fetched now, not a point-in-time vendor archive'
        result = research(frame, adjusted=adjusted, ticker=args.ticker, as_of=args.as_of,
                          cfg=Settings(target=args.target, stop=args.stop), benchmark=benchmark)
        result['source'] = source
    except (ValueError, OSError, KeyError, RuntimeError) as e:
        print(f'Unavailable: {e}')
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix('.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    args.output.with_suffix('.md').write_text(markdown(result))
    args.output.with_suffix('.html').write_text(comparison_html(result))
    print(markdown(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
