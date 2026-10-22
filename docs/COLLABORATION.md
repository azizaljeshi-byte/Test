# How we work on StockWatch

Three AI tools (Claude, ChatGPT and Codex) and the project owner work on this repo together. GitHub is the
shared source of truth: every change is a branch and a pull request, and every decision is written on the
pull request where everyone can see it. None of the tools talk to each other directly.

## Roles

| Who | Does | Doesn't |
|---|---|---|
| **Project owner** | Decides what gets built and approves any change to the investment methodology. Merges pull requests, then reboots the Streamlit app. Manages secrets and repo settings. | |
| **Claude** (Claude Code) | Builds changes the owner asks for on `claude/<topic>` branches. Runs the tests, opens the pull request, answers review comments and pushes fixes to the same branch. Reviews pull requests written by ChatGPT or Codex (see the table below). | Merge, push to the default branch, or push to another tool's branch. |
| **ChatGPT** | **First independent review** of pull requests written by Claude or Codex. Checks that the pull request does what its description says, that the methodology impact is stated honestly, that the wording is plain English for a phone reader, and what could go wrong after deploy. Builds on `chatgpt/<topic>` branches when the owner assigns it work. | Merge, or push to another tool's branch. |
| **Codex** | **Second independent review** of pull requests written by Claude or ChatGPT. Reviews the code itself: correctness, edge cases, tests, rate limits, secrets, and that missing data stays "unknown". Builds on `codex/<topic>` branches when the owner assigns it work. | Merge, or push to another tool's branch. |

Whoever writes a pull request never counts as its reviewer:

| Author | First review | Second review |
|---|---|---|
| Claude | ChatGPT | Codex |
| ChatGPT | Claude | Codex |
| Codex | ChatGPT | Claude |

If a reviewer isn't available, the owner decides whether to wait or to merge with one review. The pull
request should say which review was skipped.

## GitHub identities

Claude and ChatGPT act on GitHub through the owner's account. Codex posts as its own bot,
`chatgpt-codex-connector[bot]`; ask for its review by commenting `@codex review` on the pull request. So:

- **Claude's and ChatGPT's reviews are pull request comments, not formal approvals.** GitHub refuses
  "Approve" on your own pull request. Start each review comment with a bold heading naming the reviewer,
  e.g. **ChatGPT review**, so the history shows who said what. Codex's reviews already carry its name.
- **Branch protection:** require a pull request before merging, but set **required approvals to 0**. With
  approvals required, nobody could merge, the owner included.
- **For approvals GitHub enforces,** Claude and ChatGPT would each need their own GitHub identity (for
  example a separate bot account or GitHub App). Until then, the owner's merge is the approval.

## The workflow

1. **Start from the default branch.** The default branch is `claude/stock-dashboard-alerts-rr9r83`, the
   repo's default and the branch Streamlit Cloud deploys from. Branch off its latest commit, one topic per
   branch: `claude/<topic>`, `chatgpt/<topic>` or `codex/<topic>`.
2. **Never commit to the default branch directly.** Merging is deploying: whatever lands there goes live on
   the owner's phone after the next reboot.
3. **Open a pull request into the default branch** and fill in the template (`.github/pull_request_template.md`):
   purpose, files changed, tests, methodology impact and deployment risk.
4. **Reviews happen on the pull request**, in the order the table above gives for the author (for Claude's
   pull requests: ChatGPT first, then Codex). The pull request's review checklist names who did each review
   and any review that was skipped.
   - **Label each finding:** **blocking** (must be fixed before merge) or **non-blocking** (a suggestion).
   - **Reviewers don't push to the author's branch:** they comment, and the author fixes and pushes to the same branch.
   - **Answer every blocking finding:** the author fixes it or replies saying why not.
5. **The owner merges** once the reviews are done, then reboots the app. No tool merges, including its own
   pull request.
6. **Keep history readable:** don't force-push or rewrite a branch someone else is reviewing. Fixes go on top as new commits.

## The investment methodology is protected

Unless the owner asks for it explicitly, pull requests must not change how stocks are scored, judged or
traded. That logic lives in `stockwatch/technical.py`, `fundamental.py`, `relative.py`, `signals.py`,
`catalysts.py`, `deepdive.py`, `street.py`, `analogs.py`, `tradeplan.py`, `turbo.py`, `market.py`, and the
verdict rules in `engine.py`. It also covers:

- **Tier rules and their defaults** in `stockwatch/config.py`: `DEFAULT_TIERS` (fundamental/technical
  weights, stop-loss %, trailing-stop ATR multiple, maximum position size) and `risk_per_trade_pct`, which
  sets position sizing.
- **The same rules in `portfolio.example.yaml`:** its `tiers:` and `settings:` blocks.
- **Thresholds in `ui.py`:** for example the reassess rebound and the radar rings.

When a pull request does touch it, the description must say so and explain which numbers or calls change and
why. Reviewers should check that claim against the diff.

## Checks every pull request must pass

- **Tests:** `python -m pytest -q` (no network needed). Add tests for new logic.
- **Lint:** `python -m pyflakes stockwatch/*.py dashboard.py tests/*.py`.
- **Screen changes:** check them at phone width (390px), offline with `STOCKWATCH_DEMO=1 streamlit run dashboard.py`.
- **No secrets:** the repo is public. Never commit keys, the ntfy topic, the Google Sheet link or holdings.
