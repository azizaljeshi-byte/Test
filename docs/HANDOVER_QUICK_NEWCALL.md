# Handover: Quick and New call improvements (owner, 11 Nov 2026)

For Sonnet or Codex. The owner asked for these to be coded after a review of every real Quick and New call paper trade through Mon 9 Nov
(Quick 307 closed trades, -$1,605, 41% wins; New call 46, +$1,426, 57% wins; test sells and hand sells left out) and of the candidate log
(1,380 flagged candidates over 7 days with the price 30 and 60 minutes later). The goal: buy more stocks with a higher win rate.

Read `CLAUDE.md` and `docs/COLLABORATION.md` first. These change trading rules, so say so in the pull request. Every rule goes behind a named
constant with a comment giving the owner, the date and the evidence, like the existing ones in `stockwatch/quick.py`. Add tests for each.
Do not deploy mid-session: the owner applies updates after the US close.

## How far to trust the evidence
11 trading days, one crash day (Thu 5 Nov), Quick's rules changed on 7 Nov (only 12 trades under today's rules). The patterns were found on
the same trades they are judged on. Candidate numbers are the price an hour after the flag, not entries with stops. So: task 0 comes first.

## Task 0 (first): replay on 5-minute bars
The numbers below come from the trade records only (trades removed or resized, no bars). Before any rule goes live, extend
`scripts/quick_replay.py` (and `scripts/scenario_search.py`) to switch each Quick rule below on and off over the stored days, and add the same
for New call (`scripts/replay_trades.py` is the nearest start). Report per rule: trades, win rate, total, profit factor, green days, worst day,
split into the two weeks. Needs Yahoo, so it runs on the owner's PC (`.bat` writing to `data/`, using `.venv\Scripts\python.exe`; open the
database from a copy, the app keeps it locked: see `scripts/ema_on_trades.py`). Codex can take this.

## Quick (`stockwatch/quick.py`)

| # | Rule | Evidence (record replay) |
|---|---|---|
| Q1 | **Skip wild stocks**: no entry when ATR(14) / price is over `MAX_RANGE_PCT = 6.0`. Log the skip ("too wild: daily swing N% of the price"). | 101 wild trades: 29% wins, -$1,700, red on 8 of 11 days. The other 206: 47% wins, +$95. Whole account: -$1,605 -> +$95, green days 4 -> 7 of 11, worst day -$608 -> -$180. Holds in both weeks (week 2: 55% wins, +$274). Cut-off 5% or 6% both work; 7% and 8% do not. Candidate log agrees for bounces: calm stocks up after an hour 82-87%, wild 18-29%. |
| Q2 | **Trade calm bounces across the S&P 500**, not only tracked stocks. This is queue item 33 (whole-market scan, rank, enter the best). Start with bounce candidates with ATR/price at or under 4.5% from the candidate list (`funnel.py` already reads all ~500 every 5 minutes). Respect the Yahoo limit (3 in flight; bulk downloads). | 163 untracked calm bounce candidates in 5 days: about 80% up an hour later, +0.5 to +0.8% on average, shallow dips. Tracked bounce candidates: 44% up, -1.5%. Two strong days (3 and 6 Nov) carry most of it. |
| Q3 | **A stock that runs away without a pullback gets a half-size entry** instead of being dropped (`WATCH_CHASE_PCT` path, "ran away without a pullback"). Constant `RUNAWAY_STARTER = True`, size half of the grade size, normal stop. | 22 dropped candidates: 20 up an hour later, +2.6% on average, all reached +1%. One strong day (9 Nov), so the weakest evidence here: replay before switching on. |
| Q4 | **Only the #1 ranked setup each round.** | Ranked #1: 25 trades, 52% wins, +$91. Ranked #2 or lower: 36 trades, 19% wins, -$858. Record replay with Q1: +$169. |
| Q5 | **Same size for grade A and B** (`SIZE_PCT`), until grade A proves better. | Grade A: 101 trades, 37% wins, -$1,168; B: 113, 44%, -$120. A stocks are wilder (average swing 6.9% against 4.2%); in calm stocks A and B are equal (49% and 47%). Small effect on its own (-$1,605 -> -$1,414). |
| Q6 (watch, do not code yet) | Entries on 2-5x normal volume. | 36 trades, 19% wins, -$1,031, but 16 of them are one day (6 Nov). Add to the replay only. |

Q1 + Q4 + Q5 together on the records: 192 trades, 48% wins, +$200, 8 of 11 days green. That is break-even, not an edge: the extra trades and the
win rate have to come from Q2.

## New call (`stockwatch/paper_newcall.py`)

| # | Rule | Evidence |
|---|---|---|
| N1 | **Smaller positions so it can hold more stocks**: `SIZE_CAP_PCT` 15 -> about 7.5 (keep `MAX_POSITIONS = 10`). | On 10 Nov it had 5 open positions using about $37,000 of $50,000, so new BUY calls had no cash. Same trades at half size: +$713 instead of +$1,426, so it only pays if the freed cash finds trades as good. Replay with the held-back buys. |
| N2 | **Low volume: half-size entry instead of no entry** (`MIN_PACE = 0.8` block, "volume only Nx normal"). Keep the block when volume is not read yet. | The main brake: 83 of 191 held-back buys. The 31 followed: +0.5% after an hour, +0.8% at the close, average worst dip -0.6% (bought ones: +2.0%, 95% up). |
| N3 | **Keep** the weak-chart block, the market gate and the crash flag. | Held-back stocks went on to close -1.3% (weak chart), -2.7% (market gate), -4.4% (volume not read). |
| N4 | **Test a break-even stop once a trade is up 1%.** Do not code before the bar replay. | All losses come from the "falling" exit (17 trades, -1.6% each); 6 of 20 losers had been up 1% or more. From the records the result is anywhere between -$670 and +$1,645, because the order of the high and the low inside 22 winning trades is not recorded. |
| N5 | **Keep re-entries and ADD calls unrestricted.** | 2nd and 3rd entries in the same stock the same day: 5 wins of 6, +$823. ADD: 82% wins; BUY: 49%. |

## Related fixes the owner wants (see `docs/QUEUE.md`)
Item 35: indicator fixes (short history, Bollinger width, RSI 100 where it should be unknown). Item 36: support and resistance fixes.

## Who can take what
Codex: task 0, Q1, Q4, Q5, N1, N2 (small, well-bounded, with tests). Sonnet or Claude: Q2 (touches the scan, the rate limits and the tracker
thread) and Q3. N4 waits for the replay result and the owner's word.
