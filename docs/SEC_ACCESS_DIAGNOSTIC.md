# MSFT official SEC access diagnostic

Follow-on to [issue #13](https://github.com/azizaljeshi-byte/Test/issues/13#issuecomment-6345611889); owner selected the official SEC route. No external provider, API key, purchase, proxy bypass or app/trading integration.

The cloud sandbox currently fails at **proxy CONNECT 403**, before an SEC-origin response; its allowlist omits `data.sec.gov` and `www.sec.gov`. A valid SEC identity cannot fix that network policy. This PR provides a manual GitHub-hosted diagnostic for normal permitted access, rather than claiming that local SEC validation succeeded.

## Run in an authorized environment

1. Configure the existing private repository secret `SEC_USER_AGENT` with a descriptive name and contact email. Do not paste it in issues, logs or command arguments. No SEC API key is required.
2. Once the workflow is reviewed and available on the default branch, open **Actions → MSFT official SEC diagnostic (manual research) → Run workflow**. No schedule or automatic trigger is added. Only the owner approves a merge; creating this workflow does not deploy or run it.
3. Inspect the decision-first summary and `msft-sec-diagnostic` artifact. A green process means at least one financial field was filing-verified, not that valuation evidence is complete. Missing identity or zero verified fields exits 2; artifacts are still published. An empty field universe reports zero/zero, not full coverage.

CLI alternative, in a runtime with normal authorized access and privately configured identity:

```bash
python -m stockwatch.sec_access --output /tmp/msft-sec/report
```

## What is checked

Companyfacts and submissions are probed independently for MSFT CIK 789019. The existing evidence adapter then reuses the responses, chooses actual accessions and checks the original filing index/instance. No guessed filing is presented as audited. Identity is validated before any request and logged only as configured/missing/invalid.

The transport logs host/path, attempt, layer and HTTP status without response bodies, headers or contact values. Proxy CONNECT failure is distinct from a received HTTP 403/429; the latter is marked **origin unconfirmed**, since an intermediary can also produce an HTTP response. Other network/read/redirect failures use sanitized messages. Redirects are refused. Requests remain on official SEC MSFT paths.

Requests are serial, spaced at least 0.5 seconds apart and cached per URL, including failures, for the run. Only 429/503 can receive one retry, honoring a valid Retry-After up to 30 seconds; longer/invalid waits stop rather than retry early. Missing Retry-After uses two seconds. 403, proxy-policy denial and other errors are not retried. Original app clients are unchanged. The limiter is per diagnostic process: the owner must keep aggregate use across app/jobs/machines below SEC's [10 requests/second limit](https://www.sec.gov/about/developer-resources). Do not run unrelated bulk jobs simultaneously. Workflow concurrency serializes only this workflow.

Verified/provisional/unavailable counts refer to selected financial fields, not valuation readiness. Verified rows pass Phase 1B and original-filing checks; provisional rows have a selected value but an unverified filing; stale/conflicting/unknown/non-applicable rows are unavailable. Third-party observations cannot enter this route. The existing model still refuses missing market/share/lease/assumption inputs.

Outputs are report JSON, Markdown and sanitized diagnostic JSON. Raw source bodies stay in process memory; this runner does not write/upload source snapshots, contact values or issuer documents. It retains existing hashes/source provenance in the report, but is **not** a full replay archive; use the separate evidence CLI with appropriate private retention for that. Artifact retention is seven days.

## Validation boundary

Offline tests cover identity refusal, request spacing/cache, 429/503 retries and Retry-After budget, proxy versus HTTP denial, partial endpoint outage, original archive failure, synthetic successful extraction, provenance and safe artifacts. Synthetic fixture values do not describe MSFT. A successful GitHub-hosted run with the configured contact secret remains outstanding; neither a synthetic test nor a readable documentation page proves runtime access. Official sources remain authoritative and free: [API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).
