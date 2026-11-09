"""Tape screen composition from existing saved readings. Display only.

No new indicator, threshold, call or account decision is calculated here.
"""
from __future__ import annotations

from html import escape
import math
from urllib.parse import quote

from . import dayboard, design, simplecall, stockhead, tradelevels, ui

CSS='''
.ts{max-width:800px;margin:auto;color:var(--dz-ink);font:15px/1.5 var(--sans);overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.ts small,.ts-soft{color:var(--dz-soft);font-size:12px}.ts-big{font-size:30px;font-weight:700;line-height:1.15;margin:12px 0 16px}
.ts-price{font-size:38px;font-weight:700;line-height:1.1;margin:12px 0}.ts h3,.stApp .ts h3{font-size:13px !important;color:var(--dz-soft) !important;margin:20px 0 8px}
.ts-tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:12px 0 18px}.ts-tile{background:var(--dz-surface);border:1px solid var(--dz-line);border-radius:14px;padding:11px 12px;min-width:0}
.ts-tile b{display:block;font-size:22px;line-height:1.2;margin:4px 0}.ts-tile small{display:block}
.ts-stock{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 12px;border-top:1px solid var(--dz-line);padding:12px 0}
.ts-stock a{color:var(--dz-ink);font-weight:700;text-decoration:none}.ts-tag{border:1px solid var(--dz-c,var(--dz-line));color:var(--dz-c,var(--dz-ink));border-radius:99px;font-size:12px;padding:2px 9px;align-self:start;white-space:normal}
.ts-stock p{grid-column:1/-1;font-size:12px;color:var(--dz-soft);margin:0}.ts-stock details{grid-column:1/-1;font-size:12px}.ts-stock summary{cursor:pointer;min-height:32px;color:var(--dz-soft)}
.ts-chips{display:flex;flex-wrap:wrap;gap:6px}.ts-chips a{border:1px solid var(--dz-line);border-radius:99px;padding:7px 12px;min-height:44px;color:var(--dz-soft);text-decoration:none;font-size:13px;box-sizing:border-box}
.ts-chips a[aria-current=page]{background:var(--dz-surface);color:var(--dz-ink);font-weight:700}
.ts-call{border-left:3px solid var(--dz-c);padding:12px 14px;margin:16px 0;background:var(--dz-surface);border-radius:12px}.ts-call b{display:block;font-size:30px}
.ts-dots{display:flex;gap:5px;margin:8px 0}.ts-dots i{width:8px;height:8px;border-radius:50%;background:var(--dz-line)}.ts-dots i.on{background:var(--dz-ink)}
.ts-warning{border-left:3px solid var(--dz-watch);padding:8px 12px;font-size:13px;margin:10px 0}.ts-table{background:var(--dz-surface);border:1px solid var(--dz-line);border-radius:14px;padding:6px 12px;margin:8px 0}
.ts-table table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:13px}.ts-table td{padding:9px 0;border-top:1px solid var(--dz-line);vertical-align:top;overflow-wrap:anywhere}.ts-table tr:first-child td{border:0}.ts-table td:last-child{text-align:right;font-weight:600;width:48%}
.ts-table small{display:block;font-weight:400}.ts .sh-r{font-size:13px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 12px;padding:9px 0;border-bottom:1px solid var(--dz-line)}.ts .sh-r small{grid-column:1/-1}
.ts .sh-bad{color:var(--dz-loss)}.ts .sh-good{color:var(--dz-gain)}.ts .sh-mid{color:var(--dz-watch)}.ts .sh-l{font-size:12px;color:var(--dz-soft)}
.ts-px{grid-column:1/-1;font-size:14px}.ts-px small{margin:0 2px 0 6px}.ts-foot{margin:12px 0;color:var(--dz-soft);font-size:12px}.ts-news .sh-n{border-top:1px solid var(--dz-line);padding:10px 0;font-size:13px}.ts-news a{color:var(--dz-ink)}.ts-news small{display:block}
'''


def number(v):
    return v if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) else None


def money(v):
    v=number(v)
    return 'unknown' if v is None else f'${v:,.2f}'


def stock_link(ticker):
    return '?view=target&amp;t='+quote(str(ticker),safe='')


def chips(tickers, selected):
    return '<div class="ts ts-chips">'+''.join(f'<a href="{stock_link(t)}" target="_self"'+(' aria-current="page"' if t==selected else '')+f'>{escape(str(t))}</a>' for t in tickers)+'</div>'


def radar_summary(snaps,market,need,buy,earnings,market_note=""):
    unknown=sum(bool(s.get('payload',{}).get('error')) or s.get('verdict')=='ERROR' for s in snaps)
    headline=f'{len(need)} need'+('s' if len(need)==1 else '')+' your attention' if need else 'Readings incomplete' if unknown else 'Nothing urgent right now'
    tiles=[('Market',market or 'unknown',market_note or 'Market reading unknown'),('Buy zone',str(len(buy)),'Stocks in range'),
           ('Needs attention',str(len(need)),'Stocks to review'),('Earnings this week',str(len(earnings))+' known' if any((s.get('payload',{}).get('events') or {}).get('days_to_earnings') is not None for s in snaps) else 'unknown','Known report dates only')]
    return f'<style>{CSS}</style><div class="ts"><div class="ts-big">{headline}</div><div class="ts-tiles">'+''.join(
        f'<div class="ts-tile"><small>{label}</small><b>{escape(value)}</b><small>{escape(note)}</small></div>' for label,value,note in tiles)+'</div></div>'


