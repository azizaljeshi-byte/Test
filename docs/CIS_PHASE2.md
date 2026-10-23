# CIS phase 2 (Issue #31): automatic candidates, whole-list shadow, data licensing

**Status: research and shadow only.** Nothing here changes a live call, a trade plan, the alert memory or
Telegram. The CIS decision switch stays off; there is no active mode. Builds on PR #30 (Issue #29).

## Bottom line

1. **Automatic candidate levels: built, compared, NOT validated.** The candidate extractor reproduces every
   reference state (confirmed and provisional) for ISRG, FICO, CRDO and PODD as of 22 Oct 2026, and its
   floors sit close to the analyst's. But the walk-forward test shows its **failure levels carry no
   information beyond volatility**: they're a median 1.25 ATR below price and get closed below within 20
   sessions about as often as any level the same ATR distance below price (53% vs 53%). Candidates therefore
   stay **diagnostics**: they're shown, never turned into a call, and never approved automatically.
2. **Whole-list coverage:** a CIS call exists only for stocks with a reviewed packet (ISRG, FICO, CRDO
   owner-accepted; PODD proposed). Every other stock is CIS UNSUPPORTED and keeps its legacy call, labelled.
   Research → Chart judgment → "Compare my list" shows, per stock, the CIS call or UNSUPPORTED, the legacy
   call, the candidate's state, the legacy stop/target vs the candidate levels, an alert-diff preview and a
   Finnhub price cross-check.
3. **Data licensing: resolved by removal.** No redistribution right for Yahoo-derived prices was found, so
   those files are no longer in the repository (they stay private and hash-verified, below).
4. **Finnhub:** used as a second source for the shadow only: today's price, high and low (the intraday facts
   the app didn't have), cross-checked against Yahoo. If the two disagree by more than 0.5%, neither is used
   for intraday facts and the disagreement is shown.

## Data-license disposition (workstream C, item 9)

