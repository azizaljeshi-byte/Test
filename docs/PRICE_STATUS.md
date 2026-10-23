# Price status: record high to deep breakdown

One plain label per stock, so the app can say where the price stands. Code: `stockwatch/status.py`.
Stored with the technical data (`technical.price_status`), shown as a chip on each list row and as a statement on Details.

## The seven statuses (best to worst)

| Status | Rule (on the last completed daily close) | Meaning for a held stock |
|---|---|---|
| **Record high** | Highest close in the history we hold (5 years, so a 5-year high) | Hold. Trail your stop. |
| **Strong uptrend** | Within 5% of that high, above the 50- and 200-day averages | Hold. |
| **Pullback** | 5% to 15% below the high, above both averages | Hold and watch. |
| **Weakening** | Below the 50- or 200-day average, or more than 15% below the high, and above the support zone | Tighten the stop. |
| **Testing support** | Close inside the support zone | Heads-up: protect the trade; a close below the zone is a breakdown. |
| **Breakdown** | Close below the support zone (the CIS `warning` and `failure` states) | A fact by default ("closed below support, automatic level, not reviewed: check the chart"); **exit** when the switch is on. |
| **Deep breakdown** | Close below the deeper level (the CIS `major_damage` level) | Same, one level lower. |

The support zone and the two lower levels are the automatic candidate levels from `cis/candidates.py`
(the ones the CIS shadow view labels "unreviewed"). The 5% and 15% cut-offs are `STRONG_NEAR` and
`PULLBACK_MAX` at the top of `status.py`. The three trend statuses (record high, strong uptrend, pullback) and
weakening use only price and the averages, not the support levels.

## Rules

- **Only a completed daily close confirms a status.** A live quote can only add a `provisional` note
  ("the live price reads BREAKDOWN; confirmed only if a session closes there"). Bars come through
  `decision.current_bars`, so stale or gappy history is refused. The quality check and the support levels use the
  last 420 bars, so one bad bar years ago can't blank the status; the record high looks at every close we hold.
- **Unknown is unknown.** Too few bars, stale history or a bad bar in the window give `NO READ` with the reason
  (shown on Details, kept off the list). If the support levels can't be placed, the trend statuses still work,
  `floor_known` is false, and Details says a breakdown can't be confirmed.
- **Watchlist names** get the same status but never an exit instruction ("Not a buy until it recovers").
- **Telegram:** a message about a stock whose status is testing support, breakdown or deep breakdown adds one line:
  `Price status: BREAKDOWN (daily close X, date)`. Which stocks get a message, and when, is unchanged.

## The exit switch (`status.EXIT_ON_BREAKDOWN`, off by default)

Off: the status is display only. It changes no score, verdict, trade plan, call or alert.

On: for a held stock, a confirmed breakdown or deep breakdown (a completed close, never a live quote) becomes a
SELL call everywhere at once, so no screen shows "hold" under a broken support:
- the trade plan becomes the exit plan (`tradeplan.exit_on_breakdown`, applied after `reconcile`);
- the call is `REDUCE / EXIT` through `transitions.effective_stance`, so the list, the radar (act now: "support broke:
  exit the trade") and Telegram agree; a forced exit is not treated as "verdict and plan disagree";
- Telegram sends HOLD → SELL after the usual two-run confirmation, with an exit line and the status.

**Why it is off.** `docs/CIS_PHASE2.md` tested these automatic levels walk-forward and found their failure levels
carry no information beyond volatility: price closes below them within 20 sessions about as often as below any
level the same ATR distance away (53% vs 53%). The repo's conclusion is that candidates stay diagnostics and never
become a call. A forced exit would turn exactly those levels into SELL alerts. Turn the switch on only if you accept
that, or after the levels have been reviewed into packets (`level_packet.stage`). The bigger step is to feed the
status from reviewed packets instead of candidates, which this change does not do.

## A breakdown never sits under "buy more"

Always on, independent of the exit switch. The plan's entry zone and the status's support zone come from different
level systems, so a stock can be inside the plan's add zone while closed below the automatic support. A confirmed
breakdown (completed close) under a buy or add call turns the call and plan into HOLD (WAIT FOR CONFIRMATION on a
watchlist name) with "don't add yet · closed below support X"; the radar says "support broke: don't add yet"
(`status.blocks_buy`, `tradeplan.hold_off_buying`, `transitions.effective_stance`). It sells nothing. Testing
support keeps the buy: buying at support is coherent. The engine's verdict label is unchanged.

## Numbers and a second opinion

Every row shows the numbers behind the status: `LEVELS S 98.00 · deeper 90.00 · R 101.50` (support zone low, the deeper
level, nearest automatic resistance above the close). Details adds the full zones. For a weak or broken stock
(weakening, testing support, breakdown, deep breakdown) the app also asks Finnhub for its own technical read (the
buy / neutral / sell count of its daily indicators, plus its support and resistance levels, `finnhub.second_opinion`,
cached 6 hours in `data.second_opinion`) and shows `confirms`, `disagrees` or `mixed` on Details. Display only: it
changes no status, call or alert. Healthy stocks and screening runs make no request. Finnhub may keep these endpoints
on a paid plan; whatever it refuses is simply left off (not verified against the live API from the build environment).

## Telegram

A message is sent on every status change among the seven steps, with the same two-run confirmation, silent first baseline and retry as call alerts (`status.ALERT_ON_CHANGE`, `docs/TELEGRAM_ALERTS.md`). With many tickers this can be frequent; limiting it to weakening and worse is a small change in `transitions.status_reading`.

## Known limits

- "Record high" is the highest close in the history we load (5 years by default), not an all-time high.
  Loading `period="max"` would make it all-time at the cost of a bigger download for every ticker.
- With the switch on, the radar dot keeps the colour and wedge of the engine's verdict: a held stock with a HOLD
  verdict and a broken support sits in the hold wedge but on the act-now ring, with the SELL call on its row.
- The support levels are automatic and unreviewed, and they need 210 sessions of history.
- Not yet checked against live Yahoo data from the build environment (it can't reach Yahoo). The quality check is the
  CIS one already used on live data; a rejected history shows `NO READ` with the reason rather than a guess.
