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
