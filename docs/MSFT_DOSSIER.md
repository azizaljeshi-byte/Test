# MSFT decision-first research dossier

Authorized by [issue #13](https://github.com/azizaljeshi-byte/Test/issues/13#issuecomment-6346251110) and the [owner-inspected gap update](https://github.com/azizaljeshi-byte/Test/issues/13#issuecomment-6346698538). Scope: MSFT, official SEC, manual research. No UI, production scores/trade plans/alerts/portfolio, price forecast, paid API, autonomous agent or schedule.

## Decision card

`msft_dossier` leads with separate **business economics** and **valuation** conclusions. It can describe observed revenue and operating-margin changes and positive/negative cash-investment evidence. It cannot establish price attractiveness: contemporaneous price, spot fully diluted claims, capital/lease scope, discount inputs, approved forward cases and competitive evidence remain absent. Valuation therefore stays **INSUFFICIENT EVIDENCE**, with empty cases and no reverse-implied growth. Positive accounting history is not a BUY signal, moat proof or a 3/6/12-month return prediction.

Positive/opposing findings are generated from actually matched data, never forced to a target count. Fewer findings mean fewer supported conclusions. Neutral endpoint changes and unproven competitive claims are not converted into positive evidence. The card shows uncertainty, missing inputs and observations that would change the assessment; fiscal tables and structured provenance are secondary expandable sections.

## Annual, TTM and matching gates

- Select up to five fiscal years per core field using the existing annual-history quality layer. Preserve revisions/conflicts and add fallback-concept scope warnings. Original-instance checks match exact concept, accession, unit, company-wide context and actual period; publication chronology must satisfy start ≤ end ≤ filed ≤ as-of.
- Calculate business trends only for aligned revenue, operating income, OCF, cash PP&E spending and SBC sharing an exact fiscal period and accession. Ratios use reported USD values; no split/price normalization or automatic restatement repair. Revenue must be positive and capex/SBC nonnegative for this diagnostic.
- Keep the latest consecutive run of at most three complete aligned years, stopping at the first older gap. Identical same-year copies retain their accession provenance; conflicting values or fiscal periods mark that year ambiguous and stop the run rather than silently selecting a revision. Business-economics status requires at least two consecutive fiscal years (350–380 days between ends) and a latest year no more than 550 days before as-of. These explicit conservative research coverage/freshness rules are not investment thresholds or adopted portfolio policy. Historical annual observations are not relabeled current TTM figures.
- Revenue change is the cumulative change between labeled fiscal endpoints, not an annualized growth forecast. Operating-margin change is percentage points. OCF less cash PP&E is not FCFF and does not separately charge SBC; cash capex excludes finance-lease-funded expansion and has no inferred maintenance/growth split. No leverage or spot dilution ratio is invented.
- TTM remains a separate component ledger from Phase 1B. A derived TTM number is usable only if the inherited TTM gate passes and **every** annual/YTD component independently matches the original filing with correct dates/units. A missing original document blocks the derived result. No annual/TTM mixing in trends.

## The owner-reported four provisional and one reconciliation case

The successful prior diagnostic was attempt #2 of run [39815958305](https://github.com/azizaljeshi-byte/Test/actions/runs/39815958305), artifact **12442751941**. Its authenticated logs confirmed aggregate extraction coverage; the owner subsequently inspected its detailed report and identified `basic_shares`, `diluted_shares`, `eps_diluted`, `shares_outstanding`, and `dna` as the gaps. That report was not downloaded into this sandbox, whose storage-host access is also blocked. No issuer metric is copied, guessed or hardcoded from those aggregate counts.

Two concrete parser limitations have bounded fixes:

1. An unprefixed measure QName such as `shares` can use an explicitly declared default namespace. The unit resolver now honors that namespace rather than dropping the unit. Missing/undeclared namespaces remain unresolved. Divided USD/share units receive the same resolution; EPS units are never assumed from a number.
2. The original instance parser skipped DEI. It now accepts only `EntityCommonStockSharesOutstanding` from SEC DEI namespaces, retaining the existing undimensioned-context and unit/period gates. Other DEI fields are not broadly accepted.

These changes are independently exercised on synthetic XML. **They are not a claim that all four real provisional rows are fixed.** A fresh hosted run exposes each field's actual selected source and filing-check result. Even a successful match to cover-page or EPS-average shares does not establish a spot fully diluted same-class denominator, corporate-action basis or future dilution.

`dna` retains quality/scope warnings. Depreciation and total depreciation/amortization can describe different components; the dossier does not combine, replace or silently choose them to force a valuation. The investigations ledger reports current status and source for all five fields. Stale/unknown/unverified data never becomes positive business evidence.

## Manual pipeline and replay

The existing **MSFT official SEC diagnostic (manual research)** workflow now also writes `dossier.json` and `dossier.md` to its seven-day artifact. It puts the dossier decision card first in the Actions summary. Dossier collection uses the reviewed paced official transport with private `SEC_USER_AGENT`; it leaves the existing diagnostic outputs intact. Each process caches sources/failures, requests at most two per second and uses bounded 429/503 retries. The diagnostic and dossier are separate serial steps, so they may each fetch the same endpoint once; the owner must still respect the aggregate SEC budget across other jobs/machines.

After review and owner merge, manually dispatch the existing workflow. No automatic hosted run or deployment is implied by this PR. A complete multi-year card exits zero; insufficient verified history exits 2 while summary/artifact steps still run. A green step is not a valuation-readiness certificate.

```bash
python -m stockwatch.msft_dossier --as-of 2026-10-22 --output /tmp/msft-dossier
# Optional source retention is LOCAL/PRIVATE, never enabled by the public workflow:
python -m stockwatch.msft_dossier --output /tmp/msft-dossier \
  --save-private-sources /tmp/private-msft-sources.json
python -m stockwatch.msft_dossier --snapshot /tmp/private-msft-sources.json \
  --as-of 2026-10-22 --output /tmp/replayed-dossier
```

Snapshots use the existing version, source bodies and hashes. Replay never fetches absent sources. Earlier as-of replay may lack older filing documents; affected figures stay unverified. A current companyfacts snapshot filtered by filing date is not certified point-in-time history, and hashes are integrity checks rather than authenticity. Keep snapshots private and handle issuer-document retention rights separately; no raw XML, API response bodies, private contact or new access secrets are published in artifacts/comments.

## Validation boundary

Offline synthetic tests establish multi-year arithmetic, exact-period alignment, stale/gapped/single-year refusal, source outage, original-filing/replay/as-of behavior, true 10-K annual + current 10-Q YTD − prior 10-Q YTD component verification/refusal, duplicate-year ambiguity, rendered Markdown block separation, units/default namespaces and DEI dimensions, unchanged scenario refusal, report ordering and AST isolation. The synthetic numbers do not describe Microsoft. Previous hosted success establishes that official access worked in that run; it does not validate this new dossier or prove every economic input is suitable. Fresh hosted verification and independent content review remain required.
