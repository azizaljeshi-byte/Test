# CIS chart decisions (Issue #29): shadow replacement for the technical BUY / SELL / HOLD logic

**Status: SHADOW, OFF by default.** Nothing in this document changes a live call, a trade plan, the alert
memory or Telegram. Activation needs Codex review, Claude corrections, a Codex re-review, a methodology check
and the owner's explicit approval.

- Switch: `STOCKWATCH_CIS_DECISIONS`. Unset or anything else = **off**. `shadow` = the Details page shows a
  labelled "CIS chart decision · shadow" card under the existing trade plan. There is **no active mode**.
- Code: `stockwatch/cis/decision.py` (adapter), `stockwatch/cis/shadow.py` (old-vs-CIS comparison),
  `stockwatch/cis/` (engine; see `docs/HANDOFF.md`). Research → Chart judgment is the diagnostics view.
- Supported stocks: only those with a **reviewed level packet**: ISRG, FICO, CRDO (owner-accepted in chat) and
  PODD (analyst proposed, not yet separately accepted), all as of the 22 Oct 2026 close. Every other stock is
  **CIS UNSUPPORTED** and keeps its existing call, labelled legacy. Levels are never generated for other
  tickers; automatic level selection is unvalidated and out of scope.

## State names (owner-approved, Issue #29 comment 6370570304)

A technical STATE is not a trading ACTION. Names are display labels; the internal ids, thresholds and state
machines are unchanged.

| Internal id | Shown as | Meaning (completed daily close) |
|---|---|---|
| `above_floor` | SUPPORT HOLD | at or above the floor's top edge |
| `testing_floor` | SUPPORT HOLD · TESTING | inside the floor zone; defense not yet proven |
| `warning` | SUPPORT BREAK | below the floor's lower edge |
| `failure` | TRADE INVALIDATED | below the packet's tactical-failure level |
| `major_damage` | TREND BREAKDOWN | below the major-damage level |
| ceiling `testing` | RESISTANCE TEST | a quote/wick in the band, or a close back inside it after a breakout (unresolved) |
| ceiling `close_above` | BREAKOUT CONFIRMED | a completed close above the band's upper edge |
| ceiling `retest_defended` | BREAKOUT RETEST HELD | a later session traded into the band and closed above it |
| ceiling `failed_breakout` | FAILED BREAKOUT | after a breakout, a completed close below the band's lower edge |

"Below" is strict: a close exactly at a threshold is not below it. The live quote and the session's low are
shown as **provisional** and **intraday** facts; only a completed close changes the state behind an action.

## State → action (owner-approved mapping with corrections, comment 6370597469)

| Confirmed state | Held | Watchlist |
|---|---|---|
| no reviewed packet / no floor / no completed close | CIS UNSUPPORTED (legacy call shown, labelled) | same |
| TRADE INVALIDATED or TREND BREAKDOWN | Tier 1 (core): **RISK — REVIEW REDUCTION/EXIT**; tactical contract: **EXIT TACTICAL**; otherwise (Tier 2, no contract): **REVIEW REQUIRED** | NO TRADE |
| FAILED BREAKOUT (any ceiling) | REDUCE/EXIT REVIEW (EXIT TACTICAL with a contract) | NO TRADE |
| SUPPORT BREAK | TRIM / REDUCE REVIEW (stop adding) | NO TRADE |
| SUPPORT HOLD · TESTING | HOLD | WAIT FOR SUPPORT CONFIRMATION |
| SUPPORT HOLD, a ceiling at BREAKOUT RETEST HELD | HOLD | WAIT — REVIEW NEW FLOOR (a new floor is a new reviewed packet version, never installed automatically) |
| SUPPORT HOLD, a ceiling at BREAKOUT CONFIRMED | HOLD | SETUP CANDIDATE (pending follow-through) |
| SUPPORT HOLD, RESISTANCE TEST | HOLD | WAIT |
| SUPPORT HOLD otherwise | HOLD | WAIT, SETUP CANDIDATE or a conditional BUY ON DIP proposal (entry check below) |

