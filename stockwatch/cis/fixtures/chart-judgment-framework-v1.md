# Independent chart judgment — agreed reference, v1

Recorded 23 October 2026. This file preserves the agreed method for this chat. It does not modify StockWatch, a global skill or an automated trading system.

## Locked method: condition, location and staged downside

Use real adjusted price/volume data and independent judgment. The website's verdict is context, not the source of our verdict. State instrument, timeframe, as-of session and whether a quote/bar is forming. Show current state before giving an entry idea. A stock can be outside healthy levels; do not manufacture a lower constructive floor to label it healthy.

1. Constructive floor: a supported price zone we want buyers to hold. Above it supports the current setup, but does not automatically make an entry attractive.
2. Testing the floor: price enters the zone; observe buyer defense. Falling into support alone is not a buy signal.
3. Warning: a close below the floor's lower edge. Stop adding and review/reduce under the predefined tactical plan.
4. Tactical failure: a separate close-based invalidation; exit the position opened for that setup under the agreed plan. Do not lower it to avoid acknowledging failure.
5. Major damage: a deeper structural support breach. This describes broader damage, not a reason to stay in a failed tactical trade.

Touches and intraday crossings generate early warnings. A daily close confirms a daily-close rule. Clearly identify conditions already observed, intraday-only breaches and conditions still pending. A close-based exit does not guarantee the threshold as an execution price; overnight gaps can exceed the planned risk. Position size and reduction percentages are separate choices based on risk budget and holding purpose.

Keep technical condition, evidence confidence, entry quality and directional probabilities separate. Subjective scenarios must specify horizon, anchor and mutually exclusive endpoint thresholds; they are not calibrated probabilities or percentage-return forecasts. Show all historical matches under a reproducible causal rule, small-sample limitations, interim excursions and contrary outcomes. Endpoint returns cannot substitute for managing the path.

## Recorded examples — dated snapshots, not permanently current levels

| Stock | Constructive zone | Warning close | Tactical failure close | Major damage close |
|---|---|---|---|---|
| ISRG | 436–440; above 440 preferred | below 436 | below 424 | below 398.99 |
| FICO | 780–790; above 790 preferred | below 780 | below 750 | below 660 |
| CRDO | 180–185 must be reclaimed and defended | below 180, already confirmed | below 160; crossed intraday in captured quote | below 149; crossed intraday, closing confirmation pending |
| PODD | 140–142; above 142 preferred | below 140 | below 133 | below 126 |

All figures are USD from the 22/23 October 2026 analysis. For CRDO, do not describe 149 as a new healthy floor: it is a deeper damage boundary while the constructive zone remains lost. PODD is the final proposed example and has not yet received a separate user acceptance of its precise levels.

The four-stock functional/design test round is now closed. CIS implementation requirements are in `CIS-chart-framework-v1-implementation-notes.md`; reference packets, synthetic state cases and schema are supplied alongside it. Closure means the intended behavior has been documented and checked, not that automatic level selection, probabilities or a profitable trading edge have been validated. No production change or deployment was performed.

## Upward extension — structural ceiling analysis

User clarification: the reverse side is an upside ceiling ladder, not simply a profit-taking or trailing-stop strategy. Final names for the downside and upside setups remain undecided.

For the upside side, identify successive resistance zones with dated actual highs/lows, moving-average confluence where relevant, volume behavior and the evidence needed to clear each zone. Include the same visible “Why this read” as the downside side. Distinguish nearby repair levels, the constructive reclaim, stronger confirmation, prior rally highs and distant historical supply; do not imply all ceilings have equal importance.

Initial clearance means a completed daily close above the upper edge. Stronger confirmation requires a subsequent successful retest and continued defense, supported by participation. A wick is a test, not confirmation. Rejection or a close back below a broken zone can mark a failed breakout. A confirmed former ceiling can become a candidate new floor.

Ceilings describe where price must prove itself, not where it must stop or eventually return. Do not infer a chance of reaching each ceiling from a condition score, the three-category endpoint probabilities, or a stock having traded there before. Keep current state/bias intact: an upside route can be mapped even when the stock is bearish and no recovery is confirmed. Use the same frozen data for matched comparison, with partial-session values separated.

CRDO's 23 October captured upside map: 160–165, 180–185, 195–200, 214–215, 231–232, 245–250, 270–287, 308–309 USD. Upper historical band is rounded outward to include the actual 286.24 high. All remain conditional at the captured 153.01 quote. These are dated reference zones, not live or permanent levels.

## Optional profit-management extension — not the requested reverse setup

Define a healthy upward trend from higher rally highs, defended higher lows and constructive participation, with weekly context. Rising price alone does not establish a healthy trend.

Alongside the downside ladder, specify the first and next profit-taking zones from actual resistance and reward/risk. They are checkpoints, not promised targets. When price remains above a defended rising floor, retain the trend position. At resistance, review taking a predefined portion; rejection, failed breakouts or weakening participation strengthen that case. If resistance is broken and held with follow-through, retain the remaining trend position rather than assuming every target touch requires a full exit.

Raise the constructive floor after a confirmed higher low or a successful breakout/retest establishes new support. Reassess warning and tactical-failure levels from that new structure and volatility. Protective levels for an existing tactical position may ratchet upward; do not loosen them to accommodate a deteriorating trade. Keep historical levels and update reasons visible. Breakout confirmation and a held retest remain pending until observed.

Partial-profit fractions must be selected before execution. A 25% / 25% / remaining 50% trail is an illustration, not a locked default or an optimized rule. Do not automatically move protection to entry cost unless the chart supports that level. Do not automatically sell the full position just because price or RSI is high.

For a rising position, the same warning/failure hierarchy now protects gains: loss of the raised constructive floor prompts reduction review; breach of the raised failure level ends that tactical setup. Do not keep using an obsolete, much lower initial failure level after an explicitly adopted tighter structure-based protection plan.

Reference on execution mechanics: [SEC investor bulletin on stop and trailing orders](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-15). Our structural daily-close framework is distinct from a broker's fixed-dollar/percentage trailing-stop order, which can trigger intraday and does not guarantee execution price.
