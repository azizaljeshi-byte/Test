# SEC data quality (valuation Phase 1B)

Phase 1B of the valuation work in Issue #2. Phase 1 (`docs/SEC_DATA_AUDIT.md`) found which inputs SEC
provides. This checks whether the figure each input would use is fit to use, before any valuation model
exists. **This is read-only.** `stockwatch/sec_quality.py` isn't imported by the app, so scores, signals,
plans and screens don't change. It computes no valuation, fair value, buy-under price or score, and
fills in or normalizes nothing.

## Statuses

Every figure gets one:

| Status | Meaning |
|---|---|
| **usable** | No problem found. Not the same as valuation-ready: scope choices and disclosures outside XBRL still matter. |
| **needs reconciliation** | A person must check or choose: the figure was revised, another tag for the same measure disagrees, one filing gives two values, the selected tag has a wider or narrower scope (e.g. includes noncontrolling interests), or several share classes. |
| **stale** | Older than the company's latest report. Don't use it as current. |
| **unknown** | Not reported, or reported only in another currency. Never treated as zero, estimated or converted. |
| **not applicable** | A generic measure that doesn't fit the company: EBIT, operating cash flow, capex, investments and debt for banks and insurers. The figure and any staleness are still shown. |

## What it checks, per company

- **Which figure is selected, and from where:**
  - Flows (income, cash flow, share averages): the latest fiscal year in an annual report (350 to 380 days).
  - Instants (balance sheet, cover-page shares): the latest date.
  - Provenance: the first tag in `FIELDS`' priority order that reports that period, with its period, form, filing date and accession number.
- **No look-ahead:** only facts filed on or before the as-of date (`--as-of`, default today), for periods ended by then.
- **Revised and amended figures:** the first-filed and latest-filed values for the period. A change of more than 0.5% between filings is "needs reconciliation"; an amendment (10-K/A) is noted.
- **Conflicting facts:**
  - Two values for one period in the same filing: none is shown as the figure.
  - Two period starts for one period end (a fiscal-year change).
  - Another tag for the same measure with a different amount.
- **Scope, not conflict:** tags that measure something wider or narrower, listed in `SCOPE` with a percentage difference. Examples: total vs noncurrent debt, depreciation alone vs D&A, including restricted cash.
- **Staleness against the company, not today:**
  - **Annual figures:** stale when the company has already reported a newer fiscal year for revenue, net income or operating cash flow. An annual figure isn't stale just because the next fiscal year hasn't ended.
  - **Balance-sheet figures:** stale when older than the latest balance sheet.
  - **Dilution disclosures:** stale when older than the latest fiscal year.
  - **Everything:** stale when the company hasn't reported for 200 days.
- **Trailing twelve months:** built the same way as the app's SEC fallback (latest year-to-date + last fiscal year − the same period a year earlier, one tag), with each part's period and accession number.
  - **A missing part:** the report says which.
  - **A part revised in a later filing:** "needs reconciliation", with every filing's value named.
  - **A part given two values in one filing:** "unknown", with no number shown.
  - **The fiscal year's own problems** (conflicting tags, a scope choice) carry over from the figure selection.
- **Balance sheet on one date** (the latest cash or equity date): cash, short-term investments, short- and long-term debt, and operating and finance leases.
  - A component not reported for that date is unknown. It is never carried forward from an older date.
  - Two values for the date in one filing make a component unknown, with no number shown. A value revised in a later filing needs reconciliation.
  - Different same-date concepts are compared too: only explicit field-specific pairs in `BALANCE_SCOPE_PAIRS` establish known scope differences. A tag's individual `SCOPE` description never exempts an unrecognized pair; other differing amounts need reconciliation.
  - Lease current portions are shown separately.
  - Where all three are tagged, LongTermDebt is checked against its noncurrent plus current portions.
  - Total interest-bearing debt isn't computed: that's a Phase 2 choice.
- **Shares and dilution:**
  - Basic and diluted weighted averages for the latest reported quarter-length period (70–110 days). An older quarter is flagged stale; annual and year-to-date averages never stand in for a quarter. If no quarter is tagged, the quarterly figure is unknown.
  - Every cover-page count on its date.
  - Options outstanding, unvested awards, antidilutive securities and convertible shares, where tagged as one company-wide figure.
  - The same rule for each latest-period share or dilution figure: two values in one filing give unknown with no number, and a revision needs reconciliation.
  - Fully diluted shares are always **unknown**: the pieces can't be added without their terms.
- **Financial companies and share classes:**
  - **Banks** (SIC 6020–6036), **insurers** (6300–6411) and other financials (6000–6799) get the generic measures marked not applicable, plus a list of the data a sector model would need instead.
    This applies to selected figures, TTM and balance-sheet rows. Raw provenance and existing staleness or conflict explanations remain available; TTM and balance-sheet rows retain their underlying `data_status`.
  - **Several tickers or cover-page counts:** flagged as possible share classes (or listed preferred shares).

## Checked against the filing itself

For the tickers given to `--reconcile` (default MSFT, MU, AVGO), the latest fiscal year's revenue, net
income, operating cash flow and capex are looked up in the issuer's own filing:

1. Find the filing by the selected figure's accession number.
2. Download its XBRL instance.
3. Find the same tag and period without dimensions (a company-wide figure), in **USD** (the filing's unit declarations are resolved).
   The same number in another currency, or in a unit the filing doesn't declare, is **unverified**, never a match.

- **Inline XBRL:** it tags the numbers printed in the 10-K, so a match confirms that StockWatch retrieved the right figure for the right period.
- **What it doesn't check:** the issuer's accounting, or whether the figure suits a valuation.
- **If the filing can't be read** or has no such figure, the result is **unverified**, with the reason.

Capex is cash paid for property and equipment (gross), as tagged. It isn't maintenance capex, and it leaves
out assets funded by leases. The report lists, for the same period, proceeds from selling PP&E,
payments for other productive assets, finance-lease principal payments and assets obtained under new
finance leases, observed only.
Each context figure has a status and source. Conflicting values in one accession give unknown with no amount; later revisions need reconciliation and name the filing values and accessions.

## Running it

The repo is public: public example tickers only, never a list of private holdings.

- **GitHub:** Actions → "SEC data audit (read-only)" → Run workflow.
  - **Inputs:** `tickers` (default MSFT MU RIVN BRK-B JPM AVGO) and `reconcile` (default MSFT MU AVGO).
  - **Where the report appears:** on the run's summary page, in the job log, and as `sec-quality.md` and `sec-quality.json` in the `sec-data-audit` artifact.
  - **Job result:** fails if no company could be retrieved.
- **Locally:** `python -m stockwatch.sec_quality MSFT MU RIVN BRK-B JPM AVGO --reconcile MSFT MU AVGO --markdown q.md --json q.json`
  (set `SEC_USER_AGENT` to "Your Name you@example.com"; add `--as-of 2026-03-01` for a point-in-time view).

## What it doesn't do

- **No valuation:** no fair value, DCF, P/B model, buy-under price, score, signal or trade plan.
- **No normalization:** it doesn't adjust, combine, convert or estimate figures, including total debt, net debt, maintenance capex and fully diluted shares.
- **No sector data yet:** the bank and insurer data it lists is not collected.
- **XBRL only:** it doesn't read the filing's text, footnotes or press releases. A filing check covers the four figures above, for the companies named.
