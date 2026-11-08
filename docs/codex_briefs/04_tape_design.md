# Brief 4: the "Tape" look for the whole app (owner, 8 Nov 2026)

**Goal.** Re-skin the phone app in the look the owner picked ("Tape": deep blue, one big number per screen, ivory text, green and coral only for gain and loss),
and replace the wrapped row of 10 tab buttons with a bottom bar plus a More page. **Display only: no scoring, signal, verdict, trade plan, tier rule, threshold or alert changes.**

Samples to match (open the HTML files in a browser at about 390px; sample numbers only):
- `docs/design/tape/samples_three_directions.html`: the Quick screen. The owner picked **Direction A (Tape)**; B and C are there only for comparison. Do not build them.
- `docs/design/tape/tabs.html`: Radar, More, Portfolio, Momentum.
- `docs/design/tape/details.html`: the Details tab (the call, the price ladder, short tables).

Branch `codex/tape-design-<part>` from `claude/stab-study` for now (it holds the new Quick "waiting for a pullback" list that Part 2 shows); after the owner merges it, rebase onto the default branch.
Pull requests into the default branch, template filled in, reviews as in `docs/COLLABORATION.md` (ChatGPT first, then Claude). **Three pull requests, in this order**, so each can be reviewed and rolled back alone:

## Part 1: tokens and navigation (`codex/tape-design-nav`)
- Put the look in one place: `stockwatch/design.py` (it already holds the dark and light themes and `theme_css`). Tokens from the sample: deep blue background `#0d1a2c`, card `#14253c`, line `#233855`, ivory text `#f2efe8`, soft text `#9fb0c8`, gain `#4fd6a5`, loss `#ff8a7a`. Define a light version of each (the sample is dark only), keep Auto / Dark / Light working, keep contrast readable.
- Font: Familjen Grotesk (Google Fonts), with the system sans fallback. Numbers use tabular figures. No other font.
- Navigation (`dashboard.py`, the `VIEWS` / `SHOWN_VIEWS` / `st.segmented_control("View", ...)` block): a fixed bottom bar with five buttons **Radar, Portfolio, Quick, Momentum, More**. More opens a page with the rest in three groups: Look up (Details, S&P 500, Ask the AI, Extended), Practice accounts (Paper, Log), Display (Theme, Sweep now). Keep every `?view=` address working (`?view=target&t=TICKER` links from alerts and the app must still open Details on that stock). A dot on a More item when something waits there (Ask the AI: a recheck is due) is optional; only if the data is already available.
- The bar must clear the phone's safe area, must not cover the last row of any page, and must keep working when the page auto-reloads (CLAUDE.md: capture button actions in `on_click` callbacks or session state; never run long work inline).
- Streamlit's own widgets (buttons, pills, expanders, selects) get the tokens too, in both themes (see `_LIGHT_WIDGETS` in `design.py` for how light is done today).

## Part 2: Quick and Momentum screens (`codex/tape-design-quick`)
- `stockwatch/quick_view.py`: top = day total as the one big number, small line with trades and share won. Then "Waiting for a pullback" (reads `book["watch"]`: ticker, signal price, pullback low if any, a word: "Not yet" or "Turning up"), then Open, then Closed. Each trade row has the ticker, time, a small price path with the entry dot, the stop as a dashed line and the exit dot (the sample's SVG; draw it from the trade's `entry`, `stop0`, `exit` and, if available, the stored path; if no path is stored, show the row without the picture, never a made-up one), the result in dollars and percent, and the exit reason in plain words.
- Fields now on a Quick trade: `signal` and `pullback_low` (new on 7 Nov), `stop0`, `entry`, `exit`, `pct`, `result`, `exit_reason`, `rank`, `of`. Missing values show "unknown".
- Momentum (`stockwatch/rising_view.py`): the rows as in `tabs.html` (move, volume against normal, one plain reason line).

## Part 3: Radar, Portfolio, Details and the rest (`codex/tape-design-screens`)
- Radar: the "does anything need me" line as the one big statement, four small tiles (market, buy zone, needs attention, earnings this week), then the stock list with one status word per row (Act, Buy zone, Hold). Existing wording and colours that carry meaning stay (colour is never the only signal).
- Portfolio: total value as the one big number, holdings with result right-aligned, suggested adds as one short card.
- Details (`stockwatch/details.py`, `ui.py`, `tradelevels.py`, `ui.levels_line`): as `details.html`: stock chips, price, the call word with the "x of 5 checks agree" dots, WHY / CHANGED / WATCH NEXT, the price ladder drawn to scale (resistance, chart exit, price, plan stop, support, from the same data the page uses today), then short tables for plan, chart, company and news. Show only the figures the page already shows; do not add new indicators.
- Remaining tabs (S&P 500, Paper, Log, Ask the AI, Extended): tokens only, no new layouts.

## Ground rules (`CLAUDE.md`)
- No change to scoring, signals, verdicts, trade plans, tier rules or thresholds. If a change touches any, stop and say so on the pull request.
- Missing or blocked data is "unknown", never 0, with the reason on screen. Never show two conflicting answers.
- Plain English, short labels, tappable links (`?view=target&t=TICKER`). The owner reads on a phone.
- Check every screen at 390px with Playwright, offline (`STOCKWATCH_DEMO=1 streamlit run dashboard.py`; Chromium under `/opt/pw-browsers/`), in dark and light. Put the screenshots in the pull request (synthetic data only; the repo is public: no holdings, keys, ntfy topic or Sheet link).
- Tests: `python -m pytest -q` and `python -m pyflakes stockwatch/*.py dashboard.py tests/*.py` stay green; add tests for the pure HTML functions.
- If something here is unclear or wrong, say so on the pull request rather than guessing.
