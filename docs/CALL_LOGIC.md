# How each call is made

Written 27 Oct 2026 with the owner, from the code (not from memory). Read-only: nothing here changes a rule.
The NVDA walk-through uses the data on screen that morning: Friday 23 Oct close, because Monday's bar was still missing.

## The layers, in the order they are built

| # | What you see | Built by | Rule in one line |
|---|---|---|---|
| 1 | Score (e.g. 85) | `engine` | Fundamentals and technicals blended by tier (Tier 1: 65% fundamentals). A quality rating, not the decision |
| 2 | Signals | `engine`, `technical` | Each is a risk or an opportunity with severity 1 to 3 (trailing stop, entry trigger, thesis break, position limit, after-hours move of 3%+) |
| 3 | Verdict badge | `engine._verdict` | Held: urgent risk gives RISK - REVIEW; entry signal gives OPPORTUNITY - ADD; target reached or score under 40 gives TRIM / REVIEW; 65+ gives STRONG HOLD; else HOLD. Watchlist: entry signal gives BUY SETUP; urgent risk or under 40 gives AVOID; else WATCH |
| 4 | Chart status | `status` | Seven states from completed daily closes: record high, strong uptrend, pullback, weakening, testing support, breakdown, deep breakdown. Weakening = below the 50 or 200-day average, or more than 15% under the high |
| 5 | Trade plan stance | `tradeplan` | Starts from the verdict, then two overrides: a confirmed breakdown can force REDUCE / EXIT (off by default), and failed entry gates turn any buy into HOLD (WAIT on a watchlist stock) |
| 6 | Call word | `ui._action` | BUY NOW, BUY ON DIP, BUY ON BREAKOUT, BUY MORE, WAIT, HOLD, PASS, SELL SOME, SELL. A sell on a stock up 3%+ today, or back above its trailing stop, shows REASSESS |
| 7 | Radar | `ui.ring`, `dayboard` | Ring: 1 act now, 2 getting close, 3 nothing to do. Word: ACT, BUY, WATCH, CALM. Six checks (structure, momentum, second opinion, price data, market, signals) give the "N of 5 sure" gauge |
| 8 | Alerts | `transitions`, `notify` | A message when the call class changes, only after two readings in a row. Currently sent only by the GitHub job, not the PC |
| 9 | Paper account | `decision` | Its own order: hard stop, warning exit at 15:45 New York, target, then entry only if every gate passes |
| 10 | CIS | `cis/decision` | A newer chart-state rule set. Off by default, shadow only |

Entry gates (`status.entry_blockers`), all must be clear to buy: chart not weakening or testing support; momentum not falling, weak or fading; TradingView and Finnhub not SELL; the other price source not disagreeing.

## NVDA, step by step (Friday data)

1. Fundamentals 98, technical 60, score 85.
2. Signal `quality_entry` fires: fundamentals 65+ and an entry trigger. The trigger here is just an up-trend with RSI under 40 (RSI 38).
3. Verdict: OPPORTUNITY - ADD.
4. Chart status: testing support (close inside the 210.18 to 214.70 zone).
5. Gates: chart testing support, momentum weak, TradingView SELL. Three blockers.
6. Plan stance: ADD becomes HOLD, "don't buy yet".
7. Call word: HOLD. Radar word: WATCH. The top badge reads "no usable signal" (see problem 4).

## Where it contradicts itself

1. **Four different stops** on one page: ATR trailing stop 215.00 (1-month high minus 4 ATR), plan stop 192.78 (3 ATR under price), chart exit 210.18 (support low), position stop (-25% from cost, Tier 1). "The stop has been hit" refers to the first one only.
2. **Verdict versus plan.** The verdict says add; the plan says hold. Both are shown.
3. **A dip counts as an entry trigger.** For a strong stock in an up-trend, RSI under 40 alone fires "add / buy zone", even while the chart is testing support.
4. **"No usable signal"** on the top badge is a fallback label printed when no reason was filled in, even for a stock with a readable signal.
5. **"Support broke: don't add yet"** is the radar's fixed reason for any blocked buy, even when support has not broken (NVDA only tested it).
6. **Two sets of levels.** "Support 210.18 to 214.70, resistance 211.68 to 216.34" (chart levels) next to "support near 208.08, resistance near 213.19" (a different calculation). The zones overlap.
7. **Position 25.1% against a 15% limit** is shown as a risk line but changes no call.
8. **A confirmed breakdown changes no call** (`EXIT_ON_BREAKDOWN` is off). CRDO's SELL SOME comes from the trailing stop, not from the chart.
9. **Old data.** Until the next sweep, price and chart are Friday's, while the after-hours number is measured against Monday's close.

## Decisions for the owner before any rule changes

1. Which line is "the" exit: one stop per stock, with the others shown as information only?
2. Should a stock already held and strong ever get ADD from RSI under 40 alone?
3. Over the position limit: show TRIM, or keep it as a note?
4. A confirmed chart breakdown on a held stock: does it override the plan, or stay a warning?
5. One call per stock, chosen in a fixed order, data fresh, then exits, then size, then entry. Shown beside the old labels in shadow mode first, trading nothing.
