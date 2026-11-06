"""Read-only untracked-index data, not connected to trading or the tracker yet.

Tracker integration calls refresh(tracked, now), which only starts one daemon
worker and returns. snapshots(now) performs no I/O. Yahoo download calls are
batched and share the existing throttle; internal parallel downloads are off.
No calls, scores, plans or synthetic BUY verdicts are generated.
"""
from __future__ import annotations

import copy
import logging
import math
import pickle
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from .data import NY, _yahoo, us_session
from .technical import atr

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
BUNDLED = Path(__file__).parent / 'universe' / 'sp500.csv'
COLS = ['Open', 'High', 'Low', 'Close', 'Volume']


def _number(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


@_yahoo
def _download(tickers, interval):
    import yfinance as yf
    frame = yf.download(list(tickers), period='3mo' if interval == '1d' else '1d', interval=interval,
                        group_by='ticker', auto_adjust=True, prepost=False,
                        threads=False, progress=False, timeout=5)
    out = {}
    for ticker in tickers:
        try:
            if isinstance(frame.columns, pd.MultiIndex):
                sub = frame[ticker] if ticker in frame.columns.get_level_values(0) else frame.xs(ticker, axis=1, level=1)
            else:
                sub = frame if len(tickers) == 1 else pd.DataFrame()
            out[ticker] = sub.reindex(columns=COLS).dropna(how='all')
        except KeyError:
            out[ticker] = pd.DataFrame(columns=COLS)
    return out


def earnings_dates(path: Path, now: datetime) -> dict:
    """Read only the owner's trusted local study pickle. Never download dates.

    Missing/stale or history-only dates do not imply no upcoming earnings.
    Pickles must never come from an untrusted upload or remote source.
    """
    try:
        if not 0 <= now.timestamp() - path.stat().st_mtime <= 7 * 86400:
            return {}
        value = pickle.loads(path.read_bytes())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, EOFError, pickle.UnpicklingError, TypeError):
        return {}


def _record(ticker, daily, minute, now, dates, min_price, min_volume):
    reasons = []
    row = {'ticker': ticker, 'price': None, 'fetched_at': now.isoformat(), 'as_of': None,
           'change': None, 'volume': None, 'vol_avg20': None, 'atr': None,
           'days_to_earnings': None, 'bars': pd.DataFrame(columns=COLS), 'chart': None,
           'eligible': False, 'why': [], 'payload': {}}
    try:
        daily = daily[COLS].sort_index()
        daily = daily[~daily.index.duplicated(keep='last')]
        daily = daily[[pd.Timestamp(t).date() < now.date() for t in daily.index]]
        # Require a complete trailing window; dropping bad observations would
        # silently turn a 20-session average into a shorter one.
        tail = daily.tail(20)
        if len(tail) < 20 or tail.isna().any().any() or not all(math.isfinite(float(v)) for v in tail.to_numpy().flat):
            raise ValueError('incomplete daily window')
        if (tail[['Open','High','Low','Close']] <= 0).any().any() or (tail['Volume'] < 0).any():
            raise ValueError('invalid daily values')
        if (now.date() - pd.Timestamp(tail.index[-1]).date()).days > 4:
            raise ValueError('daily history is stale')
        row['vol_avg20'] = float(tail['Volume'].mean())
        row['atr'] = float(atr(tail).iloc[-1])
        previous = float(tail['Close'].iloc[-1])
    except (KeyError, ValueError, TypeError, IndexError):
        previous = None
        reasons.append('Daily history missing, invalid or stale; average volume, change or ATR unknown.')
    try:
        minute = minute[COLS].sort_index()
        if minute.index.tz is None:
            raise ValueError('minute timestamps have no timezone')
        minute.index = minute.index.tz_convert(NY)
        minute = minute[~minute.index.duplicated(keep='last')]
        minute = minute[[t.date() == now.date() and (9,30) <= (t.hour,t.minute) < (16,0) and t <= now for t in minute.index]]
        if minute.empty or minute.isna().any().any():
            raise ValueError('incomplete minute bars')
        if not all(math.isfinite(float(v)) for v in minute.to_numpy().flat):
            raise ValueError('nonfinite minute bars')
        if (minute[['Open','High','Low','Close']] <= 0).any().any() or (minute['Volume'] < 0).any():
            raise ValueError('invalid minute values')
        row.update(price=float(minute['Close'].iloc[-1]), volume=float(minute['Volume'].sum()),
                   as_of=minute.index[-1].isoformat(), bars=minute.copy())
        row['change'] = row['price'] / previous - 1 if previous else None
        row['chart'] = {'day':now.date().isoformat(), 'open':float(minute['Open'].iloc[0]),
                        'hi':float(minute['High'].max()), 'lo':float(minute['Low'].min()),
                        's':[[t.timestamp(), float(p)] for t,p in minute['Close'].items()]}
    except (KeyError, ValueError, TypeError, IndexError, AttributeError):
        reasons.append('Today’s regular-session minute bars or volume are unknown.')
    upcoming = []
    for d in dates.get(ticker, []) or []:
        try:
            day = pd.Timestamp(d).date()
            if day >= now.date():
                upcoming.append((day - now.date()).days)
        except (TypeError, ValueError):
            pass
    row['days_to_earnings'] = min(upcoming) if upcoming else None
    if row['price'] is not None and row['price'] < min_price:
        reasons.append(f'Price below {min_price:g} feed minimum.')
    if row['vol_avg20'] is not None and row['vol_avg20'] < min_volume:
        reasons.append(f'20-day average volume below {min_volume:g} feed minimum.')
    if row['vol_avg20'] is None or row['vol_avg20'] <= 0 or row['volume'] is None:
        reasons.append('Volume or average volume unknown or not positive.')
    if row['atr'] is None or not math.isfinite(row['atr']) or row['atr'] <= 0:
        reasons.append('ATR unknown or not positive.')
    row['why'] = reasons
    row['eligible'] = not reasons
    row['payload'] = {'quote': {'market_state':'REGULAR', 'live_price':row['price'], 'live_time':row['as_of'],
                                'live_change':row['change'], 'live_volume':row['volume'], 'fetched_at':row['fetched_at']},
                      'technical': {'atr':row['atr'], 'vol_avg20':row['vol_avg20']},
                      'events': {'days_to_earnings':row['days_to_earnings']}}
    row['earnings_note'] = '' if upcoming else 'Next earnings date unknown in the local cache.'
    return row


