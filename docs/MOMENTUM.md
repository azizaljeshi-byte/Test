# Momentum and kind of move

`stockwatch/momentum.py`. Display only: it changes no score, status, call or alert.

Shown as a `FLOW` line on each row (left off for quiet strength), a statement with the numbers on Details, and one `Flow:` line on status-change Telegram messages.

```
How the move is happening: its momentum, and what kind of move it is. Display only; it never changes a score,
status, call or alert.

Momentum (from the last completed daily bars): RSI(14), the 20-day return and MACD against its signal line.
  strong       up 8%+ over 20 sessions with MACD above its signal
  building     up over 20 sessions with MACD above its signal
  stabilising  down over 20 sessions but MACD has turned up
  fading       up over 20 sessions but MACD has turned down
  weak         down over 20 sessions with MACD below its signal
  falling      down 10%+ over 20 sessions with RSI under 40

Kind of move, first match wins (the others that also hit are listed in `also`):
  event          one session in the last 10 moved 6%+ (and 2.5 ATRs) on 2x its usual volume, the way the 20-day move went
  market         the market (benchmark) is itself 3%+ against the stock's direction over 20 sessions and the stock has not moved
                 more than 3 points further than it: the stock is going with the market
  sector         same test against the sector fund, when the market doesn't explain it
  distribution   5+ distribution days in 25 sessions (down 0.2%+ on higher volume than the day before) and more volume
                 on down days than up days over 20 sessions: sustained selling
  accumulation   the mirror: 5+ heavy-volume up days and more volume on up days
  drift          none of the above while momentum is negative: no event, no heavy selling, not the market
  none           nothing unusual while momentum is positive

Distribution days are the standard IBD count; RSI and MACD are the standard definitions. Unknown is unknown: too
little or unusable history gives `known` False with the reason, never a guess.
```

## Known limits

- Event detection is price and volume only (a big move on 2x volume); it doesn't read news or the earnings calendar, so it says "event-driven" for any such day, not specifically earnings.
- Thresholds (6% / 2.5 ATR / 2x volume, 5 distribution days, 3 points vs the market) are standard rules of thumb, not tuned on this watchlist.
- Sector comparison needs the sector fund to load; without it only the market test runs.
