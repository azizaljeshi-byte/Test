# Historical Chart Pattern Lab

Issue #9's isolated research baseline compares actual adjusted daily OHLCV sequences. It does not change `analogs.py`, the dashboard, scoring or any trading verdict. Claude owns valuation Phase 2A (#8); this lab is a separate tactical research track.

## What the first version does

- Compares 20-, 40-, and 60-bar formations. A 100-bar trailing context establishes daily volatility and the stock's trend (close above/below its trailing mean).
- Distance = 60% RMS normalized log-close path difference + 25% RMS volatility-scaled log open/high/low relative to close + 15% RMS log relative-volume difference. Close paths retain their direction and time order. No dynamic time warping, outcome-based tuning or cross-stock pooling.
- Matches stock trend and volatility (historical/current volatility ratio 0.5–2). When an adjusted benchmark is supplied, also matches its trailing trend and volatility range. Yahoo CLI fetches SPY; CSV users may provide `--benchmark-csv`. Missing benchmark dates are never filled. Sector regimes remain unmodeled.
- Reserves the earliest 70% of bars as a fixed historical library. The latest query and chronological holdout queries only use library episodes whose **entire forward horizon** ends before the training cutoff and before the query's entire context starts.
- Greedily selects nearest independent episodes: each full 100-bar context plus 60-bar forward outcome must be disjoint from every other selected episode. Episodes are independent in the sense of non-overlapping data, not proof of statistical independence. Results for different formation lengths are **not pooled**.
- Replays 5/20/60-bar outcomes from formation-end close. The hypothetical +15% target, −8% stop and 0.2% round-trip cost are configurable research assumptions, not recommended trades. Returns are adjusted close-to-close minus cost, independent of any hypothetical early exit. Maximum favourable/adverse excursion uses highs/lows; peak-to-trough drawdown uses daily closes. Gaps/slippage/executable fills are not modeled. Same daily bar hitting both barriers counts as stop first and is explicitly flagged.
- Reports median return, target-first/stop-first/no-hit rates, time to target, excursions, drawdown, and Wilson 95% intervals. These are sample descriptions, **not probabilities of future profit**.
- Shows matched-regime and buy-the-dip (negative five-bar return) baselines with identical costs/horizons. Baselines use recent non-overlapping qualifying episodes without shape selection. Disjoint chronological holdout queries compare frozen-library median-return predictions against realized returns using mean absolute error. A holdout query is scored only when all three methods have the configured minimum sample (default eight).
- Reports sensitivity at 0.75×, 1×, and 1.25× the predeclared distance cutoff, for every window. No setting is chosen by outcome. Configuration is exported in JSON.

The current prototype deliberately emits **INSUFFICIENT EVIDENCE** rather than promoting a small sample or prediction-error comparison into a trading signal. A future candidate rule needs meaningful holdout sample counts, economic performance after realistic costs, sector/event/liquidity/dilution checks, multiple-testing discipline and owner approval. There are no live BUY/SELL labels, targets for private holdings, probabilities, sizing or automatic trades.

## Data contract and limits

CSV input must contain `Date,Open,High,Low,Close,Volume`, ascending unique daily dates, finite positive prices, valid OHLC ranges and nonnegative volume. `--adjusted` explicitly attests that the OHLCV values are consistently adjusted. Yahoo uses the existing rate-limited `YahooProvider.history(auto_adjust=True)`. The CLI excludes today's New York daily bar, which may still be forming.

No resampling, forward fills, inferred timestamps or split corrections. Contexts or outcome paths crossing missing ordinary weekdays, gaps over seven calendar days, or adjacent price ratios above 1.4× (either direction) are excluded. The US federal-holiday calendar is an **approximation**, not a full exchange calendar: e.g. Good Friday may be treated as a missing session; unusual closures or genuine crash events may be rejected. A real exchange-calendar adapter and corporate-action audit are prerequisites for stronger claims. Dividends/splits in current vendor history can revise old data: `--as-of` prevents future rows entering formation/outcomes, but does not make the underlying vendor data a point-in-time archive.

When price/volume are missing or malformed, refuse the input. No qualifying quarter, symbol or financial data is inferred. Unknown market regime and sample insufficiency remain visible. The standalone HTML shows normalized **real closes**, with formation solid and forward paths dashed, dates and hypothetical outcome tables; the shape matcher also uses candle ranges and volume even though those are not drawn as candles.

## Run

```bash
python -m stockwatch.chart_patterns MSFT --output /tmp/chart-msft
python -m stockwatch.chart_patterns EXAMPLE --csv adjusted.csv --adjusted --benchmark-csv spy-adjusted.csv --as-of 2024-12-31 --target .15 --stop .08 --output /tmp/chart-example
```

Outputs are `.json`, `.md`, and a standalone `.html` with no external scripts or network dependencies. At phone width, each chart scrolls horizontally; text stays within the viewport. The separate manual Actions workflow **Chart Pattern Lab (research only)** generates the same artifacts for public sample tickers. It fails on unavailable input instead of publishing invented results. It has not been run on live Yahoo data in this environment.

## Reproducible real-price example

[AMZN comparison](examples/chart-pattern-amzn.html), [report](examples/chart-pattern-amzn.md), and [JSON](examples/chart-pattern-amzn.json) use Plotly's public historical fixture at pinned commit `0c447c47b757ad74edecab31f0d72f849d2e67c2`. This is **2013–2018 historical data**, not today's setup. AMZN had no splits/dividends in that interval; original prices are preserved, not restated for its 2022 split. Source URL, date span and file SHA-256 are recorded in JSON. No SPY benchmark is included in this fixture.

```bash
curl -fL https://raw.githubusercontent.com/plotly/datasets/0c447c47b757ad74edecab31f0d72f849d2e67c2/all_stocks_5yr.csv -o /tmp/all_stocks_5yr.csv
python scripts/chart_pattern_example.py /tmp/all_stocks_5yr.csv
```

The unmodified default settings produce three non-overlapping dated matches per formation length, below the minimum of eight, and **zero qualifying holdout evaluations**. Thus this example demonstrates real chart retrieval, matching and refusal, **not an out-of-sample edge**. No positive edge has been established. Synthetic fixtures test arithmetic/invariants, not investing performance.

## Validation

Run `python -m pytest -q` and `python -m pyflakes stockwatch/*.py dashboard.py tests/*.py scripts/*.py`. Focused tests cover shape/scale invariance, no future-row dependence, disjoint episodes, barrier ordering, daily same-bar ambiguity, missing sessions, weekends, price discontinuities, malformed data, benchmark gaps, frozen-library holdout boundaries, adjustment attestation, sample refusal, report output and no production imports.

Performance sanity: 50 serial runs of the default three-window configuration on the 1,259-bar public AMZN fixture completed in 58.21 seconds, peak process RSS 183,644 KiB (including loading the larger source CSV). This reuses one public ticker as a workload proxy, not evidence from 50 independent stocks. Runtime grows with history length and holdout evaluation count; this is a manual lab, not an inline dashboard operation.
