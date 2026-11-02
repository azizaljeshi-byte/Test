> **Prerequisite (read first).** `stockwatch/events.py` is not on this branch's base yet: the owner's PC runs newer code than GitHub (last GitHub
> commit 25 Oct). The code sync pull request has to be merged before this task can start; the draft patch below is written against the PC version
> of `events.py` and will apply after that sync. Until then this file is only the written brief.

# Task for Codex: make the "stocks changed" phone push readable

Branch: `codex/push-format`, off the latest default branch. Follow `CLAUDE.md` and `docs/COLLABORATION.md` (pull request, template, no merge).
Display text only. No change to scoring, calls, signals, thresholds or when a push is sent.

## Problem
When many of the owner's stocks change call in one sweep, `stockwatch/events.py` (`call_flips`) sends one ntfy push with one long
sentence-style line per stock. On a phone (ntfy app, plain text) it is a wall of text: "NVDA: WAIT FOR TURN -> EXIT. Closed 204.64,
under the exit line 210.18 (-0.9 swings). Fell 4.2%." x14, cut at 12 lines with "+2 more". The same happens for the watchlist
"status changes" push and the "New call buy signals" push.

## What the owner wants
Readable at a glance, on a phone. Group by the new call, most urgent first, one stock per line, short numbers. Suggested shape
(plain text, emoji for the group; ntfy does not render markdown on every client, so do not rely on it):

    🔴 EXIT: sell or trim (2)
    INTC  −28.6% on 4x volume · closed 65.76, exit line 84.65
    NVDA  −4.2% · closed 204.64, exit line 210.18

    🟠 ON THE LINE: no new buys (1)
    ORCL  (was wait for turn)

    🟡 WAIT FOR TURN (2)
    SBUX, ONDS  (was hold)

    🟢 ADD (1)
    DIS  (was on the line)

- Title (ASCII only, <= 120 characters, HTTP header): `6 of your stocks changed: 2 exit, 1 on the line, 2 wait for turn, 1 add`.
- Sell calls: biggest drop first, show the day's move, volume only when >= 2x on a >= 3% drop, and the close against the exit line.
- Quiet calls (WAIT FOR TURN, HOLD, WAIT, ADD): just the tickers, with what they were before.
- Watchlist status changes (3 or more) use the same grouping; fewer than 3 keep today's short lines.
- Buy signals: two short lines per stock (ticker, call, live price; then the close and how far above the exit line).
- Nothing may be cut with "+N more" for a normal sweep: raise the line cap for the grouped bodies. ntfy bodies are cut at 3800 bytes in `notify.ntfy_send`; keep the grouped text under that, and when it would not fit, drop the least urgent group's detail, never the sell calls.
- Missing data is left out of a line, never shown as 0.
- The push priority, tags, click link and the "owned stocks first" behaviour stay as they are.

## Starting point
`draft_events.patch` (unified diff against the current `stockwatch/events.py` and `tests/test_events.py`) is a working first draft by
Claude: `grouped_lines`, `grouped_title`, a `max_lines` argument on `_push`, and updated tests. It passed `tests/test_events.py`;
the full suite and a phone check were not run. Use it, improve it, or replace it. Please also check: the arrow and minus characters in the
body (UTF-8 is fine in the body, not in the title), a sweep of 20+ changes, and the 3800-byte cut.

## Done means
`python -m pytest -q` and `python -m pyflakes stockwatch/*.py dashboard.py tests/*.py` pass; tests cover the grouping, the order, the title,
the byte limit and the "fewer than 3" case; the pull request shows a before and after sample of each of the three pushes.
