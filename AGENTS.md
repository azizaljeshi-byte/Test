# StockWatch: notes for Codex (and any other coding agent)

StockWatch is a personal stock dashboard (Streamlit) that the owner reads on a phone. Read `docs/HANDOFF.md`
first: features, code map, data sources, configuration, decisions and known limits. Roles and the shared
workflow between Claude, ChatGPT, Codex and the owner are in `docs/COLLABORATION.md`.

## Your role
- **Reviewing:** you are the **second independent reviewer** of pull requests, after ChatGPT. Review the code itself: correctness, edge cases, tests, rate limits, secrets, and that missing data stays "unknown".
- **Labelling findings:** mark each finding **blocking** or **non-blocking**. Comment on the pull request; don't push to the author's branch.
- **Building:** when the owner assigns you work, build it on a `codex/<topic>` branch and open a pull request.

## Working on this repo
- **Default branch:** `claude/stock-dashboard-alerts-rr9r83`. Streamlit Cloud deploys from it, so merging is deploying. **Never commit or push to it directly.**
- **Branches:** branch off the latest default branch, one topic per branch. Don't push to `claude/*` or `chatgpt/*` branches.
- **Pull requests:** open one into the default branch and fill in `.github/pull_request_template.md`. Answer every blocking finding with a fix pushed to the same branch, or a reply saying why not.
- **Merging:** never merge, not even your own pull request. The owner merges and then reboots the app.
- **Methodology:** don't change scoring, signals, verdicts, trade plans or their thresholds unless the owner asks. When a change does, say so in the pull request. The list of protected files is in `docs/COLLABORATION.md`.
- **Tests:** `python -m pytest -q` (no network needed; Yahoo, SEC and Finnhub are faked). Keep them green and add tests for new logic.
- **Lint:** `python -m pyflakes stockwatch/*.py dashboard.py tests/*.py`.
- **Offline UI:** `STOCKWATCH_DEMO=1 streamlit run dashboard.py`. Check screen changes at phone width (390px).

## Rules that came from real bugs
- Missing or blocked data is "unknown", never a score of 0. Say why on screen.
- Never show conflicting answers (for example "exit" and "bullish"): reconcile them, or show no signal.
- Session comes from the New York clock (`data.us_session`), not Yahoo's `marketState`.
- The page auto-reloads when the live tracker lands results: capture button actions in `on_click` callbacks or session state, and run long work on the tracker thread (`live.py`), never inline in the page.
- The page must never wait on Yahoo: read the tracker's last copy (`CachedProvider.peek_history`) or start a background thread.
- Respect the rate limits: Yahoo through `@_yahoo` (3 in flight), SEC (4 in flight), Finnhub (about 1 request a second); use bulk downloads for many tickers.
- Streamlit renders HTML through React: never put a `checked` attribute on a radio input (it locks the input).
- The repo is public: never commit keys, the ntfy topic, the Google Sheet link or holdings.
- The owner reads on a phone: plain English, short labels, tappable links (`?view=target&t=TICKER`).
