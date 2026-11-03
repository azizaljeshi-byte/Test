# StockWatch: notes for later and the draft PR

Written 26 Oct 2026 while GitHub access was blocked and the app ran on the owner's own Windows PC.
No holdings, links, keys or tickers-owned are listed here on purpose: the repo is public.

## A. Changes made on the PC (display only), to bring into a pull request

Each one changes text or layout only. No scoring, signal, verdict, trade-plan value, tier rule or threshold was touched.

| File | Change | Test |
|---|---|---|
| `stockwatch/radar_search.py` (new), `dashboard.py` | Search box above the Radar filters: ticker or company name, every word must match, blank keeps all | `tests/test_radar_search.py` |
| `stockwatch/ui.py` `trade_plan` | When buying is held back, the plan card starts with "Not adding yet: <reason>"; the zone row says "(on hold)"; "Trigger" reads "Buy again when" | `tests/test_trade_plan_hold.py` |
| `stockwatch/briefing.py` `stock` | A buy-looking verdict over a WAIT plan now says "is a WAIT, not a buy yet: <reason>" | `tests/test_briefing_wait.py` |
| `dashboard.py` | Paper tab footer shows a build label (test-1, search-1, search-2, wait-1). Remove or keep as a version tag | none |
| `run_stockwatch.py` (PC only, not for the repo) | Starts the app, reads the settings file, restarts on `update_ready.txt` (waits for the US market to close unless the file says `now`), restarts after a crash | none |

Also local only, not yet pushed: branch `claude/paper-safety` (audit items F04-F07, F14, F17). Needs pushing and a PR when GitHub access returns. Audit items are in `docs/AUDIT_LOG.md` (PR #66, owner to merge).

## B. Waiting for the owner's go-ahead (methodology or plan-affecting, so not done)

1. **Outlook box volatility collapses when the market is closed.** The 12-month bear, base and bull lanes are built from the options feed's implied volatility. While the market is closed that value is near zero, so all three lanes are equal and "chance it is higher" reads 100%. The same number feeds the trade plan's forward score (0.5 up at 60% or more, 0.5 down below 45%), so a fix can flip a bias. Options: (1) leave it, it clears at the open; (2) display-only "not enough data while the market is closed"; (3) ignore implausibly low volatility and fall back to price-history volatility, then list which plans change. Owner chose to leave it and re-check at the open.
2. **One decision per stock.** A single stock can show five labels (watch, buy-setup score, testing support, falling, wait for confirmation). Collapse into one straight answer. Reconciles calls, so it waits until after the paper test.
3. **Entry path is ambiguous on the plan card.** A plan can show a pullback entry zone and a breakout trigger above it without saying which applies. The paper engine enters only on a buy call, with no failing entry check, earnings more than 2 days away, and price inside the zone at that moment. Show one rule on the card.
4. **Fundamentals line names the same pillar as best and weakest** (for example "best on valuation (100), weakest on valuation (100)"), and a perfect valuation score looks suspect. Check the pillar scoring and the wording when pillars tie or only one exists.
5. **Second price source (Stooq) unreachable** from the PC. The card says "no read". Decide whether to keep it, replace it, or hide the line when it can't be reached.
6. **Overnight prices.** The tracker covers 4:00 am to 8:00 pm New York only. Options: leave, label cards "overnight, not updated", or add an overnight source (probably paid).
7. **Plain-English summary box** at the top of a stock page (three lines: call, what re-opens it, what to watch today). Owner leaning yes, only if it replaces reading and adds no new scores. A TradingView script was judged not worth it for now.
13. **Rebound / momentum capture as a second paper strategy (owner interested, rules still to come from the owner).** Example from 26 Oct: a stock with a broken chart and weak fundamentals (call: pass) rebounded about 5% intraday and the system could not act on it, by design (swing rules need a confirmed chart and a daily close). Run it as its own paper bucket, separate from the swing results: trigger (size of the day move, volume vs normal, how early in the session), small size, tight stop, trailing or end-of-day exit, time limit. Needs live volume and the fast price lane (item 10). Owner to answer: what move, how long to hold, how to exit.
8. **Holiday calendar** before 26 Nov (US market holidays are not recognised). Audit item F08.
9. **S&P 500 scanner picks in the paper test (owner approved, 5 picks, next update).** Each morning before the open, take the S&P scan's "BUY SETUP" results (not all finalists), keep the best 5, run the normal full analysis on each (same entry checks, stops, targets; Yahoo limit of 3 in flight), and let the paper engine trade them in the regular session only. Keep them in a separate bucket: the Paper tab and report show them apart from the hand-picked Test list so the two can be compared. Paper only: no scoring, signal or threshold change. Picks are chosen before the open, so it goes live the day after it is built.
10. **Fast price lane (owner approved the direction).** Use the Finnhub key for live prices on the paper list and open positions only (check first that the free plan streams live US trades for up to 50 symbols), keep the rest on the 1-minute Yahoo refresh. The paper engine fills at the streamed price. Respect the Finnhub limit (about 1 request a second on REST on the free plan). Owner is considering Finnhub Basic ($49.99 a month, billed quarterly, personal use): 150 API calls a minute, US 1-minute OHLC (10 years), tick data (5 years), websocket 250 symbols. Not yet confirmed: whether the data is real-time or delayed (check the rows below on the plan page), refund terms. Do not subscribe until a build is ready. With Basic: live volume and a 1-minute chart from the plan's own bars, request limit raised to match. No change to analysis or rules.
11. **Blocked-buys log repeats the same block every 20 seconds** (same stock, same reason, hundreds of rows, and the Sheet tab floods). Log a block only when the reason changes, or once per stock per hour.
12. **Decision review (owner wants it).** Revisit how calls are made, using real paper results: one decision per stock (item 2), the entry gates and which ones block most, the wait-versus-buy wording, and the outlook inputs (item 1). Do it with at least a few sessions of paper data, and list every rule change in the pull request.

## C. Existing fix queue (see `docs/AUDIT_LOG.md`)
A1, A4/F04 (done on the paper-safety branch), A5/F03, B3, B6, technical-bar fix, A3/F02 (owner picks fail-open or fail-closed), F19 Turbo overwrite, F08 holiday calendar, F10, F16 CI, F09 urgent path, F11/F18, F13/B7. Reassess-on-bounce stays as it is by the owner's choice.

## D. Running it on the PC
- Start: shortcut in the Startup folder runs `run_stockwatch.py` with the venv Python. Settings are read from the local settings file (never commit it).
- Update while away: write changed files into the app folder, then create `update_ready.txt` (text `now` to restart immediately). Old files are kept in the `previous` folder for rollback.
- Only one copy may run (port 8501). To stop everything: `taskkill /F /IM python.exe`.
- The cloud copy must not also trade: keep the paper list link out of the cloud secrets.
- Live tracking is 4:00 am to 8:00 pm New York; paper trading only acts in the regular session (9:30 am to 4:00 pm New York).

## E. Draft pull request text
Title: Display-only: Radar search, held-back buy notice on the plan card, straight WAIT headline

Summary: three display changes (section A). No change to scoring, signals, verdicts, trade plans, tier rules or thresholds.
Tests: `python -m pytest -q` (832 passed, 35 skipped), `python -m pyflakes stockwatch/*.py dashboard.py tests/*.py` clean.
Not in this PR: everything in section B.
