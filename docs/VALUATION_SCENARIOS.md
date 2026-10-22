# Phase 2A-2: valuation scenario research

Issue #8, owner-approved handoff [6341705172](https://github.com/azizaljeshi-byte/Test/issues/8#issuecomment-6341705172). Codex implements; ChatGPT reviews first, Claude second. This module is isolated from production. It adds no BUY/SELL, scores, sizing, probabilities, live screens or automated alerts. PR #10's historical-chart work is separate.

## What is implemented

- **MSFT/AVGO cash-compounder family:** ten-year, driver-based FCFF research scenarios and enterprise/common-equity bridge. Five explicit annual driver sets, then a five-year linear fade to terminal settings. The model includes operating margins, taxes, depreciation, operating working capital, maintenance versus growth investment, SBC and additional non-SBC dilution. An independent comparable EV/FCFF lens is reported separately, never averaged into the scenario range.
- **MU/cyclical family:** six-year evidence table with status-gated revenue, operating margins, capex and operating cash conversion across cycle phases. At least five comparable complete annual observations and a material revenue decline or operating loss/profit cycle are required. Median nominal fiscal revenue (no inflation adjustment) becomes the normalized starting scale; observed operating-WC/revenue is retained. Explicit scenario margins and reinvestment assumptions still determine the forward cases; median capex/margin/conversion evidence is displayed, not silently made a forecast of memory pricing. There is no trailing peak-multiple shortcut.
- **JPM/banks:** a separate steady-state residual-income P/TBV lens, with cost of equity, sustainable ROTCE, growth and an explicit capital reserve. It requires reconciled tangible COMMON equity, common share class/dilution, observed regulatory capital, credit losses, funding and historical ROTCE. It never computes industrial EV/FCF or bank WACC. An independently observed comparable P/TBV can be reported separately.
- **RIVN/cash-burning:** retains 2A-1's backward-looking runway and EPS-denominator growth; intrinsic value stays unavailable. Insurers/REITs/utilities/other unsupported families remain unavailable. VRT is explicitly deferred until the hardware/asset-life audit.

Classification remains the existing 2A-1 research heuristic, not an automatic industry-economic truth. No conglomerate sum-of-parts model or segment-specific forecasts are implemented: do not use a consolidated industrial classifier to certify a conglomerate's model suitability. A segment/conglomerate case requires a separately scoped adapter/model. The default pilot is MSFT, AVGO, MU, JPM, RIVN and BRK-B; no private portfolio is loaded.

## Evidence before values

`stockwatch/valuation_scenarios.yaml` is versioned and `approved: false`. It contains the specification's illustrative 5% ERP, a minimum discount/terminal spread of 2 percentage points, and the **sensitivity-only** 8/10/12% × 1.5/2.5/3.5% grid. Company packets are deliberately empty: **no company forecasts, beta estimates, maintenance capex, fully diluted counts or bank facts have been fabricated.** The new models run on complete attributed packets; the supplied real-company configuration will generally report UNAVAILABLE or ASSUMPTIONS REQUIRED. It does not provide production-ready fair values.

Each observation/assumption record contains:

```yaml
value: 0.04             # an example of the schema, not today's Treasury yield
unit: ratio             # USD, shares, ratio, multiple or contract
kind: observation       # or analyst_assumption / policy (never treated as a market observation)
status: usable          # unknown/stale/needs reconciliation blocks the input
period_end: '2026-02-27' # date of observation / assumption set, NOT future projection date
available_on: '2026-02-27'
source: 'Independent source URL or filing citation; synthetic examples say SYNTHETIC'
rationale: 'Why this observation/assumption and scope are appropriate'
```

Dates must satisfy period end ≤ availability ≤ run-as-of. SEC-origin records additionally require `origin: SEC`, `accn`, `form`, and `filed`; filing availability is validated. Baseline revenue also requires `period_start` and must match the exact annual fact selected by Phase 1B. Numbers must be finite, correctly unit-tagged and dated; missing values never become zero. Citation metadata cannot establish the truth of a financial claim: a human must independently check the linked evidence and scope. This is a documented adapter contract, **not an autonomous financial-disclosure parser or verified data vendor**.

