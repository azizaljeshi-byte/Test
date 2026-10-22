# MSFT valuation evidence readiness — Phase 3

[Owner authorization](https://github.com/azizaljeshi-byte/Test/issues/13#issuecomment-6347916886). Standalone MSFT-only research; no DCF, price target, probability, approved forecast, tax/ERP policy or trading decision. No UI, portfolio, alert, scheduler, chart, paid API or secret changes. The existing manual dossier workflow runs the new code after review/owner merge; nothing is automatically dispatched.

## Decision first, evidence underneath

The additive **`msft-dossier.3`** contract preserves prior fields and adds `valuation_readiness` (`msft-readiness.1`): field status/value/unit/source/date/freshness, exact concept matches, lease arithmetic, supported versus unsupported computations, and explicit blockers. Its plain-language summary is on the card; full provenance remains expandable. Original `readiness_gates` still covers multi-year evidence and model assumptions; the new ledger complements it rather than certifying completion.

`usable` means the specified observation passed the stated date/unit/original-source checks; it does **not** mean economic scope is approved for a valuation. `reconcile` preserves a conflict or a candidate requiring independent review. `unavailable` records the exact missing/stale/source/access/approval reason. The new runner never calls the scenario engine. Valuation stays **INSUFFICIENT EVIDENCE**, with empty cases and no reverse expectations even if Treasury or some accounting fields are available.

## Capital and share evidence

Reuse official SEC captures and original-instance matching at the latest reported balance date, with filing availability/as-of and a 200-day capital freshness rule inherited from the research config. The ledger separately queries cash, short-term investments, reported long-term debt total/noncurrent/current maturities, short borrowings, commercial paper, finance/operating lease totals/current/noncurrent components, preferred/minority concepts, and common shares. Exact concept names remain visible. Missing preferred/minority tags are **not** zero or documented absence; another concept or filing-note review may be necessary.

A complete lease total/current/noncurrent trio can pass a dated arithmetic reconciliation. The bridge must count that total **once**, not add it to its components. No total debt sum or enterprise/equity value is automatically constructed: debt totals and commercial paper/short-borrowing/current-maturity concepts can overlap or omit components, and lease inclusion needs note-level economic review. Short-term investments are not automatically surplus; restricted/operating scope remains a blocker.

Common outstanding shares are an accounting observation, not a fully diluted spot denominator. Cover-page/basic/diluted-EPS evidence remains in the existing matching investigation. Options/RSUs, treasury-stock/exercise-price treatment, vesting/antidilutive claims, share class and corporate actions remain unresolved; this phase does not infer a spot denominator by adding awards to weighted averages. Debt coupon/interest-expense ratios are not substituted for contemporaneous marginal borrowing yields. Issuer terms/yield evidence is still requested, not invented. Depreciation versus total D&A remains gated alongside maintenance/growth cash PP&E and lease-funded expansion.

## New official Treasury source

The only newly enabled live source is the [official daily Treasury XML feed](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed), not a market-data aggregator. The [government catalog](https://catalog.data.gov/dataset/interest-rate-statistics-daily-treasury-yield-curve-rates) identifies the dataset as public with CC0 licensing. No authentication, registration or purchase is added. Request only the as-of year and, if necessary, the prior year for a seven-day boundary window; serialize at no more than one request/second, cache source/failure per run, refuse redirects, and cap response reads at 5 MB. No undocumented assumption of a vendor rate entitlement or unlimited request budget.

The XML parser selects `NEW_DATE` / `BC_10YEAR`, converts published percent to ratio and retains URL/hash/date. Empty values are not zero, same-date conflicting yields need reconciliation, schema drift/source outage/staleness produces unavailable. The result is a nominal ten-year **par yield**, not a zero-coupon curve or company WACC. ERP and tax are separate owner assumptions, with **no 5% default**.

Daily feed dates lack certified intraday publication timestamps. This prototype conservatively uses a rate no earlier than the *following calendar day*, disclosing that availability convention rather than claiming same-day/historical PIT precision. Current feed data can be revised; replay is integrity-preserving, not a certified vintage archive. Rates older than seven calendar days fail the explicit research freshness rule.

The sandbox's normal Treasury fetch on 2026-10-22 failed at proxy CONNECT 403. Documentation access is **not** live-rate validation. New Treasury/SEC readiness outputs require an authorized hosted run and independent review. No Treasury yield or MSFT issuer financial value was sourced live here.

## Price and beta interfaces — deliberately no new market fetch

External public-market redistribution rights and contemporaneous corporate-action consistency have not been verified for this pipeline. Under the owner's explicit gate/interface exception, **no market provider is enabled**, no quote or beta is silently taken from a vendor, and the default report says exactly why price/beta are unavailable. The existing app's Yahoo clients are unchanged and are not treated as proof of new artifact-display rights.

Pure candidate validators support future reviewed evidence:

- A close capture must identify MSFT common, positive USD/share, raw-unadjusted basis, quote/availability/capture dates, source/provider/permission reference and split/action review. Stale/future captures, adjusted-versus-share basis conflicts, wrong class and incomplete metadata fail. Metadata alone does not authenticate the source: even a schema-passing price is **reconcile**, never a completed market-cap/share basis. Unknown extra fields are dropped, and credential-bearing source URLs are refused.
- Beta is reproducible covariance/variance of **monthly simple returns** from at least 37 consecutive monthly MSFT/SPY closes (36 returns), exact matching dates, no fills, positive finite prices and the same declared split/dividend adjustment basis. Every observation must be available by as-of and the endpoint within 45 days. Zero variance, missing months, mismatched/forward/stale/unadjusted inputs refuse. Output retains window, frequency, adjustment basis, sample count, sources and a hash of inputs. It stays **reconcile** pending independent source rights, corporate-action and sampling review, not adopted WACC beta.

These functions are not a secret-bearing upload endpoint and are not wired into CLI/production market ingestion. No beta, borrowing cost, capital weight or WACC is fabricated. Independent source access/permissions and note-level reconciliation remain acceptance work, rather than being implied complete by a successful schema check.

## Presentation and cash-return interpretation

Currency movements now use readable B/M scales (small synthetic amounts use two decimals); pp changes use one decimal. Structured JSON numerical fields keep original precision. Fiscal labels derive the end date from evidence, e.g. `FY2025 → FY2026 (ended 30 Jun)`; June is not hardcoded. Persistent findings explicitly say whether both residual dollars and margin declined, or which one did. When latest OCF/revenue improves despite the residual divergence, the card explicitly acknowledges it.

The owner-reviewed Phase 2 FY2024–26 pattern is a validation reference only; this code recomputes all amounts and never embeds those issuer figures. Cash residual deterioration and improved latest OCF/revenue can coexist. Neither establishes incremental ROIC, AI payback, asset lives or causation. Forward maintenance/growth spending, lease expansion, terminal fade/ROIC and bear/base/bull drivers remain owner-reviewed assumptions.

## Operation and private replay

Existing manual workflow invocation remains `python -m stockwatch.msft_dossier --output ...`; normal live invocation also attempts the official Treasury feed. SEC snapshot replay performs **no network**; if Treasury capture is absent its input is unavailable instead of silently fetched.

```bash
python -m stockwatch.msft_dossier --output /tmp/msft-readiness \
  --save-private-sources /tmp/private-sec.json --save-private-treasury /tmp/private-treasury.json
python -m stockwatch.msft_dossier --as-of 2026-10-22 --output /tmp/msft-replay \
  --snapshot /tmp/private-sec.json --treasury-snapshot /tmp/private-treasury.json
```

Private snapshots are optional and are not uploaded by the workflow. Reports contain selected financial facts, links and hashes, not source bodies/credentials. Source failure never erases valid business evidence or manufactures valuation readiness. Unknown/malformed source arguments may still fail the CLI; unavailable financial observations are explicit report outcomes.

## Verification and unresolved work

Synthetic fixtures test dated Treasury percent conversion, same-day exclusion, stale/missing/conflicting/feed-drift/outage/hash refusal; price class/split/adjustment/availability guards; exact beta reproduction and missing/alignment/zero-variance refusal; original-filing same-date capital matches, missing claims, lease sum/date conflicts, explicit overlap refusal; replay/isolation; readable scaled currency/FY labels and OCF counterevidence. Prior cash/annual/TTM regressions remain. Tests contain no actual MSFT values.

Outstanding: authenticated/authorized new hosted source run, independent source/filing comparison, permitted contemporaneous market capture, spot fully diluted and award reconciliation, complete economic debt/lease/surplus/claim scope, justified beta and marginal borrowing yield, and explicit owner policy/forward-case approvals. No future valuation execution is enabled by this PR.
