# SEC financial-data audit (valuation Phase 1)

Phase 1 of the valuation work in Issue #2: before designing any valuation model, find out which
financial-statement inputs SEC EDGAR actually provides, how much history there is, and how
trustworthy it is. **This is read-only.** `stockwatch/sec_audit.py` isn't imported by the app, so
scores, signals, plans and screens don't change.

## What it checks, per company

For each valuation input (below), from SEC's XBRL "company facts":

- **Coverage:** how many *distinct* fiscal years are reported (5 wanted), the latest figure with its
  period end, form and filing date, and the trailing twelve months for dollar amounts.
  - **Overlapping periods:** annual periods ending within 300 days of a newer one (a fiscal-year change,
    or duplicate periods) are flagged and not counted.
  - **"Covered" means coverage only:** it doesn't establish that the figures are comparable or normalized
    enough to value a company on.
- **Reporting tag changes:** companies switch XBRL tags over the years (e.g. `SalesRevenueNet` to
  `RevenueFromContractWithCustomerExcludingAssessedTax`). The audit stitches the history across tags and
  says where the switch happened. The app's current extraction only reads the tag with the newest data,
  which loses the years before a switch.
- **Restatements:** a year re-filed more than 0.5% away from its first filing.
- **Amended filings:** values that come from a 10-K/A.
- **Stock splits:** a split is confirmed for a year only when shares were re-filed up by a whole
  multiple and EPS down by the same multiple, or the reverse. Then those rows aren't restatements. A
  whole multiple without that inverse move is reported as "possibly a split, not confirmed" and still
  counts as a restatement.
- **Units:** fields reported only in another currency are "other units only", never converted.
- **Staleness:** the latest figure is more than 200 days old.
- **Share counts:**
  - several cover-page share counts for the same date (multi-class companies)
  - cover-page shares more than 15% away from *basic* weighted-average shares from the nearest period
    (diluted only if basic isn't reported), with the date gap stated. The two measure different things
    (one date vs a period average), so this is a prompt to check for a missing class, a split or large
    buybacks/issuance before cover-page shares are used for market cap. It isn't proof of an error.
- **Financial companies:** SIC 6000–6799, where free cash flow, current ratio and debt/equity mean
  different things.
- **App comparison:** exactly what the app's SEC fallback (`sec.fetch_facts`) keeps today, computed
  on the same downloaded file.

Missing or unreadable data is reported as missing or unavailable, with the reason. Nothing is
estimated or filled in.

## Fields

Revenue, operating income (EBIT), net income, operating cash flow, capital expenditure, stock-based
compensation, depreciation & amortization, interest expense, dividends paid, share buybacks, cash &
equivalents, short-term investments, long-term and short-term debt, operating and finance lease
liabilities, PP&E (net and gross, observed only, for later maintenance-capex work), shareholders' equity,
basic and diluted weighted-average shares, diluted EPS, and cover-page shares outstanding. The candidate XBRL tags for each are in `FIELDS` in `stockwatch/sec_audit.py`.

## Running it

The repo is public, so only run it on **public example tickers**, never a list of private holdings.

- **GitHub:** Actions → "SEC data audit (read-only)" → Run workflow. The report appears on the run's
  summary page and as a downloadable `sec-data-audit` artifact (Markdown and JSON). It uses the
  `SEC_USER_AGENT` secret.
  - **Status line:** the report opens with **COMPLETE**, **PARTIAL** or **NO DATA**, with counts and the
    reason for each unavailable company.
  - **Job result:** fails on NO DATA and shows a warning on PARTIAL, so a green run means SEC data was
    retrieved. The command's exit code is 0 / 1 / 2 to match.
- **Locally:** `python -m stockwatch.sec_audit MSFT MU RIVN BRK-B JPM AVGO --markdown audit.md --json audit.json`
  (set `SEC_USER_AGENT` to "Your Name you@example.com").

The default examples cover:

| Ticker | Covers |
|---|---|
| MSFT | a cash generator |
| MU | a capital-intensive company |
| RIVN | a cash-burning issuer |
| BRK-B | multiple share classes |
| JPM | a bank |
| AVGO | a recent 10:1 split |

## What it doesn't do

- **Not yet run on real SEC data:** the tests use synthetic SEC-shaped data. They show the checks behave
  as intended, not that SEC access or the tag mapping works for real companies. The first real run
  (above) is what verifies that.
- **No valuation:** it computes no valuation, fair value, buy-under price or score.
- **No maintenance capex split:** it doesn't separate maintenance from growth capex. That needs
  disclosures beyond these XBRL tags, and is a Phase 2 question.
- **No point-in-time rebuild:** it doesn't reconstruct full point-in-time history. It records first-filed
  and latest-filed values per year, which is the raw material for that.