Phase 1B raw revenue, operating income, D&A, capex, SBC and cash must be usable before nonfinancial scenario output. A packet cannot override those SEC disputes. Baseline operating WC must match the annual revenue end. Capital balances share one date and, when SEC identifies a latest balance sheet, must use that exact date. Share evidence cannot predate a known newer SEC cover-page count. Bank inputs must use the latest company-reported period. The configured age bounds also refuse stale market/capital observations. These age bounds (price/Treasury 7 days, beta/comparables 120, capital/borrowing cost 200, normalized cash flow 550) are explicit **prototype research assumptions subject to review**, not adopted policy.

### Nonfinancial packet

`companies.TICKER.observations` requires:

| Keys | Units / constraints |
|---|---|
| `price`, `shares` | USD/share price and shares respectively. Positive, same `class_id` and `split_basis_date`, no future corporate-action basis. |
| `cash`, `investments`, `debt`, `preferred`, `noncontrolling` | USD, nonnegative, same balance-sheet date; zero must be explicitly evidenced. Surplus investments and claim scope must be economically reviewed. |
| `debt_noncurrent`, `debt_current`, `finance_lease_liabilities` | USD, nonnegative, same date. Non-lease current + noncurrent debt + all finance-lease liabilities must equal the total. No missing component is silently assumed zero. |
| `revenue` | USD, exact annual SEC fact/period. |
| `operating_working_capital` | USD, same annual date; excludes cash/financing items. Negative operating WC is supported. |
| `treasury_10y`, `beta`, `borrowing_cost` | Decimal ratios, sourced as-of observations. Beta requires a `method` describing regression window/adjustment. Borrowing-cost source/rationale must explain observed yield or interest/debt basis; a generic hurdle is not borrowing cost. |
| `peer_ev_fcff` | Optional independent positive multiple with source/peer rationale, contemporaneous date. Not levered P/FCF. |
| `independent_normalized_fcff` | Optional positive USD with `method` showing a separately constructed normalized unlevered cash flow after SBC, same lease scope. Never automatically taken from the DCF forecast. |

`contracts` contains attributed reconciliation records with unit `contract`:

- `business_scope.value: operating_business_consolidated_drivers_reconciled`: a human economic/segment review supports the consolidated operating model. A conglomerate or unresolved sum-of-parts case is unsupported; do not attest this merely because the 2A-1 heuristic says compounder.
- `share_basis.value: fully_diluted_common_same_class`: reconcile basic common shares, existing awards/convertibles and conversion between classes; preserve evidence in source/rationale. This is not inferred from EPS-denominator shares.
- `corporate_actions.value: verified_price_share_basis`: dated price and fully diluted shares on the same split/class basis. A current Yahoo retrospective series alone does not certify a historical market-cap basis.
- `lease_scope.value: finance_leases_in_debt_and_investment_operating_leases_in_costs`: debt includes financing leases; investment includes finance-lease-funded additions; operating leases remain operating costs. Prevent a lease-funded asset from disappearing from both debt and reinvestment.
- `cross_check_basis.value: ev_fcff_after_sbc_same_lease_scope`: the optional peer/normalized-FCFF lens uses the same unlevered scope. No averaging with intrinsic values or Street targets.
- `capital_tax`: an attributed decimal `ratio` tax assumption for the cost-of-debt shield.

`scenarios.bear/base/bull` each require **five annual ratios** for `growth`, `margin_pre_sbc`, `tax`, `dna_pct`, `maintenance_pct`, `growth_capex_pct`, `wc_pct`, `sbc_pct`, `non_sbc_dilution`. Each field is a full attributed record, `kind: analyst_assumption` (or policy), `value: [y1,y2,y3,y4,y5]`. They must be independently sourced or explicitly attributed analyst views, not automatically bullish industry averages or +/- changes to the resulting value. `terminal` holds scalar records for those drivers plus `roic`. Terminal `growth` is used as g; all non-growth drivers fade from year 5 to their scalar targets by year 10. Cases must produce an ordered bear≤base≤bull range; the code refuses rather than relabeling inconsistent cases.

### Math and scope

