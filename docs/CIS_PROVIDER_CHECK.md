# Second market-data source: can anything corroborate Yahoo? (Issue #29, deliverable B)

Research only, 23 Oct 2026. No subscription, secret, integration or provider call was made.

## Bottom line

**Status: OPEN validation item.** No second source has corroborated anything yet; this is a desk review.

- **Side-by-side ISRG sample: NOT VERIFIED for every provider.** This build environment can't reach any
  market-data host (Yahoo, Alpaca, Massive/Polygon, Finnhub, Twelve Data, Stooq all fail to connect, and their
  documentation sites don't resolve), and no provider credentials exist here. Nothing below was measured.
- **Recommendation: defer a paid confirmation feed. If you want corroboration now, try Alpaca's free plan for
  completed daily bars only**, run privately with your own key through the offline comparison helper
  (`stockwatch/cis/source_check.py`). It can corroborate completed daily OHLC from consolidated (SIP) history at
  no cost; it cannot corroborate live quotes (free real-time is IEX-only, a few percent of volume).
- For a real-time consolidated second quote, the cheapest documented options are Massive (Polygon) Starter
  (~$29/month, 15-minute delayed) or Alpaca Algo Trader Plus (~$99/month, real-time SIP). Neither is needed
  for CIS v1, whose decisions use completed daily closes.

## What the providers document (doc-reported, NOT verified)

Every row comes from search results quoting the providers' docs or third parties; the providers' own pages
couldn't be opened from here. Treat prices and limits as "check before buying".

| | Alpaca | Massive (formerly Polygon) | Finnhub (current free key) | Twelve Data |
|---|---|---|---|---|
| Free tier coverage | real-time **IEX only**; historical SIP (all exchanges) except the latest 15 minutes | end-of-day data, ~5 calls/min, about 1–2 years of history (sources differ) | real-time US quote (third parties); **daily candles may return "no access" on free keys** (user report) | default feed is real-time but from venues worth **~5% of US volume** (Twelve Data support) |
| Paid tier | Algo Trader Plus ~$99/mo: real-time SIP, no history restriction | Starter ~$29/mo (15-min delayed), Developer ~$79/mo, Advanced ~$199/mo real-time (third-party, pricing page not confirmed) | All-in-one / market-data plans ~$50/mo (sources conflict) | Grow ~$29/mo (Level A), Pro, Ultra; full consolidated feed by contacting sales |
| Rate limits | free: 200 calls/min | free: 5/min; paid: unlimited | free: 60/min | free: 8 credits/min, 800/day |
| Extended hours | trades in pre/post on SIP history; free real-time IEX only | in trades/aggregates on paid tiers (not confirmed) | not confirmed | pre/post listed on a higher paid tier |
| Adjustment | bars are **raw by default**; `adjustment=split / dividend / spin-off / all` (forum reports of missed corporate actions) | `adjusted=true` by default; split-only vs split+dividend is **documented inconsistently** | not confirmed | not confirmed |
| Timestamps | RFC-3339 (UTC) per the API reference (not confirmed here) | Unix milliseconds, UTC (off-by-one-day risk if read as New York) | Unix seconds | exchange-local strings |
| Licensing | free plan for testing, "not for live trading decisions" (Alpaca staff) | individual / non-professional prices; business separate | free for personal, non-commercial use | exchange licensing on paid levels |

## How to run the ISRG comparison once you approve a source

1. Privately download ISRG daily bars for 2025-10-01 to 2026-10-22 from the second source, **split- and
   dividend-adjusted** to match the reference convention (OHLC × adjusted-close / close; volume as reported),
   as a CSV with Date, Open, High, Low, Close, Volume.
2. `compare(yahoo_bars, other_bars, ("yahoo", "other"), "2026-10-22")` from `stockwatch/cis/source_check.py`,
   with `yahoo_bars` = `stockwatch/cis/fixtures/ISRG-adjusted-daily.csv`.
3. It reports, separately: sessions only one source has (a missing or partial session), a drifting close ratio
   (an adjustment difference), a volume gap (exchange coverage, e.g. IEX-only), and each source's own SMA20/50/200,
   RSI14, ATR14 and relative volume on the last common session. Live quotes need matching trade timestamps on
   both sides; compare trade times, never fetch times.

## Risks

- A single-venue (IEX) feed agreeing with Yahoo on price says little about volume or relative volume.
- Adjustment conventions differ by default (raw vs split vs split+dividend); a mismatch there isn't an error.
- Free tiers are for testing; terms can change (Finnhub candle access already has).
- Another source adds keys, rate limits and a failure mode; it should stay optional and fail to "unknown".

## Sources (search results; pages not opened)

- Alpaca: [About Market Data API](https://docs.alpaca.markets/docs/about-market-data-api),
  [forum: adjusted bars](https://forum.alpaca.markets/t/v2-api-bars-request-adjustment-not-working/12893),
  [forum: basic plan data](https://forum.alpaca.markets/t/old-market-data-in-basic-account-subscription/16741),
  [changelog: spin-off adjustment](https://docs.alpaca.markets/us/v1.1/changelog/optionally-adjust-bars-after-spin-offs)
- Massive / Polygon: [pricing guide (third party)](https://qveris.ai/guides/polygon-pricing-optimized/),
  [splits and dividends endpoints](https://www.massive.com/blog/new-splits-and-dividends-endpoints),
  [API tutorial (timestamps)](https://www.quantt.co.uk/resources/polygon-api-tutorial)
- Finnhub: [GitHub issue #546: free plan candles](https://github.com/finnhubio/Finnhub-API/issues/546),
  [pricing summary (third party)](https://apicostcalc.com/finnhub.html),
  [estimates pricing (official)](https://finnhub.io/pricing-stock-estimates)
- Twelve Data: [US equities market data](https://support.twelvedata.com/en/articles/9935903-us-equities-market-data),
  [API credit limits](https://support.twelvedata.com/en/articles/5194820-api-credits-limits),
  [pricing](https://twelvedata.com/pricing)
