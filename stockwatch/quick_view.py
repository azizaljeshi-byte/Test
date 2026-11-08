"""Tape Quick display. Stored values only; no trading, scoring or provider calls."""
from __future__ import annotations

from datetime import datetime
from html import escape
import math
from urllib.parse import quote
from zoneinfo import ZoneInfo

from . import paper_layout as pl

NY, RIYADH = ZoneInfo('America/New_York'), ZoneInfo('Asia/Riyadh')
CSS = '''
.tq{color:var(--dz-ink);font:15px/1.5 var(--sans);max-width:800px;margin:auto;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.tq h2{font-size:17px;margin:8px 0}.tq h3{font-size:13px;color:var(--dz-soft);margin:20px 0 8px}.tq small,.tq-muted{color:var(--dz-soft);font-size:12px}
.tq-day{font-size:46px;font-weight:700;line-height:1.1;margin:6px 0}.tq-up{color:var(--dz-gain)}.tq-dn{color:var(--dz-loss)}
.tq-watch{background:var(--dz-surface);border:1px solid var(--dz-line);border-radius:14px;padding:12px}
.tq-w{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 10px;padding:6px 0}.tq-w small{grid-column:1/-1}
.tq-pill{font-size:12px;border:1px solid var(--dz-line);border-radius:99px;padding:3px 9px;align-self:start;color:var(--dz-soft)}
.tq-row{display:grid;grid-template-columns:64px minmax(0,1fr) auto;gap:10px;align-items:center;border-top:1px solid var(--dz-line);padding:12px 0}
.tq-row.no-path{grid-template-columns:minmax(0,1fr) auto}.tq-row a,.tq-w a{color:var(--dz-ink);text-decoration:none;font-weight:700}
.tq-row small{display:block}.tq-result{text-align:right;white-space:nowrap;font-weight:600}.tq-reason,.tq-levels{grid-column:1/-1;font-size:12px;color:var(--dz-soft)}
.tq-row svg{display:block;width:100%;height:40px}.tq-foot{margin-top:16px;padding-top:12px;border-top:1px solid var(--dz-line);color:var(--dz-soft);font-size:12px}
.tq-note{padding:10px 0;color:var(--dz-soft);font-size:13px}.tq details{margin-top:12px}.tq summary{cursor:pointer;min-height:44px}
'''


