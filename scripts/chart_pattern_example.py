"""Reproduce the dated AMZN demo from Plotly's public five-year daily-price fixture.

Download source as documented in docs/CHART_PATTERN_LAB.md; this script does no network I/O.
AMZN had no splits or dividends during this interval; historical prices are preserved.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stockwatch.chart_patterns import Settings, comparison_html, markdown, research

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('source_csv', type=Path)
p.add_argument('--output', type=Path, default=Path('docs/examples/chart-pattern-amzn'))
a = p.parse_args()
f = pd.read_csv(a.source_csv)
f = f.loc[f.Name == 'AMZN'].drop(columns='Name').copy()
f['date'] = pd.to_datetime(f['date'])
f = f.rename(columns={c: c.title() for c in f.columns}).set_index('Date').sort_index()
for c in f.columns:
    f[c] = pd.to_numeric(f[c].astype(str).str.replace(',', ''))
if f.empty or f.index.min() < pd.Timestamp('2013-01-01') or f.index.max() >= pd.Timestamp('2019-01-01'):
    raise ValueError('adjustment attestation only applies to the pre-split demo interval')
r = research(f, adjusted=True, ticker='AMZN historical fixture', cfg=Settings())
r['source'] = {'url': 'https://raw.githubusercontent.com/plotly/datasets/0c447c47b757ad74edecab31f0d72f849d2e67c2/' + a.source_csv.name,
               'sha256': hashlib.sha256(a.source_csv.read_bytes()).hexdigest(),
               'rows': len(f), 'start': str(f.index[0].date()), 'end': str(f.index[-1].date()),
               'adjustment': 'AMZN had no splits or dividends during 2013–2018. Historical prices preserved, not restated for 2022 split.',
               'excluded': 'Other tickers excluded; no fabricated timestamps; no SPY supplied.'}
a.output.parent.mkdir(parents=True, exist_ok=True)
a.output.with_suffix('.json').write_text(json.dumps(r, indent=2, allow_nan=False))
a.output.with_suffix('.md').write_text(markdown(r))
a.output.with_suffix('.html').write_text(comparison_html(r))
print(json.dumps({'rows': len(f), 'as_of': r['as_of'], 'windows': [
    {'window': w['window'], 'matches': len(w.get('matches', [])),
     'evaluations': w.get('walk_forward', {}).get('n')} for w in r['windows']]}))
