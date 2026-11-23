# Untracked index feed (Codex task 2 from PR #75)

Read-only module; no tracker, Quick or New call integration yet. Claude connects it after review.

Tracker integration:

```python
from stockwatch import universe_feed
universe_feed.refresh(tracked_tickers, now)  # schedules one background cycle, returns immediately
rows = universe_feed.snapshots(now)         # only fresh, eligible records; no network
all_rows = universe_feed.records(now)       # includes filter/missing/stale reasons
```

The singleton reads the bundled index list. Pass every tracked ticker (including watchlist stocks) to exclude them. Filters are constructor settings on `Feed`: `min_price=5`, `min_volume=500_000`, `batch_size=50`, `max_age=120`, `max_seconds=20`, `refresh_seconds=60`. A private caller can instantiate its own feed with different settings. No account thresholds are changed.

Each record has price, fetch and bar times, fractional day change versus the last completed daily close, today's regular-session volume, 20 completed sessions' average volume, ATR (existing 14-period formula), current-day minute OHLCV bars, a full-day `chart` path compatible with `quick.read_chart`, cached days to earnings, and `payload.quote/technical/events` fields. `paper_live.fresh_price` accepts fresh records. No score, call, plan or BUY label is invented. Claude must decide how to rank records without those fields.

Missing or stale price, volume, daily average or ATR excludes a record with reasons. Zero measured volume remains zero. The next earnings date is independently unknown if no future date is in the trusted local weekly cache; historical earnings dates are not proof there is no upcoming report. Feed eligibility alone is not an earnings clearance or trading authorization.

Only regular-session cycles start (existing New York clock helper; its holiday limitation remains). Old, naive, future-day, incomplete or nonfinite minute data cannot enter ranking. Snapshots are copied so a caller cannot mutate the cache. A cycle failure invalidates the previous table for ranking until a successful cycle; diagnostic rows remain available. No overlapping refreshes.

Every Yahoo bulk-download invocation uses the existing `_yahoo` semaphore and `threads=False`, avoiding internal parallel calls that would exceed the shared limit. Minute data is requested once per batch per cycle; daily history is cached for the session. There are no new per-stock metadata/earnings requests. **A yfinance download is a logical multi-ticker invocation, not one guaranteed HTTP request:** the library performs underlying per-ticker requests. Live HTTP counts and timing remain unverified; this distinction is a limitation against a literal “one HTTP request per batch” reading of the brief.

The worker deadline discards late results and stops further batches. An in-flight yfinance batch cannot be cancelled by this module, so it can remain busy beyond the deadline; refresh calls still return immediately and overlapping workers are refused. Downloads have a five-second library request timeout. The worker occupies at most one shared Yahoo slot; it cannot promise zero competition with the existing tracker. A live benchmark is required before enabling this feed on the owner's PC.

Measured with in-memory, handmade frames for 270 invented stocks (50 minute bars each):

| Cycle | Logical bulk calls | Elapsed | Eligible |
|---|---:|---:|---:|
| Cold | 12 | 2.10 s | 270 |
| Warm daily cache | 6 | 1.95 s | 270 |

These are **offline parsing/copying measurements**, not Yahoo latency or HTTP request counts. The runtime network policy does not permit Yahoo, so no live downloads were attempted. The default 20-second deadline is configurable and has not been calibrated to live refreshes.