def radar_rows(snaps,changed=None):
    rows=[]
    for snap in sorted(snaps,key=lambda s:(bool(s["payload"].get("watchlist")),ui._ring_sort(s))):
        c=simplecall.of(snap)
        pp=ui.price_parts(snap)
        px=f'<b>{money(pp.get("price"))}</b> {design.change_pill(pp.get("day"))}'
        if pp.get('ext'):
            lab,eprice,echg=pp['ext'];px+=f' <small>{escape(lab)} {money(eprice)}</small> {design.change_pill(echg)}'
        elif pp.get('note'):
            px+=f' <small>{escape(pp["note"])}</small>'
        rows.append(f'<div class="ts-stock dz-{c["cls"]}"><a href="{stock_link(snap["ticker"])}" target="_self">{escape(snap["ticker"])}</a>'
                    f'<span class="ts-tag">{escape(c["word"])}</span><div class="ts-px">{px}</div><p>{escape(c["why"] or "No new reading.")}</p>'
                    f'<p>{escape(simplecall.fund_line(c))}</p>'
                    f'<details><summary>How sure: the checks</summary>{dayboard._sure_html({"checks":dayboard.checks(snap),"sell_side":c["group"]=="sell","sure":c["sure"],"change":None})}</details></div>')
    return f'<style>{CSS}</style><div class="ts">'+(''.join(rows) or '<small>No stocks match this view.</small>')+'</div>'


def detail_header(snap):
    p=snap['payload'];pp=ui.price_parts(snap)
    c=simplecall.of(snap)
    dots='';sure=c.get('sure')
    if sure:
        agree,known=sure
        dots='<div class="ts-dots" aria-hidden="true">'+''.join('<i'+(' class="on"' if i<agree else '')+'></i>' for i in range(known))+'</div>'
        certainty=f'{agree} of {known} checks agree'
    else:
        certainty='Checks not counted for this call'
    sub=str(p.get('name') or snap['ticker'])+' · '+('watching' if p.get('watchlist') else 'you own it')
    px=money(pp.get('price'))
    extra=''
    if pp.get('ext'):
        label,price,change=pp['ext'];extra=f'<small>{escape(label)} {money(price)} {design.change_pill(change)}</small>'
    elif pp.get('note'):
        extra=f'<small>{escape(pp["note"])}</small>'
    word,_,why=stockhead.reading(snap)
    line=f'Exit line {c["line"]:,.2f}' if c.get('line') else 'Exit line unknown'
    return (f'<style>{CSS}</style><div class="ts"><div class="ts-price">{px}</div>{design.change_pill(pp.get("day"))}{extra}'
            f'<div><small>{escape(sub)}</small></div><div class="ts-call dz-{c["cls"]}"><b>{escape(c["word"].upper())}</b>{dots}<small>{escape(certainty)}</small></div>'
            f'<small>{escape(c["why"])}</small><div class="ts-foot">{escape(line)} · {escape(simplecall.fund_line(c))}</div>'
            f'<small>{escape(word)} · {escape(why)}</small></div>')


def detail_ladder(snap):
    rows=stockhead.ladder(snap)
    return tradelevels.scaled_html(rows,number(ui.price_parts(snap).get('price')))


def detail_tables(snap,now=None):
    p=snap['payload'];plan=p.get('plan') or {}
    levels={row['label']:row for row in stockhead.ladder(snap)}
    plan_rows=[]
    for label in ('Exit line','Plan stop'):
        row=levels.get(label) or {}
        plan_rows.append((label,money(row.get('level')),row.get('note','No saved level')))
    targets=plan.get('targets') or []
    target=targets[0].get('price') if targets else None
    rr=number(plan.get('rr'))
    plan_rows.extend([('First target',money(target),''),('Reward against risk',f'{rr:g} to 1' if rr is not None else 'unknown','')])
    plan_html=''.join(f'<tr><td>{escape(label)}<small>{escape(note)}</small></td><td>{value}</td></tr>' for label,value,note in plan_rows)
    chart=''.join(stockhead.technicals(snap)) or '<small>Chart values unknown.</small>'
    company=''.join(stockhead.fundamentals(snap))
    return (f'<style>{CSS}</style><div class="ts"><h3>Your plan</h3><div class="ts-table"><table>{plan_html or "<tr><td>Plan unknown</td></tr>"}</table></div>'
            f'<h3>Chart</h3><div class="ts-table">{chart}</div><h3>Company</h3><div class="ts-table">{company}</div>'
            f'<h3>News</h3><div class="ts-table ts-news">{stockhead._news_html(snap,now)}</div></div>')
