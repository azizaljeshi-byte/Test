# Phone notification proposal — awaiting owner approval

Design only. Do not implement until the owner approves the three mock notifications in the draft PR description. All example symbols below are invented; no destinations or private configuration values are included.

## Proposed layout

Combine the three New call change digests into one push per sweep when any currently eligible event exists. Show held-stock exits and stops first, then buy signals, then other held-stock changes, and finally one short watchlist summary. Preserve the existing priority of each event; the combined push uses the highest included priority. Keep urgent information before any size cap.

Use plain English for visible calls, including previous-call labels and reasons. Replace technical jargon with short descriptions without changing the underlying call or its meaning. Unknown prices or levels remain unknown.

For one affected stock, the Click header opens its target page. For multiple stocks, it opens Log, where the full list remains available. Build destinations only from private runtime configuration. Include no literal addresses in committed examples. A watchlist summary ends with “Tap for the full list.”

## Mock 1 — mixed sweep

Title: StockWatch: exit signal on a stock you own

    YOUR STOCKS — CHECK FIRST
    FICTA: Exit signal. Closed 18.20, below exit level 18.50.

    BUY SIGNALS
    FICTB: New buy signal. Price 24.10.

    Watchlist: 4 other changes. Tap for the full list.

Click destination: Log page. Priority: 5, inherited from the existing held-stock exit event.

## Mock 2 — buy signals and watchlist changes

Title: StockWatch: 2 new buy signals

    BUY SIGNALS
    FICTC: New buy signal. Price 32.40.
    FICTD: Add signal. Price 15.60.

    Watchlist: 3 other changes. Tap for the full list.

Click destination: Log page. Priority: 2, matching the existing watchlist events.

## Mock 3 — one held-stock exit

Title: FICTE: exit signal on a stock you own

    Closed 41.20, below exit level 42.00.
    Previous call: Hold. Now: Exit.
    Tap to review this stock.

Click destination: FICTE target page. Priority: 5, unchanged.

These are alternative sweep examples, not three pushes from one sweep. Amounts and symbols are invented. Existing suggested actions and factual reasons must retain their meaning when present; examples do not introduce a new trade instruction.

## Implementation and validation after approval

Touch the three digest builders in stockwatch/events.py and delivery/link formatting in stockwatch/notify.py as needed. Add offline tests with invented symbols for grouping/order, one push per eligible sweep, no push with no eligible events, unchanged trigger/baseline/deduplication behavior, inherited priorities, single-stock and digest Click destinations, missing configuration, unknown values, and message-size caps. Run focused tests, full suite, lint, and check phone readability.

Methodology impact: none. No scoring, trading, event eligibility, cooldown, confirmation, or flip suppression changes. Paper-trade, price-move, news, and unrelated notification streams are outside this consolidation.

No suggestion to suppress back-and-forth flips is included. Any future suggestion must be separately labelled for owner approval.