- **What was found:** Yahoo's terms are widely described as personal-use only, and Yahoo's data comes from
  licensors with redistribution restrictions. No source granting redistribution rights was found; the
  current terms text couldn't be opened from the build environment. Sources (secondary):
  [Yahoo help: downloading historical data](https://help.yahoo.com/kb/SLN2311.html),
  [Intrinio on Yahoo Finance API terms](https://intrinio.com/blog/yahoo-finance-api-replacement),
  [SLU course notes (2016)](https://cs.slu.edu/~goldwamh/courses/slu/csci1050/2016_Spring/lectures/stocks).
- **Disposition:** the 17 vendor-derived files (adjusted daily prices, evidence files built from them and the
  scanner audit with captured app data) are removed from the repository. What stays public: the method
  documents, the packet schema, the analyst level packets, the acceptance ledger and the handoff manifest,
  which pins every private file's SHA-256.
- **Private use:** put the handoff files in a folder and set `STOCKWATCH_CIS_DATA` (default
  `~/.stockwatch/cis-data`). A file is used only if its SHA-256 matches the manifest (`stockwatch/cis/refdata.py`).
  Without them: CI runs on deterministic synthetic data and the 35 tests that need real prices skip; the
  Research view shows each packet's levels, states and shadow calls without charts or history.
- **History and merge order:** the files are still in PR #30's branch history, and PR #30's tip still contains
  them. To keep them out of the default branch:
  1. **Don't merge PR #30 on its own** (squash or not, its tip adds the files).
  2. When both are approved, **retarget PR #32 to the default branch** (it already contains all of #30's work)
     and **squash-merge #32**: the default branch gets one commit whose tree has no vendor files.
  3. **Close #30 as superseded** by #32.
  Purging the feature branches' history needs a force-push, which is the owner's call.
- The PR #30 screenshots (rendered charts) remain in `docs/cis-screenshots/`; remove them too if you want no
  chart renderings of vendor data in the repo.

## Candidate levels (workstream A, items 1–2)

`stockwatch/cis/candidates.py`, method `cis-candidate-levels-v1`, parameters versioned by hash. Point-in-time
(only completed bars up to the as-of session; a swing counts only once its confirming sessions have closed).

- **Floor:** the nearest support zone (two or more anchors: recent swing lows, broken resistance at least three
  sessions old, the 50/200-day averages, recent session lows as confluence only) at or below the highest close
  of the last 5 sessions. Judging against the recent high close, not today's, keeps a floor price has just
  fallen through as the floor (SUPPORT BREAK), instead of promoting a lower support to look healthy.
- **Failure / major damage:** below the most recent low under the floor; below the lowest low under that in the
  last 15, then 60 sessions; volatility fallbacks are flagged.
- **Ceilings:** swing highs, broken supports and averages above the current close, clustered, ascending.
- **Output:** a packet marked `code_candidate_unreviewed` in both fields, with no scenario weights (none are
  invented). The decision adapter treats it as CIS UNSUPPORTED.

**Approval pipeline (item 5)** — `level_packet.stage`: **candidate** (code, unreviewed) → **research_reviewed**
(`review_candidate`: a reviewer adopts it under a new ID, recording the candidate's ID and content hash, and must
supply any scenario weights) → **owner_accepted** (an entry in `fixtures/acceptances.json` for that exact ID
and content hash, added only in a reviewed PR) → activation eligible at run time (fresh levels, live data,
usable data). No step is implicit.

## Validation (workstream A, items 3–4)

### Reference comparison (as of 2026-10-22)

| Stock | Candidate floor | Reference floor | Floor overlap (IoU) | Floor top gap | Failure (cand / ref) | Gap | Major damage (cand / ref) | Gap | States (confirmed / provisional) | Reference ceilings overlapped |
|---|---|---|---|---|---|---|---|---|---|---|
| ISRG | 430–436.91 | 436–440 | 0.09 | 0.24 ATR | 426.17 / 424 | 0.17 ATR | 387.81 / 398.99 | 0.86 ATR | agree / agree (SUPPORT HOLD, SUPPORT HOLD) | 3 of 3 (candidate has 8) |
| FICO | 755–790.71 | 780–790 | 0.28 | 0.02 ATR | 725.02 / 750 | 0.56 ATR | 604.56 / 660 | 1.25 ATR | agree / agree (SUPPORT HOLD, SUPPORT HOLD) | 3 of 3 (candidate has 8) |
| CRDO | 178.59–180.83 | 180–185 | 0.13 | 0.27 ATR | 159.72 / 160 | 0.02 ATR | 147.6 / 149 | 0.09 ATR | agree / agree (SUPPORT BREAK, TRADE INVALIDATED) | 8 of 8 (candidate has 8) |
| PODD | 139.46–143.31 | 140–142 | 0.52 | 0.29 ATR | 135.56 / 133 | 0.56 ATR | 127.55 / 126 | 0.34 ATR | agree / agree (SUPPORT HOLD, SUPPORT HOLD) | 6 of 6 (candidate has 8) |

### Walk-forward, default parameters, 7 series

**All series**: 801 samples, 785 with a candidate, 16 without. Median failure level 1.25 ATR below price. Closed below it within 20 sessions: 53%; a level the same ATR distance below price on other dates: 53%.

| Group | n | Closed below failure within 20 | Closed below warning within 20 | Breakout of first ceiling | Failed after breakout | Median 20-session return | Median worst excursion |
|---|---|---|---|---|---|---|---|
| all | 778 | 409 (49%–56%) | 537 (66%–72%) | 469 (66%–73%) | 241 (47%–56%) | +1.4% | -3.6% |
| SUPPORT HOLD | 397 | 151 (33%–43%) | 208 (47%–57%) | 219 (66%–76%) | 104 (41%–54%) | +1.6% | -3.2% |
| SUPPORT HOLD · TESTING | 169 | 93 (48%–62%) | 124 (66%–79%) | 114 (63%–77%) | 60 (44%–62%) | +0.9% | -3.8% |
| SUPPORT BREAK | 212 | 165 (72%–83%) | 205 (93%–98%) | 136 (59%–72%) | 77 (48%–65%) | +1.2% | -4.4% |
| SPY above 200-day | 623 | 321 (48%–55%) | 430 (65%–73%) | 369 (67%–75%) | 194 (47%–58%) | +1.3% | -3.2% |
| SPY below 200-day | 155 | 88 (49%–64%) | 107 (61%–76%) | 100 (57%–72%) | 47 (38%–57%) | +1.5% | -6.4% |

### By series: failure level vs a volatility-distance baseline

| Series | Samples with a candidate | Median failure distance | Closed below failure within 20 | Same-distance baseline | Median 20-session return |
|---|---|---|---|---|---|
| ISRG | 247 | 1.33 ATR | 50% | 49% | +2.1% |
| FICO | 63 | 1.25 ATR | 47% | 53% | +2.0% |
| CRDO | 47 | 1.11 ATR | 54% | 53% | +2.7% |
| PODD | 60 | 1.11 ATR | 58% | 58% | -0.3% |
| SPY | 246 | 1.21 ATR | 53% | 53% | +1.3% |
| XLK | 63 | 1.27 ATR | 60% | 57% | +1.5% |
| XLV | 59 | 1.25 ATR | 55% | 57% | +0.0% |

### Parameter sensitivity

| Variant | Samples with a candidate | Closed below failure within 20 | Same-distance baseline | From SUPPORT HOLD | From SUPPORT BREAK |
|---|---|---|---|---|---|
| default | 785 of 801 | 409 (49%–56%) | 53% | 151 (33%–43%) | 165 (72%–83%) |
| tighter zones (tol 0.35) | 782 of 801 | 424 (51%–58%) | 56% | 167 (36%–46%) | 191 (70%–80%) |
| wider zones (tol 0.75) | 789 of 801 | 370 (44%–51%) | 49% | 132 (29%–38%) | 121 (69%–82%) |
| swing k=1 | 796 of 801 | 427 (51%–58%) | 54% | 159 (36%–45%) | 173 (71%–82%) |
| swing k=3 | 766 of 801 | 401 (49%–56%) | 53% | 150 (34%–43%) | 156 (72%–83%) |
| reference 10 sessions | 798 of 801 | 444 (53%–60%) | 56% | 121 (32%–42%) | 226 (71%–81%) |

Gaps are in ATR14 at the as-of session. "Overlapped" means a candidate zone touches the reference zone; candidate zones can be wide (e.g. ISRG 462.4–472), which flatters that count.

### What the validation does and doesn't show

- The method was shaped by looking at the four reference charts as of 22 Oct 2026, so the reference comparison
  is **in-sample**. The walk-forward runs over 2006–2026 (ISRG, SPY) and 2020/2022–2026 (others) with the
  method fixed; it's out-of-sample in time but uses the same seven series.
- Samples are 20 sessions apart, so 20-session outcomes don't overlap within a series. SPY, XLK and XLV are
  correlated with the stocks, so samples across series aren't independent; the Wilson intervals are optimistic.
- Survivorship: only tickers that exist today. Corporate actions: adjusted prices (current adjustment, not
  point-in-time). No exchange calendar: weekdays stand in for sessions. Stale feeds: the live path refuses old
  or gappy caches (DATA REVIEW); the walk-forward uses complete history.
- Breakout and failed-breakout counts use the first candidate ceiling and the same ceiling state machine as
  the shadow; they describe the past, not probabilities.
- **Conclusion:** the floors and states line up with the analyst on the references, but the automatic failure
  levels behave like a volatility stop. They can't support a TRADE INVALIDATED call. Any change to the method
  must be specified and validated again before it's looked at for approval, never tuned on these outcomes.

**On your own list (private):** `python -m stockwatch.cis.validate --watchlist` runs the same walk-forward on
every ticker in your holdings list and writes the report into a **new** owner-only folder (0700, file 0600;
default `~/.stockwatch/cis-reports/walk-forward-<time>/`). It refuses to run in CI, to write inside a Git
checkout, through a symlink or into an existing folder, and its errors never print the path or a ticker.

**Freshness for every ticker:** the whole-list shadow applies the same rule as reviewed packets before any
candidate is computed: the latest completed bar may trail the last expected session by at most one weekday,
with at most one weekday missing among the ten before it. A stale or gappy cache is a data problem, with its
last session shown, and no current candidate state.

## Whole-list shadow (workstream B, items 6–7)

`stockwatch/cis/watchlist.py`, run by "Compare my list" in Research → Chart judgment on a background thread
(Yahoo bars and quotes through the app's cached provider; Finnhub about one call a second).

| Coverage | Stocks | What's shown |
|---|---|---|
| owner-accepted packet | ISRG, FICO, CRDO (when on your list) | CIS shadow call, with every gate (data, staleness, approval, live) |
| proposed packet | PODD (when on your list) | CIS shadow call, marked "proposed, not owner-accepted", never eligible |
| no packet | everything else | **CIS UNSUPPORTED**; the legacy call stays, labelled legacy |
| candidate (all with usable data) | diagnostic only | candidate state, floor, failure and first ceiling; never a call |

Per stock it also shows:
- the legacy stop and target against the candidate failure level and first ceiling, and whether the legacy
  target is a measured move with no chart level behind it;
- an **alert-diff preview**: whether the Telegram decision class would change if CIS were active for that stock
  (REVIEW actions need a new class and are never shown as a sell; unsupported stocks: no change);
- the **Finnhub cross-check**: agree, disagree (by how much) or not compared, and why.

Demo screenshot (synthetic data, so every stock reads "data problem"): `docs/cis-screenshots/watchlist-shadow-390-demo.png`.

## Integration and rollout plan (items 6, 8): nothing is activated

**Legacy paths that CIS would replace for a supported stock** (see `docs/CIS_DECISIONS.md`): the technical part of
`engine._verdict`, `tradeplan.build/refine/reconcile` entry/stop/target (incl. the invented 2R measured move),
`analogs.replay`, the `technical_breakdown/technical_turn` signals, and the stance that
`transitions.effective_stance` / `ui._action` read. **Kept with priority:** non-technical urgent risk vetoes
(position size over the tier limit, stop from cost, thesis/fundamental breaks, unfavourable earnings setups,
SEC risks, severity-3 signals).

Gated rollout, each step a separate owner decision:
1. **Shadow (now):** `STOCKWATCH_CIS_DECISIONS=shadow` shows CIS beside legacy on Details; "Compare my list" for
   the whole list. No alerts.
2. **Per-ticker allowlist:** only packets at `owner_accepted` in the ledger, evaluated live, fresh (≤20 sessions,
   as-of close still matches history), with usable data. Everything else stays legacy.
3. **Dry run:** a Telegram dry-run mode that logs which CIS class changes *would* be sent, for at least two weeks,
   compared with the legacy alerts.
4. **Activation for allowlisted tickers:** the first CIS run re-baselines those tickers silently in the alert
   memory (no burst of changes); add a REVIEW alert class; deduplicate via the existing two-run confirmation.
5. **Kill switch / rollback:** unset the switch (back to legacy at once, alert memory re-baselines silently);
   revert the PR for a full rollback. Audit trail: the packet ID and content hash travel with every CIS call.

## Second source protocol (item 10)

- **Finnhub (key configured by the owner, not visible to this build environment):** `/quote` gives the price,
  today's high/low and the trade time. Used only in the shadow; accepted only if its timestamp is valid, from
  today's New York session and not in the future, and its numbers are finite and consistent (low ≤ price ≤
  high). It stands in for a missing Yahoo quote only under the Yahoo rule (a regular-session trade at most 60
  minutes old); its high/low are used as intraday facts only when it agrees with a current Yahoo quote.
  A stock that can't be compared at all still gets a full row, so one gap never stops the list.
  Prices are compared only when **both** are current regular-session trades (each at most 60 minutes old);
  a pre-market, aged or extended-session quote on either side is "not comparable", even at the same price, and
  Finnhub's high/low are then not used. Daily candles on the free plan may be refused
  ("no access"); they're not used.
- **Daily bars:** for a side-by-side check, download a second source's adjusted daily bars privately and run
  `stockwatch/cis/source_check.compare` (see `docs/CIS_PROVIDER_CHECK.md`). Still **NOT VERIFIED**: no market-data
  host was reachable from the build environment.
- No subscriptions or new keys were added.
