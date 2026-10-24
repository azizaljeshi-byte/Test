# Multi-source news and critical-news alerts

Display and Telegram only. The extra stories live in `events["wire"]`; `catalysts.py` still scores only Yahoo's
`events["news"]`, so no score, signal, verdict or plan changes.

## Sources (no new keys)
Yahoo (what the app already fetched), Google News RSS (searched by company name, last 2 days), SEC EDGAR 8-K filings
(from the filings the scan already fetched; the item numbers set the tier) and Finnhub company news when
`FINNHUB_API_KEY` is set. Each source that fails says why on screen ("Not read: Google News"); one failing never blocks
the others. Cached 10 minutes per ticker; Google News uses at most 3 requests in flight.

## Tiers and ranking
| Tier | What | Telegram |
|---|---|---|
| HOT | bankruptcy, delisting, fraud, SEC/DOJ probe, restatement, trading halt, guidance cut or withdrawn, FDA rejection, recall, data breach, CEO or CFO leaving abruptly, short-seller report, share sale, a plunge; 8-K items 1.03, 3.01, 4.02, 1.05 | yes |
| IMPORTANT | up/downgrades, earnings, deals, guidance raise, contracts, approvals, buybacks | no |
| ROUTINE | everything else | no |

The same story from several sources is merged (headline word overlap 55%+) and shows every source. Inside a tier:
more sources, then newer, then held over watchlist. The keyword lists are in `newsfeed.HOT` and `newsfeed.IMPORTANT`.

## Telegram
Once per story, only HOT, only when first seen within 24 hours, at most 6 per scan (the rest follow next run). The first
run records what is already out there silently. A failed send stays unseen and retries. Memory is the encrypted alert
state under the reserved key `__news_seen__` (story ids and times only, pruned after 7 days; no headlines, no tickers).
`newsfeed.NEWS_ALERT_MIN = 4` switches the alerts off. Speed: the scan runs about every 15 minutes (GitHub may delay it),
so an alert arrives within roughly 15 to 20 minutes of the story reaching a source; it is not instant.

## On screen
Radar: a "Critical news" strip (or "No critical news on your list", plus which sources were not read). Details: every
story for the stock, ranked, with its sources. Briefing: "News on your names" now uses all sources, HOT and IMPORTANT first.
