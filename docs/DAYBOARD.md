# Day Board (the Radar page)

Display only. It re-presents the call, price status, momentum and second opinions already on each snapshot. It changes no
score, signal, verdict, plan, stop, threshold or alert, and the Details page and Telegram keep the full status names.

## What the page shows
- **Headline and gauge board** (`dayboard.board`): one sentence ("2 need you, 3 are close and 14 are calm"), a dial with
  a needle for the holdings you own overall, and five columns (Bad, Weak, Neutral, Good, Strong) with a chip per stock under
  the step it reached. Tap a chip for a quick summary under the board. UNCLEAR stocks sit in their own row.
- **Cards**: ACT / BUY cards large, WATCH tiles in a two-column grid, CALM chips. Tap a card to open it in place
  (`<details>`, no script) and use "Open full details" for the Details page.

## The words (from `ui.ring` and the plan's call, no new rule)
| Word | Meaning |
|---|---|
| ACT | the plan says sell or sell some (a sell waiting for the close is WATCH) |
| BUY | buy or buy more, and the price is in the entry zone now |
| WATCH | something is close: near an entry or stop, earnings soon, a buy held back by a breakdown |
| CALM | nothing to do |
| UNCLEAR | an error or no usable signal |

## The gauge and the "x/6 sure" count
Six checks, each bullish, neutral, bearish or unknown: price structure, momentum, second opinion (TradingView, else
Finnhub), price data (Stooq), against the market (3-month relative strength, +/-2%), and signals. The gauge is their
average on five steps. At least 3 must be readable, otherwise the gauge says UNCLEAR and why. If the gauge points the
other way from the call (ACT with GOOD or STRONG, BUY with BAD or WEAK) it shows UNCLEAR instead of two answers. "x/6 sure"
counts the known checks that agree with the call (ACT: bearish, BUY: bullish); unknown checks are left out, never counted
as a no. HIGH is 80%+ agreeing, MEDIUM 55%+, else LOW. The dial needle is the average of the stocks you own (all stocks when none are owned).

## Support and resistance zones (`zones.py`)
Swing highs and lows from about two years of completed bars, joined when within 1.5%. Points: 4+ touches 2, 2-3 touches 1,
50 or 200-day average inside +1, round number +1, heavy volume +1, reacted in the last 90 days +1, older than 400 days -1.
HIGH is 4+, MEDIUM 2-3, LOW 0-1. Too little history gives "no read" with the reason. The existing status levels, stops and
alerts still use the CIS candidates; moving them onto these zones would be a methodology change and needs the owner's say.
