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
| Q1 | **Wild stocks stay tradable, at reduced risk** (owner, 11 Nov: do NOT skip them, on up days they catch good moves). When ATR(14) / price is over `WILD_RANGE_PCT = 6.0`: enter at half the grade size (`WILD_SIZE_FRAC = 0.5`) and tag the trade "wild" so it can be judged separately. The replay must also test "wild only when the market is up" (market gate healthy) against half size, and the owner picks. | 101 wild trades: 29% wins, -$1,700, red on 8 of 11 days; green only on the three strong days (27 Oct, 3 Nov, 9 Nov: +$214 together, the other eight days -$1,914), which fits the owner's point. The other 206 trades: 47% wins, +$95. Half size on the records: wild loss -$1,700 -> about -$850. Candidate log, bounces: calm stocks up after an hour 82-87%, wild 18-29%. |
| Q2 | **Open Quick to the S&P 500: rank every setup, then decide the entry** (owner confirmed 11 Nov). This is queue item 33. Not only tracked stocks; the pullback rule applies to these too. Start from the candidate list (`funnel.py` already reads all ~500 every 5 minutes). Respect the Yahoo limit (3 in flight; bulk downloads). | 163 untracked calm bounce candidates in 5 days: about 80% up an hour later, +0.5 to +0.8% on average, shallow dips. Tracked bounce candidates: 44% up, -1.5%. Two strong days (3 and 6 Nov) carry most of it. |
| Q3 | **Pullback rule stays exactly as it is** (owner, 11 Nov: the pullback must not disappear). No runaway entry. | For the record only: 22 candidates dropped as "ran away without a pullback" were up +2.6% an hour later (20 of 22), all on one strong day (9 Nov). Not to be coded. |
| Q4 | **Only the #1 ranked setup each round.** | Ranked #1: 25 trades, 52% wins, +$91. Ranked #2 or lower: 36 trades, 19% wins, -$858. Record replay with Q1: +$169. |
| Q5 | **Same size for grade A and B** (`SIZE_PCT`), until grade A proves better. | Grade A: 101 trades, 37% wins, -$1,168; B: 113, 44%, -$120. A stocks are wilder (average swing 6.9% against 4.2%); in calm stocks A and B are equal (49% and 47%). Small effect on its own (-$1,605 -> -$1,414). |
| Q6 (watch, do not code yet) | Entries on 2-5x normal volume. | 36 trades, 19% wins, -$1,031, but 16 of them are one day (6 Nov). Add to the replay only. |

Owner decisions so far (11 Nov): Q1 changed to reduced risk, Q2 yes, Q3 dropped (pullback stays). Q4 and Q5 not decided yet. The extra trades and the
win rate have to come from Q2.

## New call (`stockwatch/paper_newcall.py`)

| # | Rule | Evidence |
|---|---|---|
| N1 | **Replaced by "Both accounts: no money limit" below** (owner, 11 Nov). | On 10 Nov New call had 5 open positions using about $37,000 of $50,000, so new BUY calls had no cash. |
| N2 | **Low volume: half-size entry instead of no entry** (`MIN_PACE = 0.8` block, "volume only Nx normal"). Keep the block when volume is not read yet. | The main brake: 83 of 191 held-back buys. The 31 followed: +0.5% after an hour, +0.8% at the close, average worst dip -0.6% (bought ones: +2.0%, 95% up). |
| N3 | **Keep** the weak-chart block, the market gate and the crash flag. | Held-back stocks went on to close -1.3% (weak chart), -2.7% (market gate), -4.4% (volume not read). |
| N4 | **Test a break-even stop once a trade is up 1%.** Do not code before the bar replay. | All losses come from the "falling" exit (17 trades, -1.6% each); 6 of 20 losers had been up 1% or more. From the records the result is anywhere between -$670 and +$1,645, because the order of the high and the low inside 22 winning trades is not recorded. |
| N5 | **Keep re-entries and ADD calls unrestricted.** | 2nd and 3rd entries in the same stock the same day: 5 wins of 6, +$823. ADD: 82% wins; BUY: 49%. |

| N6 | **Open New call to the S&P 500**: work out the one call (`onecall.py`) for the untracked S&P stocks too, same rule, then rank and enter. Needs daily bars for ~500 stocks once a day (bulk download) and the level finder on each; keep the Yahoo limits. | The biggest pool of missed stocks: of 400 untracked candidates followed, 131 rose 2% or more after being flagged (or closed 1.5% up). New call cannot see them: it only judges the ~120 tracked stocks. |
| N7 | **Test an entry for stocks already going up** (call WAIT or HOLD: more than `ENTRY_ATRS = 1.5` swings above the exit line, which the rule never buys). Shadow or half size first, tagged "trend", stop and exits as today. Replay first. | The owner's point (11 Nov): it does not trade stocks that have been going up. 27 tracked WAIT candidates not bought: +0.8% an hour later, +1.7% at the close, shallow dips, 9 of 27 good. Small sample, a few big winners (INBS, CDW, BBY). |
| N8 | **Weak-chart block: test easing it when the market is strong.** Do not remove it. | It held back the most winners of any block (15 of 36 rose 2%+; on 9 Nov HPE, PLTR, RR and DELL, +4 to 5% by the close) but on average the held-back stocks closed -1.3% with -3.3% dips, so it protects on weak days. |

What New call buys is far better than anything it skips (bought: 13 of 21 good, +2.8% at the close; every skipped group averages worse), so the
aim is a bigger pool (N6) and one new entry type (N7), not looser checks. Its real record to 9 Nov is 26 wins of 46 (57%), +$1,426.

## Both accounts: no money limit, a cap on open trades (owner, 11 Nov)
The owner wants Quick and New call to take every good trade with no cash ceiling (no fake $50,000), and at most 15 open trades each.
- **Fixed dollars per trade** replace the percent-of-account sizing (`quick.SIZE_PCT`, `quick.POSITION_PCT`, `paper_newcall.SIZE_CAP_PCT`): proposed $5,000 a trade for both (to be confirmed by the owner; grade and half-size rules scale from it). Cash can go negative or is not tracked; the page shows money in use, realized and unrealized result, and result per trade in percent.
- **Cap: 15 open trades** per account (`quick.MAX_OPEN` is already 15; `paper_newcall.MAX_POSITIONS` 10 -> 15). At the cap a new setup is logged as skipped ("15 open").
- **Restate the percent-of-account brakes in dollars**: Quick's day-loss stop (`DAY_LOSS_PCT`, 1% of $50,000 = $500) and anything else that divides by the account.
- Ideas offered to the owner, not decided: at most 4 or 5 open trades per sector so the 15 are not one theme; when full, a clearly higher-ranked setup may replace the weakest open trade.

## Related fixes the owner wants (see `docs/QUEUE.md`)
Item 35: indicator fixes (short history, Bollinger width, RSI 100 where it should be unknown). Item 36: support and resistance fixes.

## Who can take what
Codex: task 0, Q1, N2, the no-money-limit change, and Q4, Q5 once the owner decides (small, well-bounded, with tests). Sonnet or Claude: Q2 and N6 (they touch the scan, the rate
limits and the tracker thread). N4, N7 and N8 wait for the replay and the owner's word. N4 waits for the replay result and the owner's word.
