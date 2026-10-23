# Private portfolio risk research (Issue #22)

`python -m stockwatch.portfolio_risk` creates a **local, private** HTML dashboard,
structured JSON report, and replay capture. It is standalone: no Streamlit,
production score, trade plan, scanner, storage, alert or notification integration.
No workflow is added. Telegram work in #21 is independent.

## Owner operation

First review the offline synthetic example (no configured portfolio is read):

```bash
python -m stockwatch.portfolio_risk --demo --output /tmp/stockwatch-synthetic-review
```

Open `report.html` in that directory locally. Identifiers SYNTHA, SYNTHB and SYNTHW,
positions, sector, OHLCV and cash are invented. The fixed demonstration as-of is
2026-10-23T12:00:00Z, not live market evidence. At that fixture, invested equities
are USD 1,649.62, supplied cash USD 500, NAV USD 2,149.62, and unrealized P/L USD
299.62. Two held names and one zero-share watchlist are distinct. The simultaneous
-10% equity shock is approximately USD -164.96; no probability is assigned.

After owner authorization, on a trusted local machine with private configuration:

```bash
python -m stockwatch.portfolio_risk --portfolio /private/path/positions.yaml --output /private/path/new-report
```

Alternatively omit `--portfolio` to read the existing `STOCKWATCH_PORTFOLIO` YAML
secret from the environment. Never place its value on a command line, in chat,
public issue, source control or workflow. No Google Sheet or local/example fallback
is attempted. Explicit file inputs using the example filename are refused. The
owner must supply actual positions and verify broker/corporate-action accuracy;
software cannot certify that supplied positions are real.

The supported private YAML uses the existing `holdings` list with `ticker`, `tier`
(1 core or 2 tactical), explicit `shares`, and `cost_basis` (USD **per share**, required
for positive holdings; zero is allowed). Optional top-level `cash` is a nonnegative
USD amount; absent/null means unknown. Optional `currency: USD` and each row's
`sector` are supported. No sector label is guessed. Notes, target prices, tier
settings and unrelated private config are neither consumed nor copied to reports.
Duplicate tickers, including overlapping tier/watchlist entries, are refused rather
than silently counted twice. Consolidate broker lots privately first, with weighted
per-share basis; negative shares, missing shares, unsupported currency and malformed
positions refuse the report. Watchlist rows have zero shares and no value/weight.
This version supports unlevered USD long equities and USD cash only.

Replay uses the original captured as-of and never accesses the network:

```bash
python -m stockwatch.portfolio_risk --portfolio /private/path/positions.yaml --replay /private/path/prior-report/capture.json --output /private/path/new-replay
```

The same private portfolio and capture reproduce results. Capture version
`private-capture.1` contains raw evidence plus as-of; it is not a certified archival
source, nor a tamper-proof broker record. Output contract is `private-portfolio-risk.1`.

## Privacy boundary

Output must be a NEW directory outside Git checkouts, with no symlink ancestors.
The parent must already exist. Directories are mode 0700, generated files 0600;
existing directories/files are never overwritten. HTML has no scripts, external
assets or network dependencies; values are escaped and a restrictive CSP is set.
Do not publish or serve it on a public host. Local filesystem permissions do not
replace access control on a shared machine or encrypted storage.

Both real and demo CLI runs refuse CI/GitHub Actions environments. No workflow
uploads, console holdings tables, provider exception strings or configuration
values are emitted. Upstream logging/stdout/stderr are suppressed during live
collection; terminal output is generic. `report.json`, `report.html` and
`capture.json` contain sensitive positions and must stay private. This feature does
not change or claim to secure existing production scan workflows: never wire this
runner into public CI or existing uploads. No private inputs or output artifacts
were accessed/generated for this implementation; verification uses synthetic data.

## Evidence and rules