class Feed:
    def __init__(self, *, universe=None, download=None, clock=None, batch_size=50,
                 min_price=5., min_volume=500_000., max_age=120., max_seconds=20., refresh_seconds=60.):
        if batch_size < 1 or any(not math.isfinite(v) or v < 0 for v in (min_price,min_volume,max_age,max_seconds,refresh_seconds)):
            raise ValueError('invalid feed settings')
        self.universe = universe
        self.download = download or _download
        self.clock = clock or (lambda: datetime.now(NY))
        self.batch_size, self.min_price, self.min_volume = batch_size, min_price, min_volume
        self.max_age, self.max_seconds, self.refresh_seconds = max_age, max_seconds, refresh_seconds
        self._lock, self._busy = threading.Lock(), False
        self._rows, self._daily, self._daily_day = {}, {}, None
        self._excluded, self._attempt = set(), None
        self.stats = {'calls':0, 'seconds':None, 'error':None}

    def refresh(self, tracked, now=None):
        """Non-blocking tracker entry point. No overlapping or off-session work."""
        now = (now or self.clock()).astimezone(NY)
        with self._lock:
            self._excluded = set(tracked)
            if us_session(now) != 'REGULAR' or self._busy:
                return False
            if self._attempt is not None and 0 <= (now - self._attempt).total_seconds() < self.refresh_seconds:
                return False
            self._busy, self._attempt = True, now
        threading.Thread(target=self._work, args=(now,), daemon=True, name='universe-feed').start()
        return True

    def _work(self, now):
        start, calls = time.monotonic(), 0
        def fetch(group, interval):
            nonlocal calls
            if time.monotonic() - start > self.max_seconds:
                raise TimeoutError()
            calls += 1
            result = self.download(group, interval)
            if time.monotonic() - start > self.max_seconds:
                raise TimeoutError()
            return result
        try:
            universe = self.universe if self.universe is not None else pd.read_csv(BUNDLED)['ticker']
            with self._lock:
                names = sorted(set(universe) - self._excluded)
            daily = self._daily.copy() if self._daily_day == now.date() else {}
            minute = {}
            for i in range(0,len(names),self.batch_size):
                group = names[i:i+self.batch_size]
                missing = [t for t in group if t not in daily or daily[t].empty]
                if missing:
                    daily.update(fetch(missing,'1d'))
                minute.update(fetch(group,'1m'))
            fetched = self.clock().astimezone(NY)
            if fetched.date() != now.date() or us_session(fetched) != 'REGULAR':
                raise TimeoutError('session ended')
            dates = earnings_dates(ROOT / 'data' / 'earnings_dates_cache.pkl', fetched)
            rows = {t:_record(t,daily.get(t,pd.DataFrame()),minute.get(t,pd.DataFrame()),fetched,dates,self.min_price,self.min_volume) for t in names}
            with self._lock:
                self._rows, self._daily, self._daily_day = rows, daily, now.date()
                self.stats = {'calls':calls, 'seconds':time.monotonic()-start, 'error':None}
        except Exception as exc:
            # Avoid provider exception bodies: they can contain private addresses.
            with self._lock:
                self.stats = {'calls':calls, 'seconds':time.monotonic()-start, 'error':type(exc).__name__}
            log.warning('untracked feed skipped cycle: %s',type(exc).__name__)
        finally:
            with self._lock:
                self._busy = False

    def records(self, now=None):
        """Full diagnostic table, including filtered, stale and missing records."""
        now = (now or self.clock()).astimezone(NY)
        with self._lock:
            rows = copy.deepcopy([r for t,r in self._rows.items() if t not in self._excluded])
            error = self.stats['error']
        for r in rows:
            stale = us_session(now) != 'REGULAR'
            for key in ('fetched_at','as_of'):
                try:
                    age = (now - datetime.fromisoformat(r[key])).total_seconds()
                    stale |= not 0 <= age <= self.max_age
                except (ValueError, TypeError):
                    stale = True
            if stale:
                r['why'].append('Quote is stale or outside the regular session.')
            if error:
                r['why'].append('Latest feed cycle failed: '+error)
            r['eligible'] = r['eligible'] and not stale and not error
        return rows

    def snapshots(self, now=None):
        """Only fresh qualifying snapshots; no network or trading side effects."""
        return [r for r in self.records(now) if r['eligible']]


_feed = Feed()


def refresh(tracked, now=None):
    return _feed.refresh(tracked, now)


def snapshots(now=None):
    return _feed.snapshots(now)


def records(now=None):
    return _feed.records(now)
