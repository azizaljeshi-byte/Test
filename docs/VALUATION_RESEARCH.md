# Valuation research (Phase 2A-1)

Issue #8. A read-only research layer: for each company it picks the kind of valuation that fits how
the business earns its cash, says why, and runs only what the data supports. `stockwatch/valuation_lab.py`
isn't imported by the app. It shows **no fair value, BUY/SELL, score or probability**, and changes no
signal, plan or screen.

## Classification

Deterministic, with the rule that fired shown in the report:

| Family | Rule | 2A-1 output |
|---|---|---|
| Bank | SIC 6020–6036 | unavailable: tangible equity and other bank inputs not collected yet |
| Not supported in 2A | insurers, REITs, utilities, other financials (by SIC) | the reason |
| Cash-burning | TTM operating cash flow minus capex below zero | cash runway and dilution; no intrinsic value |
| Cyclical | in the last 6 fiscal years, a revenue fall of 15% or more, or both an operating loss and a profit | the cycle evidence; the mid-cycle model is in 2A-2 |
| Cash compounder | OCF minus capex positive in each of the last 3 fiscal years, no cycle | reverse valuation |
| Insufficient evidence | anything else, including fewer than 5 fiscal years | the reason |

The thresholds are in `valuation_assumptions.yaml` (`classifier`), as is an `overrides` list for public
tickers with a stated reason.

## Inputs and gates

Every input comes from the Phase 1B data-quality layer (`sec_quality`) with its status and filing
source.

- **Gate:** a critical input that isn't **usable** (unknown, stale, needs reconciliation) makes the model unavailable, with the reason. Nothing is estimated, carried forward or filled with zero.
- **No look-ahead:** `--as-of` uses only filings made, and closes printed, by that date.
- **Price:** the close on or before the as-of date (Yahoo, not dividend-adjusted), or `--price TICKER=VALUE`.
- **Market cap:** price × the single cover-page share count. Several share classes make it unavailable.

## Reverse valuation (cash compounders)

What annual growth the market price implies for owner free cash flow (OCF − capex − SBC, trailing
twelve months):

- **Projection:** 10 years. Years 1–5 grow at the implied rate; years 6–10 fade linearly to the terminal rate; then a Gordon terminal value. Year-end discounting.
- **Equity-level:** OCF is after interest, so the cash flow is set against market cap and needs no tax-rate assumption.
- **Sensitivity only:** a grid of discount rate 8/10/12% × terminal growth 1.5/2.5/3.5%. Beta and cost of debt aren't collected, so there is no measured cost of capital. Each cell also shows how much of the value is the terminal value.
- **Lease-adjusted line:** where the trailing twelve months is a single fiscal year and assets obtained under new finance leases are tagged, a second line subtracts them. That spending isn't in capex.
- **Conservative capex:** it is gross, so it includes growth capex.

## Cash runway (cash-burning companies)

- **Runway:** (cash + short-term investments on the latest balance-sheet date) ÷ (capex − OCF over the trailing twelve months), in months.
- **Dilution:** diluted weighted shares in the latest quarter against the same quarter a year earlier, plus securities left out of diluted EPS.
- **Excluded:** undrawn credit lines, debt maturities and new financing, which aren't collected.

## Risk lenses

- **P/E:** market cap ÷ TTM net income.
- **Owner FCF yield.**
- **Debt ÷ TTM operating cash flow:** debt counts only where its parts reconcile on the balance-sheet date; leases aren't added.
- **Net debt.**
- **Capex ÷ revenue:** flagged above 15% as equipment-heavy.
- **Capex ÷ D&A.**
- **Equipment/GPU useful life:** N/A until depreciation lives are collected.

## Assumptions

`stockwatch/valuation_assumptions.yaml` is versioned, and every value says where it came from. They are
research settings, **not adopted as policy** (`approved: false`); changing one needs the owner's
approval in a pull request. In 2A-1:

- **From ChatGPT's spec (Issue #8):** the 10-year horizon with a 5-year fade, terminal growth 2.5% (1.5–3.5%), the 8/10/12% grid and ERP 5% (used from 2A-2).
- **Claude's, flagged for approval:** the classifier thresholds.

## Running it

Public example tickers only.

- **GitHub:** Actions → "SEC data audit (read-only)" → Run workflow, input `valuation` (default MSFT AVGO MU JPM RIVN BRK-B). The report is on the run summary, in the log, and in the artifact as `valuation.md` and `valuation.json`.
- **Locally:** `python -m stockwatch.valuation_lab MSFT AVGO MU JPM RIVN BRK-B --markdown v.md --json v.json`.

## Not in 2A-1

- **Models:** the scenario DCF, the mid-cycle model and the bank P/TBV–ROE model are 2A-2, and need owner approval.
- **Cost of capital:** no measured WACC or cost of equity.
- **Street targets:** none.
- **Probabilities and trading:** none, and no connection to BUY/SELL, scores or sizing.
