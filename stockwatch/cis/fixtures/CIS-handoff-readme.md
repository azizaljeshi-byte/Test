# CIS handoff — start here

The four-stock chart test round is complete. Read `CIS-chart-framework-v1-implementation-notes.md` first, then inspect the four packets and synthetic cases in `CIS-chart-framework-v1-acceptance.json`.

`CIS-chart-framework-v1-packet.schema.json` describes complete reference packets; `CIS-chart-framework-v1-validation.txt` states the checks performed and limits. `chart-judgment-framework-v1.md` preserves the conversation's agreed reference and clarification that upside analysis is a ceiling ladder, not merely profit-taking.

The remaining JSON/CSV files are frozen market-data/evidence inputs. `CIS-handoff-manifest.json` records file hashes. Quotes were captured at different times on 23 October 2026; completed-session comparisons use 22 October. These are not live prices.

Implementation boundary: fixed, documented analyst level packets plus deterministic state evaluation can be coded now. The exercise did not validate universal automatic floor/ceiling selection, calibrated scenario probabilities or a profitable strategy. Final user-facing names remain open. No production deployment, orders or new notifications were performed or requested as part of building this handoff.
