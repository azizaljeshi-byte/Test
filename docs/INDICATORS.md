# Stronger chart reading: indicators to study (recorded, NOT built)

Recorded at the owner's request for later study and development. Nothing here is live. The owner picked **weekly trend
alignment as the starting point**.

## Principle
More indicators do not make a call more accurate when they measure the same thing (RSI, MACD and stochastic all read
momentum); stacking them only adds false confidence. `docs/CIS_PHASE2.md` already found the automatic levels carry no
information beyond volatility. Add only what brings information the app lacks, and prove it first.

## Candidates
| Area | Have now | Candidate | Why it is new information |
|---|---|---|---|
| Trend and structure | 50/200-day averages, status ladder, graded zones | **Weekly trend alignment** (start here) | A daily dip inside a rising weekly trend differs from one inside a falling weekly trend |
| Momentum | RSI, MACD, cause labels | none | already covered |
| Volume | distribution and accumulation days | on-balance volume; anchored VWAP from the last earnings or gap day | who is in profit or under water at this price; whether volume confirms the move |
| Trend strength | TradingView's ADX shown | ADX in our own check | real trend vs chop, so a bounce is not trusted in a range |
| Volatility | ATR | squeeze and ATR percentile | quiet before a big move; an unusually violent drop |
| Relative strength | against SPY, 3 months | against the sector; new relative-strength highs | weak on its own vs dragged by its sector |
| Market context | RISK-ON / RISK-OFF mood | breadth (share of S&P stocks above their 50-day) | a rally led by a few names is weaker |
| Positioning | nothing | short interest, days to cover | squeezes and violent drops; needs a data source |
| Insiders | SEC forms fetched | Form 4 buying and selling | real money behind a view; rare but strong |
| Estimates | earnings dates | estimate revisions | the direction of analysts' numbers often leads price; needs a data source |

Suggested order after weekly alignment: volume (OBV, anchored VWAP), sector relative strength, ADX and the volatility
squeeze, breadth. Short interest and estimate revisions need new data sources, so they come later.

## How to add one (so confidence stays honest)
1. Build it as a display-only check, like the TradingView and Stooq reads (`docs/DAYBOARD.md` lists the six checks).
2. Test on our own history whether it improves the call beyond what the app already has; drop it if not.
3. Only indicators that earn their place count toward the "x/6 sure" total, and the total changes with them.
4. Anything that would change a buy or sell rule goes through its own pull request (see `docs/TIGHTENING.md`).

## Weekly trend alignment: first sketch
Resample the completed daily bars to weeks (Friday close, no partial week). Read the 10 and 30-week averages and the
weekly close against them: **rising** (close above a rising 30-week), **falling**, or **mixed**. Show it as a seventh
check on the Day Board and one line on Details ("Weekly: rising, a daily dip inside an up-trend"). Too few weeks gives
"unknown" with the reason. Test question: do daily pullbacks inside a rising weekly trend recover more often than inside
a falling one, on our own history?