def _num(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else None


def _price(value):
    n=_num(value)
    return 'unknown' if n is None else f'{n:,.2f}'


def _money(value, signed=False):
    n=_num(value)
    if n is None:
        return 'unknown'
    sign=('+' if n>=0 else '−') if signed else ('−' if n<0 else '')
    return f'{sign}${abs(n):,.2f}'


def _pct(value):
    n=_num(value)
    return 'unknown' if n is None else f'{n:+.1f}%'


def _tone(value):
    n=_num(value)
    return '' if n is None or n==0 else 'tq-up' if n>0 else 'tq-dn'


def _when(value):
    try:
        at=datetime.fromisoformat(str(value))
        return at.replace(tzinfo=NY) if at.tzinfo is None else at
    except (ValueError,TypeError):
        return None


def _day(value):
    at=_when(value)
    return at.astimezone(NY).date() if at else None


def _time(value):
    at=_when(value)
    return at.astimezone(RIYADH).strftime('%d %b · %H:%M') if at else 'unknown time'


def _link(ticker):
    text='unknown' if ticker is None else str(ticker)
    return f'<a href="?view=target&amp;t={quote(text,safe="")}" target="_self">{escape(text)}</a>'


def day_summary(book: dict, prices: dict, now: datetime) -> dict:
    """Same components as quick.day_result; incomplete results stay unknown.

    Win share uses only closed-today trades with measured outcomes (flat is not
    a win). An undated closed trade makes the day's total indeterminate.
    """
    today=now.astimezone(NY).date()
    closed=[t for t in book.get('trades',[]) if t.get('status')=='CLOSED' and _day(t.get('closed'))==today]
    outcomes=[_num(t.get('result')) for t in closed]
    known=[n for n in outcomes if n is not None]
    unknown=int('trades' not in book or 'positions' not in book)+sum(n is None for n in outcomes)+sum(t.get('status')=='CLOSED' and _day(t.get('closed')) is None for t in book.get('trades',[]))
    live=[]
    for ticker,pos in book.get('positions',{}).items():
        price,entry,shares=(_num(v) for v in (prices.get(ticker),pos.get('entry'),pos.get('shares')))
        if price is None or entry is None or shares is None or price<=0 or entry<=0 or shares<=0:
            unknown+=1
        else:
            live.append((price-entry)*shares)
    total=sum(known)+sum(live) if not unknown else None
    return {'total':total, 'closed':len(closed), 'known':len(known), 'unknown':unknown,
            'win_share':sum(n>0 for n in known)/len(known) if known else None,
            'open':len(book.get('positions',{}))}


def price_path(trade: dict) -> str:
    """Draw only an explicitly saved [timestamp, price] path. No invented points.

    Timestamp is ISO or epoch seconds. Event dots use actual event times/prices
    and are omitted if their time is outside the saved window. No path is
    currently saved on Quick trades; absence deliberately renders no SVG.
    """
    path=trade.get('path')
    if not isinstance(path,list) or len(path)<2:
        return ''
    points=[]
    for item in path:
        if not isinstance(item,(list,tuple)) or len(item)!=2:
            return ''
        when,price=item
        at=_when(when) if isinstance(when,str) else None
        sec=at.timestamp() if at else _num(when)
        price=_num(price)
        if sec is None or price is None or price<=0 or (points and sec<=points[-1][0]):
            return ''
        points.append((sec,price))
    lo_t,hi_t=points[0][0],points[-1][0]
    entry,stop,exit_=(_num(trade.get(k)) for k in ('entry','stop0','exit'))
    values=[p for _,p in points]+[p for p in (entry,stop,exit_) if p is not None and p>0]
    low,high=min(values),max(values)
    span=high-low or high*.01
    x=lambda t:4+(t-lo_t)/(hi_t-lo_t)*112
    y=lambda p:35-(p-low)/span*30
    coords=' '.join(f'{x(t):.2f},{y(p):.2f}' for t,p in points)
    marks=''
    result=_num(trade.get('result'))
    exit_color='--dz-ink' if result is None or result==0 else '--dz-gain' if result>0 else '--dz-loss'
    for time_key,price,color in (('opened',entry,'--dz-ink'),('closed',exit_,exit_color)):
        at=_when(trade.get(time_key))
        if at and price is not None and price>0 and lo_t<=at.timestamp()<=hi_t:
            marks+=f'<circle cx="{x(at.timestamp()):.2f}" cy="{y(price):.2f}" r="3" fill="var({color})"/>'
    stop_line=f'<line x1="4" x2="116" y1="{y(stop):.2f}" y2="{y(stop):.2f}" stroke="var(--dz-loss)" stroke-dasharray="3 3"/>' if stop is not None and stop>0 else ''
    return (f'<svg viewBox="0 0 120 40" role="img" aria-label="{escape(str(trade.get("ticker") or "Stock"),quote=True)} saved price path">'
            f'<title>Saved observations; entry and exit dots when timed; dashed initial stop {_price(stop)}</title>{stop_line}'
            f'<polyline fill="none" stroke="var(--dz-soft)" stroke-width="1.6" points="{coords}"/>{marks}</svg>')


def trade_row(trade: dict, position=None, price=None) -> str:
    opened=trade.get('status')=='OPEN'
    result,pct=_num(trade.get('result')),_num(trade.get('pct'))
    if opened:
        entry,shares=(_num((position or {}).get(k)) for k in ('entry','shares'))
        price=_num(price)
        result=(price-entry)*shares if price is not None and entry is not None and shares is not None and entry>0 and price>0 and shares>0 else None
        pct=(price/entry-1)*100 if result is not None else None
    display_entry=(position or {}).get('entry') if opened else trade.get('entry')
    path=price_path(trade)
    rank,of=_num(trade.get('rank')),_num(trade.get('of'))
    ranking=f'{rank:g} of {of:g}' if rank is not None and of is not None else 'unknown'
    tags=' · '.join(label for label,_ in pl.sold_tags(trade))
    reason=trade.get('reason') if opened else trade.get('exit_reason')
    return (f'<div class="tq-row{ "" if path else " no-path"}"><div>{_link(trade.get("ticker"))}<small>{_time(trade.get("opened"))}</small></div>{path}'
            f'<div class="tq-result {_tone(result)}">{_money(result,True)}<small>{_pct(pct)}</small></div>'
            f'<div class="tq-levels">Entry {_price(display_entry)} · Initial stop {_price(trade.get("stop0"))} · '
            f'{"Now " + _price(price) if opened else "Exit " + _price(trade.get("exit")) + " at " + _time(trade.get("closed"))}<br>'
            f'Signal {_price(trade.get("signal"))} · Pullback low {_price(trade.get("pullback_low"))} · Rank {ranking}</div>'
            f'<div class="tq-reason">{escape(str(reason)) if reason else "Reason unknown"}{" · " + escape(tags) if tags else ""}</div></div>')


def parts(st: dict, prices: dict | None=None, now=None) -> tuple[str,list,str]:
    """Retain the existing split so native sell/confirm buttons keep their callbacks."""
    now=(now or datetime.now(NY)).astimezone(NY)
    book,state=st.get('book') or {},st.get('state') or {}
    prices=prices or {}
    summary=day_summary(book,prices,now)
    won='unknown' if summary['win_share'] is None else f"{summary['win_share']:.0%}"
    top=(f'<div class="tq"><h2>Quick trading</h2><small>Quick · {now:%d %b} NY · day total</small>'
         f'<div class="tq-day {_tone(summary["total"])}">{_money(summary["total"],True)}</div>'
         f'<small>{summary["closed"]} closed trades · {won} won ({summary["known"]} known) · {summary["open"]} open<br>Closed today + open result</small>')
    if summary['unknown']:
        top+=f'<div class="tq-note">{summary["unknown"]} required readings unknown; day total unavailable.</div>'
    if state.get('note'):
        top+=f'<div class="tq-note">{escape(str(state["note"]))}</div>'
    for ticker,why in (state.get('skipped') or {}).items():
        if ticker in book.get('positions',{}):
            top+=f'<div class="tq-note">{escape(str(ticker))}: {escape(str(why))}</div>'
    if st.get('sheet_error'):
        top+=f'<div class="tq-note">Not saved to Drive: {escape(str(st["sheet_error"]))}</div>'
    top+='<h3>Waiting for a pullback</h3><div class="tq-watch">'
    watch=book.get('watch') or {}
    for ticker,w in watch.items():
        low=_num(w.get('pull_lo'))
        word='Dipped, waiting for the turn' if low is not None and low>0 else 'Waiting for a dip'
        top+=(f'<div class="tq-w">{_link(ticker)}<span class="tq-pill">{word}</span>'
              f'<small>Signal {_price(w.get("p0"))} · Pullback low {_price(w.get("pull_lo"))}</small></div>')
    top+=('' if watch else '<small>No stocks waiting.</small>')+'</div><h3>Open now</h3></div>'
    opens=[]
    for trade in book.get('trades',[]):
        pos=book.get('positions',{}).get(trade.get('ticker'))
        if trade.get('status')=='OPEN' and pos:
            opens.append((trade['ticker'],trade_row(trade,pos,prices.get(trade['ticker']))))
    closed=[t for t in reversed(book.get('trades',[])) if t.get('status')=='CLOSED']
    rest='<div class="tq"><h3>Closed</h3>'+(''.join(trade_row(t) for t in closed[:15]) or '<small>No closed trades yet.</small>')
    if len(closed)>15:
        rest+=f'<small>Showing the latest 15 of {len(closed)} closed trades.</small>'
    rest+=(f'<details><summary>Account and skipped setups</summary><small>Start {_money(book.get("start"))} · Cash {_money(book.get("cash"))}</small>')
    for ticker,why in (state.get('skipped') or {}).items():
        rest+=f'<div class="tq-note">{escape(str(ticker))}: {escape(str(why))}</div>'
    for item in reversed(book.get('skipped',[])[-8:]):
        rest+=f'<div class="tq-note">{escape(str(item.get("ticker") or "unknown"))}: {escape(str(item.get("reason") or "Reason unknown"))}</div>'
    rest+='</details><div class="tq-foot">Fake money only · dates and times Riyadh.</div></div>'
    return top,opens,rest


def open_html(opens: list) -> str:
    return '<div class="tq">'+(''.join(card for _,card in opens) or '<small>No open trades.</small>')+'</div>'


def html(st: dict, prices: dict | None=None, now=None) -> str:
    top,opens,rest=parts(st,prices,now)
    return f'<style>{CSS}</style>{top}{open_html(opens)}{rest}'