- Live collection uses the existing Yahoo/yfinance personal-use provider and Yahoo
  throttle wrapper, sequentially for unique positions/watchlist plus SPY. Raw close
  and adjusted OHLCV are fetched separately with 20-second request timeout; currency
  metadata must confirm USD and dates must match. No paid API, new credential or
  notification setting is needed. Source availability/permissions remain the owner's
  responsibility for local personal use; redistribution is not authorized here.
- It intentionally uses completed daily closes, not real-time execution quotes.
  Same-day bars are excluded under a following-calendar-day availability convention.
  All rows require at least 200 numeric valid daily bars, ordered unique weekday
  dates, no gaps over seven calendar days, positive prices and nonnegative volume.
  Quote/capture date, provider, source, as-of and age are retained. Last close/capture
  must be at most four calendar days old; this is a disclosed research freshness
  limit, not an exchange-calendar or live-trading guarantee. Source failures, stale,
  future, invalid and missing history all mean unavailable, with generic private-safe
  reasons. A timestamp alone does not certify source accuracy.
- Position value is current shares × raw close; P/L subtracts supplied share cost.
  Corporate actions and share/basis consistency require the owner's reconciliation.
  Adjusted technical prices are explicitly **not raw-price order levels**.
- Every held position must have a usable quote on the SAME date before calculating
  total equity, portfolio P/L, weights, sectors or dollar stress scenarios. Coverage
  is position count, never misleading partial value coverage. Individual verified
  position values remain visible. Watchlist/benchmark outages do not invalidate
  otherwise complete held equity arithmetic.
- NAV/cash allocation require supplied cash. Otherwise weights are explicitly
  equity-only, with cash/NAV unknown. No partial portfolio totals, portfolio VaR,
  invented historical portfolio drawdown or forward loss probability. Position
  drawdown measures adjusted close versus the peak in the fetched window; actual
  portfolio drawdown needs historical positions, cash flows and an equity curve.
- Trend is up if close > MA50 > MA200, down if close < MA50 < MA200, otherwise mixed.
  ATR14 is a simple average of true range; support/resistance use prior 20 sessions'
  low/high, excluding current bar. Volume compares latest with prior 20-session mean.
  Counter-trend strength requires positive 20-session stock return against negative
  SPY return on the same latest date. These are observations, not calibrated odds.
- Historical Pearson correlations use 60 adjusted daily returns and exactly matching
  latest 61 close dates; mismatched dates or constant returns mean unavailable.
  Pair correlations and SPY correlation are neither a forecast nor sector causation.
  Sector exposure uses only owner-supplied labels, retaining Unknown.
- Missing evidence or ordered downtrend produces **review**. Otherwise holdings say
  **hold** (monitor), watchlist **add-watch** (investigate). Complete-coverage weights
  above 15% (T1) / 7% (T2) produce **reduce-review**, a concentration investigation,
  never a sell instruction. With unknown cash these thresholds compare equity-only
  weights and may overstate concentration versus total wealth. No scoring or
  production tier defaults are changed. No automatic transactions or notifications.
- Uniform -10%/-20% equity scenarios are hypothetical simultaneous shocks, cash
  unchanged, with explicit assumptions and no probabilities. Financial/valuation
  packets and calibrated historical analogues are not ingested: unavailable is
  explicit on each position. Existing MSFT-only SEC readiness does not establish
  valuation evidence for other issuers; there are no fair values or add orders.

## Validation and remaining requirements

Synthetic tests cover holdings/watchlist, tier overlap, negative/zero/missing input,
cash unknown, incomplete/stale/invalid/different-date quotes, partial provider outage,
reproducible flags/correlation/stress arithmetic, offline replay, escaped HTML,
owner-only output, checkout/symlink/CI refusal, suppressed logs and app isolation.
Mobile HTML is checked at 390px without external requests. No live private holdings
scan or notification is dispatched during implementation.

Before relying on a private run, owner must approve it, configure accurate actual
holdings and basis/cash, confirm provider access and data freshness/corporate
adjustments, and review financial/analogue evidence gaps. Changes require ChatGPT
first review, Claude independent second review, then owner merge approval.
