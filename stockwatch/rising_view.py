"""Tape Momentum rows, from existing saved readings. Display only."""
from __future__ import annotations

from datetime import datetime
from html import escape
import math
from urllib.parse import quote
from zoneinfo import ZoneInfo

CSS='''
.tm{max-width:800px;margin:auto;color:var(--dz-ink);font:15px/1.5 var(--sans);overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.tm-big{font-size:30px;font-weight:700;line-height:1.1;margin:12px 0}.tm small{font-size:12px;color:var(--dz-soft)}
.tm-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 12px;border-top:1px solid var(--dz-line);padding:12px 0}
.tm-row a{color:var(--dz-ink);font-weight:700;text-decoration:none}.tm-right{grid-column:2;grid-row:1/3;text-align:right;font-weight:600;white-space:nowrap}
.tm-right small{display:block;font-weight:400}.tm-up{color:var(--dz-gain)}.tm-dn{color:var(--dz-loss)}
.tm-reason{font-size:12px;color:var(--dz-soft)}.tm-tag{font-size:11px;color:var(--dz-soft);margin-left:6px}
.tm details{margin:12px 0}.tm summary{min-height:44px;cursor:pointer;color:var(--dz-soft);font-size:12px}
.tm-metrics{width:100%;table-layout:fixed;border-collapse:collapse;font-size:12px}.tm-metrics td,.tm-metrics th{padding:8px 3px;text-align:left;overflow-wrap:anywhere;border-bottom:1px solid var(--dz-line)}
'''
ARROW={1:'▲',-1:'▼',0:'●'}


def _num(v):
    return v if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) else None


def _value(v,precision=1,signed=False):
    v=_num(v)
    return 'unknown' if v is None else format(v,('+' if signed else '')+f'.{precision}f')


def _arrow(r,key):
    return ' '+ARROW.get((r.get('dir') or {}).get(key),'') if key in (r.get('dir') or {}) else ''


def reason(row):
    if row.get('miss'):
        return 'Waiting: '+str(row['miss'])
    if row.get('tag')=='FADING':
        return 'Price and momentum fell since the previous run.'
    rsi,hist=_num(row.get('rsi_d')),_num(row.get('hist_d'))
    if rsi is None or hist is None:
        return 'Momentum change unknown.'
    return ('RSI rising' if rsi>0 else 'RSI not rising')+'; '+('MACD improving.' if hist>0 else 'MACD not improving.')


def table(rows: list[dict]) -> str:
    """Compact rows as in Tape; preserve the old measurements behind a disclosure."""
    body=[];measurements=[]
    for r in rows:
        ticker=str(r.get('t') or 'unknown')
        sym=escape(ticker)
        tags=(' <span class="tm-tag">yours</span>' if r.get('tracked') else '')
        if r.get('tag') in ('NEW','FADING'):
            tags+=f'<span class="tm-tag">{r["tag"]}</span>'
        change=_num(r.get('chg'))
        move='unknown' if change is None else _value(change,signed=True)+'%'
        tone='' if change is None or change==0 else 'tm-up' if change>0 else 'tm-dn'
        vol='unknown' if _num(r.get('vol_x')) is None else f'{r["vol_x"]:.1f}× normal'
        body.append(f'<div class="tm-row"><div><a href="?view=target&amp;t={quote(ticker,safe="")}" target="_self">{sym}</a>{tags}</div>'
                    f'<div class="tm-right {tone}">{move}<small>Volume {vol}</small></div>'
                    f'<div class="tm-reason">{escape(reason(r))}</div></div>')
        measurements.append(f'<tr><td>{sym}</td><td>{_value(r.get("price"),2)}{_arrow(r,"price")}</td>'
                            f'<td>{_value(r.get("rsi"))}{_arrow(r,"rsi")}<br>change {_value(r.get("rsi_d"),signed=True)}<br>day {_value(r.get("rsi_day"),0)}</td>'
                            f'<td>{_value(r.get("hist"),2,True)}{_arrow(r,"hist")}<br>change {_value(r.get("hist_d"),2,True)}</td>'
                            f'<td>{vol}{_arrow(r,"vol")}</td></tr>')
    return (f'<style>{CSS}</style><div class="tm">'+(''.join(body) or '<small>No stocks in this run.</small>')+
            ('<details><summary>Measurements · arrows compare the previous run</summary><table class="tm-metrics"><thead><tr>'
             '<th>Stock</th><th>Price</th><th>RSI</th><th>MACD</th><th>Volume</th></tr></thead><tbody>'+''.join(measurements)+'</tbody></table></details>' if rows else '')+'</div>')


def stamp(state: dict) -> str:
    try:
        at=datetime.fromisoformat(str(state.get('at')))
        if at.tzinfo is None:
            return 'unknown time zone'
        return f'{at.astimezone(ZoneInfo("America/New_York")):%H:%M} New York, {at.astimezone(ZoneInfo("Asia/Riyadh")):%H:%M} Riyadh'
    except (ValueError,TypeError):
        return 'unknown time'


def headline(state: dict) -> str:
    count=_num(state.get('pass'))
    value='unknown' if count is None else f'{count:g}'
    return (f'<style>{CSS}</style><div class="tm"><small>Rising now</small><div class="tm-big">{value} stocks building momentum</div>'
            f'<small>Updated {escape(stamp(state))}</small></div>')


def left_line(state: dict) -> str:
    out=state.get('left') or []
    return '' if not out else 'Left the list: '+'; '.join(f'{x["t"]} ({x["why"]})' for x in out)
