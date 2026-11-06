# Brief for Codex: valuation screen and the rest of the S&P 500 (owner, 6 Nov 2026)

Two tasks the owner wants Codex to take. Each is its own branch and its own pull request (`codex/valuation-screen`, `codex/universe-feed`),
branched from `claude/stab-study` for now (it holds `stockwatch/portfolio.py`, the new Portfolio account the first task feeds); after the owner merges
the `claude/stab-study` pull request, rebase onto the default branch. Pull requests go into the default branch and follow `docs/COLLABORATION.md`.
Reviews of Codex's pull requests: ChatGPT first, then Claude.

Ground rules (from `CLAUDE.md`, they matter here):
- Missing or blocked data is "unknown", never a score of 0. Say why.
- Do not change scoring, signals, verdicts, trade plans or tier rules. Both tasks ADD readings; they do not change any existing call.
- Respect rate limits: Yahoo through `@_yahoo` (3 in flight), SEC (4 in flight), Finnhub (about 1 request a second). Use bulk downloads for many tickers.
- Long work runs on the tracker thread (`live.py`), never inline in the page. Session comes from `data.us_session` (New York clock).
- Tests need no network (fake Yahoo, SEC, Finnhub). Keep `python -m pytest -q` and `python -m pyflakes stockwatch/*.py dashboard.py tests/*.py` green.
- The repo is public: no keys, ntfy topic, Google Sheet link or holdings. Plain English on screen, short labels, phone width (390px).

## Task 1: the undervalued / overvalued screen (`stockwatch/valuation_screen.py`, new)

Why: the Portfolio account (`portfolio.py`) adds only to stocks that are undervalued AND have very strong fundamentals. Today `portfolio.undervalued()` and
the fundamentals bar are simple first versions the owner wants improved and also wants an "overvalued" side (to help decide what to trim or avoid).

What exists (read, do not edit): `fundamental.py` (score 0 to 100, pillars valuation/growth/quality/balance, `analyst_upside`), `deepdive.py` (fair value from
up to three methods: analysts, own history, peer multiple; `fair_value = {low, mid, high, methods, upside}`), `portfolio.py` (`undervalued`, `add_check`, the
constants `FUND_ADD`, `FAIR_UP`, `ANALYST_UP`, `MIN_METHODS`), stored snapshots (`store.latest_snapshots()`: `payload.research.valuation.fair_value`,
`payload.fundamental`, `fundamental_score`).

Build: pure functions that take a stored snapshot and a price and return a plain-English reading, for example
`reading(snap, price) -> {"label": "undervalued" | "fair" | "overvalued" | "unknown", "fair_gap": ..., "analyst_gap": ..., "methods": n, "why": "..."}`
and `very_strong(snap) -> (bool, why)`.
- Undervalued today means: fair value (at least 2 methods) 15% or more above the price AND the analyst target 10% or more above. Keep that as the default, but check
  it against the stored data: how many of the ~236 tracked stocks pass, and do the outliers look right (fair value from one odd method, a tiny analyst count)?
  Propose better thresholds with the numbers behind them in the pull request. Do not change the thresholds in `portfolio.py` yourself.
- Overvalued: the mirror image (price well above fair value and the analyst target below the price), with the same guard on unknowns.
- Very strong fundamentals: the score is 75 or more today. Suggest whether a pillar floor (no pillar weak) is worth adding; show how many stocks it removes.
- Unknown stays unknown (no fair value, one method, no analyst target): never counted as cheap or expensive.
Deliver: the module, tests with hand-made snapshots, and a short note in the pull request with the pass counts on a real database copy (ask the owner for one if needed).
Claude wires it into `portfolio.py` after the review.

## Task 2: the rest of the S&P 500 (`stockwatch/universe_feed.py`, new)

Why: Quick and the New call account only see the ~230 tracked stocks, because only those have minute-by-minute data. The other ~270 S&P 500 stocks are logged by
`candidates.py` as "S&P only" and neither account can trade them. The owner wants Quick to scan the whole index, rank every setup, then enter the best one
(queue item 33). Claude will change Quick's loop; Codex builds the data feed it will read.

Build: one module that, on the tracker thread, keeps a read-only table for the untracked S&P 500 stocks (list in `stockwatch/universe/`), refreshed during
the regular session, with per stock: last price and when it was fetched, today's change, today's volume, the 20-day average volume, the ATR, today's 1-minute bars
(enough to read the day's chart the way `quick.read_chart` needs), and the days to earnings from the cached dates (`data/earnings_dates_cache.pkl`, see `earnings_study.py`).
- Use bulk downloads (one multi-ticker request per batch), not one request per stock. Respect the Yahoo limit above. Say what is stale or missing per stock.
- A stock with a missing price, volume or average is "unknown" and is left out of the ranking, with the reason kept.
- Minimum price and volume filters are a setting (default: price $5 or more, 20-day average volume 500,000 or more); they only decide what the feed keeps.
- It must never slow the existing tracker: a failed or slow download skips the cycle and logs why.
Deliver: the module, a function Quick can call (for example `universe_feed.snapshots(now)` returning records shaped like the tracked-stock snapshots the accounts read
through `paper_live.fresh_price`), tests with a faked Yahoo, and a short note on how long a full refresh takes and how many requests it makes.
Do not change `quick.py` or `paper_newcall.py`; Claude does that after the review.

## Both tasks
- Put the numbers you measured in the pull request, in tables, minimal wording (the owner reads on a phone).
- If something in this brief is unclear or wrong, say so on the pull request rather than guessing.