**Mandates.** The holding model has tiers only (README: Tier 1 "core", Tier 2 "tactical") and no trade
contract linking a position to a packet. So a broken level never produces an unconditional sell: Tier 1 gets a
risk review, and anything without a known contract gets REVIEW REQUIRED. `tactical_contract=True` (EXIT
TACTICAL) exists in the adapter for a future contract model (#27) and is unused by the app.

**Entry check (watchlist, SUPPORT HOLD, first ceiling not reached).** Reward/risk at the **worst permitted
entry** (the floor's top edge) to the **first ceiling's lower edge**, against the fixed failure level, gross and
net of an illustrative 0.2% round trip. `RR_MIN = 1.5` is a provisional, configurable, **unvalidated
screening filter**, not a buy rule or evidence of positive expectancy. A conditional **BUY ON DIP** proposal
also needs: a dated defense of the floor in the last 10 completed sessions (traded into the zone, closed at or
above its top), no verified event (earnings) inside the 20-session horizon, the first ceiling still NOT
REACHED, and usable data. Passing the filter without the rest = SETUP CANDIDATE; failing it = WAIT. **No order
is placed**, ever. There is no BUY NOW in v1.

**Existing labels.** Each action maps to an existing plan stance where one fits (BUY ON DIP → BUY ON PULLBACK,
WAIT variants → WAIT FOR CONFIRMATION, TRIM / REDUCE REVIEW → TRIM / PROTECT, EXIT TACTICAL → REDUCE / EXIT,
NO TRADE → NO TRADE). The three REVIEW actions have **no existing label** on purpose: they must not be shown or
alerted as a sell.

## Reference outcomes (22 Oct 2026 close; quotes 23 Oct, different times)

| Stock | Held (any tier) | Watchlist | Reward/risk at worst entry (gross / net) |
|---|---|---|---|
| ISRG | HOLD (SUPPORT HOLD) | WAIT | 1.38 / 1.25 |
| FICO | HOLD (SUPPORT HOLD) | WAIT | 1.05 / 0.97 |
| PODD | HOLD (SUPPORT HOLD) | WAIT (also blocked by earnings 4 Nov, before the open) | 0.89 / 0.83 |
| CRDO | TRIM / REDUCE REVIEW (SUPPORT BREAK); quote 153.01 provisionally TRADE INVALIDATED; the 142.89 wick crossed 149 and recovered | NO TRADE | — |

## Old vs CIS on the same frozen bars (`python -m stockwatch.cis.shadow`)

Legacy rows run the existing engine (verdict → `tradeplan.build/refine/reconcile`) on the frozen completed bars.
The frozen inputs have no fundamentals, events or research, so these are the engine's own "fundamentals
unavailable, price action only" path, the one production takes when Yahoo blocks fundamentals. The ISRG
"live app capture" row is the live app's call recorded in the reference round (verdict BUY SETUP with the
website's fundamental score 77; `fixtures/ISRG-scanner-audit.json`).

| Stock | Case | Legacy verdict → plan | Legacy entry / stop / target | CIS action | CIS levels | Changed | Non-technical risk signals |
|---|---|---|---|---|---|---|---|
| ISRG | held, Tier 1 (core) | STRONG HOLD → HOLD | 430.85–437.36 / 404.79 / 592.85 (52-week high) | HOLD (SUPPORT HOLD) | floor 436.00–440.00, failure < 424.00 | no | fundamentals_unavailable |
| ISRG | held, Tier 2 | STRONG HOLD → HOLD | 430.85–437.36 / 417.81 / 495.93 (2R measured move) | HOLD (SUPPORT HOLD) | floor 436.00–440.00, failure < 424.00 | no | fundamentals_unavailable |
| ISRG | watchlist | WATCH → WAIT FOR CONFIRMATION | 395.04–401.55 / 372.25 / 448.17 (resistance) | WAIT (SUPPORT HOLD) | floor 436.00–440.00, failure < 424.00 | no | fundamentals_unavailable |
| ISRG | watchlist (live app capture) | BUY SETUP (observed in the app, fundamentals 77) → BUY NOW | 437.34–443.85 / 424.34 / 473.10 (2R measured move) | WAIT (SUPPORT HOLD) | floor 436.00–440.00, failure < 424.00 | yes | none |
| FICO | held, Tier 1 (core) | TRIM / REVIEW → TRIM | 730.11–752.32 / 689.99 / 1,089.83 (2R measured move) | HOLD (SUPPORT HOLD) | floor 780.00–790.00, failure < 750.00 | yes | fundamentals_unavailable, lagging_market |
| FICO | held, Tier 2 | TRIM / REVIEW → TRIM | 730.11–752.32 / 734.42 / 1,000.97 (2R measured move) | HOLD (SUPPORT HOLD) | floor 780.00–790.00, failure < 750.00 | yes | fundamentals_unavailable, lagging_market |
| FICO | watchlist | AVOID → NO TRADE | 730.11–752.32 / 652.37 / 877.51 (resistance) | WAIT (SUPPORT HOLD) | floor 780.00–790.00, failure < 750.00 | yes | fundamentals_unavailable, lagging_market |
| CRDO | held, Tier 1 (core) | TRIM / REVIEW → TRIM | 156.09–163.80 / 116.51 / 302.52 (52-week high) | TRIM / REDUCE REVIEW (SUPPORT BREAK) | floor 180.00–185.00, failure < 160.00 | yes | fundamentals_unavailable, lagging_market |
| CRDO | held, Tier 2 | RISK - REVIEW → REDUCE / EXIT | 156.09–163.80 / 131.93 / 302.52 (52-week high) | TRIM / REDUCE REVIEW (SUPPORT BREAK) | floor 180.00–185.00, failure < 160.00 | yes | fundamentals_unavailable, lagging_market |
| CRDO | watchlist | AVOID → NO TRADE | 156.09–163.80 / 129.11 / 302.52 (52-week high) | NO TRADE (SUPPORT BREAK) | floor 180.00–185.00, failure < 160.00 | no | fundamentals_unavailable, lagging_market |
| PODD | held, Tier 1 (core) | TRIM / REVIEW → TRIM | 144.52–146.81 / 134.41 / 175.54 (2R measured move) | HOLD (SUPPORT HOLD) | floor 140.00–142.00, failure < 133.00 | yes | fundamentals_unavailable |
| PODD | held, Tier 2 | TRIM / REVIEW → TRIM | 144.52–146.81 / 138.98 / 166.40 (2R measured move) | HOLD (SUPPORT HOLD) | floor 140.00–142.00, failure < 133.00 | yes | fundamentals_unavailable |
| PODD | watchlist | AVOID → NO TRADE | 144.52–146.81 / 136.52 / 163.94 (2R measured move) | WAIT (SUPPORT HOLD) | floor 140.00–142.00, failure < 133.00 | yes | fundamentals_unavailable |


What changes and why:
- **ISRG (live app): BUY NOW → WAIT.** The old plan bought at 437–444 with a 424.34 stop and a **2R measured-move
  target (473.10) that no chart level supports**; its stop also jumped between 425.48 and 441.69 on a 2-cent
  quote change. CIS keeps 424 fixed and finds only 1.38 (gross) reward/risk to the first actual ceiling
  (462–463).
- **FICO / PODD held: TRIM → HOLD.** The old TRIM comes from the composite score falling under 40 when only the
  technical score is available, not from a price level; CIS holds while the floor holds. The old FICO and PODD
  targets are 2R measured moves.
- **CRDO held Tier 2: REDUCE / EXIT → TRIM / REDUCE REVIEW.** The close is below the floor but above the 160
  tactical-failure level; the exit is only provisional until a session closes below 160.
- **FICO / PODD watchlist: AVOID/NO TRADE → WAIT.** Legacy AVOID comes from the low composite. CIS is
  technical-only, so at activation the non-technical controls below must still be able to veto.

## Today's decision path (what CIS would replace)

1. `technical.analyze` → technical score (trend, RSI, MACD, volume, 52-week location) + technical signals.
2. `relative.analyze` nudges the technical score; `fundamental.analyze` → fundamental score.
3. `engine._verdict`: urgent risk signals, `quality_entry`, `target_reached`, composite thresholds (40 / 65)
   → BUY SETUP / WATCH / AVOID / OPPORTUNITY - ADD / HOLD / STRONG HOLD / TRIM / REVIEW / RISK - REVIEW.
4. `tradeplan.build`: entry zone from swing support, SMA20/50 and ATR; stop below structure or 2–3× ATR;
   target from resistance / 52-week high / fair value / consensus, else an **invented 2R measured move**.
5. `analogs.replay` replays that stop/target; `tradeplan.refine` adjusts by street/events/history;
   `tradeplan.reconcile` resolves conflicts with signals.
6. `transitions.effective_stance` (shared with `ui._action`) → the call shown on cards and sent to Telegram.

## Retired at activation (for supported stocks only; nothing is retired now)

- `tradeplan.build` entry zone, stop and **2R measured-move target** → the packet's floor zone, failure level
  and dated ceilings.
- `analogs.replay` / `tradeplan.refine` win-rate replay of a mechanically chosen stop/target → CIS same-stock
  history (descriptive only, never a probability).
- The **technical part** of `engine._verdict` (composite thresholds, `quality_entry` from the technical score)
  → the CIS state → action mapping.
- `technical_breakdown` / `technical_turn` score-swing signals → CIS state transitions.

**Kept and taking precedence over a CIS HOLD/WAIT at activation** (non-technical risk controls): position size
over the tier limit, stop-loss from cost, thesis/fundamental breaks, unfavourable earnings setups, SEC/filing
risks, and anything marked urgent (severity 3). The shadow table lists which of these were present.

## Alerts and migration (nothing changes now)

- In shadow mode nothing reaches `transitions`, the alert memory or Telegram (a test asserts that `engine`,
  `tradeplan`, `transitions`, `ci_scan`, `notify`, `scanner` and `live` don't import `stockwatch.cis`).
- At activation: the CIS stances use existing labels, so `STANCE_CLASS` keeps working; the three REVIEW actions
  need a new `REVIEW` class (never shown as SELL). The first CIS run must **re-baseline** every supported stock
  silently (as an ownership change does today), so the switch itself can't send a burst of "changes".
- Unsupported stocks keep their legacy calls and alerts until they have reviewed packets.

## Limits

- The four level sets were selected by an analyst; nothing here selects levels or proves they generalise.
- The 465+ passing tests check the code against the fixtures and the agreed rules. They are **not** evidence of a
  profitable strategy, calibrated odds or the right 1.5 threshold; Codex should assess sensitivity (1.5, 2.0, …)
  once real historical samples exist.
- No exchange calendar: completed sessions are bars dated before today's New York date; holidays and early
  closes aren't verified.
- Packets are snapshots: their levels are as of 22 Oct 2026 and need explicit new versions to change.
