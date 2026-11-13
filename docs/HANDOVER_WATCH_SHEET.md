# Watch tab: pick stocks from the small-cap list into a very close watchlist (owner, 13 Nov 2026)

For Codex. Claude has already made the **Watch** tab in the owner's small-cap Google Sheet (the same sheet as Shortlist and Log; its link
and key stay in his Windows environment, never in the repo). Columns: **A Ticker, B My comment** (the owner types these, yellow cells),
**C Status, D Company, E Price, F Day %, G Call, H Checked** (the app fills these, grey text). Rows start at 2.

## What to build
1. `stockwatch/watch_sheet.py`
   - `read(sheet)` returns `[{"ticker", "comment"}]` from columns A and B (rows 2+). Upper-case, trim, drop blanks and duplicates, accept only
     `^[A-Z][A-Z0-9.\-]{0,9}$` (anything else gets Status "not a ticker"). At most 60 rows are used (a technical ceiling, say so in Status).
   - Connect with `smallcap_sheet.connect(env)` using `STOCKWATCH_WATCH_SHEET_URL` if set, otherwise `STOCKWATCH_SMALLCAP_SHEET_URL`
     (same pattern as `buy_setups_log.sheet_env`). Errors are sanitised: no link, no key in any message or log.
   - `write_back(sheet, rows)` updates only columns C to H of rows that have a ticker, in one batch call. Never touch A or B, never clear
     the tab, never reorder. Status values: `Watching`, `Already in your list`, `No prices found`, `Not a ticker`, `Over the 60 limit`.
2. Sync on the **tracker thread** (`live.py`), every 5 minutes, in its own short-lived thread like the S&P scan so a slow sheet never
   delays a sweep (CLAUDE.md rule: long work never inline in the page). Save the result in a settings key `watch_sheet`
   (`{"at", "items": [{"ticker","comment"}], "error"}`). A failed read keeps the previous list and records the error; it never empties it.
3. `live.current_portfolio`: add `Holding(ticker, 2, 0)` for every ticker in `watch_sheet` that is not already a holding. Do it for both the
   `wide=True` and `wide=False` paths. These are real watchlist stocks (not `extras`): full read, Radar card, alerts, and open to Quick and
   New call like any watchlist stock. Remove the ticker from the tab and it leaves the list; stored snapshots and any open trade stay
   (`wide_extras` already keeps open-trade stocks tracked).
4. Radar card: one plain line "Your note: ..." under the call when the owner has a comment (read from the `watch_sheet` setting; escape it).
   Tappable link as elsewhere (`?view=target&t=TICKER`). Phone-first, short labels.
5. Status page: one line "Watch tab: N stocks, read HH:MM" or the error.
6. Tests (no network; fake the sheet and the provider): read/validation, write-back touches only C:H, failed read keeps the old list,
   portfolio gains the stocks and drops them when removed, duplicate of an existing holding is not added twice, comment is escaped on the card.

## Rules
- No change to scoring, signals, verdicts, trade plans or tier rules. Say so in the pull request (methodology: none).
- Missing price data is "unknown" with a reason in Status, never 0.
- Respect the rate limits (the new stocks join the normal sweep; no extra per-stock reads outside it).
- Repo is public: no sheet link, key or holdings in code, tests or docs.
- Lint `python -m pyflakes stockwatch/*.py dashboard.py tests/*.py`; tests `python -m pytest -q`. Branch `codex/watch-sheet`.
- The owner's PC dashboard.py is ahead of the default branch (unmerged work): keep the dashboard change small and say which lines changed so
  Claude can patch the PC copy by hand.

## Paste-ready prompt
"Read CLAUDE.md and docs/HANDOVER_WATCH_SHEET.md and build it on branch `codex/watch-sheet`. Open a pull request with the template filled."
