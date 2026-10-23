"""Independent chart judgment (CIS framework v1): read-only, explain-only technical analysis.

This package is deliberately separate from `engine`, `tradeplan`, alerts and the Research lab's shape
matching. It measures completed daily bars, evaluates analyst-selected floor/ceiling level packets with
fixed deterministic state machines, and describes same-stock history. It never places orders, sends
notifications or changes the main dashboard's verdicts.

Modules:
  features     completed-bar data quality and indicator measurements
  level_packet versioned, immutable level packets and their validation
  state        downside floor and upside ceiling state machines
  history      causal same-stock analogue selection and outcomes
  explain      "Why this read" observations built only from structured evidence
  fixtures     frozen 23 October 2026 reference inputs (ISRG, FICO, CRDO, PODD)
"""
