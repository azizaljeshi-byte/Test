## Purpose
<!-- What this changes and why, in plain English. Link the owner's request if there is one. -->

## Files changed
<!-- Each file and what changed in it, one line each. -->

## Tests
<!-- Paste the result of `python -m pytest -q` and the lint run. For screen changes, say how they were checked at phone width (390px). -->
- [ ] `python -m pytest -q` passes
- [ ] `python -m pyflakes stockwatch/*.py dashboard.py tests/*.py` is clean
- [ ] Screen changes checked at 390px (or: no screen changes)

## Methodology impact
<!-- Does this change how stocks are scored, judged or traded (scores, signals, verdicts, trade plans, thresholds)? See docs/COLLABORATION.md. Tick exactly one. -->
- [ ] None
- [ ] Yes, requested by the owner. What changes and why:

## Deployment risk
<!-- What could go wrong once merged (Streamlit deploys from the default branch)? New secrets or settings needed? Does the owner need to reboot the app? How do we roll back? -->

## Reviews
<!-- Reviewers follow the author-specific order in docs/COLLABORATION.md; the author never reviews their own pull request.
     Claude's PRs: ChatGPT, then Codex. ChatGPT's PRs: Claude, then Codex. Codex's PRs: ChatGPT, then Claude. -->
Author: <!-- Claude / ChatGPT / Codex -->
- [ ] First review by: <!-- name -->
- [ ] Second review by: <!-- name -->
- [ ] Skipped review and the owner's decision: <!-- "none", or which review and why -->
- [ ] Owner approval to merge

<!-- Repo is public: no keys, ntfy topic, Google Sheet link or holdings in this PR. -->
