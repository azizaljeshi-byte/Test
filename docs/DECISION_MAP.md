# Where StockWatch makes a "call" (read-only map, 26 Oct 2026)

Made by reading the code, not by running new tests. No ticker names, holdings or links are listed (public repo).
Purpose: find every place a call is produced, then see where they can disagree.

## 1. The producers, in the order data flows

| # | Where | What it produces | Looks at | Used by |
|---|---|---|---|---|
| 1 | `engine._verdict` | `verdict`: BUY SETUP, OPPORTUNITY - ADD, WATCH, AVOID, HOLD, STRONG HOLD, TRIM / REVIEW, RISK - REVIEW | signals (`quality_entry`, urgent risk, `target_reached`) and the composite score only | radar grouping (`ui.sector`), headline (`briefing`), Details score line, alert text, S&P scan (BUY SETUP picks), turbo |
| 2 | `tradeplan` plan builder | `stance`: BUY NOW, BUY ON PULLBACK, BUY THE BREAKOUT, ADD, WAIT FOR CONFIRMATION, HOLD, TRIM, TRIM / PROTECT, REDUCE / EXIT, NO TRADE, plus zone, trigger, stop, targets | price structure, volatility, support | plan card, paper engine, sizing guide |
| 3 | plan rewriters, run in sequence: `refine` (street, forward score), `reconcile`, `exit_on_breakdown`, `hold_off_buying` | change the stance after step 2 | street data, price status, entry gates | same as 2. The order matters: each can overwrite the one before |
| 4 | `status` | price status code (testing support, weakening, breakdown, ...) judged on completed daily closes; `entry_blockers`, `blocks_buy`, `forces_exit` | daily bars, TradingView / Finnhub / Stooq reads | steps 3, 5, 6, 7 |
| 5 | `transitions.effective_stance` | a second reconciled stance from (verdict, plan, watchlist, status, technical) | steps 1 to 4 | `ui._action` (the word on the card) and phone alerts |
| 6 | `ui.action` / `ui._action` / `ACTIONS` / `reassess` | the call word: BUY NOW, BUY ON DIP, BUY ON BREAKOUT, BUY MORE, WAIT, HOLD, PASS, SELL SOME, SELL, REASSESS | step 5 | radar rows, Details, guide, paper engine |
| 7 | `ui.ring` | urgency 1 act / 2 close / 3 calm and its reason | its own order: urgent risk, forced exit, plan exit, blocked buy, in zone, earnings | radar sections, "needs attention" counts |
| 8 | `decision.decide` | paper engine: ENTER, HOLD, SELL_PART, SELL_ALL, NONE | its own rule order; entry uses `status.entry_blockers`, `plan.status_exit`, the call word from step 6, earnings window, and its own zone test | paper trading only |
| 9 | `turbo` | its own buy / wait reading | plan stance, verdict, "ran past" and "chasing" tests | Turbo tab |
| 10 | `guide.verdict` | BUY, WAIT or DON'T BUY with a tick or cross per gate | the call word plus gates | guide card |
| 11 | `briefing.stock` (headline), `details` (score vs chart clash note) | sentences that restate a call | verdict, now overridden to WAIT when the plan waits | headline on pages |
| 12 | `cis` decision | shadow call, labelled "not active" | CIS packets | shadow card |

## 2. Where they can leak (disagree)

1. **The verdict never sees the chart.** Step 1 only knows signals and the score, so a stock can be BUY SETUP while the chart is testing support and the plan says wait. Everything keyed on `verdict` inherits that (grouping, S&P picks, alert text). The Details page patches it with a clash note; the headline now patches it for WAIT.
2. **The buy-block rule exists twice.** `hold_off_buying` (rewrites the plan) and `effective_stance` (rewrites the stance again at display time) both implement "never say buy over a broken chart". They agree today only because both call `status.blocks_buy`.
3. **Plan rewriters are order-dependent** (step 3). A change in one can silently alter what the next sees.
4. **Five separate "combine" functions** (ring, action, decide, turbo, guide) each choose what wins, with different orders. This is the root of "five calls for one stock".
5. **A wait plan keeps buy-plan fields.** The zone and trigger stay on the card for reference, so a zone and a breakout trigger can both show with no statement of which applies (the zone can sit below the trigger).
6. **Text says one thing, code does another.** The second-opinion line says "A second opinion only; it changes no call", but gate 5 turns a TradingView or Finnhub SELL into an entry blocker (it appears as a blocked-buy reason). When gates are on the sentence is false.
7. **Time of evaluation differs.** The plan and verdict are computed at scan time; the call word is rebuilt at render time from the saved price status. A quick refresh between scans can show a newer status over an older plan.
8. **Paper engine has a fourth copy of the entry rule** (zone test, earnings window, gates), so a screen can say WAIT or BUY while paper decides separately.
9. **Blocked buys are logged every 20 seconds** for the same reason (noise, not a disagreement).

## 3. A way to fix it (for the decision review, not built)
One function, `decide(snap)`, returns a single object: `{call, reasons[], numbers{trigger, zone, stop, targets}}`, computed once at scan time and saved on the snapshot. Radar rows, plan card, headline, alerts, guide, turbo and the paper engine all read that object and none of them recompute a call. The old functions move to `previous` and run in shadow for a few sessions so the two can be compared before switching.
