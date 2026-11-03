# Codex briefs

Ready-to-use task briefs for Codex. Each one says what to build, where, what not to touch, and how to check it.
Branch name `codex/<topic>`, pull request into `claude/stock-dashboard-alerts-rr9r83`, template filled in.
Reviews: ChatGPT first, then Claude (`docs/COLLABORATION.md`). The owner merges.

| Brief | Size | Touches trading? |
|---|---|---|
| `01_ai_tab_screen.md` | medium | No |
| `02_bouncing_chip.md` | small | No (display only) |
| `03_institutions_over_100.md` | small | No (display only) |

Rules that apply to all of them (from `CLAUDE.md`): missing data is "unknown", never 0; plain English, short labels; phone width (390px);
no keys, ntfy topic, Sheet link or holdings; don't change scoring, signals, verdicts, tier rules or thresholds; tests and pyflakes must pass.

## Screen implementation (follow-up to merged PR #69)

- `?view=ai` opens **Ask the AI**. `ask_ai_view.html` / `history_html` render saved data only. Ask queues through
  `ask_ai.request`; a five-second fragment refreshes the answer and button without waiting for a portfolio sweep.
  The existing backend handles cost limits, data collection and scoring. No AI/network call runs in the page.
- The selected demo provider saves `sample_verdict()` with a visible synthetic marker, never queues an AI request,
  and excludes demo entries from performance tiles. Pending placeholders stay on the current card, not the outcome
  history. BUY/AVOID hit rates use only ready, scored, non-demo calls; unscored results remain unknown.
- The Move chip can say **bouncing today** at ≥1 ATR while its underlying `FALLING` code and risk colour stay intact.
  Only `ui.phase_chip` consumes `phase.phase`; no trading path consumes its display label.
- Institutional ownership wording changes in `fundamentals_view` and `briefing` only. Other `institution_pct`
  occurrences are provider field mapping/demo data (`data.py`) and evidence pass-through (`deepdive.py`);
  stored values and all score arithmetic remain unchanged.

Synthetic-only phone screenshots: [Ask tab](../screenshots/pr69-ai-mobile.png) and
[history and unknown facts](../screenshots/pr69-ai-history-mobile.png). Browser verification uses an isolated
SQLite store, synthetic snapshots and a stopped background tracker; it does not send an AI request or notification.
