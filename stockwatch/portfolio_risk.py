"""Manual private holdings research. No app, scanner, trading or notification integration."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import html
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import sys

import pandas as pd
import yaml


class PrivateInputError(ValueError):
    """Messages deliberately contain no configuration contents or holding identifiers."""


def number(value, positive=False):
    return (not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


def parse_portfolio(text):
    """Explicit YAML holdings only; no file/sheet/example fallback or silent deduplication."""
    try:
        raw = yaml.safe_load(text)
        if not isinstance(raw, dict) or not isinstance(raw.get('holdings'), list) or not raw['holdings']:
            raise ValueError()
        if raw.get('currency', 'USD') != 'USD':
            raise ValueError()
        rows, seen = [], set()
        for row in raw['holdings']:
            ticker = row['ticker'].strip().upper()
            if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', ticker) or ticker in seen:
                raise ValueError()
            seen.add(ticker)
            tier, shares, basis = row['tier'], row['shares'], row.get('cost_basis')
            if isinstance(tier, bool) or tier not in (1, 2) or not number(shares):
                raise ValueError()
            if shares > 0 and (not number(basis) or not math.isfinite(shares*basis)):
                raise ValueError()
            sector = row.get('sector')
            if sector is not None and (not isinstance(sector, str) or len(sector) > 80):
                raise ValueError()
            rows.append({'ticker':ticker,'tier':tier,'shares':shares,
                         'cost_basis':basis if shares > 0 else None,'sector':sector})
        cash = raw.get('cash')
        if cash is not None and not number(cash):
            raise ValueError()
        if not any(r['shares'] > 0 for r in rows):
            raise ValueError()
        return {'holdings':rows,'cash':cash,'currency':'USD'}
    except Exception:
        raise PrivateInputError('Invalid private portfolio: require unique ticker, tier 1/2, nonnegative shares and held-position per-share USD cost_basis; optional nonnegative USD cash.') from None


def instant(text):
    stamp = datetime.fromisoformat(text.replace('Z','+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('timezone required')
    return stamp.astimezone(timezone.utc)


def series_frame(record, as_of):
    """Strict paired raw/adjusted completed daily bars; never fill or silently drop bad rows."""
    if (not isinstance(record, dict) or record.get('currency') != 'USD'
            or record.get('basis') != 'raw_close_and_split_dividend_adjusted_ohlcv'
            or record.get('provider') not in ('Yahoo/yfinance', 'SYNTHETIC')
            or not record.get('source') or instant(record['captured_at']) > as_of):
        raise ValueError('metadata')
    f = pd.DataFrame(record['bars'])
    f.index = pd.DatetimeIndex(pd.to_datetime(f.pop('date'), format='%Y-%m-%d', errors='raise'))
    if f.index.has_duplicates or not f.index.is_monotonic_increasing or len(f) < 200:
        raise ValueError('daily window')
    cols = ['raw_close','open','high','low','close','volume']
    if any(c not in f or f[c].dtype.kind not in 'ifu' for c in cols):
        raise ValueError('non-numeric')
    f = f[cols].astype(float)
    if not all(math.isfinite(x) for x in f.to_numpy().ravel()):
        raise ValueError('nonfinite')
    if ((f[['raw_close','open','high','low','close']] <= 0).any().any() or (f.volume < 0).any()
            or (f.high < f[['open','close','low']].max(axis=1)).any()
            or (f.low > f[['open','close','high']].min(axis=1)).any()):
        raise ValueError('invalid OHLC')
    last = f.index[-1].date()
    captured = instant(record['captured_at'])
    if (as_of.date()-last).days > 4 or (as_of-captured).total_seconds() > 4*86400:
        raise ValueError('stale')
    if (last >= as_of.date() or captured.date() <= last
            or any(d.weekday() > 4 for d in f.index)
            or (f.index.to_series().diff().dropna() > pd.Timedelta(days=7)).any()):
        raise ValueError('stale, incomplete or future daily history')
    return f


def technical(f):
    c=f.close
    ma50,ma200=float(c.tail(50).mean()),float(c.tail(200).mean())
    last=float(c.iloc[-1]);previous=c.shift(1)
    tr=pd.concat([f.high-f.low,(f.high-previous).abs(),(f.low-previous).abs()],axis=1).max(axis=1)
    trend='up' if last > ma50 > ma200 else 'down' if last < ma50 < ma200 else 'mixed'
    return {'trend':trend,'ma50_adjusted':ma50,'ma200_adjusted':ma200,
            'adjusted_close':last,'atr14_adjusted':float(tr.tail(14).mean()),
            'support20_adjusted':float(f.low.iloc[-21:-1].min()),
            'resistance20_adjusted':float(f.high.iloc[-21:-1].max()),
            'volume_vs_prior20':float(f.volume.iloc[-1]/f.volume.iloc[-21:-1].mean()) if f.volume.iloc[-21:-1].mean()>0 else None,
            'drawdown_from_window_peak':last/float(c.cummax().iloc[-1])-1,
            'return20':last/float(c.iloc[-21])-1,
            'basis':'Adjusted history; levels are research references, not raw-price order levels.'}


def correlation(a,b):
    if not a.index[-61:].equals(b.index[-61:]):
        return {'value':None,'observations':0,'reason':'Latest 61 daily close dates differ; no mismatched return intervals.'}
    returns=pd.concat([a.close.pct_change().rename('a'),b.close.pct_change().rename('b')],axis=1).dropna().tail(60)
    if len(returns) < 60 or returns.a.std() <= 1e-12 or returns.b.std() <= 1e-12:
        return {'value':None,'observations':len(returns),'reason':'Need 60 aligned nonconstant daily returns.'}
    value=float(returns.a.corr(returns.b))
    return {'value':value if math.isfinite(value) else None,'observations':len(returns),
            'start':str(returns.index[0].date()),'end':str(returns.index[-1].date()),
            'reason':'Historical adjusted daily Pearson correlation, not a forward probability.'}


def build(portfolio, captures, as_of):
    """All inputs private; returned structure contains holdings and must stay local."""
    if as_of.tzinfo is None:
        raise PrivateInputError('As-of requires timezone.')
    # Revalidate even programmatic callers; no bypass of strict holdings rules.
    portfolio=parse_portfolio(yaml.safe_dump(portfolio))
    frames, rows, failures = {}, [], {}
    tickers={r['ticker'] for r in portfolio['holdings']} | {'SPY'}
    for ticker in sorted(tickers):
        try:
            frame=series_frame(captures.get(ticker),as_of)
            shares=next((r['shares'] for r in portfolio['holdings'] if r['ticker']==ticker),0)
            if not math.isfinite(shares*float(frame.raw_close.iloc[-1])):
                raise ValueError('overflow')
            frames[ticker]=frame
        except Exception as exc:
            failures[ticker]='stale' if str(exc)=='stale' else 'unavailable'
    benchmark=technical(frames['SPY']) if 'SPY' in frames else None
    for holding in portfolio['holdings']:
        ticker=holding['ticker'];f=frames.get(ticker);record=captures.get(ticker) or {}
        row={**holding,'held':holding['shares']>0,'market_value':None,'unrealized_pl':None,'weight':None,
             'cost_value':holding['shares']*holding['cost_basis'] if holding['shares']>0 else None,
             'quote':{'status':failures.get(ticker,'unavailable'),'price':None,'date':None,'provider':None,
                      'reason':'Stale under four-calendar-day close/capture rule.' if failures.get(ticker)=='stale' else 'Provider failed, data missing or malformed; no verified quote.'},'technical':None,
             'flag':'review','reasons':[],
             'financial_evidence':{'status':'unavailable','reason':'No issuer financial packet ingested. MSFT-only SEC readiness does not cover this portfolio; no valuation or add conclusion.'},
             'analogue_probability':None}
        if f is not None:
            row['quote']={'status':'usable','price':float(f.raw_close.iloc[-1]),'date':str(f.index[-1].date()),
                          'provider':record['provider'],'source':record['source'],'captured_at':record['captured_at'],
                          'basis':'Raw completed daily close; following-calendar-day availability; not a live quote.',
                          'age_calendar_days':(as_of.date()-f.index[-1].date()).days}
            row['technical']=technical(f)
            if row['held']:
                row['market_value']=holding['shares']*row['quote']['price']
                row['unrealized_pl']=row['market_value']-row['cost_value']
            if row['technical']['trend']=='down':
                row['reasons'].append('Close below MA50 below MA200: investigate deterioration.')
            else:
                row['flag']='hold' if row['held'] else 'add-watch'
                row['reasons'].append('No ordered downtrend; hold means monitor, add-watch means investigate only.')
            if benchmark and f.index[-1] == frames['SPY'].index[-1]:
                row['correlation_spy']=correlation(f,frames['SPY'])
                row['counter_trend_strength']=row['technical']['return20']>0 and benchmark['return20']<0
        else:
            row['reasons'].append('Missing, stale, malformed or failed USD daily quote/history; no position valuation.')
        rows.append(row)
    held=[r for r in rows if r['held']]
    available=[r for r in held if r['quote']['status']=='usable']
    dates={r['quote']['date'] for r in available}
    complete=len(available)==len(held) and len(dates)==1
    equity=sum(r['market_value'] for r in held) if complete else None
    cost=sum(r['cost_value'] for r in held)
    cash=portfolio['cash'];nav=equity+cash if complete and cash is not None else None
    denominator=nav if nav is not None else equity
    if complete:
        for r in held:
            r['weight']=r['market_value']/denominator
            r['weight_basis']='NAV including supplied cash' if nav is not None else 'invested equities only; cash unknown'
            threshold=.15 if r['tier']==1 else .07
            if r['weight']>threshold:
                r['flag']='reduce-review'
                r['reasons'].append(f'Exposure exceeds disclosed tier investigation threshold ({threshold:.0%}); review concentration, no sell instruction.')
    sector_values={}
    if complete:
        for r in held:
            key=r['sector'] or 'Unknown'
            sector_values[key]=sector_values.get(key,0)+r['market_value']
    pairs=[]
    for i,a in enumerate(held):
        for b in held[i+1:]:
            if a['ticker'] in frames and b['ticker'] in frames:
                pairs.append({'tickers':[a['ticker'],b['ticker']],**correlation(frames[a['ticker']],frames[b['ticker']])})
    scenarios=[]
    if complete:
        for label,shock in [('Broad equity stress',-.1),('Severe equity stress',-.2)]:
            loss=equity*shock
            scenarios.append({'label':label,'assumed_uniform_equity_return':shock,'dollar_change':loss,
                              'nav_change_fraction':loss/nav if nav else None,
                              'assumptions':'All held equities fall together; supplied cash unchanged. Hypothetical sensitivity, no probability or forecast.'})
    priorities={'biggest_exposures':sorted([{'ticker':r['ticker'],'weight':r['weight']} for r in held],key=lambda x:-(x['weight'] or 0))[:3] if complete else [],
                'most_deteriorated':sorted([{'ticker':r['ticker'],'return20':r['technical']['return20']} for r in held if r['technical']],key=lambda x:x['return20'])[:3]}
    return {'priorities':priorities,'version':'private-portfolio-risk.1','private':True,'as_of':as_of.isoformat(),
            'synthetic':all((captures.get(t) or {}).get('provider')=='SYNTHETIC' for t in tickers),
            'summary':{'status':'complete_equity_quotes' if complete else 'INSUFFICIENT EVIDENCE',
                       'held_positions':len(held),'usable_positions':len(available),'watchlist_positions':len(rows)-len(held),
                       'quote_dates':sorted(dates),'coverage_basis':'Position count, never a fabricated value-weighted coverage.',
                       'equity_value':equity,'cost_value':cost,'unrealized_pl':equity-cost if complete else None,
                       'cash':cash,'nav':nav,'cash_weight':cash/nav if nav else None,
                       'portfolio_drawdown':None,'portfolio_drawdown_reason':'Actual historical holdings, flows and equity curve unavailable.'},
            'positions':rows,'market_stress':{'benchmark':'SPY','technical':benchmark,
                       'status':'unavailable' if benchmark is None else benchmark['trend'],
                       'reason':'Trend lens only; no calibrated market-loss probability.'},
            'sector_exposure':[{'sector':s,'value':v,'weight':v/denominator} for s,v in sorted(sector_values.items())],
            'sector_basis':'Owner supplied classifications; Unknown retained. No inferred sector labels.',
            'pair_correlations':pairs,'scenarios':scenarios,
            'rules':{'tier1_concentration':.15,'tier2_concentration':.07,'freshness_calendar_days':4,
                     'history_min_bars':200,'correlation_daily_returns':60,
                     'flags':'Missing/downtrend → review; concentration → reduce-review; otherwise held → hold / watchlist → add-watch. Investigation only, never automatic transactions.'},
            'limitations':['No calibrated historical analogue probabilities supplied; unavailable, never a score converted to probability.',
                           'Raw closes value current shares; adjusted bars measure technical returns. Corporate-action holdings/basis reconciliation remains owner responsibility.',
                           'No portfolio totals, weights, exposures or scenario dollar losses on partial or different-date held quotes.',
                           'Unlevered USD long-only equities and optional USD cash; no FX, shorts, derivatives, dividends, fees or tax-lot accounting.',
                           'No automatic trades, alerts, notifications, workflow uploads or app integration.']}


def render(report):
    esc=lambda v:html.escape(str(v))
    def val(v,percent=False):
        return 'Unknown' if v is None else f'{v:.1%}' if percent else f'{v:,.2f}'
    s=report['summary']
    labels={'equity_value':'Equities · USD','unrealized_pl':'Unrealized P/L · USD','cash':'Cash · USD','nav':'NAV · USD','cash_weight':'Cash allocation'}
    cards=''.join(f'<div class="card"><strong>{esc(labels[k])}</strong><p>{esc(val(s[k],k=="cash_weight"))}</p></div>'
                  for k in ('equity_value','unrealized_pl','cash','nav','cash_weight'))
    rows=[]
    # Investigation priorities first; watchlist clearly separate in each row.
    order={'reduce-review':0,'review':1,'hold':2,'add-watch':3}
    for r in sorted(report['positions'],key=lambda r:(order[r['flag']],-(r['market_value'] or 0))):
        tech=r['technical'] or {}
        rows.append('<article class="card"><h2>'+esc(r['ticker'])+' · '+esc(r['flag'])+'</h2><p>'+esc('HELD' if r['held'] else 'WATCHLIST · zero shares')+' · T'+esc(r['tier'])+'</p>'
                    +'<p>'+esc('; '.join(r['reasons']))+'</p><dl>'
                    +''.join('<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>' for k,v in [
                        ('Value / P&L (USD)',val(r['market_value'])+' / '+val(r['unrealized_pl'])),
                        ('Shares / per-share basis',val(r['shares'])+' / '+val(r['cost_basis'])),
                        ('Weight',val(r['weight'],True)+' · '+r.get('weight_basis','coverage incomplete')),
                        ('Quote',r['quote']['status']+' · '+str(r['quote']['provider'] or 'Unknown')+' · '+str(r['quote']['date'] or 'Unknown')),('Trend / window drawdown',str(tech.get('trend','Unknown'))+' / '+val(tech.get('drawdown_from_window_peak'),True)),
                        ('Adjusted MA50 / MA200',val(tech.get('ma50_adjusted'))+' / '+val(tech.get('ma200_adjusted'))),
                        ('Adjusted support / resistance (20 sessions)',val(tech.get('support20_adjusted'))+' / '+val(tech.get('resistance20_adjusted'))),
                        ('Adjusted ATR14 / volume vs prior 20',val(tech.get('atr14_adjusted'))+' / '+val(tech.get('volume_vs_prior20'))),
                        ('20-session return / counter-trend strength',val(tech.get('return20'),True)+' / '+str(r.get('counter_trend_strength','Unknown'))),('Financial evidence',r['financial_evidence']['reason'])])+'</dl></article>')
    benchmark=report['market_stress']['technical'] or {}
    lens='<section class=card><h2>Market stress · SPY</h2><p>'+esc(report['market_stress']['status'])+' · 20-session return '+esc(val(benchmark.get('return20'),True))+'</p><p>Trend evidence only; no market-loss probability.</p></section>'
    exposures='<section class=card><h2>Biggest exposures</h2>'+''.join('<p>'+esc(x['ticker'])+' · '+esc(val(x['weight'],True))+'</p>' for x in report['priorities']['biggest_exposures'])+'<h2>Weakest 20-session returns</h2>'+''.join('<p>'+esc(x['ticker'])+' · '+esc(val(x['return20'],True))+'</p>' for x in report['priorities']['most_deteriorated'])+'</section>'
    scenarios='<section class=card><h2>Hypothetical stress</h2>'+''.join('<p>'+esc(x['label'])+' ('+esc(val(x['assumed_uniform_equity_return'],True))+'): USD '+esc(val(x['dollar_change']))+'</p>' for x in report['scenarios'])+'<p>Uniform equity shocks; cash unchanged. Assumptions, not forecasts.</p></section>'
    details={k:report[k] for k in ('market_stress','sector_exposure','sector_basis','pair_correlations','scenarios','rules','limitations')}
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>Private portfolio research</title><style>body{font:16px system-ui;background:#101923;color:#eaf0f4;max-width:1000px;margin:auto;padding:18px}h1{font-size:1.6rem}h2{font-size:1.2rem}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}.card{background:#1c2a37;border:1px solid #456;padding:16px;margin:12px 0;border-radius:12px}dt{color:#a9c4d5;margin-top:10px}dd{margin:4px 0;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><body><h1>Private portfolio research'+(' · SYNTHETIC DEMO' if report['synthetic'] else '')+'</h1><p>'+esc('Equity quotes complete' if s['status']=='complete_equity_quotes' else 'Insufficient evidence')+' · '+esc(report['as_of'])+'</p><p>'+esc(f"Quote coverage: {s['usable_positions']}/{s['held_positions']} held positions; {s['watchlist_positions']} watchlist. Cash unknown stays unknown. No automatic transactions.")+'</p><div class="grid">'+cards+'</div>'+lens+exposures+scenarios+''.join(rows)+'<details><summary>Full evidence, rules and uncertainties</summary><pre>'+esc(json.dumps(details,indent=2,allow_nan=False))+'</pre></details></body></html>'


def live_capture(ticker):
    # Existing Yahoo semaphore/retry wrapper; serial calls, no new provider or secrets.
    from .data import _yahoo
    @_yahoo
    def fetch():
        import yfinance as yf
        t=yf.Ticker(ticker)
        raw=t.history(period='1y',auto_adjust=False,timeout=20)
        currency=t.history_metadata.get('currency')
        adjusted=t.history(period='1y',auto_adjust=True,timeout=20)
        if currency != 'USD' or not raw.index.equals(adjusted.index):
            raise ValueError('currency or date mismatch')
        today=datetime.now(timezone.utc).date()
        bars=[]
        for index,r in adjusted.iterrows():
            day=index.date()
            if day >= today:
                continue
            bars.append({'date':str(day),'raw_close':float(raw.loc[index,'Close']),
                         **{k.lower():float(r[k]) for k in ('Open','High','Low','Close','Volume')}})
        return {'currency':currency,'basis':'raw_close_and_split_dividend_adjusted_ohlcv',
                'provider':'Yahoo/yfinance','source':'https://finance.yahoo.com/quote/'+ticker+'/history/',
                'captured_at':datetime.now(timezone.utc).isoformat(),'bars':bars}
    return fetch()


def demo():
    """Invented identifiers and positions only; independent of private environment."""
    now=datetime(2026,10,23,12,tzinfo=timezone.utc)
    holdings=[{'ticker':'SYNTHA','tier':1,'shares':10,'cost_basis':80,'sector':'Synthetic sector'},
              {'ticker':'SYNTHB','tier':2,'shares':5,'cost_basis':110,'sector':'Synthetic sector'},
              {'ticker':'SYNTHW','tier':2,'shares':0}]
    captures={}
    for j,t in enumerate(['SYNTHA','SYNTHB','SYNTHW','SPY']):
        bars=[]
        for i,day in enumerate(pd.bdate_range(end='2026-10-22',periods=252)):
            close=100+(i*.1 if j%2==0 else -i*.08)+math.sin(i/5)
            bars.append({'date':str(day.date()),'raw_close':close,'open':close,'high':close+1,'low':close-1,'close':close,'volume':1000+i})
        captures[t]={'currency':'USD','basis':'raw_close_and_split_dividend_adjusted_ohlcv','provider':'SYNTHETIC',
                     'source':'synthetic deterministic bars','captured_at':now.isoformat(),'bars':bars}
    return {'holdings':holdings,'cash':500,'currency':'USD'},captures,now


def write_private(directory, report, captures):
    """New directory only, outside any Git checkout, owner-only, no symlinks."""
    path=Path(directory).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)) or any((p/'.git').is_file() or (p/'.git/HEAD').exists() for p in (path,*path.parents)):
        raise PrivateInputError('Output must be outside Git checkouts with no symlink ancestors.')
    path.mkdir(mode=0o700,parents=False,exist_ok=False)
    for name,body in [('report.json',json.dumps(report,indent=2,allow_nan=False)),('report.html',render(report)),
                      ('capture.json',json.dumps({'version':'private-capture.1','as_of':report['as_of'],'captures':captures},allow_nan=False))]:
        fd=os.open(path/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:
            f.write(body)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Manual PRIVATE local holdings research. Never use in public CI.')
    parser.add_argument('--demo',action='store_true')
    parser.add_argument('--portfolio',help='Explicit private YAML file; otherwise STOCKWATCH_PORTFOLIO YAML text')
    parser.add_argument('--replay',help='Private capture.json; never fetches')
    parser.add_argument('--output',required=True,help='NEW private directory outside Git checkouts')
    args=parser.parse_args(argv)
    try:
        if os.environ.get('CI') or os.environ.get('GITHUB_ACTIONS'):
            raise PrivateInputError('Private holdings runner is disabled in CI, including demo.')
        if args.demo:
            if args.portfolio or args.replay:
                raise PrivateInputError('Demo cannot mix with private inputs.')
            portfolio,captures,now=demo()
        else:
            text=Path(args.portfolio).read_text() if args.portfolio else os.environ.get('STOCKWATCH_PORTFOLIO')
            if not text or (args.portfolio and Path(args.portfolio).name=='portfolio.example.yaml'):
                raise PrivateInputError('Explicit real private portfolio required; example fallback disabled.')
            portfolio=parse_portfolio(text)
            now=datetime.now(timezone.utc)
            if args.replay:
                snapshot=json.loads(Path(args.replay).read_text())
                if snapshot.get('version') != 'private-capture.1':
                    raise PrivateInputError('Unsupported private capture version.')
                now=instant(snapshot['as_of'])
                captures=snapshot['captures']
            else:
                captures={}
                # Upstream libraries can print ticker, errors or configuration: suppress locally, never log them.
                old_logging=logging.root.manager.disable
                logging.disable(logging.CRITICAL)
                try:
                    with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                        for ticker in sorted({r['ticker'] for r in portfolio['holdings']}|{'SPY'}):
                            try:
                                captures[ticker]=live_capture(ticker)
                            except Exception:
                                captures[ticker]={'status':'unavailable'}
                finally:
                    logging.disable(old_logging)
                now=datetime.now(timezone.utc)
        report=build(portfolio,captures,now)
        write_private(args.output,report,captures)
    except Exception:
        print('Private report failed; check private configuration, output directory and source access locally. No holdings logged.',file=sys.stderr)
        return 1
    print('Private local report written. Holdings and captures must remain private; no notification sent.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
