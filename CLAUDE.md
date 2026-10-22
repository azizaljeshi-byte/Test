# StockWatch: notes for Claude

Read `docs/HANDOFF.md` first: features, code map, data sources, configuration, decisions and known limits.

## Working on this repo
Claude, ChatGPT and Codex share this repo through branches and pull requests. Roles and the full workflow are in `docs/COLLABORATION.md`.

- **Default branch:** `claude/stock-dashboard-alerts-rr9r83`. Streamlit Cloud deploys from it, so merging is deploying. **Never commit or push to it directly.**
- **Branches:** work on a feature branch off the latest default branch, named `claude/<topic>`, one topic per branch. Don't push to `chatgpt/*` or `codex/*` branches.
- **Pull requests:** open one into the default branch and fill in `.github/pull_request_template.md`. Your pull requests are reviewed by ChatGPT first, then Codex; when you review ChatGPT's or Codex's, follow the order in `docs/COLLABORATION.md`. Answer every blocking finding with a fix pushed to the same branch, or a reply saying why not.
- **Merging:** never merge, not even your own pull request. The owner merges and then reboots the app.
- **Methodology:** don't change scoring, signals, verdicts, trade plans or their thresholds unless the owner asks. When a change does, say so in the pull request.
- Tests: `python -m pytest -q` (no network needed; Yahoo, SEC and Finnhub are faked). Keep them green and add tests for new logic.
- Offline UI: `STOCKWATCH_DEMO=1 streamlit run dashboard.py`. Check UI changes at phone width (390px) with Playwright; the Chromium executable is under `/opt/pw-browsers/`.
- Lint: `python -m pyflakes stockwatch/*.py dashboard.py tests/*.py`.

## Rules that came from real bugs
- Missing or blocked data is "unknown", never a score of 0. Say why on screen.
- Never show conflicting answers (for example "exit" and "bullish"): reconcile them, or show no signal.
- Session comes from the New York clock (`data.us_session`), not Yahoo's `marketState`.
- The page auto-reloads when the live tracker lands results: capture button actions in `on_click` callbacks or session state, and run long work on the tracker thread (`live.py`), never inline in the page.
- Respect the rate limits: Yahoo through `@_yahoo` (3 in flight), SEC (4 in flight), Finnhub (about 1 request a second); use bulk downloads for many tickers.
- The repo is public: never commit keys, the ntfy topic, the Google Sheet link or holdings.
- The owner reads on a phone: plain English, short labels, tappable links (`?view=target&t=TICKER`).