`EBIT = revenue × (margin_pre_sbc − sbc_pct)`. SBC is charged **once** in EBIT, not subtracted a second time from NOPAT. `NOPAT = EBIT − tax × max(EBIT,0)`; loss tax credits are not assumed. `FCFF = NOPAT + D&A − maintenance investment − growth investment − Δ operating WC`. All cash flows are nominal USD at year-end. The final-year operating profit grows at g into year 11. From then, reinvestment is **NOPAT₁₁ × g/ROIC**, so terminal FCFF funds its growth before Gordon capitalization. This explicit normalized terminal method can differ from year-10 capex ratios; the forecast/terminal bridge and terminal value share are inspectable, rather than silently perpetuating a growth capex holiday. Positive terminal NOPAT and `0 ≤ g < ROIC ≤ 1` are required.

WACC = (rf + beta × illustrative ERP) × E/(D+E) + observed borrowing cost × (1−tax) × D/(D+E). E uses the same reconciled quoted-class price and fully diluted common count. D uses the reconciled debt including financing leases. The bridge helper can subtract preferred/minority claims, but the current measured-WACC adapter supports common equity and debt only: **any positive preferred/minority claim blocks company scenarios** pending a separately evidenced market-weight/cost adapter. It never silently ignores their financing cost. The model makes no claim that a generic discount grid is a measured WACC. The grid is emitted only after baseline drivers and capital evidence pass. If Treasury/beta/borrowing-cost evidence is missing, the grid can remain visible with an explicit assumed-rate label, while all measured-rate company scenarios stay UNAVAILABLE. A missing operating baseline or capital bridge does not get a numeric grid.

Additional dilution is **non-SBC** and assumes no financing proceeds or change in enterprise operations/funding. First bridge **undiluted EV** to the entire common-equity claim (EV + cash + surplus investments − contractual debt − preferred/minority claims). Then multiply that common claim by a PV-weighted ownership fraction:

`dilution_claim_weight = (Σ PV(FCFFₜ)/cumulative_share_factorₜ + PV(terminal value)/factor₁₀) / undiluted_EV`.

`equity_per_current_share = undiluted_common_equity × dilution_claim_weight / initial_reconciled_shares`.

`dilution_weighting_pv` is a **timing-weight proxy**, not a claim that creditors' enterprise value or contractual balances have been diluted. Net cash participates in the entire common claim too. This is a documented proportional-common-claim stress, not a financing transaction model: new issuance proceeds, refinancing benefits, buybacks, or changes to enterprise capital structure are not invented. A nonpositive EV or weight outside (0,1] cannot support this convention and is refused, including loss-funding cases where the timing proxy would appear to benefit initial owners. Significant capital restructuring requires a separate model.

**Terminal non-SBC dilution must be exactly zero.** The explicit driver schedule still has five annual assumptions then a linear fade to its zero terminal target by year ten. A positive, negative or nonfinite terminal issuance rate is refused (no scenario or sensitivity numbers), rather than silently stopping continuing issuance at year ten. Accordingly the ordinary Gordon denominator and r−g spread test remain valid. Future SBC is already charged once as an expense and is never counted again as additional SBC share issuance.

Hand check: flat FCFF20 and r10% give EV200. With 2% additional issuance in years1–5 fading through1.6/1.2/0.8/0.4/0% in years6–10, the timing PV is180.2102 and common-claim weight0.901051. Ten initial shares give18.0210/share with a zero bridge, **7.2084** with debt120, **28.8336** with net cash120; even debt190 leaves positive common residual0.9011/share. An explicitly constant2% for all ten years then zero has a different timing PV175.3412; that separate stress is also checked at the bridge helper level, without changing the engine's declared fade schedule. The review's rounded180.21 example corresponds to the fade schedule.

A negative undiluted common residual after senior claims blocks the scenario set rather than emitting a negative stock price; this model cannot price distress/restructuring.

### Bank packet

Requires dated, usable USD `tangible_common_equity`, `common_equity`, `goodwill`, `other_intangibles`, `intangibles_tax_adjustment`; shares; decimal `cet1_ratio`, `credit_loss_ratio`, `funding_cost`, `historical_rotce`; Treasury/beta. TCE must equal common equity minus goodwill and intangibles plus the evidenced associated tax adjustment. All non-share bank facts share one report date; historical ROTCE and risk statistics need a documented horizon/scope in the source/rationale. No regulatory approval or safe capital threshold is inferred from a positive CET1 ratio.

