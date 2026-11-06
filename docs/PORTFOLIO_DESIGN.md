# Portfolio tab: design note (6 Nov 2026, queue item 34)

Status: BUILT (shadow, fake money), thresholds confirmed by the owner on 6 Nov with one change: fundamentals 75 (not 80), for holdings and new names alike. Cash reserve 10% confirmed. Differences from the first proposal: fair value needs at least 2 methods; adds may be fractional (the owner holds fractional shares), with a $25 minimum; the account reads the holdings when it starts and the page has a button to restart it from the Sheet after he changes his holdings. Code: stockwatch/portfolio.py (logic), portfolio_view.py (page), tests/test_portfolio.py.

Original proposal:  Shadow mode only: a fake account, never real trades.
No holdings, keys or links in this file (the repo is public); holdings are read from the owner's Sheet at run time.

## What it is
A fake account that mirrors the stocks the owner holds (every row with shares above 0) at his shares and average cost, and manages them carefully.
Quick supplies the timing (turning up, volume normal, best ranked first); New call supplies the daily call and exit line.
No change to scoring, signals, verdicts or the existing accounts' rules. Every action is logged with its reasons.

## Trim or size down a poor position (checked at 15:45 New York, never on an intraday dip)
- Poor = New call says EXIT or AVOID on the daily close AND the chart reads weakening or testing support, or momentum is falling.
- Step 1: trim 25% at the first confirmed close. Step 2: another 25% if it is still EXIT after 2 more closes. Never more than 50% on its own.
- The rest is a PROPOSAL to the owner ("sell the remaining half?") and waits for his yes. A holding is never sold to zero without it.
- Size down: a position above 15% of the portfolio is trimmed back to 15%; High or Extreme risk grade: cap 8%.
- A trim is undone by nothing automatic: no re-buy of the trimmed shares for 3 sessions unless the call is BUY/ADD again.

## Add to a stock (all must hold)
1. Very strong fundamentals: fundamental score 75 or more (holdings and new names).
2. Undervalued: fair value (mid) at least 15% above the price AND the analyst target at least 10% above.
3. New call is BUY or ADD, price near its exit line (not stretched).
4. Risk grade not High or Extreme. No earnings within 2 days.
5. Timing (Quick's read): turning up on the day, volume at least 0.8x normal, market gate open, not stopped by the crash flag.
6. Never averaging down into a broken chart: no add if the call is EXIT/AVOID or the chart reads weakening.
- Size: about 1% of the portfolio at risk from the exit line, at most 5% of the portfolio per step, at most 15% in one name, one add per name per day, two adds per day in total.

## New names (the pool is not limited to holdings)
- The account decides alone (my reading of "full veto", not yet confirmed): same six tests, with fundamentals 75 or more, a starter of at most 3% of the portfolio.
- First version looks across the tracked stocks (about 230, the ones with live data and scores). The rest of the S&P 500 comes with item 33 (bulk data).

## Cash
- Starts with holdings at cost plus a cash reserve (proposal: 10% of holdings' cost). Trims add to cash, adds spend it, never below zero.

## Display and alerts
- Same layout as Quick and New call (cash, used, total, realized, unrealized, one card per holding, hand-sell button, tags). Phone width 390px, tappable ticker links.
- A phone push for each trim, add or proposal.

## Plan
Fri 6 Nov note and thresholds; Sat to Sun 8 Nov build and tests; deploy Sunday while the market is closed; Monday check at the open.
Codex could take: the "undervalued and very strong" screen (a function that scores fundamentals and fair value from the stored snapshots).
