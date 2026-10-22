# Phase 2A-3: MSFT evidence pilot

Issue [#13](https://github.com/azizaljeshi-byte/Test/issues/13#issuecomment-6345092902) assigns this first pilot to Codex. This is a standalone, read-only adapter and decision-summary layer. No Research Lab UI, production scoring, trade plan, alert, portfolio, broker, schedule or deployment changes. AVGO follows only after the owner's MSFT checkpoint; MU/JPM and hardware depreciation remain later work.

## Decision first

JSON and Markdown lead with **INSUFFICIENT EVIDENCE**, dominant verified accounting observations, main uncertainty, a clearly hypothetical bear thesis and the observations needed to change the assessment. Usable aligned facts can explain cash PP&E/revenue, OCF minus cash PP&E, and SBC/revenue. Each calculation names its input fields, whose coverage rows retain filing period, publication date, accession, concept, unit and original-instance URL. The three calculations require the same accession and exact period; different fiscal calendars are never silently aligned. OCF minus cash PP&E is not FCFF, and no moat/demand/competitive conclusion is inferred from an accounting ratio.

This initial adapter deliberately **cannot clear a valuation conclusion**: it has no independently sourced market/share reconciliation or approved scenario assumptions. `ATTRACTIVE FOR FURTHER REVIEW`, `MIXED OR FAIRLY PRICED` and `EXPENSIVE OR RISKY` are reserved for a later separately reviewed complete-evidence rule, not inferred from positive cash flow or invented valuation thresholds. The decision is a refusal backed by a useful accounting diagnostic, not an evaluation of whether MSFT is cheap today. `ASSUMPTIONS REQUIRED` describes partial evidence; `UNAVAILABLE` describes unavailable sources or no verified fields. `PARTIAL` is factual extraction coverage, never validated investment inputs.

Bear/base/bull values, reverse-implied growth and sensitivities remain explicitly unavailable. No numerical conviction or probability is emitted. Long-term business economics are separate from 3/6/12-month market movement, for which this pilot has no model. A later separately reviewed UI PR can consume the report; nothing imports this adapter today.

## Extraction and refusal rules

- MSFT CIK **789019** only. Require the same issuer identity in official companyfacts and submissions; no arbitrary ticker or URL fetch.
- Reuse `sec_quality.quality_company` selection, statuses, revisions, tag conflicts, annual/instant dates and staleness. Preserve all selected fields, even unknown/unverified ones, in the matrix. A selected value in the matrix is **not** necessarily verified: read its status.
- Fetch the selected accession's SEC archive index and instance with existing SEC concurrency/identification controls. Reuse the instance parser. A verified row needs a unique company-wide value with matching concept, exact start/end and correct USD/shares unit, plus valid period/publication chronology. Conflicting original filing values, missing documents or units fail closed. This checks extraction, not accounting accuracy or economic scope.
- Only verified annual revenue and cash are copied directly into a partial `companies.MSFT` packet compatible with the 2A-2 evidence contract. That packet is not merged into the approved/default config and is never passed off as a completed valuation.
- All other capital-bridge inputs require economic reconciliation. Short-term investments are not automatically surplus cash. A debt tag may omit commercial paper/current maturities; a noncurrent lease is not the full lease liability. Missing preferred/minority tags are never zero.
- Cover-page shares, weighted-average basic/diluted EPS shares and spot fully diluted claims are distinct. No share count is promoted to `observations.shares`, no split convention is inferred, and there is no automatic price acquisition. Treasury, beta methodology, borrowing cost and peer/fiscal comparability require independent dated evidence. Illustrative ERP is a policy request, not a measurement.
- Maintenance versus growth capex, lease-funded investment, operating working capital, segment/competitive evidence and scenario/terminal drivers require sourced review and explicit owner assumptions. The requests distinguish issuer evidence, independent evidence, contracts and owner approval. There is no input override that bypasses these gates in this pilot.

## Source feasibility and licensing

Existing clients access only official SEC endpoints; no new dependency, connector, paid API, scraping service or secret. The existing `SEC_USER_AGENT` contact identifier is recommended. Companyfacts are public facts, while filing contents can include issuer-owned material; do not redistribute whole filings without checking rights. This PR commits no retrieved issuer documents. It commits the actual source-failure diagnostic, not a synthetic "real MSFT" valuation.

The official companyfacts attempt on **2026-10-22** returned `URLError: Tunnel connection failed: 403 Forbidden` in this environment. No SEC filing totals or MSFT financial values were retrieved or independently checked. The absence of a configured SEC contact is also reported by the existing client. This does not establish whether the endpoint will work in the owner's configured environment. [Recorded report](examples/msft-evidence-unavailable.md) and [JSON](examples/msft-evidence-unavailable.json) document the actual outcome; they are not a successful real-company validation. The outstanding acceptance check is a successful official-source run with independent comparison to the selected audited MSFT filing, followed by owner review of usefulness before adding another issuer.

## Run and replay

```bash
python -m stockwatch.valuation_evidence --as-of 2026-10-22 --output /tmp/msft-evidence
python -m stockwatch.valuation_evidence --as-of 2026-10-22 \
  --snapshot /tmp/msft-evidence.sources.json --output /tmp/msft-replay
```

Outputs: `.json` decision/coverage/partial packet, `.md` decision card with expandable evidence/requests, `.sources.json` versioned source snapshot. An honest unavailable report exits zero; inspect disposition/status rather than treating process success as financial validation. Malformed snapshot arguments can still fail the CLI.

Snapshots record collection timestamp, source URLs, SHA-256 and base64 bodies (canonical JSON for API responses; raw bytes for filing documents). They are local research artifacts by default. Replaying never fetches missing sources or retries recorded failures, and checks every body hash. This detects accidental source drift; it does not authenticate an edited snapshot. A body is limited to 20 MB after the existing client retrieves it, not a streaming download limit. Filing indices/instances are reused per accession in one run; execution is serial within the client's existing SEC concurrency limit.

As-of applies to filing availability and actual period dates. Replaying a *current* download at an old date is not certified point-in-time archival data: historical omissions and taxonomy/vendor changes cannot be reconstructed. Submissions' current issuer metadata and the inherited family classifier are descriptive context, not independently verified historic classification. Earlier replays with absent original documents stay unverified. The adapter does not turn a current retrospectively adjusted price into an historical observation.

## Inherited comparable disagreement correction

The 2A-2 EV/FCFF cross-check is an **undiluted** common claim, while the DCF base may include time-weighted extra non-SBC dilution. Both bases are now disclosed. `difference_from_base_per_share` is `null` when that ownership weight differs from one, with `comparison_status` explaining incompatibility. With no extra dilution the existing subtraction is retained. No methods are averaged, and valuation math/rates/weights otherwise stay unchanged. The Research Lab's numeric synthetic scenarios are unchanged.

## Verification

Synthetic SEC-shaped fixtures exercise original-instance matches, wrong units, conflicts, source drift, period/calendar mismatch, missing/invalid publication dates, future filings and restatements, stale values, missing leases/shares, issuer identity, archive outage and deterministic offline replay. These test arithmetic and refusal; their numbers do **not** describe Microsoft. Regression checks preserve comparable bases, 2A-2 packet compatibility/refusal and isolation from all app/trading imports. Full test and lint totals are recorded in the PR.