Contracts: common-share basis as above and `bank_tce.value: common_equity_less_goodwill_and_intangibles_net_of_tax`. Scenarios provide scalar attributed `rotce`, `growth` and USD `capital_reserve`. `Ke = rf + beta×ERP`; justified `P/TBV = (sustainable ROTCE − g)/(Ke − g)`. Apply it to (TCE minus explicit reserve), divide by reconciled common shares. Require positive TCE/shares, feasible retention (g≤ROTCE) and minimum Ke−g spread. The reserve is an explicit non-earning, non-distributable capital haircut; the assumed sustainable ROTCE applies to the remaining earning TCE and must not exclude that reserve a second time. `historical_rotce`, `cet1_ratio`, `credit_loss_ratio` and `funding_cost` are labeled **gating only**: their availability is checked, but scenario ROTCE/reserve assumptions drive value. An optional positive contemporaneous `peer_p_tbv` observation needs a peer/method description and remains a separate context, never bank EV/FCF. Missing bank inputs yield UNAVAILABLE, not an industrial fallback.

## Run / reproduce

```bash
python -m stockwatch.valuation_scenarios MSFT AVGO MU JPM RIVN BRK-B --as-of 2026-10-22 --json /tmp/scenarios.json --markdown /tmp/scenarios.md
# A reviewed config with actual evidence and attributed scenario drivers:
python -m stockwatch.valuation_scenarios MSFT --config reviewed-packets.yaml --as-of 2026-10-22
# OFFLINE SYNTHETIC arithmetic/schema demonstration, not a public company valuation:
python scripts/valuation_scenarios_example.py /tmp/valuation-synthetic
```

The synthetic example exports the complete editable YAML packet, JSON and Markdown. Revenue 100, margin 20%, no SBC/tax/growth, D&A=maintenance=2 and flat operating WC give FCFF=20 forever. With rf=4%, beta=1, ERP=5%, borrowing cost=5%, E=100, D=25, WACC=8.2%; debt/cash/investments net to zero. Base enterprise value=20/0.082=243.9024 and equity/share=24.3902. Bear/base/bull pre-SBC margins 15/20/25% give 18.2927/24.3902/30.4878. A separate synthetic peer multiple 10× independent FCFF20 gives equity/share20, a disagreement kept separate. These teaching assumptions are **not** estimates for MSFT, AVGO, MU or any real company. Its zero-growth perpetuity is for hand verification, not a change to the configured real-research sensitivity grid.

The manual SEC audit workflow has an optional `scenarios` input (blank by default). It generates Phase 2A-2 reports on the selected branch and uploads them alongside prior audit artifacts. Source retrieval failure has nonzero exit status; a completed evidence-gap diagnostic can exit 0, **which does not mean a valuation was computable**. State and gaps are in every company ledger. Do not publish private holdings or confidential source documents.

## Validation / remaining gaps

Tests cover hand-calculated perpetuity/WACC/P/TBV, five-year drivers and fade, terminal reinvestment, SBC once, time-weighted dilution, current/preferred/minority bridge, missing/stale/disputed facts, unit and split/class mismatch, future filings, r/g edge, negative interim cash flow, nonpositive terminal refusal, cyclical phases/history gaps, ordered cases, absent bank inputs and no production imports. Full offline suite and lint are run for the PR.

The runtime currently cannot independently obtain/certify the full market/normalized/fully-diluted/bank dossier from the existing SEC adapter alone. Empty real-company packets deliberately refuse numerical prices; evidence gathering/reconciliation is a remaining work item, not completed by a nonempty citation string. The prior 2A-1 live SEC run does not validate these new scenario equations. Current companyfacts and Yahoo retrospective data are not a point-in-time archive, even though future rows/filings and future-dated packet evidence are blocked. No historical accuracy, out-of-sample success probability or production readiness is claimed.

Local validation after the grouped dilution correction: 35 focused tests and 163 full-suite tests pass; pyflakes/diff checks clean. The synthetic example was reproduced. A read-only GitHub CLI API probe returned Forbidden in this environment, so the new manual workflow/live SEC pilot was not dispatched; it remains reproducible from the branch workflow. This is not a claim that real-company scenario evidence was fetched or verified.
