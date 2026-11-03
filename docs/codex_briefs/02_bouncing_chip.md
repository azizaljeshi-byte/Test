# Brief 2: "bouncing today" on the Move chip (display only)

**Request (owner, 2 Nov; QUEUE item 29).** A stock in a daily breakdown that is up about 1 daily range or more today should show
"bouncing today" (reason: daily chart still broken) instead of "falling", so it does not look stale next to a live +2%
(examples: GOOG, GOOGL, RR, NRXP).

**Where.** `stockwatch/phase.py` (`_move_atr` already exists). Find where the chip text is chosen for the falling case.

**Rules.** Display only: the stock's phase used by New call, Quick or any trade rule must not change. If the function feeds a rule,
add a separate display label instead of editing the value that rules read. Missing price or ATR = leave the chip as it is.
Threshold: today's move at or above 1.0 x ATR (put it in a named constant).

**Check.** Tests: breakdown + up 1.2 ATR gives "bouncing today"; breakdown + up 0.5 ATR stays "falling"; no price data stays unchanged;
a stock not in breakdown is unchanged. Confirm in the PR that no trade code reads the changed value (list the places you searched).
Methodology impact: None.
